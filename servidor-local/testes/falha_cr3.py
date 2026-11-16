"""Injeta falhas no simulador do CR3, escrevendo no registrador STATUS (4009).

Serve para ensaiar o CA-07 (comportamento em falha) sem o robô: o gateway, no modo de status
(MODBUS_REG_STATUS=4009), lê esse registrador enquanto o robô se move ou está ocioso.

    --parada   STATUS = 3: robô parado (pausa, botão de parada, emergência) -> estado Stopped
    --alarme   STATUS = 2: alarme ou colisão                               -> estado Error: Robot Alarm
    --pronto   STATUS = 0: limpa a falha (depois mande Calibrate pela AAS)
    --ler      só mostra o STATUS atual

Perda de conexão: pare o simulador (docker stop hermes-sim-cr3, ou feche a janela dele).

Uso:
    python falha_cr3.py --parada [--host 127.0.0.1 --porta 5020]
"""
import argparse

from pymodbus.client import ModbusTcpClient

REG_STATUS = 4009
TEXTO = {0: "pronto", 1: "em movimento", 2: "alarme", 3: "parado"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--parada", action="store_const", dest="valor", const=3)
    g.add_argument("--alarme", action="store_const", dest="valor", const=2)
    g.add_argument("--pronto", action="store_const", dest="valor", const=0)
    g.add_argument("--ler", action="store_const", dest="valor", const=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=5020)
    a = ap.parse_args()

    cli = ModbusTcpClient(a.host, port=a.porta, timeout=3)
    if not cli.connect():
        raise SystemExit(f"Simulador não encontrado em {a.host}:{a.porta}")
    try:
        if a.valor is not None:
            r = cli.write_register(REG_STATUS, a.valor, slave=1)
            if r.isError():
                raise SystemExit(f"Falha ao escrever no registrador {REG_STATUS}: {r}")
            print(f"STATUS ({REG_STATUS}) <- {a.valor} ({TEXTO[a.valor]})")
        r = cli.read_holding_registers(REG_STATUS, count=1, slave=1)
        if not r.isError():
            v = r.registers[0]
            print(f"STATUS ({REG_STATUS}) = {v} ({TEXTO.get(v, '?')})")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
