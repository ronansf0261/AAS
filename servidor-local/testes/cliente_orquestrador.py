"""Cliente OPC UA no papel do orquestrador: comanda um ciclo de pick-and-place pela AAS.

O mesmo cliente serve aos dois robôs (teste de troca): só muda o servidor AAS que ele acessa.
Funciona contra o servidor local (aas_local.py) ou contra o aas_core do laboratório.
Baseado em Hermes/cr3-aas/teste/cliente_orquestrador.py.

1. Mostra limites (TechnicalData/.../CoordinateLimits, se a AAS tiver), HomePosition e garra.
2. Escreve PickPosition e PlacePosition (e abertura/fechamento da garra, se informados).
3. Escreve OperationalState = Start (ou Calibrate com --calibrate).
4. Espera o OperationalState virar Idle ou Error e mostra o tempo.
   Saída: 0 = Idle, 2 = Error, 1 = tempo esgotado.

Perfis (--robo), com valores padrão que cada argumento pode sobrepor:
    cr3          opc.tcp://127.0.0.1:4886, pick (200, 150, 100), place (-200, 150, 100)
    educacional  opc.tcp://127.0.0.1:4885, pick (140, 120, -62), place (-140, 120, -62),
                 garra abre 180 / fecha 45 (raspberrypi-integration/payload_template.json)

Uso:
    python cliente_orquestrador.py                              # CR3, ciclo válido
    python cliente_orquestrador.py --pick 100 50 50             # CR3, dentro da cúpula -> Error
    python cliente_orquestrador.py --calibrate
    python cliente_orquestrador.py --robo educacional           # Robô Educacional
"""
import argparse
import asyncio
import sys
import time

from asyncua import Client, ua

AAS = "AssetAdministrationShell"
GC = [AAS, "PickAndPlace", "PickAndPlacePositioning", "GripperControl"]
LIMITES = [AAS, "TechnicalData", "TechnicalProperties", "CoordinateLimits"]
HOME = [AAS, "PickAndPlace", "ArmWorkspace", "HomePosition"]


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


async def escrever(no, valor):
    """Escreve respeitando o tipo que o nó já tem (o export I4AAS mistura Int32 e String)."""
    tipo = (await no.read_data_value()).Value.VariantType
    if tipo in (ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64,
                ua.VariantType.UInt16, ua.VariantType.UInt32, ua.VariantType.UInt64):
        convertido = int(round(float(valor)))
    elif tipo in (ua.VariantType.Float, ua.VariantType.Double):
        convertido = float(valor)
    else:
        tipo, convertido = ua.VariantType.String, str(valor)
    await no.write_value(ua.DataValue(ua.Variant(convertido, tipo)))


async def ler(c, caminho):
    return await (await achar(c, caminho + ["Value"])).read_value()


PERFIS = {
    "cr3": {"url": "opc.tcp://127.0.0.1:4886", "pick": [200.0, 150.0, 100.0],
            "place": [-200.0, 150.0, 100.0], "abertura": None, "fechamento": None},
    "educacional": {"url": "opc.tcp://127.0.0.1:4885", "pick": [140.0, 120.0, -62.0],
                    "place": [-140.0, 120.0, -62.0], "abertura": 180.0, "fechamento": 45.0},
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robo", choices=PERFIS, default="cr3", help="perfil de valores padrão")
    ap.add_argument("--url")
    ap.add_argument("--pick", nargs=3, type=float, metavar=("X", "Y", "Z"))
    ap.add_argument("--place", nargs=3, type=float, metavar=("X", "Y", "Z"))
    ap.add_argument("--abertura", type=float, help="Grabber/ParallelGripping/OpeningWidth")
    ap.add_argument("--fechamento", type=float, help="Grabber/ParallelGripping/ClampingWidth")
    ap.add_argument("--calibrate", action="store_true", help="só volta para a home")
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()
    for chave, valor in PERFIS[a.robo].items():
        if getattr(a, chave) is None:
            setattr(a, chave, valor)

    async with Client(a.url) as c:
        print(f"Conectado a {a.url}  (perfil {a.robo})\n")
        try:
            lim = {k: await ler(c, LIMITES + [k]) for k in
                   ("MinLimitX", "MaxLimitX", "MinLimitY", "MaxLimitY", "MinLimitZ", "MaxLimitZ")}
            print(f"CoordinateLimits: X [{lim['MinLimitX']}, {lim['MaxLimitX']}]  "
                  f"Y [{lim['MinLimitY']}, {lim['MaxLimitY']}]  Z [{lim['MinLimitZ']}, {lim['MaxLimitZ']}]")
        except RuntimeError:
            print("CoordinateLimits: a AAS não tem TechnicalData (sem validação de limites na AAS)")
        home = [await ler(c, HOME + [f"{e}Position"]) for e in "XYZ"]
        print(f"HomePosition:     {home}")
        print(f"Grabber:          {await ler(c, [AAS, 'Grabber', 'GripperType'])}, "
              f"abertura {await ler(c, [AAS, 'Grabber', 'ParallelGripping', 'OpeningWidth'])}, "
              f"fechamento {await ler(c, [AAS, 'Grabber', 'ParallelGripping', 'ClampingWidth'])}\n")

        if not a.calibrate:
            for eixo, v in zip("XYZ", a.pick):
                await escrever(await achar(c, GC + ["PickPosition", f"{eixo}Position", "Value"]), v)
            for eixo, v in zip("XYZ", a.place):
                await escrever(await achar(c, GC + ["PlacePosition", f"{eixo}Position", "Value"]), v)
            if a.abertura is not None:
                await escrever(await achar(c, [AAS, "Grabber", "ParallelGripping", "OpeningWidth", "Value"]), a.abertura)
            if a.fechamento is not None:
                await escrever(await achar(c, [AAS, "Grabber", "ParallelGripping", "ClampingWidth", "Value"]), a.fechamento)
            print(f"Posições escritas: pick={a.pick} place={a.place}")

        estado = await achar(c, GC + ["OperationalState", "Value"])
        comando = "Calibrate" if a.calibrate else "Start"
        atual = await estado.read_value()
        if isinstance(atual, str) and atual.lower() in ("start", "calibrate"):
            # Sem mudança de valor não há notificação: volta para Idle antes de comandar.
            print(f"OperationalState estava em {atual}; voltando para Idle antes do comando")
            await escrever(estado, "Idle")
            await asyncio.sleep(1)

        t0 = time.perf_counter()
        await escrever(estado, comando)
        print(f"OperationalState = {comando}  (aguardando Idle ou Error...)")
        await asyncio.sleep(0.3)
        while time.perf_counter() - t0 < a.timeout:
            v = await estado.read_value()
            if isinstance(v, str) and v.lower() == "idle":
                print(f"\nCiclo concluído: OperationalState voltou para Idle em {time.perf_counter() - t0:.2f} s")
                return 0
            if isinstance(v, str) and v.lower().startswith("error"):
                print(f"\nCiclo recusado: OperationalState = {v!r} em {time.perf_counter() - t0:.2f} s")
                return 2
            if isinstance(v, str) and v.lower() == "stopped":
                print(f"\nCiclo interrompido: OperationalState = 'Stopped' em {time.perf_counter() - t0:.2f} s")
                return 3
            await asyncio.sleep(0.1)
        print(f"\nTempo esgotado ({a.timeout:.0f} s) sem Idle/Error. Verifique broker, gateway e simulador.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
