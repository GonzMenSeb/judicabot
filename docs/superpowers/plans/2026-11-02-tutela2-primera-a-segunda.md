# Tutela 2.ª instancia: de 01PrimeraInstancia a 02SegundaInstancia — Plan de implementación

> **Para agentes:** este plan se ejecuta por olas con subagentes (implementación en Sonnet, revisión adversarial en Opus en las barreras). Los pasos usan casillas (`- [ ]`). Cada tarea solo toca los archivos que tiene asignados.

**Objetivo:** que la carpeta `01PrimeraInstancia`, arrastrada a la interfaz, produzca `salidas/02SegundaInstancia/C01Principal/` numerada (acta copiada, auto que asume, fallo y formato de calidad opcional), el oficio a la Corte por radicar, borradores de correo y documentos de trabajo, con el fallo como copia visual de 53001/12001.

**Arquitectura:** se conserva el grafo LangGraph (apertura → consideraciones → decisión humana → caso concreto → ensamblar). Cambian: ingesta (clasificación por contenido, solo 1.ª instancia, etapa de revisión de documentos), textos fijos (nuevo `formulas.py`), maquetación generación B (nuevo `formato_b.py` + `render.py`), documentos nuevos (`documentos/`), armado de carpetas (`salidas.py`, `expediente.py`), API/servidor (estado `revision`, comando `iniciar`, árbol y zip) e interfaz (arrastrar y soltar, pantalla Documentos).

**Tecnología:** Python 3.12, uv, LangGraph, pydantic v2, python-docx, pypdf/pdftotext, pytesseract+pypdfium2, FastAPI, JS sin framework.

**Spec:** `docs/superpowers/specs/2026-11-02-tutela2-primera-a-segunda-design.md`. Material: `referencia/analisis/*.md`, `referencia/analisis/ground_truth_1a.json`, `referencia/casos/<radicado>/` (gitignored, con datos personales: nunca copiar texto de casos a código ni a pruebas versionadas).

## Restricciones globales

- Comentarios: los mínimos imprescindibles. Nada de docstrings ni comentarios narrativos.
- No inventar: si un valor no está en este plan, en el spec o en `referencia/`, se mide o se pregunta; nunca se supone.
- No hacer commits (el usuario no lo ha autorizado). No ejecutar formateadores sobre todo el repo. Cada tarea corre solo sus pruebas: `cd backend && uv run pytest tests/<archivo> -q`. La suite completa se corre en la barrera.
- Cada tarea toca **solo** los archivos que lista. `models.py` y `config.py` quedan congelados después de la Tarea 1.
- Ningún texto, nombre ni número de un caso real entra en `backend/` (código ni pruebas). Los fixtures con datos reales van en `referencia/` (gitignored).
- Generación B es la predeterminada y la única en la que se exigen formato y textos nuevos. La A sigue funcionando (usa los textos nuevos con sus títulos, fórmula de mérito y página antiguos).
- Nunca generar constancias de hechos ajenos o futuros (actas, impresiones de correos enviados). Nunca firmar ni incrustar firmas.
- Fechas en letras con día de dos cifras: `seis (06) de octubre de dos mil veintiséis (2026)`.
- `⟦FALTA: …⟧` resaltado en amarillo para todo dato que no se pudo extraer.

## Decisiones tomadas en el plan (llamadas del constructor, a revisar por el usuario)

1. **Competencia según 53001** (regla "manda 53001"): subtítulo `Competencia`, primer párrafo con "Este despacho" en minúscula y segundo párrafo que nombra al a quo y la fecha. El spec §7.1 decía que ya coincidía, pero eso solo vale contra 12001.
2. NOTIFICAR y REMITIR según 53001 (sin "e intervinientes"; REMITIR sin artículo citado).
3. Nombre del juzgado de origen: se extrae del fallo de 1.ª instancia y se valida con el número del radicado. Si no aparece, se deriva del radicado (cardinal en letras) y se alerta. Tres formas: encabezado `JUZGADO 18 …`, cuerpo `Juzgado Dieciocho …`, PRIMERO `Juzgado Dieciocho (18) …`.
4. Margen inferior del fallo 73,4 pt (el verificador excluyó 72 pt; rango medido 73,1–73,7).
5. Títulos I–VII con tabulación (en 53001 VI y VII usan espacio; se unifica a tabulación por el spec §7.1.6).
6. Borradores de correo en `.docx` (la tabla de 3 celdas se pega en Outlook).
7. Derechos en el RESUELVE con artículo calculado: "al mínimo vital", "a la vida digna" (léxico de femeninos, ver Tarea 5).
8. Etiqueta de la parte accionada/vinculada: femenino singular por defecto ("Accionada"), concordada en número; el modelo puede indicar género.
9. Clasificación por reglas deterministas sin paso de LLM (la prueba de punta a punta en modo `fake` no podría ejercer un clasificador con modelo).

## Foco de revisión

1. Carpeta soltada de cualquiera de las dos formas (solo `01PrimeraInstancia` o la carpeta del caso con `02SegundaInstancia`/`02SegundaInstacia`): todo es 1.ª instancia salvo lo que está bajo una carpeta `02Segunda*`, que se ignora con una alerta. Lo prueba la Tarea 4.
2. Archivos con nombres no informativos (`001.pdf`, `002.pdf`…): la clasificación se sostiene por contenido. Lo prueba la Tarea 4 (variante anónima del marcador).
3. Caso sin acta de reparto de la impugnación (40601): no se bloquea, el auto queda como 001 y no hay hueco. Lo prueban las Tareas 4 y 10.
4. Rutas anidadas de descarga: `trabajo/previo.docx` y `02SegundaInstancia/C01Principal/003…docx` se descargan; `../` y rutas absolutas se rechazan. Lo prueban las Tareas 10 y 12.
5. Destinatarios con artículo ("el BANCO X") y "respecto de el Juzgado": nunca "a el" ni "de el". Lo prueba la Tarea 5.

---

## Mapa de archivos y olas

| Ola | Tarea | Archivos (exclusivos) |
|---|---|---|
| 1 | T1 Modelos y configuración | `tutela2/models.py`, `tutela2/config.py`, `tests/test_models.py` (nuevo) |
| 1 | T2 Letras y radicado | `tutela2/letras.py` (nuevo), `tutela2/radicado.py` (nuevo), `tests/test_letras.py`, `tests/test_radicado.py` |
| 1 | T3 Primitivas de formato B | `tutela2/formato_b.py` (nuevo), `tutela2/assets/rama_judicial_logo.png` (copia de `referencia/assets/rama_judicial_header_logo.png`), `tutela2/documentos/__init__.py` (vacío), `tests/test_formato_b.py` |
| 1 | T4 Marcador de aceptación y fixtures | `tests/test_aceptacion.py` (nuevo), `backend/pyproject.toml`, `referencia/decisiones/<radicado>.json` ×9 |
| 2 | T5 Fórmulas → T6 Maquetación del fallo (en cadena) | T5: `tutela2/formulas.py`, `tests/test_formulas.py`. T6: `tutela2/render.py`, `tests/test_render.py` |
| 2 | T7 Ingesta por contenido | `tutela2/ingest.py`, `tutela2/clasificar.py` (nuevo), `tests/test_ingest.py`, `tests/test_clasificar.py` |
| 2 | T8 Auto y oficio | `tutela2/documentos/auto.py`, `tutela2/documentos/oficio.py`, `tests/test_doc_auto_oficio.py` |
| 2 | T9 Formato Factor Calidad | `tutela2/documentos/formato.py`, `tutela2/assets/formato_factor_calidad.docx` (si se consigue la plantilla oficial), `tests/test_doc_formato.py` |
| 2 | T9b Borradores de correo | `tutela2/documentos/correos.py`, `tests/test_doc_correos.py` |
| — | Barrera 2 + revisión Opus | — |
| 3 | T10 Salidas, expediente, API y grafo | `tutela2/salidas.py`, `tutela2/expediente.py` (nuevos), `tutela2/api.py`, `tutela2/graph.py`, `tutela2/cli.py`, `tests/test_expediente.py` (nuevo), `tests/test_graph.py`, `tests/test_api.py` (nuevo) |
| 3 | T11 Prompts y cliente falso | `tutela2/prompts/*.md`, `tutela2/llm.py`, `tests/test_llm.py` |
| 3 | T12 Servidor | `tutela2/server.py`, `tests/test_server.py` |
| 3 | T13 Interfaz | `tutela2/static/app.js`, `tutela2/static/styles.css`, `tutela2/static/index.html` |
| 4 | T14 Aceptación punta a punta, comparación visual, README | `tests/test_aceptacion.py`, `backend/scripts/comparar_visual.py` (nuevo), `README.md` |
| — | Barrera final + revisión Opus | — |

---

## Contratos compartidos (fijados aquí; nadie los cambia sin actualizar este plan)

### C1. Modelos (T1)

`Rol` agrega `"anexo"`. Campos nuevos (todos opcionales o con valor por defecto, para no romper JSON guardados):

```python
class Doc:            evidencia: str = ""; rol_origen: Literal["contenido", "usuario"] = "contenido"
class Ingesta:        esperados_faltantes: list[str] = []; alertas_lectura: list[str] = []; ignorados: list[str] = []
class Metadatos / MetadatosLLM (ambos):
    impugnantes: list[str] = []                       # frase completa por impugnante: "la ciudadana Ana Pérez identificada con C.C. 1.234"
    resultado_a_quo: Optional[str] = None             # verbo en pasado 3.ª sing.: "declaró improcedente el amparo …"
    accionante_tratamiento: Optional[str] = None      # "la señora" | "el señor" | "la sociedad" …
    accionante_identificacion: Optional[str] = None   # "identificada con cédula de ciudadanía 1.000.000.000"
    juez_a_quo_nombres: Optional[str] = None
    juez_a_quo_apellidos: Optional[str] = None
    genero_accionadas: Optional[Literal["m", "f"]] = None
    genero_vinculadas: Optional[Literal["m", "f"]] = None
class Metadatos (solo):
    juzgado_a_quo_numero: Optional[int] = None
    juzgado_a_quo_funcion: Optional[Literal["conocimiento", "control_garantias"]] = None
    juzgado_a_quo_letras: Optional[str] = None        # "Dieciocho", "Décimo", "Cuarenta y Siete"
    juzgado_a_quo_plural: bool = False                # "con Funciones de"
    juzgado_a_quo_derivado: bool = False              # True si salió del radicado y no del texto del fallo
class Orden:          mismo_termino: bool = False
class Decision:
    numerales_libres: list[str] = []
    orden_numerales: list[str] = []
    generar_formato: bool = False
    fecha_fallo: Optional[str] = None                 # ISO; None = hoy
    fecha_oficio: Optional[str] = None                # ISO; None = fecha_fallo
    etiqueta_encabezado: str = ""                     # sobrescribe "REVOCA Y NIEGA", p. ej. "CONFIRMA CON MODIFICACIONES"
class DatosAuto(BaseModel):                           # nuevo
    fecha: Optional[str] = None; accionante: Optional[str] = None; accionada: Optional[str] = None
```

`Decision.errores()` agrega: cada `orden_numerales` debe ser una clave válida (C3); cada numeral libre no vacío; `fecha_fallo`/`fecha_oficio` ISO válidas si vienen.

### C2. Configuración (T1)

`Despacho` (se conservan `nombre`, `nombre_cuerpo`, `ciudad`, `pie`, `correo`):

```python
juez: str = "SANTIAGO ALEJANDRO CADAVID DUQUE"
cargo_juez: str = "JUEZ"
escribiente: str = "John Mendoza"
cargo_escribiente: str = "Escribiente"
firmante_oficio: str = "JOHN MANUEL MENDOZA"
cargo_firmante_oficio: str = "Escribiente"
cargo_evaluador: str = "Juez 3° Penal del Circuito de Conocimiento"
correo: str = "pcto03med@cendoj.ramajudicial.gov.co"
telefono_correo: str = "Tel: 6042328525 Ext. 2903"
cierre_fallo: str = "NOTIFÍQUESE Y CÚMPLASE"
cierre_auto: str = "NOTIFÍQUESE Y CÚMPLASE"
pie_fallo: list[str] = [
    "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
    "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
    "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
]
pie_auto: list[str] = [
    "Juzgado Tercero Penal del Circuito con Función de Conocimiento, Edificio José Félix de Restrepo Carrera 52 # 42 – 73, Medellín, Antioquia",
    "Correo Electrónico pcto03med@cendoj.ramajudicial.gov.co, Teléfono 2328525 Ext. 92903",
]
```
(el guion de "42 – 73" es U+2013).

### C3. Claves de numerales del RESUELVE (T5, consumidas por T6, T10, T13)

`"resultado"`, `"sustitutiva"`, `"orden:<i>"` (i desde 0 sobre `decision.ordenes`), `"prevenir"`, `"desvincular"`, `"compulsa"`, `"libre:<i>"`, `"notificar"`, `"remitir"`. Orden por defecto: resultado, sustitutiva (si no es CONFIRMAR), órdenes, prevenir, desvincular, compulsa, libres, notificar, remitir. `orden_numerales` lista primero las claves que nombre (válidas, sin repetir); las existentes no nombradas siguen en el orden por defecto.

### C4. Rutas de salida (T10, `tutela2/salidas.py`; nadie más arma rutas de `salidas/`)

```
<caso>/salidas/02SegundaInstancia/C01Principal/001ActaRepartoSegunda.pdf     (si hay acta de impugnación)
<caso>/salidas/02SegundaInstancia/C01Principal/00NAutoAsumeSegunda<YYYYNNNNN>.docx
<caso>/salidas/02SegundaInstancia/C01Principal/00NFalloSegunda<YYYYNNNNN>.docx
<caso>/salidas/02SegundaInstancia/C01Principal/00NFormatoCalificacion<YYYYNNNNN>.docx  (si decision.generar_formato)
<caso>/salidas/por_radicar/OficioRemiteCorteConstitucional.docx
<caso>/salidas/borradores_correo/NotificacionFalloPartes.docx
<caso>/salidas/borradores_correo/EnvioFormatoCalidad.docx      (si formato)
<caso>/salidas/borradores_correo/RemisionCompulsaCopias.docx   (si compulsa)
<caso>/salidas/trabajo/{previo,informe_verificacion,declaracion_ia,requerimiento}.docx
```
`YYYYNNNNN` = `radicado.corto(cui)` = dígitos 13 a 21.

### C5. API (T10) y servidor (T12)

Estados: `sin_iniciar`, `incompleto`, `revision`, `esperando_decision`, `terminado`, `error` (más `corriendo` en el servidor).

```python
api.nuevo(caso_dir) -> dict        # ingesta, borra salidas/ e hilo, genera 001/002 (y requerimiento si falta algo) → "revision" | "incompleto"
api.revisar(caso_dir, roles: dict[str, str] | None, auto: dict | None) -> dict   # solo sin hilo; "revision" | "incompleto"
api.iniciar(caso_dir) -> dict      # exige caso.json completo; corre el grafo hasta la decisión → "esperando_decision"
api.estado(caso_dir) -> dict
api.decidir(caso_dir, decision: dict) -> dict
api.continuar(caso_dir) -> dict
```
Respuesta: `{"ok", "estado", "payload", "salidas": [rutas relativas a salidas/, posix, ordenadas], "resumen", "error"}`. En `revision`/`incompleto`, `resumen` incluye `documentos: [{doc_id, ruta, nombre, rol, rol_origen, evidencia, paginas, paginas_sin_texto, ruido, ajeno}]`, `faltantes`, `esperados_faltantes`, `alertas`, `metadatos`, `auto` (DatosAuto efectivo con valores por defecto).

Servidor:
- `POST /api/casos/{id}/run` con `cmd ∈ {"nuevo","iniciar","decidir","continuar"}`.
- `PUT /api/casos/{id}/revision` cuerpo `{"roles": {doc_id: rol}, "auto": {...}}` → `api.revisar` síncrono; 409 si hay un job corriendo.
- `GET /api/casos/{id}/salidas` → `{"archivos": [...]}`.
- `GET /api/casos/{id}/salidas/{ruta:path}` → archivo (vía `salidas.resolver`).
- `GET /api/casos/{id}/zip` → `application/zip` de `salidas/` con nombre `<id>.zip`.

---

## Ola 1

### Tarea 1: Modelos y configuración

**Archivos:** `tutela2/models.py`, `tutela2/config.py`, `tests/test_models.py`.
**Produce:** C1, C2.

- [ ] Prueba `test_models.py`:
  - `Decision(accion="decidir", resultado="REVOCAR", sustitutiva="NEGAR", eje="x", orden_numerales=["zzz"]).errores()` contiene un mensaje con `"zzz"`; con `orden_numerales=["resultado","notificar","orden:0"]` y una orden, sin errores.
  - `fecha_fallo="2026-13-01"` produce error; `"2026-10-21"` no.
  - `numerales_libres=["  "]` produce error.
  - `Config().despacho.pie_fallo[1] == "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19"` y `Config().despacho.juez == "SANTIAGO ALEJANDRO CADAVID DUQUE"`.
  - Un `Ingesta` y una `Decision` serializados con el esquema anterior (sin los campos nuevos) se cargan sin error.
- [ ] Correr y ver fallar; implementar; correr `tests/test_models.py` y además `tests/test_graph.py tests/test_render.py` (no deben romperse por los campos nuevos).

### Tarea 2: Letras y radicado

**Archivos:** `tutela2/letras.py`, `tutela2/radicado.py`, `tests/test_letras.py`, `tests/test_radicado.py`.
**Produce:**
```python
# letras.py
MESES: tuple[str, ...]
numero_a_letras(n: int, genero: str = "") -> str          # copia exacta de render.numero_a_letras (no borrarla de render.py)
fecha_larga(iso: str | None) -> str                        # "seis (06) de octubre de dos mil veintiséis (2026)"; inválida → "⟦FALTA: fecha⟧"
fecha_corta(iso: str | None) -> str                        # "21 de septiembre de 2026"
numero_titulo(n: int) -> str                               # 18 → "Dieciocho", 47 → "Cuarenta y Siete", 21 → "Veintiuno"
letras_a_numero(texto: str) -> int | None                  # "Dieciocho"→18, "Cuarenta y Siete"→47, "Décimo"→10, "Veintidós"→22, "primero"→1; sin tildes ni mayúsculas importa
# radicado.py
digitos(texto: str) -> str
corto(cui: str) -> str                                     # "05001408801820260053001" → "202600530"
espaciado(cui: str) -> str                                 # → "050014088018 2026 00530 01"
con_guion(cui: str) -> str                                 # → "050014088018202600530-01"
cui_1a(cui: str) -> str ; cui_2a(cui: str) -> str          # primeros 21 dígitos + "00" / "01"
@dataclass(frozen=True) class Juzgado: numero: int; funcion: Literal["conocimiento","control_garantias"]; letras: str; plural: bool = False
juzgado_de_radicado(cui: str) -> Juzgado | None            # dígitos[5:9] "4009" → conocimiento, "4088" → control_garantias; numero = int(dígitos[9:12]); letras = numero_titulo(numero)
nombre_juzgado(j: Juzgado, forma: Literal["cuerpo","cuerpo_numero","digitos","encabezado"]) -> str
```
Formas (`funcion` conocimiento → "Conocimiento", control_garantias → "Control de Garantías"; `plural` → "Funciones"):
- cuerpo: `Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín`
- cuerpo_numero: `Juzgado Dieciocho (18) Penal Municipal con Función de Control de Garantías de Medellín`
- digitos: `Juzgado 18 Penal Municipal con Función de Control de Garantías de Medellín`
- encabezado: `JUZGADO 18 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN`

- [ ] Pruebas con esos valores exactos más: `fecha_larga("2026-10-06") == "seis (06) de octubre de dos mil veintiséis (2026)"`, `fecha_larga("2026-10-21") == "veintiuno (21) de octubre de dos mil veintiséis (2026)"`, `fecha_larga("2026-10-01") == "uno (01) de octubre de dos mil veintiséis (2026)"`; `juzgado_de_radicado("05001400904720260049501")` → 47 conocimiento; `juzgado_de_radicado("05001310400320260000101")` → None.
- [ ] Implementar y correr ambas pruebas.

### Tarea 3: Primitivas de formato B

**Archivos:** `tutela2/formato_b.py`, `tutela2/assets/rama_judicial_logo.png`, `tutela2/documentos/__init__.py`, `tests/test_formato_b.py`.
**Fuente de valores:** `referencia/analisis/format_spec.md` §1–§3, §12 corregido por `format_spec_check.md` (manda el check).
**Produce:**
```python
LOGO: Path
def fuente(run, nombre: str, tam: float, *, negrita=None, cursiva=None, subrayado=None) -> None   # w:rFonts ascii/hAnsi/eastAsia/cs
def escala(run, porcentaje: int) -> None                    # <w:w w:val="114"/>; 100 no escribe nada
def espaciado(par, *, antes: float = 0, despues: float = 0, multiple: float | None = None, exacto: float | None = None) -> None
def logo(par, ancho_pt: float = 199.1, alto_pt: float = 66.0) -> None
def campo_pagina(par) -> None                              # campo PAGE
def bordes_tabla(tabla, sz_octavos: int = 4) -> None        # todos los bordes single negros
def sangria_tabla(tabla, pt: float) -> None
def alto_minimo_fila(fila, pt: float) -> None
def anchos_columnas(tabla, anchos_pt: list[float]) -> None  # tblGrid + tcW + autofit off
def configurar_fallo(doc, pie: list[str]) -> None
def configurar_auto(doc, pie: list[str]) -> None
def configurar_oficio(doc) -> None
```
Valores de `configurar_fallo`: página 11950 × 19320 twips; márgenes izq/der 54 pt, sup 72 pt, inf 73,4 pt; distancia de encabezado 0; distancia de pie 22,2 pt. Encabezado: un párrafo centrado, interlineado sencillo, 0/0, con el logo 199,1 × 66,0 pt; marca de párrafo Verdana 11. Pie: 3 párrafos centrados Cambria cursiva 8, sencillo, 0/0, sangría derecha 12 pt; línea 2 con escala 108 %. Número de página: campo PAGE Times New Roman 10 en un párrafo con marco (`w:framePr`, `hAnchor="page"`, `vAnchor="page"`, x 504,58 pt, y 868,20 pt, ancho 16,56 pt, alto 12,96 pt, `hRule="exact"`).
`configurar_auto`: 612,48 × 936,48 pt; márgenes y posiciones medidos por la Tarea 8 (aquí solo página, pie de 2 líneas centradas y un parámetro de márgenes). `configurar_oficio`: 612 × 1008 pt.

- [ ] Prueba: crear `Document()`, `configurar_fallo(doc, PIE)` con `PIE` = las 3 líneas de C2 escritas literalmente en la prueba (la Tarea 1 corre en paralelo), guardar y reabrir; afirmar ancho/alto en twips (±1), márgenes (±0,1 pt), una imagen inline en el encabezado con `cx` = Pt(199,1) ±1 % y `cy` = Pt(66,0) ±1 %, 3 párrafos de pie con los textos exactos, `rFonts ascii="Cambria"`, cursiva, `sz=16`, `w:w=108` en todas las corridas de la línea 2, `framePr` con anclas de página y x en twips 10092 ±20, `instrText`/`fldSimple` PAGE con `Times New Roman` y `sz=20`.
- [ ] Prueba de `escala(run, 114)` → XML contiene `w:w w:val="114"`; `bordes_tabla` → `w:sz="4"` en los 6 bordes.
- [ ] Implementar; correr `tests/test_formato_b.py`.

### Tarea 4: Marcador de aceptación y fixtures

**Archivos:** `tests/test_aceptacion.py`, `backend/pyproject.toml`, `referencia/decisiones/<radicado>.json` (9).
- [ ] `pyproject.toml`: registrar el marcador `aceptacion` y `addopts = "-m 'not aceptacion'"`.
- [ ] `test_aceptacion.py`, todo con `pytest.mark.aceptacion` y `skipif` si no existe `referencia/casos` (ruta: `Path(__file__).resolve().parents[2] / "referencia"`):
  - Copia de la entrada a `tmp_path/<caso>/insumos/` en dos formas: **forma A** = contenido de `01PrimeraInstancia` (lo que deja `quitar_carpeta_raiz` al soltar esa carpeta: `insumos/C01Principal/...`); **forma B** = la carpeta del caso entera (`insumos/01PrimeraInstancia/...` y `insumos/02Segunda*/...`). Forma B solo para 34601 (2.ª sin `C01Principal`) y 45901 (`02SegundaInstacia`).
  - **Variante anónima**: forma A con cada archivo renombrado a `NNN<ext>` conservando el orden de rutas.
  - Puntuación por caso, emparejando por nombre de archivo (en la anónima, por posición) con `ground_truth_1a.json`: para cada rol de `{"escrito_tutela","fallo_a_quo","impugnacion","auto_admisorio","auto_concede_impugnacion","acta_reparto_2a"}`, el conjunto de archivos predichos con ese rol debe igualar al de la verdad, salvo los de `confidence == "medium"`, que pueden tener ese rol o no. Los roles `nuevo:*` y los demás se ignoran.
  - `test_ingesta_forma_a[caso]` (9): puntuación sin diferencias, `ing.faltantes == []`, `22SentenciaTutela02072024` no es `fallo_a_quo` en 34601, `025ImpugancionAccionante` es `impugnacion` en 34601.
  - `test_ingesta_forma_b[caso]` (2): igual que A y `ing.ignorados` no vacío; ningún documento de `02Segunda*` aparece en `ing.documentos`.
  - `test_ingesta_anonima[caso]` (9): `faltantes == []` y los roles `escrito_tutela`, `fallo_a_quo`, `impugnacion` exactos.
  - Al fallar, el mensaje lista cada diferencia `archivo: esperado X, obtenido Y (evidencia: …)`.
  - `test_punta_a_punta[caso]` queda como `pytest.skip("Tarea 14")` por ahora.
- [ ] Fixtures `referencia/decisiones/<radicado>.json`: una `Decision` válida por caso que refleje el fallo real (`referencia/analisis/fallo_structure.md` §2 y el PDF del fallo): `resultado`, `sustitutiva`, `eje` breve, `derechos`, `ordenes` (con artículo en el destinatario), `compulsa` en 12001, `generar_formato` true en 49501, 53001, 12001, 45601 y 45901, `fecha_fallo` = fecha real del fallo de 2.ª, `etiqueta_encabezado` cuando el real no es expresable (45301 "CONFIRMA CON MODIFICACIONES", 40601 la suya), `decidido_por` "prueba". Validar cada una con `Decision.model_validate(...).errores() == []`.
- [ ] Correr `uv run pytest tests/test_aceptacion.py -m aceptacion -k ingesta` y guardar el resultado (se espera que falle hoy; es la línea base de la Tarea 7).

---

## Ola 2

### Tarea 5: Fórmulas (textos fijos)

**Archivos:** `tutela2/formulas.py`, `tests/test_formulas.py`. No tocar `render.py`.
**Consume:** C1, C2, `letras`, `radicado`. **Produce:**
```python
SUBTITULO_COMPETENCIA = "Competencia"
COMPETENCIA_1: str
def competencia_2(md: Metadatos) -> str
SUBTITULO_PROCEDIBILIDAD = "Presupuestos Generales de Procedibilidad de la Acción de Tutela"
PROCEDIBILIDAD_P1: str ; PROCEDIBILIDAD_P2: str ; TRANSICION: str
MERITO_ANTES = "En mérito de lo expuesto, el " ; MERITO_DESPUES = ", administrando justicia en nombre de la República y por autoridad de la Ley,"
def juzgado(md: Metadatos, forma: str) -> str          # usa radicado.nombre_juzgado con los campos juzgado_a_quo_*; si faltan, "⟦FALTA: juzgado a quo⟧"
def asunto(md: Metadatos) -> str
def etiqueta_parte(tipo: Literal["Accionad","Vinculad"], genero: str | None, n: int) -> str
def filas_encabezado(md: Metadatos, decision: Decision | None) -> list[tuple[str, str, str]]   # (clave, etiqueta, valor)
def encabezado_decision(decision: Decision | None) -> str
def con_articulo(derecho: str) -> str
def contraer(prep: Literal["a", "de"], texto: str) -> str
def ordinal(i: int) -> str
@dataclass class Numeral: clave: str; texto: str; negritas: list[str]; literales: list[str]
def numerales(decision: Decision, md: Metadatos) -> list[Numeral]   # orden según C3; `texto` empieza con el verbo (sin ordinal)
def cierre_otras_determinaciones(c: Compulsa) -> str
```
Textos literales (copiar exactos):
- `COMPETENCIA_1` = "Este despacho es competente para conocer y resolver el recurso de impugnación interpuesto contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de amparo. En su condición de superior funcional, le corresponde adelantar un examen integral de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina fijada por la Corte Constitucional."
- `competencia_2` = "Este Despacho es competente para resolver la impugnación presentada contra la sentencia de tutela proferida el {fecha_corta(fallo_a_quo)} por el {juzgado cuerpo}, de conformidad con el artículo 32 del Decreto 2591 de 1991."
- `PROCEDIBILIDAD_P1` y `_P2`: los textos de `referencia/analisis/fallo_structure.md` §3.6 (P1 y P2, versión de 12001/53001, sin la cláusula de 40601).
- `TRANSICION` = "Definido el marco jurídico aplicable y los criterios constitucionales relevantes, procede este Despacho a continuación a examinar la situación fáctica y jurídica específica puesta en conocimiento en este trámite constitucional."
- `asunto` = "Procede el Despacho a resolver {la impugnación presentada | las impugnaciones presentadas} por {impugnantes unidos con ", " y " y "} contra el fallo de tutela emitido el {fecha_larga(fallo_a_quo)} por el {juzgado cuerpo}, por medio del cual se {resultado_a_quo}." Sin `impugnantes` usa `impugnante`; sin ninguno, `⟦FALTA: impugnante⟧`; sin `resultado_a_quo`, `⟦FALTA: resultado del fallo de primera instancia⟧`. Se quita el punto final de `resultado_a_quo` si lo trae.
- `filas_encabezado`: claves y orden `radicado` ("Radicado", `espaciado(cui_2a)`), `accionante` ("Accionante", MAYÚSCULAS), `accionada` (`etiqueta_parte`, valores unidos por ", " en MAYÚSCULAS), `vinculada` (solo si hay), `procedencia` ("Procedencia", forma encabezado), `derechos` (solo si hay; ", " y MAYÚSCULAS), `decision` (solo si `decision` no es None; "Decisión", `encabezado_decision`). `etiqueta_parte("Accionad", None, 1) == "Accionada"`, `("Accionad","m",1) == "Accionado"`, `("Vinculad","m",2) == "Vinculados"`, `("Accionad","f",3) == "Accionadas"`.
- `encabezado_decision`: `etiqueta_encabezado` si no está vacía; si no, el comportamiento actual de `render.decision_encabezado`.
- `con_articulo`: si ya empieza por "al ", "a la ", "a los ", "a las " lo deja; si su primera palabra (sin tildes, minúscula) está en `{"vida","salud","dignidad","igualdad","educacion","vivienda","libertad","intimidad","honra","peticion","integridad","informacion","seguridad","estabilidad","unidad","familia","defensa","proteccion","personalidad","imagen","propiedad","alimentacion","identidad","nacionalidad","libre"}` → "a la …"; si no → "al …". Ejemplos: "mínimo vital" → "al mínimo vital", "vida digna" → "a la vida digna", "debido proceso" → "al debido proceso", "hábeas data" → "al hábeas data", "petición" → "a la petición". El texto se escribe como venga (minúsculas en el cuerpo).
- `contraer("a", "el BANCO X") == "al BANCO X"`, `contraer("a", "El Banco") == "al Banco"`, `contraer("a", "la NUEVA EPS") == "a la NUEVA EPS"`, `contraer("de", "el Juzgado X") == "del Juzgado X"`, `contraer("a", "BANCO X") == "a BANCO X"`.
- Numerales (`NOMBRE` = accionante en MAYÚSCULAS; `trat` = `accionante_tratamiento` + " " o ""; `ident` = ", " + identificación o ""):
  - resultado: "{VERBO} la sentencia proferida el {fecha_corta(fallo_a_quo)} por el {juzgado cuerpo_numero}, que {resultado_a_quo}, de conformidad con lo expuesto en la parte motiva de este proveído." — negritas `[VERBO]`.
  - AMPARAR: "AMPARAR {los derechos fundamentales | el derecho fundamental} {derechos con_articulo unidos por ", " y " y "} de {trat}{NOMBRE}{ident}." — negritas `["AMPARAR", NOMBRE]`. Derechos: los de `decision.derechos` con disposición AMPARA; si no hay, `md.derechos_invocados`.
  - NEGAR: "NEGAR el amparo solicitado por {trat}{NOMBRE} respecto de {los derechos fundamentales | del derecho fundamental} {derechos con_articulo}, por las razones expuestas en este proveído." (si singular: "respecto del derecho fundamental …").
  - IMPROCEDENTE: "DECLARAR IMPROCEDENTE la acción de tutela promovida por {trat}{NOMBRE}, por las razones expuestas en este proveído."
  - CARENCIA_*: "DECLARAR LA CARENCIA ACTUAL DE OBJETO POR {HECHO SUPERADO|DAÑO CONSUMADO|SITUACIÓN SOBREVINIENTE} en la acción de tutela promovida por {trat}{NOMBRE}, por las razones expuestas en este proveído."
  - ORDENAR: "ORDENAR {contraer('a', dest)}{' a través de su representante legal y/o quien haga sus veces,' si via_representante} que, dentro de {plazo} siguientes a la notificación de esta providencia, {conducta}." Con `mismo_termino`: "… que, dentro del mismo término, {conducta}." Con literales: termina en ":" y `literales` = `["a. …", "b. …"]`. Plazo como hoy (`las cuarenta y ocho (48) horas hábiles`). Negritas `["ORDENAR", dest sin artículo inicial]`.
  - PREVENIR (orden): "PREVENIR {contraer('a', dest)} para que {conducta}." ADVERTIR: "ADVERTIR {contraer('a', dest)} que {conducta}."
  - prevenir (lista) y desvincular: textos actuales de `render.resuelve`.
  - compulsa: "COMPULSAR COPIAS ante la {organo} para que, de estimarlo pertinente, adelante las actuaciones a que haya lugar respecto {contraer('de', respecto_de)}, conforme a lo indicado en el acápite de otras determinaciones de este proveído." Negritas `["COMPULSAR COPIAS"]`.
  - libre: el texto tal cual; negritas = la primera palabra si está toda en mayúsculas.
  - notificar: "NOTIFICAR esta providencia a las partes por el medio más expedito, de conformidad con lo dispuesto en el artículo 30 del Decreto 2591 de 1991."
  - remitir: "REMITIR el expediente a la Honorable Corte Constitucional para su eventual revisión."
- `cierre_otras_determinaciones` = "Por lo anterior, en cumplimiento del deber legal que le asiste a este funcionario, se dispondrá a compulsar copias de lo actuado ante la {organo} para que, dentro del marco de sus competencias, evalúe las situaciones descritas respecto {contraer('de', respecto_de)}."

- [ ] Pruebas: cada texto anterior con metadatos sintéticos (nombres inventados), las claves y el orden de C3 (incluido `orden_numerales` parcial), contracciones, `con_articulo`, plural de impugnaciones.
- [ ] Implementar; correr `tests/test_formulas.py`.

### Tarea 6: Maquetación del fallo (después de la Tarea 5)

**Archivos:** `tutela2/render.py`, `tests/test_render.py`.
**Consume:** `formulas`, `formato_b`, `letras`, `radicado`. Borra de `render.py` lo que ahora vive en `formulas`/`letras` (`COMPETENCIA`, `TRANSICION`, `numero_a_letras`, `fecha_larga`, `resuelve`, `_asunto`, `_cola`, `_filas_encabezado`, `decision_encabezado`) y los importa (re-exportando `numero_a_letras`, `fecha_larga` y `decision_encabezado` para no romper importaciones). Actualiza en `test_render.py` las pruebas que fijaban los textos viejos. **No borrar** `render_autoasume` ni `render_requerimiento` (los usa `api.py` hasta la Tarea 10; se limpian en la barrera final).
**Valores** (gen B; posiciones medidas en `format_spec.md` §4–§9 y `format_spec_check.md`; manda 53001):
- Página y pie: `formato_b.configurar_fallo(doc, cfg.despacho.pie_fallo)`.
- Cuerpo: Bookman Old Style 12, justificado, múltiple 1,5, antes 14,15 pt, después 0, sin sangría de primera línea.
- Sangrías por acápite (izq/der en pt, relativas a los márgenes): I–II 4,44/10,58; III–IV 4,44/4,08; V plantilla (competencia, P1, P2, transición) 11,42/23,88; V texto del modelo y VI–VII 14,18/0. Antes: 14,15 pt en I, II y VI; 12 pt en III, IV y V.
- Título del juzgado: Bookman negrita 12 MAYÚSCULAS, escala 114 %, alineado a la izquierda, sangría izq 197,21 pt y primera línea −140,43 pt, múltiple 1,14, antes 10 pt. Fecha: "Medellín, {fecha_larga}", centrada, escala 109 %, sencillo, antes 13,3 pt. Luego un párrafo vacío y la tabla.
- Tabla: 2 columnas 120,39 pt + 250,73 pt, sangría 54,02 pt, bordes ½ pt, filas con alto mínimo 21,8 pt, celdas sencillo 0/0 arriba. Etiqueta negrita tipo título; valor normal MAYÚSCULAS. Escalas (etiqueta/valor): radicado 109/109, accionante 114/100, accionada 109/100, vinculada 114/114, procedencia 114/114, derechos 109/109, decision 109/114. Después dos párrafos vacíos.
- Títulos: Bookman negrita 12 MAYÚSCULAS, `"{romano}.\t{TÍTULO}"`, centrado, sangría izq 18,9 pt, sencillo, antes 21,3 pt, seguido de un párrafo vacío sencillo; escala 114 % en el título de I–IV y VII, 119 % en V; las etiquetas III., IV. y V. con la misma escala que su título.
- ASUNTO: escala 114 %. LA IMPUGNACIÓN (IV): escala 104 %. RESUELVE: escala 104 %.
- V CONSIDERACIONES en este orden: subtítulo `Competencia` (negrita, izquierda), `COMPETENCIA_1`, `competencia_2(md)`, subtítulo de procedibilidad, P1, P2, `cons.procedibilidad` (con citas), bloques (subtítulo en negrita + texto + citas), `TRANSICION`.
- Citas (bloque): Bookman cursiva 11 subrayado sencillo, justificado, múltiple 1,5, sangrías 42,62/49,95 pt, antes y después 12 pt, comillas “ ”.
- Mérito: `MERITO_ANTES` + `cfg.despacho.nombre_cuerpo` en negrita + `MERITO_DESPUES`; luego título `RESUELVE` con el romano siguiente.
- Cada numeral: párrafo con "{ORDINAL}: " + texto; en negrita el ordinal más cada cadena de `negritas`; un párrafo vacío (múltiple 1,5) entre numerales; literales como párrafos propios con un vacío entre ellos.
- Cierre: párrafo vacío centrado, `cfg.despacho.cierre_fallo` negrita centrado, espacio de firma (párrafo vacío de alto exacto 64,6 pt), nombre del juez negrita centrado, `cfg.despacho.cargo_juez` negrita centrado, sencillo.
- OTRAS DETERMINACIONES (si hay compulsa): entre VI y RESUELVE, `hechos_ref` + `cierre_otras_determinaciones`.
- `render_fallo(estado, cfg, ruta, hoy=None)`: la fecha es `decision.fecha_fallo`, si no `hoy`, si no la de hoy.
- Gen A: conserva su página, pie, títulos y mérito; usa los mismos textos de `formulas`.
- [ ] Pruebas (leer el `.docx` generado con `construir_estado()`): tamaño y márgenes; imagen en el encabezado; 3 líneas del pie; tabla con `w:sz=4`, anchos 120,39/250,73 pt (±0,5), `tblInd` 54,02 pt; cuerpo con `w:spacing line=360 lineRule=auto`; Bookman 12; títulos que casan con `^[IVX]+\.\t[A-ZÁÉÍÓÚÑ ]+$`; cita con `i`, `u single`, `sz=22`; mérito con el nombre en negrita; numerales con "PRIMERO: REVOCAR" en negrita y un párrafo vacío entre numerales; orden de V; textos fijos literales de `formulas`; `fecha_fallo` en la línea de fecha; gen A sigue generando sin errores.
- [ ] Implementar; correr `tests/test_render.py` y `tests/test_formulas.py`.

### Tarea 7: Ingesta por contenido

**Archivos:** `tutela2/ingest.py`, `tutela2/clasificar.py`, `tests/test_ingest.py`, `tests/test_clasificar.py`.
**Consume:** C1, `radicado`, `letras`, marcador de la Tarea 4. **Produce:**
```python
# clasificar.py
def clasificar(doc: Doc) -> tuple[Rol, str]              # rol y evidencia (frase citada ≤ 160 caracteres)
def resolver_caso(docs: list[Doc], prefijo: str | None) -> None   # ajustes entre documentos: un solo fallo_a_quo (el del radicado del caso), la última acta de impugnación es acta_reparto_2a, etc.
# ingest.py
ROLES_OBLIGATORIOS = ("escrito_tutela", "fallo_a_quo", "impugnacion")
ROLES_ESPERADOS = ("auto_admisorio", "auto_concede_impugnacion", "acta_reparto_2a")
def ingerir(caso_dir: Path, cfg: Config) -> Ingesta
def reaplicar(ing: Ingesta, roles: dict[str, Rol]) -> Ingesta   # cambia roles (rol_origen="usuario") y recalcula faltantes, esperados, metadatos y alertas sin releer archivos
```
Requisitos:
- Instancia: todo es 1.ª salvo lo que cuelga de una carpeta cuyo nombre normalizado empieza por `02` o contiene `segunda`; ese subárbol no se lee y se registra en `ignorados` con una alerta. El nombre del archivo ya no decide la instancia.
- Clasificación por contenido de las primeras páginas (rasgos de `ground_truth_1a.json`, campo `evidence`); el nombre del archivo solo desempata. El acta con `ACTA INDIVIDUAL DE REPARTO` y `CLASE PROCESO` de impugnación es `acta_reparto_2a`; con otra clase, `acta_reparto_1a`. Un correo del juzgado que trae el escrito de impugnación es `impugnacion`. Una sentencia con otro radicado no es `fallo_a_quo`.
- Ajenos: se evalúan solo con los CUI de las 2 primeras páginas; un documento con rol obligatorio nunca se excluye (solo alerta).
- Metadatos: `cui_1a`/`cui_2a` con `radicado`; `juzgado_a_quo_*` buscando en el fallo `Juzgado <letras> Penal Municipal con Funci(ón|ones) de (Conocimiento|Control de Garantías)` cuyo `letras_a_numero` coincida con el número del radicado; si no aparece, `juzgado_de_radicado` + `juzgado_a_quo_derivado=True` + alerta; si el texto y el radicado discrepan, alerta. `juzgado_a_quo` = forma cuerpo. Partes y fechas como hoy, leyendo el acta de impugnación de 1.ª.
- OCR: caché por `sha256` y página en `cfg.cache_path()/ "ocr"`; `OMP_THREAD_LIMIT=1` mientras corre el pool; alerta con nombre y páginas si una pieza obligatoria queda con páginas sin texto.
- `ing.alertas` = `alertas_lectura` + alertas derivadas.
- [ ] Actualizar `test_ingest.py` (acta 2.ª ya no obligatoria, instancia por carpeta, `reaplicar`) y crear `test_clasificar.py` con textos sintéticos por rol, la sentencia de otro radicado, el correo que contiene una impugnación y dos impugnaciones.
- [ ] Iterar reglas hasta que pasen `uv run pytest tests/test_aceptacion.py -m aceptacion -k ingesta` (forma A, forma B y anónima) y `tests/test_ingest.py tests/test_clasificar.py`. Documentar en `clasificar.py` (una línea) que no hay paso con LLM.

### Tarea 8: Auto que asume y oficio a la Corte

**Archivos:** `tutela2/documentos/auto.py`, `tutela2/documentos/oficio.py`, `tests/test_doc_auto_oficio.py`.
**Produce:**
```python
def auto_por_defecto(md: Metadatos) -> DatosAuto           # fecha = reparto_2a + 1 día; accionante = md.accionante; accionada = ", ".join(md.accionadas)
def render_auto(md: Metadatos, datos: DatosAuto, cfg: Config, ruta: Path) -> Path
def render_oficio(md: Metadatos, fecha: str | None, cfg: Config, ruta: Path) -> Path
```
- Modelo visual: medir con `pdfinfo`, `pdffonts` y `pdftotext -bbox-layout` `referencia/casos/05001408801820260053001/02SegundaInstancia/C01Principal/002AutoAsumeSegunda202600530.pdf` (auto) y `referencia/casos/05001408802820260045601/02SegundaInstancia/C01Principal/006OficioRemiteCorteConstitucional.pdf` (oficio); dejar las medidas como constantes del módulo.
- Auto (familia B, Bookman Old Style, 612,48 × 936,48 pt, pie `cfg.despacho.pie_auto`): "Radicado: {cui_2a}", "Accionante: {datos.accionante}", "Accionada: {datos.accionada}", "CONSTANCIA:", "Las presentes diligencias fueron recibidas {cuando}, vía correo electrónico por reparto de la Oficina Judicial procedente del {juzgado digitos}, con impugnación del fallo de tutela de primera instancia, a Despacho del señor Juez.", "Medellín, {fecha_larga(datos.fecha)}", escribiente y cargo, logo centrado, "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO", "Medellín, {fecha_larga}", "ASUNTO: AUTO ASUME CONOCIMIENTO DE IMPUGNACIÓN DE TUTELA", "Se asume el conocimiento de las presentes diligencias. En consecuencia, pase el expediente a Despacho para el pronunciamiento que en derecho corresponda.", `cierre_auto`, espacio de firma, juez, `cargo_juez`. `cuando` = "el día de ayer" si la fecha del auto es el día siguiente al reparto; "el día {d} de {mes} del año en curso" si es el mismo año; si no, "el día {fecha_larga}"; sin fecha de reparto, `⟦FALTA: fecha de reparto⟧`.
- Oficio (Verdana, 612 × 1008 pt, logo arriba centrado, firmado por `firmante_oficio`): "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO", "Medellín, {fecha_larga}", "Asunto: REMISIÓN EXPEDIENTE DE TUTELA EN REVISIÓN" (todo en redonda; el encabezado del juzgado sí va en negrita cursiva, verificado en 45601), "Señores", "HONORABLES MAGISTRADOS", "Corte Constitucional – Sala de Revisión", "Calle 12 N° 7 – 65", "Bogotá D. C.", "Cordial Saludo", "De manera comedida y de conformidad con lo preceptuado en el artículo 31 del Decreto 2591 de 1991, les remito para su eventual revisión la acción de tutela relacionada a continuación.", "Radicado: {cui_2a}", "Accionante: {ACCIONANTE}", "Accionado: {ACCIONADAS}", espacio de firma, `firmante_oficio`, `cargo_firmante_oficio`.
- [ ] Pruebas: tamaño de página, fuentes, textos literales, logo presente, `cuando` en sus 4 casos, pie del auto.
- [ ] Implementar; correr `tests/test_doc_auto_oficio.py`.

### Tarea 9: Formato Factor Calidad

**Archivos:** `tutela2/documentos/formato.py`, `tutela2/assets/formato_factor_calidad.docx` (solo si se consigue la oficial), `tests/test_doc_formato.py`.
**Produce:** `def render_formato(md: Metadatos, decision: Decision, cfg: Config, ruta: Path) -> Path`.
- [ ] Buscar la plantilla oficial (página "Calificación de servicios" de la Unidad de Administración de la Carrera Judicial en ramajudicial.gov.co; formato "Factor Calidad Funcionarios Judiciales Art. 30", Acuerdo PSAA16-10618, posiblemente `.doc`). Si se consigue: guardar el original en `referencia/plantillas/`, convertir a `.docx` con `soffice --headless --convert-to docx`, comprobar que sus encabezados coinciden con `referencia/analisis/gems_calificacion.md` §4 y usarla como base. Si no aparece en ≈15 minutos de búsqueda, reconstruir con python-docx copiando los 5 formatos reales (`referencia/casos/*/02Segunda*/C01Principal/*Formato*` y `*Calificacion*`): 612,12 × 936,12 pt, 2 páginas, encabezado y secciones 1–6 con los textos de `gems_calificacion.md` §4 y la cuadrícula de la sección 3 (columnas 3.1–3.5 con sus rangos impresos).
- Prellenado: FECHA DE LA EVALUACIÓN = `decision.fecha_fallo` (dd / mm / aaaa); APELLIDOS = `juez_a_quo_apellidos`, NOMBRES = `juez_a_quo_nombres`; DESPACHO = juzgado encabezado sin " DE MEDELLÍN"; DISTRITO y MUNICIPIO = MEDELLÍN; FECHA DE ADMISIÓN = `fechas.admision`; FECHA DE LA PROVIDENCIA = `fechas.fallo_a_quo`; TIPO PROCESO = "SENTENCIA DE TUTELA PRIMERA INSTANCIA"; CÓDIGO ÚNICO = `cui_1a`; X en SENTENCIA; EVALUADOR = `cfg.despacho.juez` y `cargo_evaluador`. Puntajes, subtotales, total y motivación en blanco. Faltantes con `⟦FALTA: …⟧`.
- [ ] Pruebas: los textos de encabezado y secciones presentes, prellenado exacto con datos sintéticos, celdas de puntaje vacías, sin "Motivación" rellenada.
- [ ] Implementar; correr `tests/test_doc_formato.py`. Informar en el resumen si se usó la plantilla oficial o la reconstrucción.

### Tarea 9b: Borradores de correo

**Archivos:** `tutela2/documentos/correos.py`, `tests/test_doc_correos.py`.
**Produce:**
```python
def destinatarios_propuestos(ing: Ingesta) -> list[str]     # correos del "Para:"/"De:" del último documento de rol notificacion de 1.ª (por orden de ruta), sin duplicados, validados con regex de e-mail
def render_notificacion(md, ing, cfg, adjunto: str, ruta) -> Path
def render_envio_formato(md, cfg, adjunto: str, ruta) -> Path
def render_compulsa(md, decision, cfg, adjunto: str, ruta) -> Path
```
Cada `.docx` lleva al inicio "BORRADOR — no es constancia de envío", luego Para, Asunto, Adjunto, cuerpo y firma (`escribiente`, `cargo_escribiente`, "Juzgado 3 Penal del Circuito con Funciones", "de Conocimiento de Medellín", `correo`, `telefono_correo`).
- Notificación: asunto "Notifica fallo de segunda instancia radicado {cui_2a}"; "Cordial saludo,"; "Adjunto sentencia de tutela para su conocimiento:"; tabla 1×3 con bordes `con_guion(cui_2a)` | ACCIONANTE | ACCIONADAS; "Cordialmente,".
- Envío del formato: asunto "Envio formato calificación de calidad radicado {cui_1a}"; "Señores", juzgado en forma `digitos` (como el correo real de 53001), "Cordial saludo,", "Por medio del presente, se remite el Formato Factor Calidad correspondiente a la evaluación de la sentencia de primera instancia proferida por ese despacho dentro del siguiente proceso:", "Radicado: {cui_1a}", "Adjunto archivo en PDF.", "Atentamente,". Para: correo del juzgado de origen si aparece en la notificación de 1.ª.
- Compulsa: asunto "Remisión compulsa copias en tutela radicado: {cui_2a}"; "Señores", "Oficina de Reparto", `{compulsa.organo}`, "Por medio del presente, y dando cumplimiento a lo ordenado por el señor Juez {juez} dentro del fallo adjunto me permito remitirle el link del expediente de la tutela, donde es accionante {ACCIONANTE}.", "Dicha providencia dispuso lo siguiente:", el texto del numeral de compulsa, "Link de acceso al expediente:", `⟦FALTA: link del expediente⟧`, "Atentamente,". Para: "ofjudmed@cendoj.ramajudicial.gov.co".
- [ ] Pruebas con textos sintéticos (incluido un texto de notificación con "Para:" y "De:"), la tabla de 3 celdas y el aviso de borrador.
- [ ] Implementar; correr `tests/test_doc_correos.py`.

### Barrera 2

- [ ] Suite completa `uv run pytest -q`; `uv run pytest -m aceptacion -k ingesta`; `diff -ru` contra la copia base.
- [ ] Revisión adversarial con Opus (en paralelo): (a) fallo contra `format_spec*` y `fallo_structure` §3–§4 generando el `.docx` y renderizándolo a PNG; (b) ingesta contra los 9 casos y las trampas; (c) auto, oficio, formato y correos contra los PDF reales y `catalogo.md`. Cada hallazgo con evidencia; arreglos por Sonnet.

---

## Ola 3

### Tarea 10: Salidas, expediente, API y grafo

**Archivos:** `tutela2/salidas.py`, `tutela2/expediente.py`, `tutela2/api.py`, `tutela2/graph.py`, `tutela2/cli.py`, `tests/test_expediente.py`, `tests/test_graph.py`, `tests/test_api.py`.
**Produce:** C4, C5 y
```python
# salidas.py
def raiz(caso_dir: Path) -> Path ; def principal(caso_dir) -> Path ; def por_radicar(caso_dir) -> Path ; def borradores(caso_dir) -> Path ; def trabajo(caso_dir) -> Path
def listar(caso_dir: Path) -> list[str]
def resolver(caso_dir: Path, rel: str) -> Path              # ValueError si sale de salidas/ o es absoluta; FileNotFoundError si no existe
def zip_bytes(caso_dir: Path) -> bytes
# expediente.py
def numerados(nombres: list[str]) -> list[str]             # ["ActaRepartoSegunda.pdf", "AutoAsumeSegunda202600530.docx"] → ["001ActaRepartoSegunda.pdf", "002AutoAsumeSegunda202600530.docx"]
def generar_previos(caso_dir: Path, ing: Ingesta, cfg: Config, auto: DatosAuto) -> list[str]
def generar_final(caso_dir: Path, estado: dict, cfg: Config) -> dict[str, str]   # {ruta relativa: sha256}
```
- `generar_previos`: borra y recrea `principal`, copia byte a byte el `acta_reparto_2a` (desde `caso_dir/insumos/<ruta>`) si existe y genera el auto con `documentos.auto.render_auto`.
- `generar_final`: rehace 001/002, genera el fallo (`render.render_fallo`), el formato si `generar_formato`, el oficio (fecha = `fecha_oficio` o `fecha_fallo`), los borradores (formato y compulsa solo si aplican), informe y declaración en `trabajo/`. Numeración sin huecos.
- `api`: según C5; `previo.docx` y `requerimiento.docx` en `trabajo/`; `nuevo` borra `salidas/` entero; `revisar` falla con error si existe el hilo; `auto.json` guarda `DatosAuto`; el payload de decisión agrega `accionadas`, `vinculadas`, `fecha_hoy`.
- `graph.nodo_ensamblar` llama a `expediente.generar_final`.
- `cli.py`: subcomandos `nuevo`, `revisar`, `iniciar`, `estado`, `decidir`, `continuar` acordes.
- [ ] Pruebas: `numerados` sin acta empieza en 001 con el auto; árbol completo con decisión que pide formato y compulsa; sin formato no hay 004 ni `EnvioFormatoCalidad`; `resolver` rechaza `../x` y `/etc/passwd`; flujo `nuevo → revisar (cambia un rol) → iniciar → decidir` con `FakeClient` y `verificar_relatoria=False` termina en `terminado` con el árbol de C4; `revisar` después de `iniciar` devuelve error.
- [ ] Implementar; correr las tres pruebas.

### Tarea 11: Prompts y cliente falso

**Archivos:** `tutela2/prompts/apertura.md`, `consideraciones.md`, `caso_concreto.md`, `tutela2/llm.py`, `tests/test_llm.py`.
- Apertura: pedir los campos nuevos de `MetadatosLLM` (C1) con ejemplos de forma (sin datos reales): `impugnantes` (una frase por impugnante con su calidad y documento), `resultado_a_quo` (verbo en pasado utilizable tras "se" y tras "que"), tratamiento, identificación, nombres y apellidos del juez de 1.ª, géneros.
- Consideraciones: `procedibilidad` solo inmediatez, subsidiariedad y perjuicio irremediable en plano dogmático; no repetir el marco general ni la legitimación (los pone el sistema); estilo de ejemplo: los párrafos P3–P7 de `referencia/analisis/fallo_structure.md` §3.6 (copiar su texto al prompt es válido: es doctrina, no datos de partes).
- Caso concreto: agregar que verifique la procedibilidad aplicada a los hechos (legitimación, inmediatez, subsidiariedad) antes del fondo (Gem #8, regla 2), en prosa, sin subtítulos.
- `FakeClient`: llenar los campos nuevos de forma determinista a partir de los documentos (p. ej. `resultado_a_quo = "resolvió la acción de tutela"`, `impugnantes = [metadatos.impugnante or "la parte impugnante"]`).
- [ ] Pruebas: los prompts mencionan cada campo nuevo; el `FakeClient` devuelve los campos nuevos no vacíos.
- [ ] Implementar; correr `tests/test_llm.py`.

### Tarea 12: Servidor

**Archivos:** `tutela2/server.py`, `tests/test_server.py`. Según C5.
- [ ] Pruebas: `cmd="iniciar"` aceptado; `PUT /revision` llama a `api.revisar` y devuelve 409 con job corriendo; árbol de salidas; descarga anidada `trabajo/previo.docx` y `02SegundaInstancia/C01Principal/003X.docx`; `..%2F` y rutas absolutas → 404; `/zip` devuelve un zip válido con las rutas relativas.
- [ ] Implementar; correr `tests/test_server.py`.

### Tarea 13: Interfaz

**Archivos:** `tutela2/static/app.js`, `styles.css`, `index.html`.
- Casos: zona de arrastrar y soltar que recorre carpetas anidadas con `DataTransfer.items` + `webkitGetAsEntry` (`readEntries` en bucle hasta lote vacío), sube con la ruta relativa como nombre de archivo, conserva el botón de carpeta; al crear el caso ejecuta `nuevo` y abre Documentos.
- Documentos (nueva vista entre Casos y Configuración): tabla de documentos (nombre, ruta, selector de rol, evidencia, páginas sin texto, ajeno/ruido), faltantes en rojo, esperados faltantes en ámbar, alertas; campos del auto (fecha, accionante, accionada); "Guardar cambios" (`PUT /revision`), enlaces a 001 y 002, "Iniciar redacción" (`run iniciar`).
- Decisión: formato sí/no, fecha del fallo (hoy por defecto), fecha del oficio, etiqueta de encabezado opcional, numerales libres (agregar/quitar), lista de numerales con subir/bajar que produce `orden_numerales` (claves C3), `mismo_termino` en cada orden, ayuda en el destinatario: "incluya el artículo: «el BANCO X»".
- Resultado: árbol de `salidas/` agrupado por carpeta con descargas y "Descargar todo (.zip)".
- Configuración: los campos nuevos de `Despacho` con etiquetas en español (las listas `pie_fallo` y `pie_auto` como textarea de una línea por renglón).
- [ ] Verificación manual con el servidor (`uv run tutela2-ui`) y Chrome DevTools: subir 53001 por arrastre simulado o selector, revisar, iniciar en modo `fake`, decidir y descargar el zip.

---

## Ola 4

### Tarea 14: Aceptación de punta a punta, comparación visual y README

**Archivos:** `tests/test_aceptacion.py`, `backend/scripts/comparar_visual.py`, `README.md`.
- [ ] `test_punta_a_punta[caso]` (9): forma A en `tmp_path`, `config.json` con `llm.proveedor="fake"` y `verificar_relatoria=False`; `nuevo` → `revision`; `iniciar` → `esperando_decision`; `decidir(referencia/decisiones/<caso>.json)` → `terminado`; el árbol cumple C4 con numeración sin huecos (40601 sin acta: auto 001, fallo 002); el fallo cumple las comprobaciones de formato de la Tarea 6 y los textos fijos literales.
- [ ] `scripts/comparar_visual.py <fallo.docx> <referencia.pdf> <salida_dir>`: `soffice --headless --convert-to pdf`, `pdftoppm -r 70` de la página 1, la primera con cita y la última de ambos, y un PNG lado a lado por par (PIL). Ejecutarlo para 53001 y 12001 y dejar los PNG en `salidas/trabajo/comparacion_visual/` del caso de prueba.
- [ ] README: flujo nuevo, estados, carpetas de salida, aceptación (`-m aceptacion`), precondiciones de OCR.
- [ ] `uv run pytest -q` y `uv run pytest -m aceptacion -q` en verde.

### Barrera final

- [ ] Revisión adversarial con Opus del conjunto (spec §10 punto por punto, Foco de revisión, antiobjetivos) más inspección visual de los PNG; arreglos; repetir hasta que no queden hallazgos confirmados.
