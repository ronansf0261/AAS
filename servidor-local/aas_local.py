"""Servidor AAS local (OPC UA), substituto do aas_core_v1.1.2 do laboratório.

Carrega o NodeSet2 (I4AAS) da AAS e roda a camada de integração (pasta src/) do mesmo jeito
que o aas_core faz dentro do Docker:
  1. src/user_entrypoint.py -> UserEntrypoint(server).init()
  2. para cada submodelo "Submodel:<Nome>" da AAS, se existir src/<nome_snake>.py com a classe
     <Nome> (ex.: PickAndPlace -> src/pick_and_place.py), instancia e roda init(nó) numa task.

Não usa nada do hub: sem MongoDB, sem discovery, sem broker do laboratório. Os argumentos do
`command` do docker-compose (--identification, --database_host, ...) são aceitos e ignorados.

Exemplos (PowerShell, a partir de C:\\AAS):
  # AAS do CR3 + ponte OPC UA <-> MQTT do laboratório (contrato Hermes)
  .venv\\Scripts\\python servidor-local\\aas_local.py -f DobotCR3_1.aasx.xml `
      --resources integration-layer\\resources --src educational-robot-aas\\src --asset-id dobot_cr3

  # modo antigo: camada do CR3 dentro do servidor, OPC UA -> Modbus direto
  .venv\\Scripts\\python servidor-local\\aas_local.py -f DobotCR3_1.aasx.xml `
      --resources integration-layer\\resources --src integration-layer\\src --porta 4893
"""
import argparse
import asyncio
import importlib
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # torna o pacote core/ importável

from asyncua import ua  # noqa: E402
from core.asset_administration_shell import AssetAdministrationShell  # noqa: E402
from core.interfaces import BaseSubmodel  # noqa: E402
from core.log import logger  # noqa: E402


def compatibilizar_namespaces(xml: str) -> str:
    """O export I4AAS usa BrowseNames com índice 3 sem declarar o namespace.

    Versões novas da asyncua recusam isso; o aas_core do laboratório carrega o arquivo
    original. Aqui o namespace é declarado só na memória, sem alterar o arquivo.
    (Mesma função de Hermes/cr3-aas/teste/servidor_teste.py.)
    """
    bloco = re.search(r"<NamespaceUris>(.*?)</NamespaceUris>", xml, re.S)
    if bloco and bloco.group(1).count("<Uri>") < 3:
        xml = xml.replace("</NamespaceUris>", "<Uri>http://admin-shell.io/aas/2/0/</Uri></NamespaceUris>", 1)
    return xml


def compatibilizar_asyncua():
    """O export I4AAS grava enums só com o número (<Type>20</Type>); a asyncua 1.1.x espera
    "Nome_20" e aborta a carga. Aceita os dois formatos (só em memória)."""
    from enum import Enum
    from asyncua.common import ua_utils, xmlparser

    original = ua_utils.string_to_val

    def string_to_val(string, vtype):
        if isinstance(vtype, type) and issubclass(vtype, Enum) and string.strip().lstrip("-").isdigit():
            return vtype(int(string))
        return original(string, vtype)

    ua_utils.string_to_val = string_to_val
    xmlparser.string_to_val = string_to_val


def snake(nome: str) -> str:
    """PickAndPlace -> pick_and_place."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nome).lower()


def importar(modulo: str):
    """Importa src.<x>; devolve None só se o próprio módulo não existir."""
    try:
        return importlib.import_module(modulo)
    except ModuleNotFoundError as e:
        if e.name == modulo:
            return None
        raise


def registrar_erro(tarefa: asyncio.Task):
    if not tarefa.cancelled() and tarefa.exception():
        logger.error("Submodelo %s parou com erro: %r", tarefa.get_name(), tarefa.exception())


async def main():
    ap = argparse.ArgumentParser(description="Servidor AAS local (substitui o aas_core).")
    ap.add_argument("-f", "--file", required=True, help="NodeSet2 da AAS, dentro de --resources")
    ap.add_argument("--resources", default="resources", help="pasta do NodeSet2 (padrão: ./resources)")
    ap.add_argument("--src", default="src", help="pasta da camada de integração (padrão: ./src)")
    ap.add_argument("--porta", type=int, default=4886, help="porta OPC UA (a 4840 é do opcualds)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--id_short", default=None, help="nome exibido do servidor")
    ap.add_argument("--mqtt-host", default=None, help="sobrepõe MQTT_HOST (padrão localhost)")
    ap.add_argument("--mqtt-port", default=None, help="sobrepõe MQTT_PORT (padrão 1883)")
    ap.add_argument("--asset-id", default=None, help="sobrepõe ASSET_ID (padrão dobot_cr3)")
    a, ignorados = ap.parse_known_args()
    if ignorados:
        logger.info("Argumentos do aas_core ignorados: %s", " ".join(ignorados))

    # A camada de integração lê estas variáveis na importação (como no docker-compose).
    # Padrão local: broker nesta máquina, nunca o do laboratório.
    for var, valor, padrao in (("MQTT_HOST", a.mqtt_host, "localhost"),
                               ("MQTT_PORT", a.mqtt_port, "1883"),
                               ("ASSET_ID", a.asset_id, "dobot_cr3")):
        if valor is not None:
            os.environ[var] = str(valor)
        os.environ.setdefault(var, padrao)
    logger.info("MQTT_HOST=%s MQTT_PORT=%s ASSET_ID=%s",
                os.environ["MQTT_HOST"], os.environ["MQTT_PORT"], os.environ["ASSET_ID"])

    arquivo = Path(a.resources) / a.file
    src = Path(a.src).resolve()
    if not arquivo.is_file():
        sys.exit(f"NodeSet2 não encontrado: {arquivo}")
    if not (src / "__init__.py").is_file():
        sys.exit(f"Camada de integração não encontrada (falta __init__.py): {src}")

    compatibilizar_asyncua()
    # Avisos conhecidos do export I4AAS (AASMimeDataType, HasEncoding sem destino) não afetam a AAS.
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    server = AssetAdministrationShell()
    await server.init()
    endpoint = f"opc.tcp://{a.host}:{a.porta}/"
    server.set_endpoint(endpoint)
    server.set_server_name(f"{a.id_short or arquivo.stem} (servidor AAS local)")
    # ApplicationUri único por servidor (exigência do OPC UA). O padrão da asyncua é o mesmo para
    # todos, e clientes como o UaExpert confundem dois servidores rodando ao mesmo tempo.
    uri = f"urn:hermes:aas:{os.environ['ASSET_ID']}:{a.porta}"
    await server.set_application_uri(uri)  # descrição do endpoint e NamespaceArray[1]
    server_array = await server.nodes.server.get_child(["0:ServerArray"])
    await server_array.write_value(ua.Variant([uri], ua.VariantType.String))
    logger.info("Carregando %s ...", arquivo)
    await server.import_xml(xmlstring=compatibilizar_namespaces(arquivo.read_text(encoding="utf-8")))

    sys.path.insert(0, str(src.parent))
    pacote = src.name  # "src", como em /app/src no Docker

    async with server:
        logger.info("Servidor OPC UA no ar em %s (cliente: opc.tcp://localhost:%s)", endpoint, a.porta)

        mod = importar(f"{pacote}.user_entrypoint")
        if mod and hasattr(mod, "UserEntrypoint"):
            await mod.UserEntrypoint(server).init()
            logger.info("UserEntrypoint executado")

        objetos = server.nodes.objects
        aas = None
        for filho in await objetos.get_children():
            if (await filho.read_display_name()).Text.startswith("AASAssetAdministrationShell:"):
                aas = filho
                break
        if aas is None:
            sys.exit("Nó AASAssetAdministrationShell não encontrado no NodeSet2")
        logger.info("AAS: %s", (await aas.read_display_name()).Text)

        tarefas = []
        for filho in await aas.get_children():
            nome = (await filho.read_display_name()).Text
            if not nome.startswith("Submodel:"):
                continue
            sm = nome.split(":", 1)[1]
            m = importar(f"{pacote}.{snake(sm)}")
            classe = getattr(m, sm, None) if m else None
            if not (isinstance(classe, type) and issubclass(classe, BaseSubmodel)):
                logger.info("Submodelo %-14s sem lógica (src/%s.py)", sm, snake(sm))
                continue
            t = asyncio.create_task(classe(server).init(filho), name=sm)
            t.add_done_callback(registrar_erro)
            tarefas.append(t)
            logger.info("Submodelo %-14s -> %s.%s", sm, m.__name__, sm)

        logger.info("Pronto. Ctrl+C para encerrar.")
        await asyncio.Event().wait()


if __name__ == "__main__":
    if sys.platform == "win32":
        # gmqtt/aiomqtt precisam do SelectorEventLoop no Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Servidor encerrado.")
