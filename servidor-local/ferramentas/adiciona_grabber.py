"""Acrescenta o submodelo Grabber (do Robô Educacional V2) na AAS do Dobot CR3.

Por que: a ponte OPC UA <-> MQTT do laboratório (educational-robot-aas/src) lê
Grabber/ParallelGripping/OpeningWidth, ClampingWidth e Grabber/GripperType para montar o
comando. Com o Grabber, a mesma ponte serve aos dois robôs (teste de troca).

O que faz, nos DOIS arquivos da AAS do CR3 (NodeSet2 e AASX), sem reescrever o resto:
  1. copia o submodelo Grabber e a SubmodelReference dele a partir dos arquivos do Robô
     Educacional, com NodeIds novos (NodeSet2) e um identificador de submodelo novo;
  2. copia as ConceptDescriptions usadas pelo Grabber que faltarem no AASX;
  3. Grabber/GripperType recebe o mesmo valor de PickAndPlace/Gripper/GripperType;
  4. opcional (--home X Y Z): troca a HomePosition de PickAndPlace/ArmWorkspace.

As edições são feitas no texto: o restante dos arquivos fica byte a byte igual.
Rodar de novo não duplica o Grabber (só atualiza a HomePosition, se pedida).

Uso (a partir de C:\\AAS):
    python servidor-local/ferramentas/adiciona_grabber.py --home 200 150 150
"""
import argparse
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # C:\AAS
UA = "{http://opcfoundation.org/UA/2011/03/UANodeSet.xsd}"

ID_GRABBER_EDU = "https://example.com/ids/sm/5351_5111_1142_3551"
# Atenção: o id NÃO pode conter "Grabber" nem "PickAndPlace". A camada de integração pega o
# primeiro nó cujo nome exibido CONTÉM o trecho e acabaria no nó SubmodelReference:<id>.
ID_GRABBER_CR3 = "https://example.com/ids/sm/4310_6032_2611_0426"


# ----------------------------------------------------------------------------- NodeSet2
class NodeSet:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.texto = caminho.read_bytes().decode("utf-8")
        raiz = ET.fromstring(self.texto.encode("utf-8"))
        self.nos = {n.get("NodeId"): n for n in raiz if n.get("NodeId")}

    def nome(self, nid):
        d = self.nos[nid].find(UA + "DisplayName")
        return d.text if d is not None else ""

    def refs(self, nid):
        r = self.nos[nid].find(UA + "References")
        return list(r) if r is not None else []

    def filhos(self, nid):
        return [r.text for r in self.refs(nid)
                if r.get("IsForward", "true") != "false" and r.text in self.nos
                and r.get("ReferenceType") in ("HasComponent", "HasProperty")]

    def filho(self, nid, nome):
        for c in self.filhos(nid):
            if self.nome(c) in (nome, "Submodel:" + nome):
                return c
        raise KeyError(f"'{nome}' não encontrado em '{self.nome(nid)}'")

    def caminho_ate(self, partes):
        nid = self.aas()
        for p in partes:
            nid = self.filho(nid, p)
        return nid

    def aas(self):
        return next(k for k in self.nos if self.nome(k).startswith("AASAssetAdministrationShell:"))

    def subarvore(self, raiz_id):
        """Mesma regra de Hermes/cr3-aas/ferramentas/gera_nodeset_cr3.py."""
        vistos, pilha = [], [raiz_id]
        while pilha:
            nid = pilha.pop()
            if nid in vistos:
                continue
            vistos.append(nid)
            for r in self.refs(nid):
                alvo = r.text
                if (r.get("IsForward", "true") != "false" and r.get("ReferenceType") != "HasTypeDefinition"
                        and alvo in self.nos and alvo.startswith("ns=1;i=") and int(alvo.split("=")[-1]) >= 7500):
                    pilha.append(alvo)
        return vistos

    def bloco(self, nid):
        """Texto original do nó <UAxxx NodeId="nid">...</UAxxx>."""
        m = re.search(r'<(UA\w+) NodeId="%s"[^>]*?(?:/>|>.*?</\1>)' % re.escape(nid), self.texto, re.S)
        if not m:
            raise KeyError(nid)
        return m

    def maior_id_ns1(self):
        return max(int(x) for x in re.findall(r"ns=1;i=(\d+)", self.texto))


def trocar_valor_string(bloco: str, valor: str) -> str:
    """Troca o conteúdo <uax:String> do <Value> de um UAVariable."""
    novo, n = re.subn(r"(<Value>\s*<uax:String[^>]*?)(?:/>|>.*?</uax:String>)",
                      lambda m: f"{m.group(1)}>{valor}</uax:String>", bloco, count=1, flags=re.S)
    if n != 1:
        raise ValueError("Valor String não encontrado no nó")
    return novo


def enxertar_nodeset(cr3: NodeSet, edu: NodeSet, tipo_garra: str) -> str:
    texto = cr3.texto
    if any(cr3.nome(c) == "Submodel:Grabber" for c in cr3.filhos(cr3.aas())):
        print("NodeSet2: Grabber já existe, nada a copiar.")
        return texto

    aas_edu = edu.aas()
    grabber = edu.filho(aas_edu, "Grabber")
    ref = next(c for c in edu.filhos(aas_edu) if edu.nome(c) == "SubmodelReference:" + ID_GRABBER_EDU)

    # Ids novos na ordem dos originais: a busca por nome depende da ordem dos filhos
    # ("Value" precisa continuar antes de "ValueType").
    ids = sorted(set(edu.subarvore(ref) + edu.subarvore(grabber)), key=lambda k: int(k.split("=")[-1]))
    prox = cr3.maior_id_ns1() + 1
    mapa = {}
    for nid in ids:
        mapa[nid] = f"ns=1;i={prox}"
        prox += 1

    valor_tipo = edu.filho(edu.filho(grabber, "GripperType"), "Value")
    blocos = []
    for nid in ids:
        b = edu.bloco(nid).group(0)
        if nid == valor_tipo:
            b = trocar_valor_string(b, tipo_garra)
        b = re.sub(r"ns=1;i=(\d+)(?!\d)", lambda m: mapa.get(m.group(0), m.group(0)), b)
        b = b.replace(ID_GRABBER_EDU, ID_GRABBER_CR3)
        blocos.append("  " + b.replace("\r\n", "\n").replace("\n", "\r\n"))
    texto = texto.replace("</UANodeSet>", "\r\n".join(blocos) + "\r\n</UANodeSet>", 1)

    # Liga a SubmodelReference e o Grabber ao nó da AAS (nesta ordem, no fim da lista).
    m = cr3.bloco(cr3.aas())
    bloco_aas = m.group(0)
    novas = "".join(f'  <Reference ReferenceType="HasComponent">{mapa[x]}</Reference>\r\n    '
                    for x in (ref, grabber))
    bloco_aas = bloco_aas.replace("</References>", novas + "</References>", 1)
    texto = texto[:m.start()] + bloco_aas + texto[m.end():]
    print(f"NodeSet2: Grabber copiado ({len(ids)} nós, {mapa[ids[0]]} a {mapa[ids[-1]]}), id {ID_GRABBER_CR3}")
    return texto


def home_nodeset(texto: str, cr3: NodeSet, home) -> str:
    for eixo, v in zip("XYZ", home):
        nid = cr3.caminho_ate(["PickAndPlace", "ArmWorkspace", "HomePosition", f"{eixo}Position", "Value"])
        m = re.search(r'<(UA\w+) NodeId="%s"[^>]*?>.*?</\1>' % re.escape(nid), texto, re.S)
        texto = texto[:m.start()] + trocar_valor_string(m.group(0), f"{v:.1f}") + texto[m.end():]
    print(f"NodeSet2: HomePosition = {home}")
    return texto


# ----------------------------------------------------------------------------- AASX
def ler_aasx(caminho: Path):
    with zipfile.ZipFile(caminho) as z:
        infos = z.infolist()
        dados = {i.filename: z.read(i.filename) for i in infos}
    nome = next(k for k in dados if k.endswith(".aas.xml"))
    return infos, dados, nome


def enxertar_aasx(cr3: str, edu: str, tipo_garra: str) -> str:
    if "<aas:idShort>Grabber</aas:idShort>" in cr3:
        print("AASX: Grabber já existe, nada a copiar.")
        return cr3
    bloco = next(b for b in re.findall(r"<aas:submodel>.*?</aas:submodel>", edu, re.S)
                 if "<aas:idShort>Grabber</aas:idShort>" in b[:300])
    bloco = bloco.replace(ID_GRABBER_EDU, ID_GRABBER_CR3)
    bloco = re.sub(r"(<aas:idShort>GripperType</aas:idShort>.*?<aas:value>)[^<]*(</aas:value>)",
                   lambda m: m.group(1) + tipo_garra + m.group(2), bloco, count=1, flags=re.S)
    bloco = bloco.replace("\r\n", "\n").replace("\n", "\r\n")
    cr3 = cr3.replace("  </aas:submodels>", "    " + bloco + "\r\n  </aas:submodels>", 1)

    ref = ("  <aas:submodelRef>\r\n"
           "          <aas:keys>\r\n"
           f'            <aas:key type="Submodel" local="true" idType="IRI">{ID_GRABBER_CR3}</aas:key>\r\n'
           "          </aas:keys>\r\n"
           "        </aas:submodelRef>\r\n      ")
    cr3 = cr3.replace("</aas:submodelRefs>", ref + "</aas:submodelRefs>", 1)

    copiadas = 0
    for cd_id in sorted(set(re.findall(r'<aas:key type="ConceptDescription"[^>]*>([^<]+)</aas:key>', bloco))):
        marca = f">{cd_id}</aas:identification>"
        if marca in cr3:
            continue
        cd = next((b for b in re.findall(r"<aas:conceptDescription>.*?</aas:conceptDescription>", edu, re.S)
                   if marca in b), None)
        if cd:
            cd = cd.replace("\r\n", "\n").replace("\n", "\r\n")
            cr3 = cr3.replace("  </aas:conceptDescriptions>", "    " + cd + "\r\n  </aas:conceptDescriptions>", 1)
            copiadas += 1
    print(f"AASX: Grabber copiado, id {ID_GRABBER_CR3}; {copiadas} ConceptDescription(s) copiada(s)")
    return cr3


def home_aasx(texto: str, home) -> str:
    ini = texto.index("<aas:idShort>HomePosition</aas:idShort>")
    for eixo, v in zip("XYZ", home):
        i = texto.index(f"<aas:idShort>{eixo}Position</aas:idShort>", ini)
        m = re.compile(r"<aas:value>[^<]*</aas:value>|<aas:value />").search(texto, i)
        texto = texto[:m.start()] + f"<aas:value>{v:.1f}</aas:value>" + texto[m.end():]
    print(f"AASX: HomePosition = {home}")
    return texto


def tipo_garra_aasx(texto: str) -> str:
    i = texto.index("<aas:idShort>Gripper</aas:idShort>")
    i = texto.index("<aas:idShort>GripperType</aas:idShort>", i)
    return re.compile(r"<aas:value>([^<]*)</aas:value>").search(texto, i).group(1)


# ----------------------------------------------------------------------------- main
def main():
    res = BASE / "integration-layer" / "resources"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodeset", type=Path, default=res / "DobotCR3_1.aasx.xml")
    ap.add_argument("--aasx", type=Path, default=res / "CR3.aasx")
    ap.add_argument("--nodeset-edu", type=Path, default=BASE / "instance-aas" / "EducationalRobot_V2.aasx.xml")
    ap.add_argument("--aasx-edu", type=Path, default=BASE / "instance-aas" / "EducationalRobotAAS_V2.aasx")
    ap.add_argument("--home", type=float, nargs=3, metavar=("X", "Y", "Z"),
                    help="nova HomePosition em mm (ex.: 200 150 150)")
    a = ap.parse_args()

    # NodeSet2
    cr3 = NodeSet(a.nodeset)
    # Grabber/GripperType acompanha o valor atual de PickAndPlace/Gripper/GripperType
    nid_tipo = cr3.caminho_ate(["PickAndPlace", "Gripper", "GripperType", "Value"])
    tipo = re.search(r"<uax:String[^>]*>([^<]*)</uax:String>", cr3.bloco(nid_tipo).group(0)).group(1)
    texto = enxertar_nodeset(cr3, NodeSet(a.nodeset_edu), tipo)
    if a.home:
        texto = home_nodeset(texto, cr3, a.home)
    ET.fromstring(texto.encode("utf-8"))  # garante XML bem formado antes de gravar
    a.nodeset.write_bytes(texto.encode("utf-8"))

    # AASX
    infos, dados, nome = ler_aasx(a.aasx)
    bom = dados[nome].startswith(b"\xef\xbb\xbf")
    xml = dados[nome].decode("utf-8-sig")
    _, dados_edu, nome_edu = ler_aasx(a.aasx_edu)
    xml = enxertar_aasx(xml, dados_edu[nome_edu].decode("utf-8-sig"), tipo_garra_aasx(xml))
    if a.home:
        xml = home_aasx(xml, a.home)
    ET.fromstring(xml.encode("utf-8"))
    dados[nome] = (b"\xef\xbb\xbf" if bom else b"") + xml.encode("utf-8")
    tmp = a.aasx.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as z:
        for info in infos:
            z.writestr(info, dados[info.filename], compress_type=info.compress_type)
    tmp.replace(a.aasx)
    print(f"Gravados: {a.nodeset}\n          {a.aasx}")


if __name__ == "__main__":
    main()
