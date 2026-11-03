from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

DPI = 70
CITA = re.compile("[““]")


def _pdf(docx: Path, destino: Path) -> Path:
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(destino), str(docx)],
        check=True,
        capture_output=True,
    )
    return destino / f"{docx.stem}.pdf"


def _paginas(pdf: Path) -> int:
    salida = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", salida, re.MULTILINE).group(1))


def _primera_con_cita(pdf: Path, total: int) -> int:
    for n in range(1, total + 1):
        texto = subprocess.run(
            ["pdftotext", "-f", str(n), "-l", str(n), str(pdf), "-"], check=True, capture_output=True, text=True
        ).stdout
        if CITA.search(texto):
            return n
    return 1


def _imagen(pdf: Path, pagina: int, destino: Path) -> Image.Image:
    prefijo = destino / f"{pdf.stem}-{pagina}"
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-f", str(pagina), "-l", str(pagina), "-png", "-singlefile", str(pdf), str(prefijo)],
        check=True,
    )
    return Image.open(f"{prefijo}.png").convert("RGB")


def _juntar(izq: Image.Image, der: Image.Image, rotulo: str, ruta: Path) -> None:
    alto = max(izq.height, der.height)
    banda = 24
    lienzo = Image.new("RGB", (izq.width + der.width + 10, alto + banda), "white")
    lienzo.paste(izq, (0, banda))
    lienzo.paste(der, (izq.width + 10, banda))
    dibujo = ImageDraw.Draw(lienzo)
    dibujo.text((4, 6), f"{rotulo} | izquierda: generado | derecha: referencia", fill="black")
    lienzo.save(ruta)


def comparar(fallo: Path, referencia: Path, salida: Path) -> list[Path]:
    salida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        generado = _pdf(fallo, tmp)
        n_gen, n_ref = _paginas(generado), _paginas(referencia)
        pares = {
            "primera": (1, 1),
            "cita": (_primera_con_cita(generado, n_gen), _primera_con_cita(referencia, n_ref)),
            "ultima": (n_gen, n_ref),
        }
        creados = []
        for nombre, (pg, pr) in pares.items():
            ruta = salida / f"{fallo.stem}_{nombre}.png"
            rotulo = f"{nombre}: generado p.{pg}/{n_gen}, referencia p.{pr}/{n_ref}"
            _juntar(_imagen(generado, pg, tmp), _imagen(referencia, pr, tmp), rotulo, ruta)
            creados.append(ruta)
    return creados


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("uso: comparar_visual.py <fallo.docx> <referencia.pdf> <salida_dir>", file=sys.stderr)
        return 2
    for ruta in comparar(Path(argv[1]), Path(argv[2]), Path(argv[3])):
        print(ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
