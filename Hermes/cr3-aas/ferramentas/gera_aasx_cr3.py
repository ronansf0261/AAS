"""Gera o pacote AASX do Dobot CR3 (metamodelo AAS V2.0) a partir do AASX do Robô Educacional.

O conteúdo é o mesmo do NodeSet2 gerado por gera_nodeset_cr3.py: mesma estrutura de
PickAndPlace e Grabber, identidade do CR3 e o submodelo TechnicalData.

Uso: python gera_aasx_cr3.py <EducationalRobotAAS_V2.aasx> <DobotCR3AAS.aasx>
"""
import copy
import sys
import zipfile
import xml.etree.ElementTree as ET

from gera_nodeset_cr3 import COMMUNICATION, ID_TECHNICAL_DATA, IDS, TECHNICAL_DATA, VALORES

AAS = "http://www.admin-shell.io/aas/2/0"
A = "{%s}" % AAS
for p, uri in {"aas": AAS, "IEC": "http://www.admin-shell.io/IEC61360/2/0",
               "abac": "http://www.admin-shell.io/aas/abac/2/0",
               "xsi": "http://www.w3.org/2001/XMLSchema-instance"}.items():
    ET.register_namespace(p, uri)


def main(entrada: str, saida: str) -> None:
    with zipfile.ZipFile(entrada) as z:
        arquivos = {i.filename: z.read(i.filename) for i in z.infolist()}
    nome_xml = next(k for k in arquivos if k.endswith(".aas.xml"))
    texto = arquivos[nome_xml].decode("utf-8-sig")
    for antigo, novo in IDS.items():
        texto = texto.replace(antigo, novo)
    texto = texto.replace("<aas:idShort>EducationalRobotAAS</aas:idShort>", "<aas:idShort>DobotCR3AAS</aas:idShort>")
    texto = texto.replace("<aas:idShort>EducationalRobot</aas:idShort>", "<aas:idShort>DobotCR3</aas:idShort>")
    raiz = ET.fromstring(texto)

    def submodelo(id_short):
        for sm in raiz.iter(A + "submodel"):
            if sm.findtext(A + "idShort") == id_short:
                return sm
        raise KeyError(id_short)

    def elementos(container):
        """Elementos filhos de um submodelo (submodelElements) ou de uma coleção (value)."""
        lista = container.find(A + "submodelElements")
        if lista is None:
            lista = container.find(A + "value")
        return [list(se)[0] for se in lista.findall(A + "submodelElement")], lista

    def elemento(container, id_short):
        for el in elementos(container)[0]:
            if el.findtext(A + "idShort") == id_short:
                return el
        raise KeyError(id_short)

    # 1) valores do CR3
    for caminho, valor in VALORES.items():
        el = submodelo(caminho[0])
        for parte in caminho[1:]:
            el = elemento(el, parte)
        el.find(A + "value").text = valor

    # 2) submodelo TechnicalData
    grabber = submodelo("Grabber")
    modelo_prop = elemento(grabber, "GripperType")
    modelo_smc = elemento(grabber, "Limits")

    def propriedade(id_short, categoria, descricao, valor):
        p = copy.deepcopy(modelo_prop)
        p.find(A + "idShort").text = id_short
        p.find(A + "category").text = categoria
        p.find(A + "description")[0].text = descricao
        p.find(A + "valueType").text = "string"
        p.find(A + "value").text = valor
        se = ET.Element(A + "submodelElement")
        se.append(p)
        return se

    td = copy.deepcopy(grabber)
    td.find(A + "idShort").text = "TechnicalData"
    td.find(A + "identification").text = ID_TECHNICAL_DATA
    lista = td.find(A + "submodelElements")
    for se in list(lista):
        lista.remove(se)
    for args in TECHNICAL_DATA:
        lista.append(propriedade(*args))
    smc = copy.deepcopy(modelo_smc)
    smc.find(A + "idShort").text = "Communication"
    smc.find(A + "description")[0].text = "Communication interface used by the integration layer"
    valores = smc.find(A + "value")
    for se in list(valores):
        valores.remove(se)
    for args in COMMUNICATION:
        valores.append(propriedade(*args))
    se_smc = ET.Element(A + "submodelElement")
    se_smc.append(smc)
    lista.append(se_smc)
    raiz.find(A + "submodels").append(td)

    # 3) referência ao novo submodelo no AAS
    refs = raiz.find(f"{A}assetAdministrationShells/{A}assetAdministrationShell/{A}submodelRefs")
    nova_ref = copy.deepcopy(refs.findall(A + "submodelRef")[-1])
    nova_ref.find(f"{A}keys/{A}key").text = ID_TECHNICAL_DATA
    refs.append(nova_ref)

    ET.indent(raiz, space="  ")
    arquivos[nome_xml] = b'<?xml version="1.0"?>\r\n' + ET.tostring(raiz, encoding="utf-8").replace(b"\n", b"\r\n")
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    print(f"AASX do CR3 salvo em {saida}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
