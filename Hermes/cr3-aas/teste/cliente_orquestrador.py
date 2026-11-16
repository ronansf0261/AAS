"""Cliente de teste no papel do orquestrador: comanda um ciclo de pick-and-place pela AAS.

Funciona contra o servidor do laboratório (aas_core) ou contra servidor_teste.py.

1. Lê o submodelo TechnicalData (confirma que a AAS carregada é a do CR3).
2. Escreve posições de pick e place e os parâmetros da garra.
3. Escreve OperationalState = Start.
4. Espera OperationalState voltar para Idle e mostra o tempo do ciclo.

Uso:
    python cliente_orquestrador.py --url opc.tcp://localhost:4886 \
        --pick 300 -150 50 --place 300 150 50 --abertura 180 --fechamento 45
"""
import argparse
import asyncio
import time

from asyncua import Client, ua

AAS = "AssetAdministrationShell"
GC = [AAS, "PickAndPlace", "PickAndPlacePositioning", "GripperControl"]


async def achar(client, caminho):
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


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="opc.tcp://localhost:4886")
    ap.add_argument("--pick", nargs=3, type=float, default=[300, -150, 50], metavar=("X", "Y", "Z"))
    ap.add_argument("--place", nargs=3, type=float, default=[300, 150, 50], metavar=("X", "Y", "Z"))
    ap.add_argument("--abertura", type=float, default=180)
    ap.add_argument("--fechamento", type=float, default=45)
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args()

    async with Client(a.url) as c:
        print(f"Conectado a {a.url}\n")
        print("TechnicalData:")
        for nome in ["RobotType", "NumberOfAxes", "Payload", "WorkingRadius", "Repeatability"]:
            no = await achar(c, [AAS, "TechnicalData", nome, "Value"])
            print(f"  {nome:14s} = {await no.read_value()}")
        prot = await achar(c, [AAS, "TechnicalData", "Communication", "Protocol", "Value"])
        print(f"  {'Protocol':14s} = {await prot.read_value()}\n")

        for eixo, v in zip("XYZ", a.pick):
            await escrever(await achar(c, GC + ["PickPosition", f"{eixo}Position", "Value"]), v)
        for eixo, v in zip("XYZ", a.place):
            await escrever(await achar(c, GC + ["PlacePosition", f"{eixo}Position", "Value"]), v)
        await escrever(await achar(c, [AAS, "Grabber", "ParallelGripping", "OpeningWidth", "Value"]), a.abertura)
        await escrever(await achar(c, [AAS, "Grabber", "ParallelGripping", "ClampingWidth", "Value"]), a.fechamento)
        print(f"Posições escritas: pick={a.pick} place={a.place}")

        estado = await achar(c, GC + ["OperationalState", "Value"])
        t0 = time.perf_counter()
        await escrever(estado, "Start")
        print("OperationalState = Start  (aguardando Idle...)")
        await asyncio.sleep(0.3)
        while time.perf_counter() - t0 < a.timeout:
            v = await estado.read_value()
            if isinstance(v, str) and v.lower() == "idle":
                print(f"\nCiclo concluído: OperationalState voltou para Idle em {time.perf_counter() - t0:.2f} s")
                return
            await asyncio.sleep(0.1)
        print(f"\nTempo esgotado ({a.timeout:.0f} s) sem retorno para Idle. Verifique o broker e o gateway.")


if __name__ == "__main__":
    asyncio.run(main())
