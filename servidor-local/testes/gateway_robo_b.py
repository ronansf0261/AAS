"""Roda neste PC o gateway da Raspberry Pi do Robô Educacional, sem alterar o código dele.

Executa raspberrypi-integration/main.py com três adaptações feitas só em memória:
  - Porta serial: usa SERIAL_PORT no lugar de find_robot(). No Windows a find_robot() procura
    /dev/ttyACM* e /dev/ttyUSB* e não acha nada. Padrão: socket://127.0.0.1:7777, que é o
    simulador_arduino.py. Com o Arduino real no USB, use SERIAL_PORT=COM3 (ou a porta que aparecer).
  - URLs socket:// abertas como conexão TCP (ver abrir_serial abaixo).
  - Laço de eventos SelectorEventLoop no Windows (exigido pelo aiomqtt).

Variáveis do gateway, com padrão local (o docker-compose da Raspberry define as mesmas):
    MQTT_BROKER=127.0.0.1  MQTT_PORT=1883  BAUD_RATE=1000000
    MQTT_TOPIC_COMMAND / MQTT_TOPIC_FEEDBACK = spacexlab/AAS/<ASSET_ID>/command | /state
    ASSET_ID=0000_0000_0000_0000 (o mesmo do docker-compose do educational-robot-aas)

Uso (Python 3.10+; o gateway usa a sintaxe `str | None`):
    C:\\AAS\\.venv-robo-b\\Scripts\\python servidor-local\\testes\\gateway_robo_b.py
"""
import asyncio
import os
import sys
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[2] / "raspberrypi-integration"

asset = os.environ.setdefault("ASSET_ID", "0000_0000_0000_0000")
for var, valor in {
    "MQTT_BROKER": "127.0.0.1",
    "MQTT_PORT": "1883",
    "MQTT_TOPIC_COMMAND": f"spacexlab/AAS/{asset}/command",
    "MQTT_TOPIC_FEEDBACK": f"spacexlab/AAS/{asset}/state",
    "BAUD_RATE": "1000000",
}.items():
    os.environ.setdefault(var, valor)

sys.path.insert(0, str(GATEWAY))
import main as gateway  # noqa: E402  (raspberrypi-integration/main.py)
import serial_asyncio  # noqa: E402

_abrir_serial_original = serial_asyncio.open_serial_connection


async def abrir_serial(*args, url=None, **kwargs):
    """socket://host:porta -> conexão TCP direta (mesmo StreamReader/StreamWriter da serial).

    No Windows o pyserial-asyncio lê a porta por polling de in_waiting/out_waiting, e o
    tratador socket:// do pyserial não tem out_waiting. Porta COM real segue o caminho original.
    """
    if url and url.startswith("socket://"):
        host, porta = url[len("socket://"):].rsplit(":", 1)
        return await asyncio.open_connection(host, int(porta))
    return await _abrir_serial_original(*args, url=url, **kwargs)


serial_asyncio.open_serial_connection = abrir_serial


async def porta_configurada():
    porta = os.environ.get("SERIAL_PORT", "socket://127.0.0.1:7777")
    print(f"[gateway Robô B] porta serial: {porta}")
    print(f"[gateway Robô B] MQTT {os.environ['MQTT_BROKER']}:{os.environ['MQTT_PORT']}  "
          f"comando: {os.environ['MQTT_TOPIC_COMMAND']}  retorno: {os.environ['MQTT_TOPIC_FEEDBACK']}")
    return porta


gateway.find_robot = porta_configurada

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(gateway.main())
    except KeyboardInterrupt:
        print("Gateway encerrado.")
