"""Gateway MQTT -> Modbus TCP do Dobot CR3 (contrato Hermes), com máquina de estados.

Assina spacexlab/AAS/<ASSET_ID>/command, que o servidor AAS publica quando o OperationalState
vira Start, Calibrate ou Stop. Executa no CR3 por Modbus TCP e publica o estado em
spacexlab/AAS/<ASSET_ID>/state como {"operational_state": "<estado>"} (mensagem retida: quem
assinar depois, como a AAS ao reiniciar, recebe o estado atual).

Máquina de estados (Fase 4.3 do cronograma; item 11.5 da proposta)

    Estado      OperationalState      Significado
    OCIOSO      Idle                  pronto para Start ou Calibrate
    EXECUTANDO  Executing             ciclo de pick-and-place ou retorno à home em andamento
    PARADO      Stopped               parada pedida (Stop) ou informada pelo robô; robô parado
    ERRO        Error: <código>       falha; robô parado (OP_MODE = 0) até um Calibrate

    De          Evento                              Para        Ação
    OCIOSO      start válido                        EXECUTANDO  pick -> place -> home
    OCIOSO      start inválido (coordenada, home)   OCIOSO      publica "Error: <código>" (recusa)
    OCIOSO      calibrate                           EXECUTANDO  home
    OCIOSO      stop                                PARADO      OP_MODE = 0
    OCIOSO      Modbus caiu / alarme / parada       ERRO/PARADO detectado pela vigilância
    EXECUTANDO  fim do ciclo ou da home             OCIOSO
    EXECUTANDO  stop / robô parado (STATUS 3)       PARADO      interrompe e OP_MODE = 0
    EXECUTANDO  falha (Modbus, alarme, timeout)     ERRO        OP_MODE = 0 (melhor esforço)
    EXECUTANDO  start / calibrate                   EXECUTANDO  ignorado (ocupado)
    PARADO/ERRO calibrate                           EXECUTANDO  reconecta, relê a AAS e vai à home
    PARADO/ERRO start                           PARADO/ERRO recusado: é preciso Calibrate antes

Uma recusa não muda o estado: o robô não se moveu. Toda falha deixa o robô parado e exige
Calibrate (volta à home), que é a forma de levar o robô a uma posição conhecida.

Os limites (TechnicalData/TechnicalProperties/CoordinateLimits) e a HomePosition vêm da AAS,
lidos por cliente OPC UA a cada comando: o que for editado na AAS vale no ciclo seguinte.

Uso (a partir da pasta integration-layer):
    python -m src.gateway_mqtt

Variáveis de ambiente (padrão):
    MQTT_HOST (localhost)   MQTT_PORT (1883)   ASSET_ID (dobot_cr3)
    MODBUS_HOST (localhost) MODBUS_PORT (5020)
    MOVE_TIME (1 s)         tempo de cada movimento no modo de tempo fixo
    MODBUS_REG_STATUS ()    registrador de status do controlador (ex.: 4009); vazio ou 0 = tempo fixo
    MOVE_TIMEOUT (30 s)     tempo máximo de um movimento no modo de status
    AAS_OPCUA_URL (opc.tcp://127.0.0.1:4886; "localhost" no Windows tenta IPv6 antes e custa ~2 s)
"""
import asyncio
import json
import logging
import os
import sys

import aiomqtt
from asyncua import Client

from .cr3_motion import (DEFAULT_OBJECT_HEIGHT, LIMIT_KEYS, STATUS_ALARME, STATUS_PARADO,
                         CR3Motion, FalhaMovimento, MovimentoInterrompido)
from .modbus_comm_manager import ModbusCommManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [gateway] %(message)s",
                    datefmt="%H:%M:%S")
for ruidoso in ("asyncua", "pymodbus"):
    logging.getLogger(ruidoso).setLevel(logging.WARNING)
log = logging.getLogger("gateway_cr3")

AAS = "AssetAdministrationShell"
LIMITES = [AAS, "TechnicalData", "TechnicalProperties", "CoordinateLimits"]
HOME = [AAS, "PickAndPlace", "ArmWorkspace", "HomePosition"]
CAMINHOS = {**{k: LIMITES + [k, "Value"] for k in LIMIT_KEYS},
            **{f"Home{e}": HOME + [f"{e}Position", "Value"] for e in "XYZ"}}

# Estados (o valor é o texto que vai para o OperationalState da AAS)
OCIOSO = "Idle"
EXECUTANDO = "Executing"
PARADO = "Stopped"
ERRO = "Error"

VIGILANCIA_S = 1.0  # intervalo da verificação do robô enquanto ocioso


async def achar(client, caminho):
    """Mesma regra da camada de integração: primeiro filho cujo nome exibido contém o trecho."""
    atual = client.nodes.objects
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


class LeitorAAS:
    """Lê limites e HomePosition da AAS. Os NodeIds são resolvidos uma vez; os valores, a cada comando."""

    def __init__(self, url):
        self.url = url
        self.ids = None
        self.ultimo = None

    async def ler(self):
        try:
            async with Client(self.url, timeout=5) as c:
                if self.ids is None:
                    self.ids = {k: (await achar(c, cam)).nodeid for k, cam in CAMINHOS.items()}
                v = {k: float(await c.get_node(nid).read_value()) for k, nid in self.ids.items()}
            self.ultimo = ({k: v[k] for k in LIMIT_KEYS}, (v["HomeX"], v["HomeY"], v["HomeZ"]))
        except Exception as e:
            if self.ultimo is None:
                raise RuntimeError(f"Não foi possível ler limites/home da AAS em {self.url}: {e}") from e
            log.warning("AAS indisponível (%s); usando os últimos limites lidos", e)
        return self.ultimo


class Gateway:
    def __init__(self):
        self.asset_id = os.getenv("ASSET_ID", "dobot_cr3")
        self.mqtt_host = os.getenv("MQTT_HOST", "localhost")
        self.mqtt_port = int(os.getenv("MQTT_PORT", 1883))
        self.t_cmd = f"spacexlab/AAS/{self.asset_id}/command"
        self.t_estado = f"spacexlab/AAS/{self.asset_id}/state"
        self.aas = LeitorAAS(os.getenv("AAS_OPCUA_URL", "opc.tcp://127.0.0.1:4886"))
        self.modbus = ModbusCommManager(host=os.getenv("MODBUS_HOST", "localhost"),
                                        port=int(os.getenv("MODBUS_PORT", 5020)))
        reg_status = os.getenv("MODBUS_REG_STATUS", "").strip()
        self.motion = CR3Motion(self.modbus, {}, float(os.getenv("MOVE_TIME", 1)), log,
                                status_reg=int(reg_status) if reg_status not in ("", "0") else None,
                                move_timeout=float(os.getenv("MOVE_TIMEOUT", 30)))
        self.estado = OCIOSO
        self.codigo_erro = None
        self.tarefa = None   # ciclo ou home em execução
        self.saida = None    # fila de estados a publicar (criada dentro do laço de eventos)

    # ------------------------------------------------------------------ estado
    def texto_estado(self):
        return f"{ERRO}: {self.codigo_erro}" if self.estado == ERRO else self.estado

    def publicar(self, texto):
        if self.saida is not None:
            self.saida.put_nowait(texto)

    def mudar(self, novo, motivo, codigo=None):
        anterior = self.texto_estado()
        self.estado, self.codigo_erro = novo, codigo
        log.info("ESTADO %s -> %s (%s)", anterior, self.texto_estado(), motivo)
        self.publicar(self.texto_estado())

    def recusar(self, codigo, motivo):
        """Recusa um comando sem mudar o estado; a AAS mostra "Error: <codigo>"."""
        log.warning("Comando recusado (%s): estado continua %s", motivo, self.texto_estado())
        self.publicar(f"{ERRO}: {codigo}")

    # ------------------------------------------------------------------ Modbus
    def garantir_modbus(self):
        if not self.modbus.connected:
            self.modbus.connect()
        return self.modbus.connected

    def fechar_modbus(self):
        try:
            self.modbus.client.close()
        except Exception:
            pass
        self.modbus.connected = False

    # ------------------------------------------------------------------ comandos
    async def tratar(self, dados: dict):
        cmd = str(dados.get("cmd", "")).lower()

        if cmd == "stop":
            if self.estado == EXECUTANDO:
                log.info("Stop recebido: interrompendo o movimento")
                self.motion.pedir_parada("Stop Requested")  # a tarefa muda para PARADO
            elif self.estado == OCIOSO:
                self.motion.parar_robo()
                self.mudar(PARADO, "Stop recebido com o robô ocioso")
            else:
                self.publicar(self.texto_estado())
            return

        if cmd not in ("start", "calibrate"):
            log.warning("Comando desconhecido ignorado: %r", cmd)
            return

        if self.estado == EXECUTANDO:
            log.warning("Comando %s ignorado: robô ocupado", cmd)
            self.publicar(self.texto_estado())
            return

        if cmd == "start" and self.estado in (PARADO, ERRO):
            log.warning("Start recusado no estado %s: envie Calibrate antes", self.texto_estado())
            self.publicar(self.texto_estado())
            return

        try:
            limites, home = await self.aas.ler()
        except RuntimeError as e:
            log.error("%s", e)
            self.mudar(ERRO, "AAS inacessível", "AAS Not Reachable")
            return
        self.motion.limits.clear()
        self.motion.limits.update(limites)

        if not self.garantir_modbus():
            self.mudar(ERRO, "sem conexão Modbus", "Modbus Not Connected")
            return

        if cmd == "calibrate":
            if not self.motion.validate(*home, point_name="Home Position"):
                self.mudar(ERRO, "home inválida na AAS", "Calibration Failed")
                return
            self.iniciar("retorno à home", self.rotina_home(home))
            return

        try:
            pick = [float(dados["in_coord"][e]) for e in "xyz"]
            place = [float(dados["out_coord"][e]) for e in "xyz"]
        except (KeyError, TypeError, ValueError):
            self.recusar("Invalid Command", "comando sem coordenadas válidas")
            return
        pick[2] += DEFAULT_OBJECT_HEIGHT
        place[2] += DEFAULT_OBJECT_HEIGHT
        log.info("Garra: %s (abre %s / fecha %s) — ainda sem registrador Modbus no CR3",
                 dados.get("end_effector"), dados.get("gripper_open"), dados.get("gripper_close"))
        if not (self.motion.validate(*pick, point_name="PickPosition (Robô)")
                and self.motion.validate(*place, point_name="PlacePosition (Robô)")):
            self.recusar("Coordinates Out of Bounds", "coordenada fora da área")
            return
        if not self.motion.validate(*home, point_name="Home Position"):
            self.recusar("Home Position Out of Bounds", "home inválida na AAS")
            return
        self.iniciar("ciclo", self.rotina_ciclo(pick, place, home))

    def iniciar(self, nome, rotina):
        self.motion.limpar_parada()
        self.mudar(EXECUTANDO, f"{nome} iniciado")
        self.tarefa = asyncio.ensure_future(self.executar(nome, rotina))

    async def rotina_ciclo(self, pick, place, home):
        await self.motion.move_to_pick(pick)
        await self.motion.move_to_place(place)
        await self.motion.go_home(home)

    async def rotina_home(self, home):
        await self.motion.go_home(home)

    async def executar(self, nome, rotina):
        try:
            await rotina
            self.mudar(OCIOSO, f"{nome} concluído")
        except MovimentoInterrompido as e:
            self.motion.parar_robo()
            self.mudar(PARADO, f"{nome} interrompido: {e.motivo}")
        except FalhaMovimento as e:
            self.motion.parar_robo()
            if e.codigo == "Modbus Communication Failed":
                self.fechar_modbus()
            self.mudar(ERRO, f"falha no {nome}", e.codigo)
        except Exception as e:  # exceção do pymodbus: conexão perdida
            log.error("Falha durante o %s: %r", nome, e)
            self.fechar_modbus()
            self.mudar(ERRO, f"falha no {nome}", "Modbus Communication Failed")
        finally:
            self.tarefa = None

    # ------------------------------------------------------------------ vigilância
    async def vigiar(self):
        """Com o robô ocioso, confere a conexão Modbus e o status do robô a cada segundo."""
        while True:
            await asyncio.sleep(VIGILANCIA_S)
            if self.estado != OCIOSO:
                continue
            try:
                if self.motion.status_reg is not None:
                    status = self.motion.ler_status()
                    if status == STATUS_ALARME:
                        self.motion.parar_robo()
                        self.mudar(ERRO, "alarme informado pelo robô", "Robot Alarm")
                    elif status == STATUS_PARADO:
                        self.mudar(PARADO, "parada informada pelo robô")
                elif not self.modbus.read_holding_register(4000, count=1):
                    raise FalhaMovimento("Modbus Communication Failed")
            except Exception as e:
                if self.estado == OCIOSO:
                    log.error("Vigilância: conexão com o robô perdida (%r)", e)
                    self.fechar_modbus()
                    self.mudar(ERRO, "conexão Modbus perdida", "Modbus Communication Failed")

    # ------------------------------------------------------------------ MQTT
    async def publicador(self, cli):
        while True:
            texto = await self.saida.get()
            await cli.publish(self.t_estado, json.dumps({"operational_state": texto}), retain=True)
            log.info("Publicado em %s: operational_state=%s", self.t_estado, texto)

    async def receptor(self, cli):
        async for m in cli.messages:
            try:
                dados = json.loads(m.payload.decode())["data"]
            except (ValueError, KeyError, TypeError, AttributeError):
                log.warning("Mensagem inválida em %s: %r", m.topic, m.payload)
                continue
            log.info("Comando recebido: %s", json.dumps(dados, ensure_ascii=False))
            await self.tratar(dados)

    async def rodar(self):
        self.saida = asyncio.Queue()
        modo = (f"status no registrador {self.motion.status_reg} (timeout {self.motion.move_timeout:g} s)"
                if self.motion.status_reg is not None else f"tempo fixo de {self.motion.move_time:g} s")
        log.info("Fim de movimento por %s", modo)
        if not self.garantir_modbus():
            self.estado, self.codigo_erro = ERRO, "Modbus Not Connected"
        try:  # resolve os nós da AAS já na partida; se ela ainda não subiu, tenta no 1º comando
            limites, home = await self.aas.ler()
            log.info("AAS %s: limites %s, home %s", self.aas.url, limites, home)
        except RuntimeError as e:
            log.warning("%s", e)
        log.info("Estado inicial: %s", self.texto_estado())
        vigia = asyncio.ensure_future(self.vigiar())
        try:
            while True:
                try:
                    async with aiomqtt.Client(self.mqtt_host, self.mqtt_port,
                                              identifier=f"gateway-{self.asset_id}") as cli:
                        await cli.subscribe(self.t_cmd)
                        log.info("MQTT %s:%s — aguardando comandos em %s",
                                 self.mqtt_host, self.mqtt_port, self.t_cmd)
                        self.publicar(self.texto_estado())  # sincroniza a AAS a cada (re)conexão
                        tarefas = [asyncio.ensure_future(self.publicador(cli)),
                                   asyncio.ensure_future(self.receptor(cli))]
                        feitas, pendentes = await asyncio.wait(tarefas, return_when=asyncio.FIRST_EXCEPTION)
                        for t in pendentes:
                            t.cancel()
                        for t in feitas:
                            t.result()  # propaga o MqttError
                except aiomqtt.MqttError as e:
                    log.warning("MQTT indisponível (%s); nova tentativa em 3 s", e)
                    await asyncio.sleep(3)
        finally:
            vigia.cancel()


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # exigido pelo aiomqtt

    async def principal():
        await Gateway().rodar()

    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        log.info("Gateway encerrado.")


if __name__ == "__main__":
    main()
