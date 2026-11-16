"""Servidor OPC UA de teste para a AAS do CR3 (substitui o aas_core em testes locais).

Carrega o NodeSet2 da AAS, libera para escrita os mesmos nós que o user_entrypoint.py
do laboratório e reproduz a ponte OPC UA <-> MQTT do pick_and_place.py:
  - OperationalState = Start  -> publica o comando JSON em spacexlab/AAS/<ASSET_ID>/command
  - mensagem em spacexlab/AAS/<ASSET_ID>/state -> escreve operational_state na AAS

Uso:
    python servidor_teste.py --xml ../resources/DobotCR3AAS.aasx.xml --porta 4886 \
        --mqtt-host localhost --mqtt-port 1883 --asset-id dobot_cr3
"""
import argparse
import asyncio
import json
import logging
import re

import aiomqtt
from asyncua import Server, ua

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("asyncua").setLevel(logging.WARNING)
log = logging.getLogger("servidor_teste")

AAS = "AssetAdministrationShell"
GC = [AAS, "PickAndPlace", "PickAndPlacePositioning", "GripperControl"]
CAMINHOS = {
    "estado": GC + ["OperationalState", "Value"],
    "xin": GC + ["PickPosition", "XPosition", "Value"],
    "yin": GC + ["PickPosition", "YPosition", "Value"],
    "zin": GC + ["PickPosition", "ZPosition", "Value"],
    "xout": GC + ["PlacePosition", "XPosition", "Value"],
    "yout": GC + ["PlacePosition", "YPosition", "Value"],
    "zout": GC + ["PlacePosition", "ZPosition", "Value"],
    "abertura": [AAS, "Grabber", "ParallelGripping", "OpeningWidth", "Value"],
    "fechamento": [AAS, "Grabber", "ParallelGripping", "ClampingWidth", "Value"],
    "garra": [AAS, "Grabber", "GripperType", "Value"],
}


async def achar(server, caminho):
    """Mesma regra da camada de integração: primeiro filho cujo nome exibido contém o trecho."""
    atual = await server.get_root_node().get_child(["0:Objects"])
    for trecho in caminho:
        prox = None
        for filho in await atual.get_children():
            if trecho in (await filho.read_display_name()).Text:
                prox = filho
                break
        if prox is None:
            raise RuntimeError(f"Nó com '{trecho}' não encontrado no caminho {caminho}")
        atual = prox
    return atual


def compatibilizar_namespaces(xml: str) -> str:
    """O export I4AAS usa BrowseNames com índice 3 sem declarar o namespace.

    Versões novas da asyncua recusam isso; o aas_core do laboratório carrega o arquivo
    original. Aqui o namespace é declarado só na memória, sem alterar o arquivo.
    """
    bloco = re.search(r"<NamespaceUris>(.*?)</NamespaceUris>", xml, re.S)
    if bloco and bloco.group(1).count("<Uri>") < 3:
        xml = xml.replace("</NamespaceUris>", "<Uri>http://admin-shell.io/aas/2/0/</Uri></NamespaceUris>", 1)
    return xml


class Ponte:
    def __init__(self, nos, mqtt_host, mqtt_port, asset_id):
        self.nos = nos
        self.mqtt_host, self.mqtt_port = mqtt_host, mqtt_port
        self.t_cmd = f"spacexlab/AAS/{asset_id}/command"
        self.t_estado = f"spacexlab/AAS/{asset_id}/state"
        self.fila: asyncio.Queue = asyncio.Queue()

    async def datachange_notification(self, node, val, data):
        if not isinstance(val, str):
            return
        v = val.lower()
        if v == "start":
            leit = {k: await self.nos[k].read_value() for k in self.nos if k != "estado"}
            msg = {"data": {
                "cmd": "start",
                "in_coord": {"x": str(leit["xin"]), "y": str(leit["yin"]), "z": str(leit["zin"])},
                "out_coord": {"x": str(leit["xout"]), "y": str(leit["yout"]), "z": str(leit["zout"])},
                "end_effector": str(leit["garra"]),
                "gripper_open": str(leit["abertura"]),
                "gripper_close": str(leit["fechamento"]),
            }}
            await self.fila.put(msg)
        elif v == "calibrate":
            await self.fila.put({"data": {"cmd": "calibrate"}})

    async def rodar_mqtt(self):
        while True:
            try:
                async with aiomqtt.Client(self.mqtt_host, self.mqtt_port) as cli:
                    await cli.subscribe(self.t_estado)
                    log.info("MQTT conectado em %s:%s", self.mqtt_host, self.mqtt_port)
                    await asyncio.gather(self._publicar(cli), self._receber(cli))
            except aiomqtt.MqttError as e:
                log.warning("MQTT indisponível (%s); nova tentativa em 3 s", e)
                await asyncio.sleep(3)

    async def _publicar(self, cli):
        while True:
            msg = await self.fila.get()
            await cli.publish(self.t_cmd, json.dumps(msg))
            log.info("Comando publicado em %s: %s", self.t_cmd, msg)

    async def _receber(self, cli):
        async for m in cli.messages:
            try:
                estado = json.loads(m.payload.decode()).get("operational_state")
            except (ValueError, AttributeError):
                log.warning("Mensagem inválida em %s: %r", m.topic, m.payload)
                continue
            if isinstance(estado, str):
                await self.nos["estado"].write_value(ua.Variant(estado, ua.VariantType.String))
                log.info("OperationalState <- %s", estado)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default="../resources/DobotCR3AAS.aasx.xml")
    ap.add_argument("--porta", type=int, default=4886)
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--asset-id", default="dobot_cr3")
    a = ap.parse_args()

    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{a.porta}/")
    server.set_server_name("DobotCR3AAS (servidor de teste)")
    xml = compatibilizar_namespaces(open(a.xml, encoding="utf-8").read())
    await server.import_xml(xmlstring=xml)

    nos = {k: await achar(server, c) for k, c in CAMINHOS.items()}
    for k, no in nos.items():
        if k != "garra":
            await no.set_writable()

    ponte = Ponte(nos, a.mqtt_host, a.mqtt_port, a.asset_id)
    async with server:
        sub = await server.create_subscription(500, ponte)
        await sub.subscribe_data_change(nos["estado"])
        log.info("Servidor OPC UA em opc.tcp://0.0.0.0:%s/  (tópicos %s e %s)", a.porta, ponte.t_cmd, ponte.t_estado)
        await ponte.rodar_mqtt()


if __name__ == "__main__":
    asyncio.run(main())
