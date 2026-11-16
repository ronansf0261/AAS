"""Orquestrador do Projeto Hermes (Pacote 5): executa sequências de pick-and-place pela AAS.

Fala só com a AAS, por OPC UA. Escreve as posições e o comando no OperationalState e acompanha
os estados que voltam do gateway. Não sabe qual robô está do outro lado: o mesmo orquestrador
comanda o Dobot CR3 e o Robô Educacional (teste de troca, CA-04 e CA-05).

Fluxo de uma execução
  1. Conecta à AAS e assina o OperationalState: cada mudança de estado fica registrada.
  2. Preparação: se o estado não for Idle, espera o robô terminar ou manda Calibrate.
  3. Em cada ciclo: escreve pick, place (e a garra, se a sequência pedir), escreve Start e
     espera um estado final:
        Idle -> OK   ·   Error: <código> -> ERRO   ·   Stopped -> PARADO
        sem estado final no tempo limite -> TIMEOUT (manda Stop)
  4. Depois de um ciclo com problema, recupera com Calibrate e segue
     (ou encerra, com --parar-na-falha).
  5. Grava as evidências em execucoes/<data-hora>_<sequência>/:
        ciclos.csv    um ciclo por linha, com estados observados, duração e resultado
        eventos.log   todas as mudanças de estado, com horário
        resumo.json   taxa de sucesso (CA-01/CA-04), observabilidade (CA-03), tempos e os
                      commits dos repositórios (base do ICM, CA-05)

Uso (a partir desta pasta, com o Python do projeto):
    python orquestrador.py sequencias/cr3.json                 # executa a sequência
    python orquestrador.py sequencias/cr3.json --ciclos 3      # sobrepõe o número de ciclos
    python orquestrador.py --robo cr3 --estado                 # mostra o estado na AAS
    python orquestrador.py --robo cr3 --calibrar               # leva o robô à home
    python orquestrador.py --robo cr3 --parar                  # interrompe o movimento
Ctrl+C durante uma execução manda Stop ao robô e grava o que já foi feito.
"""
import argparse
import asyncio
import csv
import json
import logging
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from asyncua import Client, ua

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent  # C:\AAS
AAS = "AssetAdministrationShell"
GC = [AAS, "PickAndPlace", "PickAndPlacePositioning", "GripperControl"]
GARRA = [AAS, "Grabber", "ParallelGripping"]
ROBOS = {"cr3": "opc.tcp://127.0.0.1:4886", "educacional": "opc.tcp://127.0.0.1:4885"}
REPOS = ("integration-layer", "educational-robot-aas", "raspberrypi-integration", "instance-aas",
         "servidor-local", "orquestrador")

OCIOSO, PARADO, ERRO = "Idle", "Stopped", "Error"

log = logging.getLogger("orquestrador")


class Abortar(Exception):
    pass


def eh_final(v):
    return isinstance(v, str) and (v == OCIOSO or v == PARADO or v.startswith(ERRO))


def resultado_de(final):
    if final is None:
        return "TIMEOUT"
    if final == OCIOSO:
        return "OK"
    if final == PARADO:
        return "PARADO"
    return "ERRO"


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


class ClienteAAS:
    """Conexão OPC UA com a AAS e assinatura do OperationalState."""

    def __init__(self, url):
        self.url = url
        self.c = None
        self.fila = asyncio.Queue()
        self.nome = "?"
        self.garra = None

    def datachange_notification(self, node, val, data):  # chamado pela assinatura da asyncua
        self.fila.put_nowait((time.monotonic(), val))

    async def conectar(self):
        self.c = Client(self.url, timeout=10)
        await self.c.connect()
        for filho in await self.c.nodes.objects.get_children():
            nome = (await filho.read_display_name()).Text
            if nome.startswith("AASAssetAdministrationShell:"):
                self.nome = nome.split(":", 1)[1]
                break
        self.no_estado = await achar(self.c, GC + ["OperationalState", "Value"])
        self.no_pick = [await achar(self.c, GC + ["PickPosition", f"{e}Position", "Value"]) for e in "XYZ"]
        self.no_place = [await achar(self.c, GC + ["PlacePosition", f"{e}Position", "Value"]) for e in "XYZ"]
        try:
            self.garra = (await achar(self.c, GARRA + ["OpeningWidth", "Value"]),
                          await achar(self.c, GARRA + ["ClampingWidth", "Value"]))
        except RuntimeError:
            self.garra = None
        sub = await self.c.create_subscription(50, self)
        await sub.subscribe_data_change(self.no_estado, queuesize=50)

    async def desconectar(self):
        if self.c is not None:
            try:
                await self.c.disconnect()
            except Exception:
                pass

    async def estado(self):
        return await self.no_estado.read_value()

    def esvaziar(self):
        while not self.fila.empty():
            self.fila.get_nowait()

    async def comandar(self, comando):
        self.esvaziar()
        await escrever(self.no_estado, comando)

    async def esperar_final(self, comando, timeout):
        """Espera um estado final depois de `comando` (None = não espera o eco do comando).

        Devolve (estado_final ou None se o tempo acabou, [(segundos, estado), ...]).
        """
        t0 = time.monotonic()
        vistos = []
        eco = comando is None

        def registrar(t, v):
            if not vistos or vistos[-1][1] != v:
                vistos.append((round(t - t0, 2), v))
                log.debug("    estado: %-34s (+%.2f s)", v, t - t0)

        while True:
            restante = t0 + timeout - time.monotonic()
            if restante <= 0:
                return None, vistos
            try:
                t, v = await asyncio.wait_for(self.fila.get(), timeout=min(restante, 1.0))
            except asyncio.TimeoutError:
                # rede de segurança caso alguma notificação se perca: lê o valor direto
                t, v = time.monotonic(), await self.estado()
            if not isinstance(v, str):
                continue
            if not eco:
                if v.lower() == comando.lower():
                    eco = True
                    registrar(t, v)
                continue
            registrar(t, v)
            if eh_final(v):
                return v, vistos


# ---------------------------------------------------------------------- operações
async def calibrar(aas, timeout):
    log.info("Calibrate: levando o robô à home...")
    await aas.comandar("Calibrate")
    final, _ = await aas.esperar_final("Calibrate", timeout)
    log.info("Calibrate -> %s", final or f"sem resposta em {timeout:g} s")
    return final == OCIOSO


async def parar(aas, timeout=10):
    await aas.comandar("Stop")
    final, _ = await aas.esperar_final("Stop", timeout)
    return final


async def preparar(aas, timeout):
    v = await aas.estado()
    log.info("Estado inicial na AAS: %s", v)
    if v == OCIOSO:
        return True
    if not eh_final(v):  # Start, Calibrate ou Executing: espera terminar
        log.info("Robô ocupado; aguardando um estado final...")
        v, _ = await aas.esperar_final(None, timeout)
        if v == OCIOSO:
            return True
    return await calibrar(aas, timeout)


async def executar_ciclo(aas, n, total, indice, passo, seq, timeout):
    pick, place = passo["pick"], passo["place"]
    for no, valor in zip(aas.no_pick, pick):
        await escrever(no, valor)
    for no, valor in zip(aas.no_place, place):
        await escrever(no, valor)
    garra = seq.get("garra") or {}
    if aas.garra and garra.get("abertura") is not None:
        await escrever(aas.garra[0], garra["abertura"])
    if aas.garra and garra.get("fechamento") is not None:
        await escrever(aas.garra[1], garra["fechamento"])

    log.debug("Ciclo %d/%d: pick %s -> place %s", n, total, pick, place)
    inicio = datetime.now()
    t0 = time.monotonic()
    await aas.comandar("Start")
    final, vistos = await aas.esperar_final("Start", timeout)
    duracao = time.monotonic() - t0
    if final is None:
        log.warning("Ciclo %d sem estado final em %g s: mandando Stop", n, timeout)
        parado = await parar(aas)
        log.info("Stop -> %s", parado or "sem resposta")
    resultado = resultado_de(final)
    estados = " -> ".join(v for _, v in vistos)
    log.info("Ciclo %2d/%d · pick %s -> place %s · %s · %5.2f s · %s",
             n, total, fmt(pick), fmt(place), estados or "(nenhum estado)", duracao, resultado)
    return {
        "ciclo": n, "passo": indice + 1,
        "pick_x": pick[0], "pick_y": pick[1], "pick_z": pick[2],
        "place_x": place[0], "place_y": place[1], "place_z": place[2],
        "inicio": inicio.isoformat(timespec="seconds"), "duracao_s": round(duracao, 2),
        "estados": estados, "estado_final": final or "", "resultado": resultado,
    }


def fmt(p):
    return "(" + ", ".join(f"{v:g}" for v in p) + ")"


def _git(pasta):
    if not (pasta / ".git").exists():
        return {"commit": None, "observacao": "não versionado"}
    try:
        rev = subprocess.run(["git", "-C", str(pasta), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        pend = subprocess.run(["git", "-C", str(pasta), "status", "--porcelain"],
                              capture_output=True, text=True, timeout=10).stdout.splitlines()
        return {"commit": rev or None, "arquivos_nao_commitados": len(pend)}
    except (OSError, subprocess.SubprocessError) as e:
        return {"commit": None, "observacao": f"git indisponível: {e}"}


def versoes():
    """Commit e alterações pendentes (para o ICM do CA-05).

    "AAS (raiz)" é o repositório que reúne todas as camadas (C:\\AAS, no GitHub): é o commit que
    vale para o ICM. Os repositórios do laboratório aparecem em seguida, para referência.
    """
    out = {"AAS (raiz)": _git(BASE)}
    for nome in REPOS:
        out[nome] = _git(BASE / nome)
    return out


def carregar_sequencia(caminho):
    seq = json.loads(Path(caminho).read_text(encoding="utf-8"))
    passos = seq.get("passos")
    if not passos:
        raise SystemExit(f"{caminho}: a sequência precisa de uma lista 'passos'")
    for i, p in enumerate(passos, 1):
        for k in ("pick", "place"):
            if not (isinstance(p.get(k), list) and len(p[k]) == 3):
                raise SystemExit(f"{caminho}: passo {i} precisa de '{k}' com [x, y, z] em mm")
    return seq


def gravar(pasta, registros, resumo):
    colunas = ["ciclo", "passo", "pick_x", "pick_y", "pick_z", "place_x", "place_y", "place_z",
               "inicio", "duracao_s", "estados", "estado_final", "resultado"]
    with open(pasta / "ciclos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        w.writeheader()
        w.writerows(registros)
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")


def resumir(seq, arquivo, aas, url, n, registros, recuperacoes, interrompida, t_inicio):
    total = len(registros)
    ok = [r for r in registros if r["resultado"] == "OK"]
    taxa = len(ok) / total if total else 0.0
    obs = sum(1 for r in registros if r["estado_final"]) / total if total else 0.0
    meta = float(seq.get("meta_sucesso", 0.95))
    dur = [r["duracao_s"] for r in ok]
    return {
        "sequencia": seq.get("nome", Path(arquivo).stem),
        "arquivo": str(arquivo),
        "aas": {"nome": aas.nome, "url": url},
        "inicio": t_inicio.isoformat(timespec="seconds"),
        "fim": datetime.now().isoformat(timespec="seconds"),
        "ciclos_planejados": n,
        "ciclos_executados": total,
        "ciclos_ok": len(ok),
        "resultados": dict(Counter(r["resultado"] for r in registros)),
        "taxa_sucesso": round(taxa, 4),
        "meta_sucesso": meta,
        "aprovado_taxa_sucesso": total == n and taxa >= meta,
        "observabilidade_estado": round(obs, 4),
        "aprovado_observabilidade": total == n and obs == 1.0,
        "duracao_ciclo_ok_s": ({"media": round(statistics.mean(dur), 2), "min": min(dur), "max": max(dur),
                                "desvio": round(statistics.pstdev(dur), 2)} if dur else None),
        "recuperacoes_com_calibrate": recuperacoes,
        "interrompida": interrompida,
        "versoes": versoes(),
        "referencial": seq.get("referencial"),
        "passos": seq["passos"],
    }


async def executar_sequencia(args):
    seq = carregar_sequencia(args.sequencia)
    url = args.url or seq.get("aas_url") or ROBOS[args.robo]
    n = args.ciclos or int(seq.get("ciclos", len(seq["passos"])))
    timeout = float(seq.get("timeout_ciclo_s", 120))
    passos = seq["passos"]

    pasta = AQUI / "execucoes" / f"{datetime.now():%Y%m%d-%H%M%S}_{Path(args.sequencia).stem}"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = logging.FileHandler(pasta / "eventos.log", encoding="utf-8")
    arq.setLevel(logging.DEBUG)
    arq.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(arq)

    aas = ClienteAAS(url)
    registros, recuperacoes, interrompida = [], 0, None
    t_inicio = datetime.now()
    try:
        await aas.conectar()
        log.info("Sequência '%s': %d ciclo(s), %d passo(s), timeout %g s por ciclo",
                 seq.get("nome", Path(args.sequencia).stem), n, len(passos), timeout)
        log.info("AAS %s em %s", aas.nome, url)
        if not await preparar(aas, timeout):
            raise Abortar("o robô não ficou Idle na preparação")
        for i in range(n):
            indice = i % len(passos)
            reg = await executar_ciclo(aas, i + 1, n, indice, passos[indice], seq, timeout)
            registros.append(reg)
            if reg["resultado"] != "OK":
                if args.parar_na_falha:
                    raise Abortar(f"ciclo {i + 1} terminou em {reg['resultado']} (--parar-na-falha)")
                recuperacoes += 1
                if not await calibrar(aas, timeout):
                    raise Abortar("a recuperação com Calibrate falhou")
    except Abortar as e:
        interrompida = str(e)
        log.error("Execução encerrada: %s", e)
    except (OSError, asyncio.TimeoutError, ConnectionError) as e:
        interrompida = f"conexão com a AAS perdida: {e!r}"
        log.error("Execução encerrada: %s", interrompida)
    except asyncio.CancelledError:
        interrompida = "interrompida pelo operador (Ctrl+C)"
        log.warning("Interrompido: mandando Stop ao robô")
        try:
            if not eh_final(await aas.estado()):
                await asyncio.wait_for(parar(aas, 5), 6)
        except Exception:
            pass
        raise
    finally:
        resumo = resumir(seq, args.sequencia, aas, url, n, registros, recuperacoes, interrompida, t_inicio)
        gravar(pasta, registros, resumo)
        await aas.desconectar()
        mostrar_resumo(resumo, pasta)
        log.removeHandler(arq)
        arq.close()
    return 0 if resumo["aprovado_taxa_sucesso"] else 2


def mostrar_resumo(r, pasta):
    print()
    print(f"Resumo — {r['sequencia']} ({r['aas']['nome']})")
    print(f"  ciclos executados: {r['ciclos_executados']}/{r['ciclos_planejados']}  {r['resultados']}")
    print(f"  taxa de sucesso:   {r['taxa_sucesso']:.0%} (meta {r['meta_sucesso']:.0%}) -> "
          f"{'APROVADO' if r['aprovado_taxa_sucesso'] else 'REPROVADO'}   [CA-01 / CA-04]")
    print(f"  estado observado:  {r['observabilidade_estado']:.0%} dos ciclos -> "
          f"{'APROVADO' if r['aprovado_observabilidade'] else 'REPROVADO'}   [CA-03]")
    if r["duracao_ciclo_ok_s"]:
        d = r["duracao_ciclo_ok_s"]
        print(f"  duração do ciclo:  média {d['media']} s (mín {d['min']}, máx {d['max']}, desvio {d['desvio']})")
    print(f"  recuperações:      {r['recuperacoes_com_calibrate']}")
    if r["interrompida"]:
        print(f"  interrompida:      {r['interrompida']}")
    print(f"  evidências:        {pasta}")


async def comando_avulso(args):
    url = args.url or ROBOS[args.robo]
    aas = ClienteAAS(url)
    try:
        await aas.conectar()
        print(f"AAS {aas.nome} em {url}")
        if args.estado:
            pick = [await no.read_value() for no in aas.no_pick]
            place = [await no.read_value() for no in aas.no_place]
            print(f"  OperationalState = {await aas.estado()}")
            print(f"  PickPosition     = {pick}")
            print(f"  PlacePosition    = {place}")
            return 0
        if args.calibrar:
            return 0 if await calibrar(aas, 120) else 2
        if args.parar:
            final = await parar(aas)
            print(f"Stop -> {final or 'sem resposta (o gateway deste robô trata Stop?)'}")
            return 0 if final == PARADO else 2
    finally:
        await aas.desconectar()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sequencia", nargs="?", help="arquivo JSON da sequência (pasta sequencias/)")
    ap.add_argument("--ciclos", type=int, help="sobrepõe o número de ciclos da sequência")
    ap.add_argument("--parar-na-falha", action="store_true", help="encerra no primeiro ciclo sem Idle")
    ap.add_argument("--robo", choices=ROBOS, default="cr3", help="atalho para a URL da AAS")
    ap.add_argument("--url", help="URL OPC UA da AAS (sobrepõe a da sequência e a do --robo)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--estado", action="store_true", help="só mostra o estado na AAS")
    g.add_argument("--calibrar", action="store_true", help="manda Calibrate e espera Idle")
    g.add_argument("--parar", action="store_true", help="manda Stop e espera Stopped")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    logging.getLogger().handlers[0].setLevel(logging.INFO)
    logging.getLogger("asyncua").setLevel(logging.ERROR)

    if a.estado or a.calibrar or a.parar:
        coro = comando_avulso(a)
    elif a.sequencia:
        coro = executar_sequencia(a)
    else:
        ap.error("informe uma sequência ou uma das opções --estado, --calibrar, --parar")
    try:
        sys.exit(asyncio.run(coro))
    except KeyboardInterrupt:
        print("Interrompido.")
        sys.exit(130)


if __name__ == "__main__":
    main()
