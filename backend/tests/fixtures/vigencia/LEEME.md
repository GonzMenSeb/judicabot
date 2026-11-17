# Fixtures del certificado de vigencia

Todo lo que hay en esta carpeta es **sintético**: ninguno de los nombres, cédulas, tarjetas
profesionales, números de certificado ni códigos de verificación corresponde a una persona real.
Los certificados reales no se versionan; se guardan fuera del repositorio, en
`$TUTELA2_DATOS/vigencias/*.pdf`, y los lee `tests/test_vigencia_real.py` (se omite si la carpeta
no existe).

| Archivo | Qué es |
|---|---|
| `formulario.html` | Reconstrucción de la página pública `Certificados.aspx` a partir de su lista de campos (campos ocultos de ASP.NET, `ddlCalidad`, `ddlTipoDocumento`, `txtDocumento`, `btnTpVigente`). Los valores de `__VIEWSTATE` y `__EVENTVALIDATION` son inventados. No lleva datos personales. |
| `vigente.txt` | Texto en el formato de `pdftotext -layout` de un certificado con la inscripción y la tarjeta `VIGENTE` y `NO REGISTRA` observaciones. Es el diseño de un certificado real con todos los datos personales cambiados por valores ficticios. |
| `no_vigente.txt` | Igual, con el estado de la tarjeta `SUSPENDIDO` y una observación. |
| `observaciones.txt` | Tarjeta `VIGENTE` pero con una observación (partida en dos líneas). |
| `sin_tpa.txt` | Sin la sección «VIGENCIA TPA»; la inscripción en el RNA figura `EXCLUIDO(A)`. |
| `otra_cedula.txt` | Un certificado válido, pero de otra cédula y otro nombre que los de `vigente.txt`. |
| `no_inscrito.txt` | Texto en el formato de `pdftotext -layout` del certificado que expide la Rama Judicial para una cédula que **no** está inscrita como abogado(a): sin nombre ni tablas de RNA/TPA, solo «la persona identificada con Cédula de Ciudadanía N.° …, NO ESTÁ INSCRITA…», el número de certificado, la fecha y el código de verificación. Es el diseño de un certificado real ya anonimizado: la cédula es `1` (no es una persona; tampoco una cédula que se pueda consultar, así que el texto tal cual no se lee y las pruebas la cambian por `1000000006`), y el número, el código y quien firma son ficticios. |
| `vacio.txt` | Vacío: el PDF no tenía texto. |
| `sintetico.pdf` | `vigente.txt` dibujado con Helvetica y cifrado con AES-256 y clave de usuario vacía, como el PDF real. Lo construye `scripts/fixture_vigencia.py`. |
| `no_inscrito.pdf` | `no_inscrito.txt` con la cédula ficticia `1000000006`, dibujado y cifrado igual que `sintetico.pdf`. |
| `e2e_vigente.pdf` | `vigente.txt` con el titular cambiado por la abogada ficticia de `scripts/caso_sintetico.py`, cifrado igual. Lo suben las pruebas de punta a punta (la abogada queda en verde). |
| `e2e_no_vigente.pdf` | `no_vigente.txt` (tarjeta `SUSPENDIDO`) con la misma abogada ficticia. Lo suben las pruebas de punta a punta (la abogada queda en rojo y bloquea la decisión). |

## Valores ficticios

| Campo | `vigente.txt` | `e2e_vigente.pdf` y `e2e_no_vigente.pdf` |
|---|---|---|
| Nombre | `MARIA FERNANDA PRUEBA LOPEZ` | `ANDREA PAOLA GIRALDO MONTOYA` |
| Cédula | `1000000001` | `1017234567` |
| Tarjeta profesional | `123456` | `287415` |
| N.° de certificado | `1234567` | `1234567` y `1234568` (los de la plantilla) |
| Código de verificación | `0123456789abcdef` repetido 4 veces | el de la plantilla |

Las demás variantes usan cédulas `1000000002` a `1000000004`, `1000000006` (`no_inscrito.pdf`) y
`1000000099`. La abogada de los
certificados de punta a punta sale de las constantes `ABOGADA`, `CEDULA_ABOGADA_PLANA` y
`TARJETA_ABOGADA_PLANA` de `scripts/caso_sintetico.py`; si cambian, rehaga los dos PDF con
`--e2e` (`tests/test_rutas_apoderados.py` lo comprueba).

## Regenerar

```
cd backend
uv run python scripts/fixture_vigencia.py            # rehace sintetico.pdf desde vigente.txt
uv run python scripts/fixture_vigencia.py --e2e      # rehace e2e_vigente.pdf y e2e_no_vigente.pdf
uv run python scripts/fixture_vigencia.py --estado no_inscrito --cedula 1000000006 \
    -s tests/fixtures/vigencia/no_inscrito.pdf        # rehace no_inscrito.pdf
uv run python scripts/fixture_vigencia.py --estado no_vigente --nombre "NOMBRE FICTICIO" \
    --cedula 1000000005 --tarjeta 123460 -s otro.pdf  # otro titular ficticio
uv run python scripts/anonimizar_certificado.py real.txt -o vigente.txt
```

`--estado` elige la plantilla (`vigente`, `no_vigente`, `observaciones` o `no_inscrito`); `--nombre`,
`--cedula` y `--tarjeta` cambian el titular y exigen `-s`, para no pisar `sintetico.pdf`. La plantilla
`no_inscrito` no trae nombre ni tarjeta: solo admite `--cedula`. Use solo datos ficticios.

`anonimizar_certificado.py` recibe la salida de `pdftotext -layout` (o el PDF) y cambia el nombre,
la cédula, la tarjeta, el número de certificado, el código de verificación y el nombre de quien
firma por valores ficticios de la misma longitud. Revise a mano las fechas y las observaciones
antes de versionar el resultado.

Los bytes de los PDF cambian en cada ejecución del script (el cifrado usa sales aleatorias); las
pruebas solo comparan el texto que se extrae de ellos.
