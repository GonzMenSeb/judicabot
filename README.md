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
- Para la interfaz: Node 24 y pnpm (`corepack enable`). Solo hace falta para compilarla; el servidor solo sirve los archivos ya generados. La imagen Docker la compila en su primera etapa.
- Red en la primera ejecución, incluso en modo `fake`: se descarga el dataset de sentencias de la Corte (datos.gov.co, unos 3,6 MB) y, con `verificar_relatoria` activo, las páginas de relatoría citadas (corteconstitucional.gov.co). Todo queda en `~/.cache/tutela2` (carpeta configurable con `cache_dir`). El dataset se refresca a los 30 días; sin red se usa la copia local si existe.

## Cómo ejecutar la interfaz

La interfaz es una aplicación Preact (`frontend/`) que FastAPI sirve ya compilada desde `backend/tutela2/static/dist/` (carpeta generada que no se versiona).

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ../backend
uv sync
uv run tutela2-ui
```

Abra http://127.0.0.1:8000. Si falta compilar el frontend, `/` responde 503 con "Falta compilar el frontend (pnpm build)". Variables de entorno opcionales: `PORT` (por defecto 8000), `HOST` (por defecto `127.0.0.1`), `CASOS_DIR` (por defecto `casos/` en la raíz del repo) y `ALLOWED_HOSTS` (lista separada por comas, por defecto `127.0.0.1,localhost`; cualquier otro nombre recibe un 400). `JUDICABOT_PASSWORD` activa una pantalla de contraseña (sin usuario) y es obligatoria si `HOST` no es local; sin ella en localhost no hay autenticación. `/healthz` queda exento. Las variables del modelo (`TUTELA2_MODELO`, `TUTELA2_MODELOS_PERMITIDOS`) se describen en *Clave de la API de Anthropic*.

Uso: **Inicio** → tarjeta "Fallo de tutela de segunda instancia" (**Casos de segunda instancia**: arrastrar `01PrimeraInstancia` o la carpeta del caso a la zona de soltar, o elegir la carpeta; la lista de casos agrupa por estado) → por cada caso, cinco pasos: **Documentos** (roles, faltantes y datos del auto) → **Proceso** (la redacción en vivo, con lo que el sistema lee, escribe y verifica) → **Borrador** (apertura, consideraciones, citas con su verificación, el modelo que redactó cada borrador y la segunda lectura de Jev; permite pedir correcciones) → **Decisión** (con la vista previa del RESUELVE, el encabezado calculado, la fecha del fallo —hoy, marcada como valor por defecto, mientras no se edite— y las advertencias no bloqueantes; las órdenes se pueden agregar con cualquier decisión sustitutiva, no solo al amparar) → **Fallo** (visor de las páginas, descargas y `.zip`). Dos pantallas valen para todos los casos: **Formato de los documentos** (datos del despacho que salen en el fallo, el auto, el oficio y los correos, y plantilla A o B) e **Inteligencia artificial** (modelo, claves y Jev).

Estados de un caso:

| Estado | Significado |
|---|---|
| `revision` | Ingesta lista; en **Documentos** se revisan roles, alertas y datos del auto, y se descargan el acta y el auto generados |
| `incompleto` | Faltan piezas obligatorias; se genera `trabajo/requerimiento.docx` con la lista |
| `esperando_decision` | Tras **Iniciar redacción**, el grafo redactó hasta las consideraciones y espera la decisión del juez |
| `terminado` | Con la decisión, se redactó el caso concreto y se generaron los documentos finales |
| `error` | Falló un paso; `continuar` lo reanuda |

La pantalla **Documentos** muestra cada archivo con su rol (editable), la evidencia de la clasificación, la opinión de Jev con su confianza cuando la hay, las páginas sin texto y los documentos ajenos, para revisar o ruido, además de los faltantes y los campos del auto (fechas, accionante, accionada y el firmante con su cargo; sin ellos firman el juez y el cargo del despacho). Los cambios se guardan antes de iniciar; una vez iniciada la redacción ya no se pueden cambiar los roles.

**Documentos para revisar.** Un documento con CUI de encabezado de otro radicado es ajeno y se excluye del análisis, salvo que su texto nombre al accionante, a la accionada del acta de reparto o al juzgado de primera instancia: entonces queda «para revisar» (`docs_revisar`, chip «Para revisar» y casilla «Es de este caso: confirmar» en su fila). Sigue en el expediente que lee el modelo, precedido de la línea `AVISO_REVISAR` («[AVISO: el encabezado de este documento pertenece a otro radicado; verifique antes de afirmar hechos]»), y los correos de notificación no lo usan. Confirmarlo es reenviar su rol por la misma vía que fija roles y ajenos (la casilla, o `revisar --roles`): queda con `rol_origen` `usuario` y sale de `docs_revisar`. La API no bloquea **Iniciar redacción**; si quedan documentos sin confirmar, la interfaz abre el diálogo «Hay documentos para revisar», que los lista y deja volver a revisar o continuar de todos modos. El informe de verificación los lista en «Pendientes y valores por defecto».

## Clave de la API de Anthropic

Por defecto el proveedor es `anthropic`, con `claude-sonnet-5-5` y `effort` en `high`. El modelo se elige en **Inteligencia artificial** (Sonnet 5.5, Haiku 5.5 u Opus 5.5) y vale para todos los casos desde la siguiente ejecución; esa pantalla también fija `effort`, `max_tokens`, reintentos y el modo de Jev, y todo queda en `<CASOS_DIR>/.preferencias.json`. Fuera de la UI, la variable `TUTELA2_MODELO` reemplaza `llm.modelo`. `TUTELA2_MODELOS_PERMITIDOS` (opcional; ids separados por comas, por ejemplo `claude-sonnet-5-5,claude-haiku-5-5`) restringe los modelos que ofrece el servidor a los de esa lista, en el orden de la lista de modelos de la UI; apagada o vacía rigen los tres, los ids desconocidos se ignoran y, si ninguno es válido, la lista queda vacía y `PUT /api/ia` rechaza cualquier modelo. Una preferencia guardada o un `TUTELA2_MODELO` fuera de la lista se ignoran. Si el `config.json` del caso (o su `llm.modelo_por_nodo`) pide un modelo no permitido, **Iniciar redacción** falla con un mensaje que lo dice antes de crear el hilo (no aplica al proveedor `fake`). Con la variable puesta, `modelo` en `GET /api/ia` y en `/api/estado-servidor` puede quedar fuera de `modelos`: la ejecución falla hasta elegir uno permitido. Los tokens de razonamiento cuentan contra `llm.max_tokens` (64000 por defecto). Si una llamada falla con "La respuesta se cortó por el límite de tokens", suba `llm.max_tokens` (el modelo admite hasta 128000) o baje `llm.effort`. Las llamadas usan streaming. Dos formas de entregar la clave:

1. Variable de entorno antes de arrancar: `export ANTHROPIC_API_KEY=sk-ant-...`.
2. Botón de la clave de Anthropic en **Inteligencia artificial**. Se guarda solo en la memoria del proceso: no se escribe a disco, no se devuelve por la API y se pierde al reiniciar el servidor.

## Jev (segunda opinión, opcional)

Jev (TypeSafe AI) es un modelo de decisión que no genera texto: contesta preguntas cerradas con una etiqueta y una confianza. Aquí se usa como segunda opinión en dos puntos que hoy no tienen verificación independiente: el rol de cada documento al ingerir y los metadatos que el modelo escribe en la apertura (sentido de la decisión de primera instancia, `decision_a_quo`, y rol de quien impugna, `impugnante_rol`). Jev nunca bloquea, nunca reintenta un nodo y nunca decide el sentido del fallo: solo deja alertas y, en modo `relleno`, asigna un rol que el código no pudo asignar. **Arranca apagado** (`jev.modo = "apagado"`).

| Modo | Qué hace |
|---|---|
| `apagado` (por defecto) | No sale ninguna petición, aunque haya clave. |
| `sombra` | Jev opina sobre el rol de cada documento con texto y verifica con tres preguntas cerradas el sentido del fallo, el sentido de `decision_a_quo` y el rol del impugnante. Las opiniones se guardan y se muestran con su confianza en **Documentos** y en **Borrador** (tarjeta "Segunda lectura de Jev"); si discrepan con una confianza igual o superior a `jev.umbral_confianza`, dejan una alerta. No cambia ningún rol. |
| `relleno` | Lo mismo que `sombra` y, además, asigna el rol a un documento que el código dejó como `otro` por no hallar rasgos de ningún rol, si la confianza de Jev llega al umbral (la fila dice "Sugerido por Jev"). Nunca pisa un rol decidido por el código ni uno fijado por usted, y no asigna `fallo_a_quo` ni `acta_reparto_2a` si otro documento ya tiene ese rol (en ese caso deja una alerta). |

Un documento sin texto (escaneado sin OCR) no genera ninguna petición. Si Jev falla (sin clave válida, tiempo agotado, servicio saturado), la ingesta y la apertura terminan igual y queda una alerta.

Los porcentajes de confianza se pintan según el umbral con el que se calcularon, que se guarda junto a cada opinión (`jev.umbral_confianza`, 0,9 por defecto, un valor inicial a calibrar; cambiarlo después no repinta lo ya calculado): desde el umbral hasta 1 el intervalo se divide en tres tercios, que se muestran en tres tonos de verde cada vez más intensos; por debajo del umbral van en gris y Jev no actúa. Si el rol propuesto por Jev difiere del vigente, la fila se resalta como discrepancia.

La clave solo vive en la variable de entorno `JEV_API_KEY`; nunca en `config.json`, en el repositorio ni en la bitácora. Dos formas de entregarla:

1. Archivo `.local.env` en la raíz del repo (está en `.gitignore`, con una línea `JEV_API_KEY=...`) y arrancar con `cd backend && uv run --env-file ../.local.env tutela2-ui`.
2. Botón de la clave de Jev en **Inteligencia artificial**. Se guarda solo en la memoria del proceso: no se escribe a disco, no se devuelve por la API y se pierde al reiniciar el servidor. Solo admite caracteres ASCII visibles, sin espacios ni saltos de línea.

Sin clave no sale ninguna petición, aunque el modo no sea `apagado`. El modo y el umbral se cambian en **Inteligencia artificial**; los demás ajustes (`jev.*`) están en `config.json`.

**Privacidad (Acuerdo PCSJA24-12243, art. 8.6).** En los modos `sombra` y `relleno` se envían datos del expediente a un tercero (TypeSafe AI). Para los roles, el nombre del archivo y un fragmento inicial de cada documento con texto, acotado por `jev.max_chars_cabecera` (1500 caracteres por defecto). Para los metadatos, la cola del fallo de primera instancia (`jev.max_chars_sentido`, 2500), la cláusula `decision_a_quo`, la cabecera del escrito de impugnación y los nombres de las partes. Nunca se envía el expediente completo. Antes de usarlo con expedientes reales, el despacho debe confirmar que los términos de TypeSafe AI cumplen el art. 8.6 (sin apropiación, uso para reentrenar ni reenvío de los datos).

Cada petición queda en la bitácora del caso como una llamada con `proveedor` `jev` (modelo, tokens y huellas sha256 del estado, las preguntas y las respuestas, más el texto de las preguntas cerradas; no guarda el texto de los documentos enviado), y alimenta la declaración del art. 10, que nombra a TypeSafe AI como proveedor y transcribe esas preguntas. También quedan, con su error, las peticiones que fallaron después de enviarse (error del servicio o tiempo agotado) y las respuestas que se descartaron por estar fuera del catálogo.

Para medir si `relleno` merece activarse hay un benchmark contra la verdad de referencia (expedientes reales en `referencia/`, que no se versiona):

```bash
cd backend
uv run --env-file ../.local.env tutela2 jev-bench --referencia ../referencia --salida /ruta/fuera/del/repo/jev-roles.md
uv run --env-file ../.local.env tutela2 jev-bench --referencia ../referencia --invertir --salida /ruta/fuera/del/repo/jev-roles-invertido.md
```

`--invertir` repite la corrida con las opciones en orden inverso para medir el sesgo hacia la primera opción. El informe contiene datos de los casos: `--salida` no puede apuntar dentro del repositorio; sin `--salida` se imprime en stdout. Las pruebas (`uv run pytest`) usan un doble de Jev y no necesitan red ni clave.

## Modo `fake` (probar sin clave)

Arranque el servidor con `TUTELA2_PROVEEDOR=fake` (también desactiva `verificar_relatoria`) o ponga `llm.proveedor` en `fake` en el `config.json` del caso. Un cliente determinista construye salidas válidas a partir del texto del expediente y de dos sentencias reales (T-200/22 y SU-082/95), y recorre todo el flujo sin llamar a ningún modelo. El texto resultante es de relleno; sirve para ver pantallas, documentos y validaciones. Los datos que salen de la ingesta (radicado, juzgado de origen, partes, fechas) son reales; los que redacta el modelo (impugnantes, resultado del fallo de origen, tratamiento e identificación del accionante, juez de origen) llevan valores ficticios.

## Configuración por caso (`casos/<id>/config.json`)

Los ajustes globales se fijan en la UI: **Inteligencia artificial** (modelo, `effort`, `max_tokens`, reintentos y modo y umbral de Jev) y **Formato de los documentos** (`despacho.*` y `plantilla_gen`, que se copian a `config.json` al crear un caso). El resto se edita en el archivo o con `PUT /api/casos/<id>/config`. Los valores por defecto están en `backend/tutela2/config.py` (`uv run tutela2 config-default`).

| Opción | Qué controla |
|---|---|
| `plantilla_gen` | `A` o `B` (por defecto `B`): generación del formato del despacho (títulos, tamaño de página, fórmula de mérito) |
| `despacho.*` | Nombre, ciudad, juez, pie de página y correo que salen en los documentos |
| `llm.proveedor` | `anthropic` o `fake` |
| `llm.modelo`, `llm.effort` | Modelo (por defecto `claude-sonnet-5-5`; en la UI lo fija **Inteligencia artificial**) y nivel de esfuerzo (`low` a `max`, por defecto `high`) |
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
| `verificar_relatoria`, `cobertura_ok`, `cobertura_alerta`, `ngram`, `exigir_mp` | Verificación de citas: texto contra la relatoría, umbrales de cobertura y exigencia de magistrado ponente. Las reglas de longitud, texto normativo y sección se suman a estos umbrales (ver *Verificación de citas*) |
| `min_citas_ok` | Citas en estado `ok` que deben tener las consideraciones (2 por defecto). Con `verificar_relatoria` activo, menos citas `ok` bloquean el nodo y fuerzan un reintento; las citas con alerta y las rechazadas no cuentan. Con `0`, la falta de citas `ok` solo da una alerta. Sin `verificar_relatoria` no se exige |
| `min_palabras_cita` | Palabras mínimas de cada cita (25 por defecto; base: percentil 10 de 57 pasajes transcritos en los 9 fallos reales de referencia). Una cita más corta se rechaza, también con `verificar_relatoria` desactivado. Con `0` no hay mínimo |
| `max_bloques_tematicos`, `permitir_listas_caso`, `jaccard_duplicados` | Límites de estilo de las consideraciones y del caso concreto |
| `rango_palabras` | Extensión esperada por sección (si se sale, solo hay alerta) |
| `max_chars_documento` | Tope de caracteres por documento enviado al modelo |
| `dataset_csv_url`, `cache_dir` | Origen y carpeta de caché del dataset de sentencias |
| `prompts_override` | Reemplazo de las instrucciones de cada nodo (la UI todavía no los edita; se cambian en el archivo) |

## Verificación de citas

Cada cita que propone el modelo se contrasta con el dataset de la Corte (existencia, año y magistrado ponente) y, con `verificar_relatoria`, con el texto de la relatoría: cobertura de n-gramas `ok` desde `cobertura_ok`, `alerta` desde `cobertura_alerta` y `rechazada` por debajo. Se suman tres reglas que se aplican a cada cita y que, a diferencia de la cobertura, valen también con `verificar_relatoria` desactivado (salvo la de sección, que necesita el texto de la relatoría):

- **Longitud:** al menos `min_palabras_cita` palabras.
- **Texto normativo:** se rechaza la cita que reproduce un artículo del corpus `backend/tutela2/assets/normas_citables.json` (art. 86 de la Constitución; arts. 1, 5, 6, 8, 10, 13, 38 y 42 del Decreto 2591 de 1991; art. 2 de la Ley 1751 de 2015), con una coincidencia de 4-gramas de al menos `cobertura_ok`.
- **Sección:** la relatoría se separa en la decisión de la mayoría (hasta el cierre `Cópiese, comuníquese… cúmplase` y las firmas), los votos separados (desde el título del salvamento o aclaración de voto, o el `COMUNICADO`, hasta el anexo) y las notas al pie y anexos. Un pasaje que solo aparece en un voto separado se rechaza (`seccion` `salvamento`); uno que solo aparece en notas o anexos, o repartido entre secciones, queda en `alerta` con `seccion` `desconocida`.

Los motivos de rechazo enuncian la regla («Regla de las citas: …»), no solo porcentajes: de lo contrario el modelo acorta la cita hasta que pasa. Con `verificar_relatoria`, los mínimos de citas y de palabras también van al modelo en el mensaje de las consideraciones, y el nodo que verifica las consideraciones **bloquea** si hay menos de `min_citas_ok` citas `ok` (el mensaje trae la regla y el conteo de propuestas, rechazadas y para revisar) y el nodo vuelve a pedirlas hasta `max_intentos`; sin `verificar_relatoria` no se exige ese mínimo y las citas quedan en `alerta`. Una oración de las consideraciones que atribuye una regla a «la jurisprudencia» sin un marcador `[[CITA:id]]` en la misma oración da una alerta.

La tabla de citas del borrador previo y del informe muestra sentencia, estado, cobertura, palabras, sección, M.P. del dataset, URL, el texto citado (recortado) y los motivos; las citas no rechazadas que estén por debajo del mínimo de palabras o provengan de un salvamento se resaltan en la tabla y se listan en «A revisar a mano».

## Caso concreto e informe

- **Caso concreto:** el modelo escribe solo marcadores `[[CITA:id]]`, nunca el texto de una sentencia. El renderizador sustituye cada marcador por «Sentencia T-NNN de AAAA, con ponencia del Magistrado X» y, después del párrafo donde aparece por primera vez, inserta el fragmento verificado como bloque de cita en modo compacto: hasta 80 palabras (`_MAX_PALABRAS_CITA_CASO` en `render.py`), en frases completas y terminado en «[…]» si se recorta; en las consideraciones el fragmento va completo. Una cita rechazada o inexistente sale como `⟦FALTA: cita verificada …⟧`.
- **Validación del caso concreto** (`validar_caso`): bloquea si ningún párrafo lleva el marcador de una cita `ok` (con `verificar_relatoria` desactivado valen también las citas con alerta; si no hay ninguna utilizable solo avisa de que la sección queda sin jurisprudencia), si hay un pasaje entre comillas de 6 palabras o más que no consta en el expediente ni en la decisión, y si la conclusión repite el último párrafo. La conclusión va solo en el campo `conclusion`. Avisa si el caso concreto no menciona el plazo de alguna orden.
- **Competencia:** un solo párrafo (`COMPETENCIA_1`), en CONSIDERACIONES en la generación B y al inicio del CASO CONCRETO en la A.
- **Informe de verificación** (`informe_verificacion.docx`):
  - «Errores bloqueantes vigentes» reúne los errores del último validador y todo mensaje `BLOQUEA:` de las alertas por nodo.
  - Si con `verificar_relatoria` ninguna cita quedó `ok`, la tabla de citas lleva el aviso «ATENCIÓN: falta jurisprudencia verificada…» y, si no hay errores bloqueantes, esa sección aclara que falta jurisprudencia en vez de decir que está limpia.
  - «PENDIENTES Y VALORES POR DEFECTO» lista: la fecha del fallo tomada por defecto (hoy) cuando no se indicó, el formato de calidad sin puntajes ni motivación, las advertencias de «Decidido por», el acta de reparto de segunda instancia ausente (la numeración empieza en 002), los documentos para revisar y los ajenos, y cada marcador `⟦FALTA…⟧` de los `.docx` generados, incluidos encabezados y pies.
- **Declaración de IA** (`declaracion_ia.docx`): las llamadas se agrupan por nodo, proveedor, modelo y prompt con su conteo (el detalle por llamada queda en el informe), el anexo transcribe también las preguntas cerradas de Jev y la herramienta consta como «Judicabot».

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

Cada comando imprime en stdout el JSON del resultado (`ok`, `estado`, `payload`, `salidas`, `resumen`, `error`) y los logs van a stderr. `nuevo` hace la ingesta, descarta el hilo anterior y borra las salidas viejas. `revisar` (solo antes de `iniciar`) aplica cambios de rol (`{doc_id: rol}`; reenviar el rol de un documento «para revisar» lo confirma) y de datos del auto (`fecha`, `fecha_reparto`, `accionante`, `accionada`, `firmante`, `cargo_firmante`); `iniciar` corre el grafo hasta la decisión. `continuar` reanuda un caso que quedó a medias por un error.

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

Campos opcionales que conviene conocer:

- `causal`: `COSA_JUZGADA` o `SUBSIDIARIEDAD`; solo vale con `sustitutiva` `IMPROCEDENTE`. El numeral dice «por configurarse el fenómeno de la cosa juzgada constitucional, …» o «por no cumplirse el requisito de subsidiariedad.» en lugar del motivo genérico, y la etiqueta del encabezado termina en «POR COSA JUZGADA» o «POR SUBSIDIARIEDAD» (por ejemplo, `REVOCA Y DECLARA IMPROCEDENTE POR COSA JUZGADA`); no cambia una `etiqueta_encabezado` escrita a mano. En la UI se muestran como «Cosa juzgada constitucional» y «Subsidiariedad». La vista previa señala un valor desconocido como faltante; `decidir` no lo valida y usa el motivo genérico.
- `fecha_fallo` (ISO): sin ella se usa la fecha de hoy, la vista previa lo indica (`fecha_por_defecto`) y el informe lo anota entre los valores por defecto.
- `decidido_por`: vacío o con un valor de prueba (`john doe`, `prueba`, `caso sintetico`; sin tildes ni mayúsculas, con `_` y `-` como espacio, igualdad exacta) no bloquea, pero deja una advertencia: «Decidido por está vacío: en la declaración de uso de IA constará «no consta».» o «Decidido por parece un valor de prueba: confirme que sea el nombre de quien decide.». Solo con `accion` `decidir`. La vista previa las devuelve aparte de los faltantes y el informe las lista.

Antes de guardar `decision.json`, el servidor normaliza `eje`, `instruccion`, la `nota` de cada reparo, los `numerales_libres` y la `conducta` de cada orden: quita `▎` (U+258E), colapsa espacios y saltos de línea a un espacio y recorta los extremos; la UI hace lo mismo al armar la decisión.

## Dónde quedan los archivos

Cada caso vive en `casos/<id>/`: `insumos/` (lo subido), `config.json`, `caso.json` (ingesta), `auto.json` (datos del auto), `hilo.sqlite` (estado del grafo), `decision.json` y `salidas/`:

```
salidas/02SegundaInstancia/C01Principal/   acta de reparto (copia), AutoAsumeSegunda, FalloSegunda y, si se pide, FormatoCalificacion, numerados 001, 002, ...; el 001 es del acta, así que sin ella empiezan en 002 y el informe lo anota
salidas/por_radicar/                       OficioRemiteCorteConstitucional.docx
salidas/borradores_correo/                 NotificacionFalloPartes, y según la decisión EnvioFormatoCalidad y RemisionCompulsaCopias (el adjunto se nombra con extensión .pdf)
salidas/trabajo/                           previo, informe_verificacion, declaracion_ia, requerimiento (si faltan piezas)
```

Los nombres terminan con los dígitos 13 a 21 del radicado (`YYYYNNNNN`). `nuevo` borra `salidas/` completo.

## Frontend (`frontend/`)

Preact 10, `@preact/signals`, Vite y TypeScript estricto; sin otras dependencias de interfaz. Los textos están en español.

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev            # Vite en http://localhost:5173 con proxy de /api a http://127.0.0.1:8000
pnpm build          # compila a ../backend/tutela2/static/dist
pnpm typecheck      # tsc --noEmit
pnpm test           # vitest + @testing-library/preact
pnpm size           # presupuestos de tamaño sobre dist/ (falla si se exceden)
pnpm e2e            # Playwright contra el servidor real
```

- **Desarrollo con proxy:** deje corriendo el backend (`cd backend && uv run tutela2-ui`) y, en otra terminal, `pnpm dev`. Con `VITE_MOCK=1 pnpm dev` las vistas responden con los datos de ejemplo de `src/vistas/*/mock.ts`; lo que no tenga dato de ejemplo se sigue pidiendo al backend.
- **Presupuestos (`pnpm size`, gzip):** JS inicial 60 KB, cada chunk de ruta 25 KB, CSS inicial 15 KB, CSS total 25 KB, fuentes 60 KB.
- **Tipos de la API:** `frontend/openapi.json` y `frontend/src/api/schema.d.ts` se generan desde el servidor con `pnpm gen:tipos` y se versionan. `src/api/contrato.ts` es el contrato escrito a mano que usan las vistas; `src/api/contrato.verificacion.ts` hace fallar `pnpm typecheck` si se aparta del esquema generado. `pnpm check:tipos` (CI) falla si `schema.d.ts` no corresponde a `openapi.json`, y una prueba del backend falla si `openapi.json` no corresponde al servidor. Tras cambiar un endpoint o su `response_model`, ejecute `pnpm gen:tipos`.
- **E2E:** `pnpm e2e` genera el caso sintético (`backend/scripts/caso_sintetico.py`), levanta dos servidores `uv run tutela2-ui` (uno abierto y otro detrás de `JUDICABOT_PASSWORD`) con `TUTELA2_PROVEEDOR=fake` y carpetas de casos temporales, y recorre el flujo. La primera vez: `pnpm exec playwright install chromium`.

Estructura:

```
frontend/
  src/api/       cliente HTTP, SSE de eventos, contrato.ts, schema.d.ts (generado)
  src/estado/    estado compartido con signals (servidor, toasts, formato)
  src/rutas/     router por hash (#/segunda/<caso>/<paso>), Shell y carga perezosa de vistas
  src/ui/        primitivas: Topbar, Pasos, Boton, Chip, Dialogo, Aviso, VisorPagina
  src/vistas/    una carpeta por pantalla: inicio, casos, documentos, proceso, borrador, decision, fallo, formato, ia
  src/estilos/   tokens, fuentes (IBM Plex Sans autoalojada) y base
  public/        favicon, manifiesto e iconos
  e2e/           pruebas Playwright
  scripts/size.mjs
```

## Pruebas

```bash
cd backend
uv run pytest                  # suite normal (excluye las de aceptación)
uv run pytest -m aceptacion    # sobre los casos reales
```

Para 53001 y 12001 la prueba de punta a punta también genera la comparación visual (primera página, primera página con cita y última, generado a la izquierda y referencia a la derecha) y la deja en `referencia/comparacion_visual/<caso>/` para revisión humana; requiere `soffice`, `pdftoppm` y `pdftotext`. Para un par cualquiera: `uv run python scripts/comparar_visual.py <fallo.docx> <referencia.pdf> <carpeta_salida>`.

Las pruebas de aceptación leen `referencia/casos` en la raíz del repo; esa carpeta contiene expedientes reales, no se versiona y, si no existe, las pruebas se omiten. Son lentas y usan OCR. Otras pruebas se omiten si no está `TUTELA2_DATOS` (carpeta con `datos/cc_sentencias.csv` y `relatoria/*.htm`). Ninguna prueba necesita red; las de `scripts/prueba_real.py` (`tests/test_prueba_real.py`) usan un SDK falso y no gastan tokens.

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

### Prueba real controlada: `scripts/prueba_real.py`

Mide con el modelo real los criterios de calidad de las citas, del caso concreto y del informe, con modelo y presupuesto acotados y solo sobre el caso sintético. A diferencia de `caso_sintetico.py correr --proveedor anthropic`, limita el gasto, rechaza otros modelos y evalúa criterios medibles en lugar de mostrar el resultado.

```bash
cd backend
uv run python scripts/prueba_real.py entrada [--texto]
uv run --env-file ../.local.env python scripts/prueba_real.py hasta-decision [--reiniciar]
uv run --env-file ../.local.env python scripts/prueba_real.py rehacer [--veces N] [--instruccion TEXTO]
uv run --env-file ../.local.env python scripts/prueba_real.py decidir [--decision decision.json]
uv run --env-file ../.local.env python scripts/prueba_real.py extremo-a-extremo [--reiniciar] [--decision decision.json]
uv run --env-file ../.local.env python scripts/prueba_real.py continuar
```

| Subcomando | Qué hace |
|---|---|
| `entrada` | No llama a ninguna API ni necesita clave. Corre el caso sintético con un cliente falso que registra lo que recibiría cada nodo e imprime, por nodo, el tamaño del `system` y del `user`, los tokens estimados y el peor caso por llamada en US$; `--texto` imprime el `system` y el `user` completos |
| `hasta-decision` | Prepara el caso en `--carpeta` (genera el sintético si falta y fija la configuración), hace la ingesta y corre `iniciar` hasta la pausa de decisión; evalúa los criterios de las consideraciones. `--reiniciar` descarta el hilo con llamadas ya pagadas (sin él, un caso ya iniciado se rechaza) |
| `rehacer` | Envía `rehacer_consideraciones` con `--instruccion` (hay una por defecto) `--veces` veces (1 por defecto) y se detiene antes si todos los criterios de las consideraciones pasan. Exige el estado `esperando_decision`; el tope es de 3 por caso |
| `decidir` | Envía la decisión de `--decision` (por defecto la del caso sintético) y evalúa el caso concreto y el informe. Exige `esperando_decision` |
| `extremo-a-extremo` | `hasta-decision` y, si queda esperando la decisión, `decidir` |
| `continuar` | Reanuda un caso que quedó a medias por un error |

Banderas comunes de los subcomandos de pago: `--carpeta` (por defecto `~/.cache/tutela2/prueba_real`), `--parada-suave` (US$5: acumulado a partir del cual no se inicia otro paso), `--aborto-duro` (US$15, que es también el máximo permitido; se exige `0 < parada suave <= aborto duro <= 15`) y `--salida` (ruta del reporte JSON; el `.md` queda al lado; por defecto `<carpeta>/reporte_<subcomando>.json`). El reporte trae el veredicto, el costo, los criterios, las citas de cada verificación con sus motivos y los pasos. Códigos de salida: 0 pasa, 1 falla o queda incompleto, 2 rechazo de seguridad o de uso, 3 parada suave, 4 aborto duro.

Seguridad:

- **Solo `claude-sonnet-5-5`.** Cualquier otro modelo se rechaza y los nombres que contienen `opus`, `fable` o `mythos` están prohibidos; también se comprueba el modelo que dice haber respondido. El script fuerza proveedor `anthropic`, `verificar_relatoria` activo, `fallbacks_default` apagado y Jev apagado, y exige `ANTHROPIC_API_KEY` en el entorno (sin ella sale con código 2).
- **Cliente vigilado.** Del SDK solo se permite `messages.stream`, sin fallbacks, betas, `extra_body` ni `extra_headers`. Antes de cada llamada se reserva su peor caso (entrada estimada por la cota de caracteres más `max_tokens` a la tarifa de salida de `PRECIOS`) y se aborta si superaría el aborto duro. Lo gastado se acumula entre invocaciones en `presupuesto.json` de la carpeta del caso; una llamada que quedó en vuelo se cuenta por su peor caso al retomar.
- **Solo el caso sintético.** La carpeta debe estar fuera del repositorio y no puede estar bajo una ruta `casos` ni `referencia`; si ya tiene contenido, debe ser un caso sintético generado por este script. Antes de pagar se comprueba que el radicado sea el ficticio, que los documentos sean los nueve sintéticos (`001.pdf` a `009.pdf`) y que cada uno contenga el nombre ficticio de la accionante.

**Nunca se usan expedientes reales con la API.** Ni `casos/` ni `referencia/` se envían a ningún proveedor (Acuerdo PCSJA24-12243, art. 8.6; ver Privacidad): el script lo hace cumplir por ruta y por contenido, y la regla vale también para cualquier otra prueba con modelo real.

## Limitaciones conocidas

- Todavía no hay `.dotx` del despacho: los `.docx` se generan con python-docx (Bookman Old Style 12 pt, formato de las generaciones A y B). Al abrirlos en una máquina sin esa fuente, Word la sustituye.
- La verificación de citas solo cubre sentencias de la Corte Constitucional (T-, SU- y C-). Otras fuentes (Consejo de Estado, Corte Suprema, leyes) no se verifican; el código bloquea las menciones de sentencias fuera de los marcadores de cita verificada. Las sentencias con letra en el número (por ejemplo `T-539A/93`) se rechazan por no poder interpretarse.
- El OCR es opcional; sin él, las páginas escaneadas no llegan al modelo y solo dejan una alerta.
- El borrador no valora pruebas ni decide: el RESUELVE sale de la decisión del juez y el caso concreto desarrolla el eje que este escribe. Todo texto debe ser revisado y firmado por el servidor judicial.
- Los datos que la ingesta no extrae (juzgado de origen, vinculadas, impugnante, derechos invocados, decisión de primera instancia) los completa el modelo; en modo `fake` quedan marcados como faltantes.
- **Artículo del oficio y del numeral REMITIR (convención por confirmar con el despacho).** El oficio a la Corte Constitucional cita el artículo 31 del Decreto 2591 de 1991 (los 3 oficios de referencia lo citan) y el numeral REMITIR no cita artículo (igual que en 53001). Los 9 fallos de referencia no siguen una convención única al remitir: artículo 31 solo (12001, 40601), artículo 32 solo (37401, 45601, 49501), ambos (45301, 45901), ninguno (53001, 34601). Fuentes secundarias ubican «dentro de los diez días siguientes a la ejecutoria del fallo de segunda instancia, el juez remitirá el expediente a la Corte Constitucional» en el artículo 32 (la sentencia C-122 de 2018 lo transcribe); no se verificó en el texto primario. El código sigue la forma de los ejemplos y no se cambia hasta que el despacho confirme artículo 31 o 32; `test_oficio_fija_la_convencion_del_articulo_31` y `test_libres_notificar_remitir` fijan la forma actual.
- Un solo proceso, un solo usuario, sin autenticación: es un prototipo local en `127.0.0.1`.

## Privacidad

Los expedientes contienen datos personales. La carpeta `casos/` está en `.gitignore` y nunca debe subirse al repositorio; las pruebas leen los expedientes reales desde fuera del repo.

El Acuerdo PCSJA24-12243 de 2024 (Consejo Superior de la Judicatura) limita el uso de IA generativa en la Rama Judicial:

- **Art. 8.6:** no introducir datos personales, sensibles o confidenciales en herramientas de IA que se apropien de ellos, permitan compartirlos o los usen para reentrenar sus modelos. Antes de usar el proveedor `anthropic` con expedientes reales, el despacho debe confirmar que los términos de su cuenta excluyen entrenamiento y retención. La UI no ofrece `claude-fable-5-1`: exige retención de datos por 30 días y la API lo rechaza (400) en organizaciones con retención cero, salvo autorización expresa de Anthropic. Un despacho que cumpla el art. 8.6 con una cuenta sin retención no puede usarlo.
- **Art. 10:** informar el uso de IA generativa (herramienta, modelo, proveedor, fecha, términos aceptados, para qué se usó y los prompts). Cada caso genera `declaracion_ia.docx` con el modelo, las fechas y el hash de las instrucciones de cada grupo de llamadas (por nodo, proveedor, modelo y prompt, con su conteo), las instrucciones transcritas en un anexo y el origen (plantilla, IA o humano) de cada sección; la constancia del servidor judicial queda pendiente de su confirmación.
