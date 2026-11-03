# tutela2: proyecto de fallos de tutela de segunda instancia

Prototipo local que ayuda a un juzgado a preparar el borrador de una sentencia de tutela de segunda instancia (impugnación). Lee el expediente (PDF de primera y segunda instancia), redacta con un modelo de lenguaje los antecedentes, la síntesis de la sentencia impugnada, la impugnación y las consideraciones doctrinales, verifica las citas de jurisprudencia contra la Corte Constitucional, **se detiene para que el juez decida** y solo entonces redacta el caso concreto. Encabezado, fórmulas, competencia, transición y RESUELVE salen de plantillas y de la decisión humana, no del modelo.

Flujo (LangGraph, un hilo SQLite por expediente):

```
ingesta y clasificación → Documentos (revisión) → apertura → consideraciones → [decisión del juez] → caso concreto → fallo
```

Entrada: la carpeta `01PrimeraInstancia` (o la carpeta del caso que la contiene). Salida: el auto que asume conocimiento, el fallo de segunda instancia y los documentos de apoyo, en la estructura de carpetas del despacho. El detalle del flujo y de las decisiones de diseño está en `docs/superpowers/specs/2026-11-02-tutela2-primera-a-segunda-design.md`.

El diseño está en `docs/diseno-tutela-2a-instancia.md` y los contratos entre módulos en `docs/CONTRATO_IMPLEMENTACION.md`.

## Requisitos

- [uv](https://docs.astral.sh/uv/) y Python 3.12 (uv lo instala si falta).
- `poppler-utils` (`pdftotext`): extrae el texto mucho más rápido y en mejor orden. Si falta, se usa `pypdf` y la ingesta deja una alerta.
- OCR para páginas escaneadas: `tesseract-ocr` y `tesseract-ocr-spa` (Debian/Ubuntu: `sudo apt install tesseract-ocr tesseract-ocr-spa`) y el extra de Python `uv sync --extra ocr`. Si falta alguno (o `ocr` está desactivado en la configuración), esas páginas quedan sin texto, la ingesta deja una alerta y su contenido no llega al modelo.
- Red en la primera ejecución, incluso en modo `fake`: se descarga el dataset de sentencias de la Corte (datos.gov.co, unos 3,6 MB) y, con `verificar_relatoria` activo, las páginas de relatoría citadas (corteconstitucional.gov.co). Todo queda en `~/.cache/tutela2` (carpeta configurable con `cache_dir`). El dataset se refresca a los 30 días; sin red se usa la copia local si existe.

## Cómo ejecutar la interfaz

```bash
cd backend
uv sync
uv run tutela2-ui
```

Abra http://127.0.0.1:8000. Variables de entorno opcionales: `PORT` (por defecto 8000), `HOST` (por defecto `127.0.0.1`), `CASOS_DIR` (por defecto `casos/` en la raíz del repo) y `ALLOWED_HOSTS` (lista separada por comas, por defecto `127.0.0.1,localhost`; cualquier otro nombre recibe un 400). `JUDICABOT_PASSWORD` activa una pantalla de contraseña (sin usuario) y es obligatoria si `HOST` no es local; sin ella en localhost no hay autenticación. `/healthz` queda exento.

Uso: **Casos** (arrastrar `01PrimeraInstancia` o la carpeta del caso; también hay botón de carpeta) → **Documentos** → **Configuración** → **Ejecutar** → **Revisión** (apertura, consideraciones, tabla de citas y alertas) → **Decisión** → **Resultado** (árbol de salidas con descargas y `.zip`).

Estados de un caso:

| Estado | Significado |
|---|---|
| `revision` | Ingesta lista; en **Documentos** se revisan roles, alertas y datos del auto, y se descargan el acta y el auto generados |
| `incompleto` | Faltan piezas obligatorias; se genera `trabajo/requerimiento.docx` con la lista |
| `esperando_decision` | Tras **Iniciar redacción**, el grafo redactó hasta las consideraciones y espera la decisión del juez |
| `terminado` | Con la decisión, se redactó el caso concreto y se generaron los documentos finales |
| `error` | Falló un paso; `continuar` lo reanuda |

La pantalla **Documentos** muestra cada archivo con su rol (editable), la evidencia de la clasificación, la opinión de Jev con su confianza cuando la hay, las páginas sin texto y los documentos ajenos o ruido, además de los faltantes y los campos del auto. Los cambios se guardan antes de iniciar; una vez iniciada la redacción ya no se pueden cambiar los roles.

## Clave de la API de Anthropic

Por defecto el proveedor es `anthropic`, con `claude-sonnet-5-5` y `effort` en `high`. El modelo se elige en el selector "Modelo" de la cabecera (Sonnet 5.5, Haiku 5.5 u Opus 5.5) y vale para todos los casos desde la siguiente ejecución; la elección queda en `<CASOS_DIR>/.preferencias.json`. Fuera de la UI, la variable `TUTELA2_MODELO` reemplaza `llm.modelo`. Los tokens de razonamiento cuentan contra `llm.max_tokens` (64000 por defecto). Si una llamada falla con "La respuesta se cortó por el límite de tokens", suba `llm.max_tokens` (el modelo admite hasta 128000) o baje `llm.effort`. Las llamadas usan streaming. Dos formas de entregar la clave:

1. Variable de entorno antes de arrancar: `export ANTHROPIC_API_KEY=sk-ant-...`.
2. Campo "API key" de la cabecera de la UI. Se guarda solo en la memoria del proceso: no se escribe a disco, no se devuelve por la API y se pierde al reiniciar el servidor.

## Jev (segunda opinión, opcional)

Jev (TypeSafe AI) es un modelo de decisión que no genera texto: contesta preguntas cerradas con una etiqueta y una confianza. Aquí se usa como segunda opinión en dos puntos que hoy no tienen verificación independiente: el rol de cada documento al ingerir y los metadatos que el modelo escribe en la apertura (sentido de la decisión de primera instancia, `decision_a_quo`, y rol de quien impugna, `impugnante_rol`). Jev nunca bloquea, nunca reintenta un nodo y nunca decide el sentido del fallo: solo deja alertas y, en modo `relleno`, asigna un rol que el código no pudo asignar. **Arranca apagado** (`jev.modo = "apagado"`).

| Modo | Qué hace |
|---|---|
| `apagado` (por defecto) | No sale ninguna petición, aunque haya clave. |
| `sombra` | Jev opina sobre el rol de cada documento con texto y verifica con tres preguntas cerradas el sentido del fallo, el sentido de `decision_a_quo` y el rol del impugnante. Las opiniones se guardan y se muestran con su confianza en **Documentos** y en **Revisión** (tarjeta "Verificación de Jev"); si discrepan con una confianza igual o superior a `jev.umbral_confianza`, dejan una alerta. No cambia ningún rol. |
| `relleno` | Lo mismo que `sombra` y, además, asigna el rol a un documento que el código dejó como `otro` por no hallar rasgos de ningún rol, si la confianza de Jev llega al umbral (la fila dice "Sugerido por Jev"). Nunca pisa un rol decidido por el código ni uno fijado por usted, y no asigna `fallo_a_quo` ni `acta_reparto_2a` si otro documento ya tiene ese rol (en ese caso deja una alerta). |

Un documento sin texto (escaneado sin OCR) no genera ninguna petición. Si Jev falla (sin clave válida, tiempo agotado, servicio saturado), la ingesta y la apertura terminan igual y queda una alerta.

Los porcentajes de confianza se pintan según el umbral con el que se calcularon, que se guarda junto a cada opinión (`jev.umbral_confianza`, 0,9 por defecto, un valor inicial a calibrar; cambiarlo después no repinta lo ya calculado): desde el umbral hasta 1 el intervalo se divide en tres tercios, que se muestran en tres tonos de verde cada vez más intensos; por debajo del umbral van en gris y Jev no actúa. Si el rol propuesto por Jev difiere del vigente, la fila se resalta como discrepancia.

La clave solo vive en la variable de entorno `JEV_API_KEY`; nunca en `config.json`, en el repositorio ni en la bitácora. Dos formas de entregarla:

1. Archivo `.local.env` en la raíz del repo (está en `.gitignore`, con una línea `JEV_API_KEY=...`) y arrancar con `cd backend && uv run --env-file ../.local.env tutela2-ui`.
2. Campo "Clave de Jev" del grupo Jev en **Configuración**. Se guarda solo en la memoria del proceso: no se escribe a disco, no se devuelve por la API y se pierde al reiniciar el servidor. Solo admite caracteres ASCII visibles, sin espacios ni saltos de línea.

Sin clave no sale ninguna petición, aunque el modo no sea `apagado`. El modo y los demás ajustes (`jev.*`) se cambian en la pestaña Parámetros de **Configuración**.

**Privacidad (Acuerdo PCSJA24-12243, art. 8.6).** En los modos `sombra` y `relleno` se envían datos del expediente a un tercero (TypeSafe AI). Para los roles, el nombre del archivo y un fragmento inicial de cada documento con texto, acotado por `jev.max_chars_cabecera` (1500 caracteres por defecto). Para los metadatos, la cola del fallo de primera instancia (`jev.max_chars_sentido`, 2500), la cláusula `decision_a_quo`, la cabecera del escrito de impugnación y los nombres de las partes. Nunca se envía el expediente completo. Antes de usarlo con expedientes reales, el despacho debe confirmar que los términos de TypeSafe AI cumplen el art. 8.6 (sin apropiación, uso para reentrenar ni reenvío de los datos).

Cada petición queda en la bitácora del caso como una llamada con `proveedor` `jev` (modelo, tokens y huellas sha256 del estado, las preguntas y las respuestas; no guarda el texto enviado), y alimenta la declaración del art. 10, que nombra a TypeSafe AI como proveedor. También quedan, con su error, las peticiones que fallaron después de enviarse (error del servicio o tiempo agotado) y las respuestas que se descartaron por estar fuera del catálogo.

Para medir si `relleno` merece activarse hay un benchmark contra la verdad de referencia (expedientes reales en `referencia/`, que no se versiona):

```bash
cd backend
uv run --env-file ../.local.env tutela2 jev-bench --referencia ../referencia --salida /ruta/fuera/del/repo/jev-roles.md
uv run --env-file ../.local.env tutela2 jev-bench --referencia ../referencia --invertir --salida /ruta/fuera/del/repo/jev-roles-invertido.md
```

`--invertir` repite la corrida con las opciones en orden inverso para medir el sesgo hacia la primera opción. El informe contiene datos de los casos: `--salida` no puede apuntar dentro del repositorio; sin `--salida` se imprime en stdout. Las pruebas (`uv run pytest`) usan un doble de Jev y no necesitan red ni clave.

## Modo `fake` (probar sin clave)

En la configuración del caso, ponga `llm.proveedor` en `fake`. Un cliente determinista construye salidas válidas a partir del texto del expediente y de dos sentencias reales (T-200/22 y SU-082/95), y recorre todo el flujo sin llamar a ningún modelo. El texto resultante es de relleno; sirve para ver pantallas, documentos y validaciones. Los datos que salen de la ingesta (radicado, juzgado de origen, partes, fechas) son reales; los que redacta el modelo (impugnantes, resultado del fallo de origen, tratamiento e identificación del accionante, juez de origen) llevan valores ficticios.

## Configuración por caso (`casos/<id>/config.json`)

Se edita desde la UI. Los valores por defecto están en `backend/tutela2/config.py` (`uv run tutela2 config-default`).

| Opción | Qué controla |
|---|---|
| `plantilla_gen` | `A` o `B` (por defecto `B`): generación del formato del despacho (títulos, tamaño de página, fórmula de mérito) |
| `despacho.*` | Nombre, ciudad, juez, pie de página y correo que salen en los documentos |
| `llm.proveedor` | `anthropic` o `fake` |
| `llm.modelo`, `llm.effort` | Modelo (por defecto `claude-sonnet-5-5`; en la UI lo fija el selector de la cabecera) y nivel de esfuerzo (`low` a `max`, por defecto `high`) |
| `llm.modelo_por_nodo`, `llm.effort_por_nodo` | Ajustes por nodo: `apertura`, `consideraciones`, `caso_concreto` |
| `llm.max_tokens`, `llm.timeout_s` | Tope de tokens de salida por llamada (64000) y tiempo máximo (1200 s) |
| `llm.fallbacks_default` | Solo actúa cuando el filtro de seguridad del modelo rechaza la solicitud (`stop_reason: refusal`). Con Sonnet y Opus pide a la API que repita la llamada en el modelo de respaldo; si la API no acepta el parámetro se reintenta sin él. El respaldo del servidor no reintenta todas las categorías de rechazo: con Sonnet 5.5 solo reintenta `cyber` y `frontier_llm` (no `bio`, `reasoning_extraction` ni `general_harms`) y con Opus 5.5 no reintenta `reasoning_extraction`. Haiku 5.5 no tiene respaldo en el servidor: ante un rechazo, la aplicación repite la llamada con Sonnet 5.5 |
| `jev.modo` | `apagado` (por defecto), `sombra` o `relleno`; ver la sección Jev |
| `jev.umbral_confianza` | Confianza mínima, entre 0 y 1 (0,9 por defecto) para que una opinión de Jev genere alerta o asigne un rol; también fija los tonos de los porcentajes en la UI |
| `jev.timeout_s`, `jev.concurrencia` | Espera máxima de la respuesta de cada petición, mayor que 0 (60 s; ante cualquier error de Jev, de conexión o de tiempo agotado la petición se reintenta una sola vez, así que la espera puede llegar al doble) y peticiones simultáneas (6) |
| `jev.max_chars_cabecera`, `jev.max_chars_sentido` | Caracteres que se envían a Jev: inicio de cada documento y de la impugnación (1500) y cola del fallo de primera instancia (2500) |
| `jev.modelo` | Modelo de Jev (`jev-latest`); no se muestra en la UI |
| `max_intentos` | Reintentos por nodo cuando el validador encuentra errores bloqueantes (3) |
| `ocr` | Usar OCR si está disponible |
| `verificar_relatoria`, `cobertura_ok`, `cobertura_alerta`, `ngram`, `exigir_mp` | Verificación de citas: texto contra la relatoría, umbrales y exigencia de magistrado ponente |
| `max_bloques_tematicos`, `permitir_listas_caso`, `jaccard_duplicados` | Límites de estilo de las consideraciones y del caso concreto |
| `rango_palabras` | Extensión esperada por sección (si se sale, solo hay alerta) |
| `max_chars_documento` | Tope de caracteres por documento enviado al modelo |
| `dataset_csv_url`, `cache_dir` | Origen y carpeta de caché del dataset de sentencias |
| `prompts_override` | Reemplazo de las instrucciones de cada nodo (pestaña de prompts de la UI) |

## Línea de comandos

```bash
cd backend
uv run tutela2 config-default
uv run tutela2 prompts-default
uv run tutela2 nuevo     --caso ../casos/<id>
uv run tutela2 revisar   --caso ../casos/<id> [--roles roles.json] [--auto auto.json]
uv run tutela2 iniciar   --caso ../casos/<id>
uv run tutela2 estado    --caso ../casos/<id>
uv run tutela2 decidir   --caso ../casos/<id> --decision decision.json
uv run tutela2 continuar --caso ../casos/<id>
```

Cada comando imprime en stdout el JSON del resultado (`ok`, `estado`, `payload`, `salidas`, `resumen`, `error`) y los logs van a stderr. `nuevo` hace la ingesta, descarta el hilo anterior y borra las salidas viejas. `revisar` (solo antes de `iniciar`) aplica cambios de rol (`{doc_id: rol}`) y de datos del auto; `iniciar` corre el grafo hasta la decisión. `continuar` reanuda un caso que quedó a medias por un error.

Ejemplo de `decision.json`:

```json
{
  "accion": "decidir",
  "resultado": "REVOCAR",
  "sustitutiva": "AMPARAR",
  "eje": "La entidad debe responder de fondo la solicitud.",
  "ordenes": [{"destinatario": "Secretaría de Movilidad de Medellín", "conducta": "responda de fondo la solicitud"}]
}
```

`accion` también admite `rehacer_apertura` y `rehacer_consideraciones` (con `instruccion`).

## Dónde quedan los archivos

Cada caso vive en `casos/<id>/`: `insumos/` (lo subido), `config.json`, `caso.json` (ingesta), `auto.json` (datos del auto), `hilo.sqlite` (estado del grafo), `decision.json` y `salidas/`:

```
salidas/02SegundaInstancia/C01Principal/   acta de reparto (copia), AutoAsumeSegunda, FalloSegunda y, si se pide, FormatoCalificacion, numerados 001, 002, ... sin huecos
salidas/por_radicar/                       OficioRemiteCorteConstitucional.docx
salidas/borradores_correo/                 NotificacionFalloPartes, y según la decisión EnvioFormatoCalidad y RemisionCompulsaCopias
salidas/trabajo/                           previo, informe_verificacion, declaracion_ia, requerimiento (si faltan piezas)
```

Los nombres terminan con los dígitos 13 a 21 del radicado (`YYYYNNNNN`). `nuevo` borra `salidas/` completo.

## Pruebas

```bash
cd backend
uv run pytest                  # suite normal (excluye las de aceptación)
uv run pytest -m aceptacion    # sobre los casos reales
```

Para 53001 y 12001 la prueba de punta a punta también genera la comparación visual (primera página, primera página con cita y última, generado a la izquierda y referencia a la derecha) y la deja en `referencia/comparacion_visual/<caso>/` para revisión humana; requiere `soffice`, `pdftoppm` y `pdftotext`. Para un par cualquiera: `uv run python scripts/comparar_visual.py <fallo.docx> <referencia.pdf> <carpeta_salida>`.

Las pruebas de aceptación leen `referencia/casos` en la raíz del repo; esa carpeta contiene expedientes reales, no se versiona y, si no existe, las pruebas se omiten. Son lentas y usan OCR. Otras pruebas se omiten si no está `TUTELA2_DATOS` (carpeta con `datos/cc_sentencias.csv` y `relatoria/*.htm`). Ninguna prueba necesita red.

## Probar con el modelo real sin datos personales

`backend/scripts/caso_sintetico.py` genera un expediente de 1.ª instancia 100 % ficticio (9 PDF con nombres neutros `001.pdf` a `009.pdf`: acta de reparto, tutela, auto admisorio, contestación, fallo, impugnación con dos reparos, auto que concede, correo de notificación y acta de reparto de la impugnación) y lo corre de punta a punta. Nombres, cédulas, NIT, correos (`@ejemplo.test`) y hechos son inventados, así que se puede enviar a la API de Anthropic sin datos personales. Requiere `soffice` (LibreOffice) para convertir a PDF y `pdftotext`.

```bash
cd backend
uv run python scripts/caso_sintetico.py generar /tmp/caso_sintetico
uv run python scripts/caso_sintetico.py correr /tmp/caso_sintetico --proveedor fake

export ANTHROPIC_API_KEY=sk-ant-...
uv run python scripts/caso_sintetico.py correr /tmp/caso_sintetico --proveedor anthropic
```

`correr` arma `<carpeta>/insumos` y `config.json`, ejecuta `nuevo`, `iniciar` y `decidir` con una decisión por defecto (REVOCAR y AMPARAR con una orden ficticia, con formato de calificación) y muestra estado, alertas, faltantes y el árbol de salidas. Con `--decision decision.json` se usa otra decisión. Con `anthropic` el script exige `ANTHROPIC_API_KEY`, avisa de las llamadas y los tokens máximos antes de empezar y pide confirmación (`--si` la omite). Con `fake` se desactiva `verificar_relatoria`; con `anthropic` queda activa.

## Limitaciones conocidas

- Todavía no hay `.dotx` del despacho: los `.docx` se generan con python-docx (Bookman Old Style 12 pt, formato de las generaciones A y B). Al abrirlos en una máquina sin esa fuente, Word la sustituye.
- La verificación de citas solo cubre sentencias de la Corte Constitucional (T-, SU- y C-). Otras fuentes (Consejo de Estado, Corte Suprema, leyes) no se verifican; el código bloquea las menciones de sentencias fuera de los marcadores de cita verificada. Las sentencias con letra en el número (por ejemplo `T-539A/93`) se rechazan por no poder interpretarse.
- El OCR es opcional; sin él, las páginas escaneadas no llegan al modelo y solo dejan una alerta.
- El borrador no valora pruebas ni decide: el RESUELVE sale de la decisión del juez y el caso concreto desarrolla el eje que este escribe. Todo texto debe ser revisado y firmado por el servidor judicial.
- Los datos que la ingesta no extrae (juzgado de origen, vinculadas, impugnante, derechos invocados, decisión de primera instancia) los completa el modelo; en modo `fake` quedan marcados como faltantes.
- Un solo proceso, un solo usuario, sin autenticación: es un prototipo local en `127.0.0.1`.

## Privacidad

Los expedientes contienen datos personales. La carpeta `casos/` está en `.gitignore` y nunca debe subirse al repositorio; las pruebas leen los expedientes reales desde fuera del repo.

El Acuerdo PCSJA24-12243 de 2024 (Consejo Superior de la Judicatura) limita el uso de IA generativa en la Rama Judicial:

- **Art. 8.6:** no introducir datos personales, sensibles o confidenciales en herramientas de IA que se apropien de ellos, permitan compartirlos o los usen para reentrenar sus modelos. Antes de usar el proveedor `anthropic` con expedientes reales, el despacho debe confirmar que los términos de su cuenta excluyen entrenamiento y retención. La UI no ofrece `claude-fable-5-1`: exige retención de datos por 30 días y la API lo rechaza (400) en organizaciones con retención cero, salvo autorización expresa de Anthropic. Un despacho que cumpla el art. 8.6 con una cuenta sin retención no puede usarlo.
- **Art. 10:** informar el uso de IA generativa (herramienta, modelo, proveedor, fecha, términos aceptados, para qué se usó y los prompts). Cada caso genera `declaracion_ia.docx` con el modelo y la fecha de cada llamada, el hash de las instrucciones y el origen (plantilla, IA o humano) de cada sección; la constancia del servidor judicial queda pendiente de su confirmación.
