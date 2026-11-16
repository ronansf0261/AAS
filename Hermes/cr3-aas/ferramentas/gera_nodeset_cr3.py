"""Gera o NodeSet2 (I4AAS) da AAS do Dobot CR3 a partir do NodeSet2 do Robô Educacional.

Mantém a mesma hierarquia de nomes usada pela camada de integração
(AssetAdministrationShell / PickAndPlace / ... / Value e Grabber / ...), troca a
identidade do ativo, ajusta os valores para o CR3 e acrescenta o submodelo
TechnicalData (dados do robô e comunicação Modbus TCP).

Uso: python gera_nodeset_cr3.py <nodeset_robo_educacional.xml> <saida.xml>
"""
import copy
import re
import sys
import xml.etree.ElementTree as ET

UA = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
TY = "http://opcfoundation.org/UA/2008/02/Types.xsd"
U = "{%s}" % UA
ET.register_namespace("", UA)
ET.register_namespace("uax", TY)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
ET.register_namespace("xsd", "http://www.w3.org/2001/XMLSchema")

BASE = "https://hub-internal.local/ids"
# Atenção: os identificadores dos submodelos NÃO podem conter os nomes "PickAndPlace" ou
# "Grabber". A camada de integração localiza os nós por trecho do nome exibido e pegaria
# o nó SubmodelReference em vez do submodelo.
IDS = {  # identificador antigo -> novo
    "https://example.com/ids/aas/4112_1092_8042_5082": f"{BASE}/aas/DobotCR3AAS",
    "https://example.com/ids/asset/0593_7181_1142_0337": f"{BASE}/asset/DobotCR3",
    "www.example.com/ids/sm/1225_9020_5022_1974": f"{BASE}/sm/DobotCR3/0001",
    "https://example.com/ids/sm/3291_3112_8042_9017": f"{BASE}/sm/DobotCR3/0002",
    "https://example.com/ids/sm/5351_5111_1142_3551": f"{BASE}/sm/DobotCR3/0003",
}
ID_TECHNICAL_DATA = f"{BASE}/sm/DobotCR3/0004"

# Valores do CR3. Strings vazias = campo a preencher com a etiqueta/manual do robô.
VALORES = {
    ("Nameplate", "URIOfTheProduct"): "https://www.dobot-robots.com",
    ("Nameplate", "ManufacturerName"): "DOBOT (Shenzhen Yuejiang Technology Co., Ltd.)",
    ("Nameplate", "ManufacturerProductDesignation"): "CR3 Collaborative Robot",
    ("Nameplate", "ContactInformation", "NationalCode"): "CN",
    ("Nameplate", "ContactInformation", "Language"): "en",
    ("Nameplate", "ContactInformation", "CityTown"): "Shenzhen",
    ("Nameplate", "ContactInformation", "TimeZone"): "UTC+8",
    ("Nameplate", "ContactInformation", "Company"): "Shenzhen Yuejiang Technology Co., Ltd.",
    ("Nameplate", "ContactInformation", "Street"): "",
    ("Nameplate", "ContactInformation", "Zipcode"): "",
    ("Nameplate", "ContactInformation", "StateCounty"): "Guangdong",
    ("Nameplate", "SerialNumber"): "",
    ("Nameplate", "YearOfConstruction"): "",
    ("Nameplate", "CountryOfOrigin"): "CN",
    ("PickAndPlace", "ArmWorkspace", "HomePosition", "XPosition"): "0",
    ("PickAndPlace", "ArmWorkspace", "HomePosition", "YPosition"): "0",
    ("PickAndPlace", "ArmWorkspace", "HomePosition", "ZPosition"): "0",
    ("PickAndPlace", "ArmWorkspace", "WorkspaceLimits", "GlobalXLimit"): "620",
    ("PickAndPlace", "ArmWorkspace", "WorkspaceLimits", "GlobalYLimit"): "620",
    ("PickAndPlace", "ArmWorkspace", "WorkspaceLimits", "GlobalZLimit"): "620",
    ("PickAndPlace", "Gripper", "GripperType"): "Parallel Gripper",
    ("PickAndPlace", "Gripper", "RatedLoad"): "0.000",
    ("PickAndPlace", "Gripper", "Status"): "Open",
    ("Grabber", "GripperType"): "Parallel Gripper",
    ("Grabber", "Limits", "StrokeLength"): "0",
    ("Grabber", "Limits", "MaxHoldingWeight"): "0.000",
}

# (idShort, categoria, descrição, valor)
TECHNICAL_DATA = [
    ("RobotType", "CONSTANT", "Type of robot", "Collaborative robot (cobot)"),
    ("NumberOfAxes", "CONSTANT", "Number of controlled axes", "6"),
    ("Payload", "CONSTANT", "Rated payload of the robot, in kg", "3"),
    ("WorkingRadius", "CONSTANT", "Maximum working radius, in mm", "620"),
    ("Repeatability", "CONSTANT", "Position repeatability (+/-), in mm", "0.02"),
    ("Weight", "CONSTANT", "Robot arm weight, in kg", "16.5"),
    ("MaxTCPSpeed", "CONSTANT", "Maximum TCP speed, in m/s", "2"),
]
COMMUNICATION = [
    ("Protocol", "CONSTANT", "Protocol used by the integration layer to command the robot", "Modbus TCP"),
    ("IPAddress", "PARAMETER", "IP address of the robot controller (factory default of LAN1, confirm on site)", "192.168.5.1"),
    ("Port", "PARAMETER", "TCP port of the Modbus TCP server on the controller", "502"),
]


def main(entrada: str, saida: str) -> None:
    texto = open(entrada, encoding="utf-8").read()
    for antigo, novo in IDS.items():
        texto = texto.replace(antigo, novo)
    texto = texto.replace("AASAssetAdministrationShell:EducationalRobotAAS", "AASAssetAdministrationShell:DobotCR3AAS")
    texto = texto.replace("Asset:EducationalRobot", "Asset:DobotCR3")
    raiz = ET.fromstring(texto)
    nodes = {n.get("NodeId"): n for n in raiz if n.get("NodeId")}
    prox = [max(int(k.split("=")[-1]) for k in nodes if k.startswith("ns=1;i=")) + 1]

    def nome(n):
        d = n.find(U + "DisplayName")
        return d.text if d is not None else ""

    def refs(n):
        r = n.find(U + "References")
        return list(r) if r is not None else []

    def filhos(n):
        return [nodes[r.text] for r in refs(n)
                if r.get("IsForward", "true") != "false" and r.text in nodes
                and r.get("ReferenceType") in ("HasComponent", "HasProperty")]

    def filho(n, nm):
        for c in filhos(n):
            if nome(c) == nm or nome(c) == "Submodel:" + nm:
                return c
        raise KeyError(f"{nm} não encontrado em {nome(n)}")

    def set_valor(var, valor, tipo="String"):
        v = var.find(U + "Value")
        for c in list(v):
            v.remove(c)
        el = ET.SubElement(v, "{%s}%s" % (TY, tipo))
        el.text = valor

    aas = next(n for n in nodes.values() if nome(n) == "AASAssetAdministrationShell:DobotCR3AAS")

    # 1) valores do CR3
    for caminho, valor in VALORES.items():
        n = aas
        for parte in caminho:
            n = filho(n, parte)
        var = filho(n, "Value")
        antigo = var.find(U + "Value")
        tipo = next(iter(antigo)).tag.split("}")[1] if antigo is not None and len(antigo) else "String"
        set_valor(var, valor, tipo if valor != "" else "String")

    # 2) clonagem de subárvores
    def subarvore(raiz_id):
        vistos, pilha = [], [raiz_id]
        while pilha:
            nid = pilha.pop()
            if nid in vistos:
                continue
            vistos.append(nid)
            for r in refs(nodes[nid]):
                alvo = r.text
                if (r.get("IsForward", "true") != "false" and r.get("ReferenceType") != "HasTypeDefinition"
                        and alvo in nodes and alvo.startswith("ns=1;i=") and int(alvo.split("=")[-1]) >= 7500):
                    pilha.append(alvo)
        return vistos

    def clonar(raiz_id):
        # Novos ids na mesma ordem dos originais: a busca por nome usa a ordem dos filhos,
        # e "Value" precisa vir antes de "ValueType".
        ids = sorted(subarvore(raiz_id), key=lambda k: int(k.split("=")[-1]))
        mapa = {}
        for nid in ids:
            mapa[nid] = f"ns=1;i={prox[0]}"
            prox[0] += 1
        for nid in ids:
            novo = copy.deepcopy(nodes[nid])
            novo.set("NodeId", mapa[nid])
            if novo.get("ParentNodeId") in mapa:
                novo.set("ParentNodeId", mapa[novo.get("ParentNodeId")])
            for r in refs(novo):
                if r.text in mapa:
                    r.text = mapa[r.text]
            raiz.append(novo)
            nodes[mapa[nid]] = novo
        return nodes[mapa[raiz_id]]

    def podar(raiz_nova, ids_clonados):
        """Remove do XML os nós clonados que ficaram sem ligação com a nova raiz."""
        vivos = set(subarvore(raiz_nova.get("NodeId")))
        for nid in ids_clonados:
            if nid not in vivos and nid in nodes:
                raiz.remove(nodes.pop(nid))

    def renomear(n, novo_nome, browse=None):
        n.find(U + "DisplayName").text = novo_nome
        n.set("BrowseName", "1:" + (browse or novo_nome))

    def remover_filhos_elementos(n, manter=("IdShort", "Category", "ModelingKind", "Description",
                                           "DataSpecification", "AllowDuplicates", "Identification",
                                           "IAASIdentifiable")):
        r = n.find(U + "References")
        for ref in list(r):
            if (ref.get("ReferenceType") == "HasComponent" and ref.text in nodes
                    and nome(nodes[ref.text]) not in manter):
                r.remove(ref)

    def ligar(pai, filho_n, tipo="HasComponent"):
        ref = ET.SubElement(pai.find(U + "References"), U + "Reference", {"ReferenceType": tipo})
        ref.text = filho_n.get("NodeId")

    def nova_propriedade(pai, id_short, categoria, descricao, valor, modelo):
        p = clonar(modelo.get("NodeId"))
        renomear(p, id_short)
        set_valor(filho(p, "IdShort"), id_short)
        set_valor(filho(p, "Category"), categoria)
        set_valor(filho(p, "Description"), descricao)
        set_valor(filho(p, "Value"), valor)
        ligar(pai, p)

    grabber = filho(aas, "Grabber")
    modelo_prop = filho(grabber, "GripperType")
    modelo_smc = filho(grabber, "Limits")

    # 3) submodelo TechnicalData
    td = clonar(grabber.get("NodeId"))
    clonados_td = subarvore(td.get("NodeId"))
    renomear(td, "Submodel:TechnicalData")
    remover_filhos_elementos(td)
    podar(td, clonados_td)
    # Identification do novo submodelo: ajusta qualquer variável Id dentro da subárvore clonada
    for nid in subarvore(td.get("NodeId")):
        n = nodes[nid]
        if n.tag == U + "UAVariable" and nome(n) == "Id":
            set_valor(n, ID_TECHNICAL_DATA)
    for id_short, cat, desc, val in TECHNICAL_DATA:
        nova_propriedade(td, id_short, cat, desc, val, modelo_prop)
    smc = clonar(modelo_smc.get("NodeId"))
    clonados_smc = subarvore(smc.get("NodeId"))
    renomear(smc, "Communication")
    remover_filhos_elementos(smc)
    podar(smc, clonados_smc)
    set_valor(filho(smc, "IdShort"), "Communication")
    set_valor(filho(smc, "Description"), "Communication interface used by the integration layer")
    for id_short, cat, desc, val in COMMUNICATION:
        nova_propriedade(smc, id_short, cat, desc, val, modelo_prop)
    ligar(td, smc)
    ligar(aas, td)

    # 4) referência ao novo submodelo no AAS
    ref_modelo = next(c for c in filhos(aas) if nome(c) == "SubmodelReference:" + IDS["https://example.com/ids/sm/5351_5111_1142_3551"])
    ref_td = clonar(ref_modelo.get("NodeId"))
    renomear(ref_td, f"SubmodelReference:{ID_TECHNICAL_DATA}")
    ligar(aas, ref_td)

    ET.ElementTree(raiz).write(saida, encoding="utf-8", xml_declaration=True)
    print(f"NodeSet do CR3 salvo em {saida} ({len(nodes)} nós; último i={prox[0] - 1})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
