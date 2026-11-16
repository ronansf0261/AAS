"""Substitui as imagens-placeholder do relatório pelas fotos reais.

Uso (na pasta Hermes/):
    pip install pillow
    python scripts/inserir_fotos.py

Por padrão procura as fotos em fotos/ com os nomes originais do Drive.
Também aceita caminhos explícitos:
    python scripts/inserir_fotos.py --fig2 a.jpg --fig3 b.jpg --fig4 c.jpg

Cada placeholder é localizado pelo nome do objeto no Word ("Figura 2", "Figura 3",
"Figura 4"), então o script continua funcionando mesmo que o texto do relatório
seja editado. A largura da figura é mantida e a altura segue a proporção da foto,
limitada a 9 cm.
"""
import argparse
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Instale o Pillow antes: pip install pillow")

BASE = Path(__file__).resolve().parent.parent
ENTRADA = BASE / "relatorio" / "Projeto_Hermes_Atividades_01-14_10.docx"
SAIDA = BASE / "relatorio" / "Projeto_Hermes_Atividades_01-14_10_final.docx"
PADRAO = {
    2: BASE / "fotos" / "WhatsApp Image 2026-10-14 at 14.50.13.jpeg",
    3: BASE / "fotos" / "WhatsApp Image 2026-10-14 at 14.50.13 (1).jpeg",
    4: BASE / "fotos" / "WhatsApp Image 2026-10-14 at 14.20.54.jpeg",
}
EMU_POR_CM = 360000
ALTURA_MAX = 9 * EMU_POR_CM


def preparar_jpeg(caminho: Path) -> tuple[bytes, int, int]:
    """Corrige a rotação EXIF e devolve (bytes JPEG, largura, altura)."""
    with Image.open(caminho) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if max(im.size) > 2000:
            im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue(), im.width, im.height


def main() -> None:
    ap = argparse.ArgumentParser()
    for n in (2, 3, 4):
        ap.add_argument(f"--fig{n}", type=Path, default=PADRAO[n])
    ap.add_argument("--entrada", type=Path, default=ENTRADA)
    ap.add_argument("--saida", type=Path, default=SAIDA)
    args = ap.parse_args()

    fotos = {n: getattr(args, f"fig{n}") for n in (2, 3, 4)}
    faltando = [str(p) for p in fotos.values() if not p.exists()]
    if faltando:
        sys.exit("Fotos não encontradas:\n  " + "\n  ".join(faltando))

    with zipfile.ZipFile(args.entrada) as zin:
        arquivos = {i.filename: zin.read(i.filename) for i in zin.infolist()}

    doc = arquivos["word/document.xml"].decode("utf-8")
    rels = arquivos["word/_rels/document.xml.rels"].decode("utf-8")

    for n, foto in fotos.items():
        bloco = None
        for m in re.finditer(r"<w:drawing>.*?</w:drawing>", doc, flags=re.S):
            if re.search(rf'<wp:docPr [^>]*name="Figura {n}"', m.group(0)):
                bloco = m
                break
        if bloco is None:
            sys.exit(f"Não encontrei o placeholder da Figura {n} no documento.")

        dados, w, h = preparar_jpeg(foto)
        xml = bloco.group(0)
        rid = re.search(r'r:embed="([^"]+)"', xml).group(1)
        cx = int(re.search(r'<wp:extent cx="(\d+)"', xml).group(1))
        cy = round(cx * h / w)
        if cy > ALTURA_MAX:
            cy = ALTURA_MAX
            cx = round(cy * w / h)

        novo_xml = re.sub(r'cx="\d+" cy="\d+"', f'cx="{cx}" cy="{cy}"', xml)
        doc = doc[: bloco.start()] + novo_xml + doc[bloco.end():]

        nome_media = f"media/figura{n}_foto.jpeg"
        arquivos["word/" + nome_media] = dados
        rels = re.sub(rf'(Id="{rid}"[^>]*Target=")media/[^"]+(")', rf"\g<1>{nome_media}\g<2>", rels)
        print(f"Figura {n}: {foto.name} ({w}×{h}) → {cx / EMU_POR_CM:.1f} × {cy / EMU_POR_CM:.1f} cm")

    arquivos["word/document.xml"] = doc.encode("utf-8")
    arquivos["word/_rels/document.xml.rels"] = rels.encode("utf-8")

    # Remove as imagens de placeholder que ficaram sem referência
    usados = set(re.findall(r'Target="(media/[^"]+)"', rels))
    for nome in [k for k in arquivos if k.startswith("word/media/")]:
        if nome[len("word/"):] not in usados:
            del arquivos[nome]

    tmp = args.saida.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for nome, conteudo in arquivos.items():
            zout.writestr(nome, conteudo)
    shutil.move(tmp, args.saida)
    print(f"\nRelatório salvo em: {args.saida}")


if __name__ == "__main__":
    main()
