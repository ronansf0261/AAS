"""Gateway simulado do CR3: responde aos comandos da AAS como a camada Modbus responderá.

Assina spacexlab/AAS/<ASSET_ID>/command, mostra o comando recebido, espera o tempo de
"execução" e publica {"operational_state": "Idle"} em spacexlab/AAS/<ASSET_ID>/state.
Serve para testar AAS + servidor + broker antes de a camada Modbus TCP ficar pronta.

Uso:
    python gateway_simulado.py --mqtt-host localhost --mqtt-port 1883 --asset-id dobot_cr3 --atraso 2
"""
import argparse
import asyncio
import json

import aiomqtt


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--asset-id", default="dobot_cr3")
    ap.add_argument("--atraso", type=float, default=2.0, help="tempo simulado da rotina, em segundos")
    a = ap.parse_args()
    t_cmd = f"spacexlab/AAS/{a.asset_id}/command"
    t_estado = f"spacexlab/AAS/{a.asset_id}/state"

    async with aiomqtt.Client(a.mqtt_host, a.mqtt_port) as cli:
        await cli.subscribe(t_cmd)
        print(f"Gateway simulado aguardando comandos em {t_cmd}")
        async for m in cli.messages:
            try:
                dados = json.loads(m.payload.decode())["data"]
            except (ValueError, KeyError, AttributeError):
                print(f"Mensagem inválida: {m.payload!r}")
                continue
            print(f"\nComando recebido: {json.dumps(dados, ensure_ascii=False)}")
            await asyncio.sleep(a.atraso)
            await cli.publish(t_estado, json.dumps({"operational_state": "Idle"}))
            print(f"Rotina simulada concluída -> Idle publicado em {t_estado}")


if __name__ == "__main__":
    asyncio.run(main())
