"""Certificados de vigencia reales, guardados fuera del repositorio.

Lee los PDF de $TUTELA2_DATOS/vigencias/*.pdf (los que descarga la Rama Judicial, nombrados
CV_RNA-TPA_<cédula>.pdf) y comprueba que el lector los entiende por completo con el extractor
de texto de esta máquina (pdftotext -layout si está instalado, pypdf si no). Se omite si la
carpeta no existe o no tiene PDF. Los datos personales no salen en los mensajes: las pruebas se
identifican por posición y los asertos solo comparan booleanos.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tutela2.vigencia import clasificar, leer_certificado

DATOS = os.environ.get("TUTELA2_DATOS")
CARPETA = Path(DATOS) / "vigencias" if DATOS else None
PDFS = sorted(CARPETA.glob("*.pdf")) if CARPETA is not None and CARPETA.is_dir() else []

pytestmark = pytest.mark.skipif(
    not PDFS, reason="TUTELA2_DATOS/vigencias no existe o no tiene certificados PDF"
)


@pytest.mark.parametrize("ruta", PDFS, ids=[f"certificado-{i}" for i in range(len(PDFS))])
def test_certificado_real_se_lee_por_completo(ruta: Path):
    cert = leer_certificado(ruta.read_bytes())
    leido = cert is not None
    assert leido, "el certificado no se pudo leer"

    assert re.fullmatch(r"\d{5,10}", cert.documento or ""), "cédula ilegible"
    assert len((cert.nombre or "").split()) >= 2, "nombre ilegible"
    assert re.fullmatch(r"[0-9a-f]{64}", cert.codigo_verificacion or ""), "código de verificación ilegible"
    assert bool(cert.numero), "número de certificado ilegible"
    assert bool(cert.expedido), "fecha de expedición ilegible"
    assert bool(cert.rna_estado), "estado del RNA ilegible"
    if cert.tpa_estado is not None:
        assert re.fullmatch(r"\d{3,7}", cert.tpa_numero or ""), "tarjeta profesional ilegible"
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", cert.tpa_fecha or ""), "fecha de la tarjeta ilegible"

    estado = clasificar(cert, cert.documento, cert.nombre)
    assert estado in ("vigente", "vigente_obs", "no_vigente"), "el certificado no se pudo clasificar"

    del_nombre = re.fullmatch(r"CV_RNA-TPA_(\d+)\.pdf", ruta.name)
    if del_nombre:
        assert del_nombre.group(1) == cert.documento, "la cédula del archivo no es la del certificado"
