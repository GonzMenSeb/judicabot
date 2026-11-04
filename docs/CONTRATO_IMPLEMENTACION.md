> Nota: el flujo vigente (primera instancia a segunda) está en `docs/superpowers/specs/2026-11-02-tutela2-primera-a-segunda-design.md`; este documento es el antecedente.

# Contrato de implementación del prototipo (v0.1)

Este archivo es la fuente de verdad compartida por todos los módulos. El diseño completo está en `docs/diseno-tutela-2a-instancia.md`.

## Reglas generales

- **Backend:** Python 3.12 + `uv`. Se ejecuta con `cd backend && uv run ...`. Las dependencias están en `backend/pyproject.toml`; si hace falta una nueva, se agrega con `uv add`.
- **Modelos y configuración:** ya existen en `backend/tutela2/models.py` y `backend/tutela2/config.py`. **No se cambian sus campos existentes.** Si falta algo, se agregan campos opcionales y nada más.
- **Comentarios:** solo los estrictamente necesarios.
- **Datos del estado:** el grafo guarda solo dicts y listas JSON (`model_dump(mode="json")`) y reconstruye los modelos Pydantic en cada nodo con `Model.model_validate`.
- **Idioma:** texto de usuario y mensajes de error en español.
- **Tests:** con pytest, en `backend/tests/`. Los tests no deben depender de red: lo que use HTTP se prueba con fixtures o con caché local. Los expedientes reales de ejemplo **no se copian al repo**; se leen desde la variable `TUTELA2_EJEMPLOS`, que apunta a `/tmp/claude-1000/-home-sebastian-versioned-code-atomatizacion-legal/ded163ec-ef84-42dc-8161-08f30a500a94/scratchpad/ejemplos_drive`. Si la variable no existe, el test hace `skip`.

## Carpeta de un caso (`casos/<caso_id>/`)

```
insumos/        PDFs (y .docx/.txt) subidos; se conservan las subcarpetas (01PrimeraInstancia/..., 02SegundaInstancia/...)
config.json     Config (tutela2.config); si falta, se usan los valores por defecto
caso.json       Ingesta serializada (la escribe `nuevo`)
hilo.sqlite     checkpointer de LangGraph; thread_id = caso_id
decision.json   última decisión enviada por la UI
salidas/        AutoAsume.docx, requerimiento.docx, previo.docx, fallo.docx, informe_verificacion.docx, declaracion_ia.docx
```

## Módulos y firmas públicas

### `tutela2/ingest.py` (determinista)

- `ingerir(caso_dir: Path, cfg: Config) -> Ingesta`
  - Recorre `insumos/` de forma recursiva.
  - Extrae el texto **página por página**. Primero intenta `pdftotext -layout -f n -l n` si el binario existe; si no, usa pypdf.
  - Una página con menos de 30 caracteres queda como `sin_texto=True`. Si `cfg.ocr` es verdadero y hay tesseract y el extra `ocr` disponible, se le pasa OCR en `spa` y se marca `ocr=True`.
  - Cada página sin texto y sin OCR genera una alerta.
- `instancia`: es `"2a"` si la ruta contiene `Segunda` o empieza por `02`; si no, `"1a"`.
- `rol`: se clasifica por el nombre del archivo, sin tildes y en minúsculas.

  | El nombre contiene | Rol |
  |---|---|
  | `actareparto` / `acta reparto` | `acta_reparto_2a` si la instancia es 2a o el nombre dice `impugnacion`/`segunda`; si no, `acta_reparto_1a` |
  | `escritotutela` | `escrito_tutela` |
  | `admi`, `avoca` | `auto_admisorio` |
  | `vincula` (y no `notifica`) | `auto_vinculacion` |
  | `respuesta`, `contestacion` | `contestacion` |
  | `fallotutela` en instancia 1a | `fallo_a_quo` |
  | `impugnacion` / `impugnación` | `auto_concede_impugnacion` si además dice `concede`; `notificacion` si dice `notifica`; si no, `impugnacion` |
  | `notifica`, `notificacion` | `notificacion` |
  | `correo`, `ingreso`, `envio`, `constancia`, `remision` | `correo` |
  | `memorial` | `memorial` |
  | `indice` | `indice` |

  Además, los archivos de la instancia 2a que son productos del despacho (`autoasume`, `fallosegunda`, `tutelasegunda`, `formatocalif`/`formatocalidad`, `notificafallo`, `enviacalific`/`enviaformato`, `compulsa`) llevan el rol `producto_despacho` y **se excluyen** del insumo.
  - Para los correos que en realidad traen la impugnación (por ejemplo, `CorreoImpugnacion`), manda la regla de `impugnacion` cuando el nombre la contiene.
- `cuis`: todos los números de 23 dígitos encontrados. Admite espacios o guiones entre grupos; se normalizan quitándolos.
  - El caso se identifica por el CUI más frecuente en el acta de reparto de 2a. Sin esa acta, se usa el más frecuente en general.
  - Los primeros 21 dígitos deben coincidir con los del caso. Un documento cuyos CUIs no coinciden ninguno se va a `docs_ajenos`, salvo que su texto nombre al accionante, a la accionada del acta de reparto o al juzgado de primera instancia: entonces va a `docs_revisar` («para revisar»). Los roles obligatorios y los documentos con rol fijado por el usuario (`rol_origen == "usuario"`) nunca pasan a ninguna de las dos listas; confirmar un documento para revisar es reenviar su rol por `reaplicar`.
- **Ruido**: se marcan `ruido=True` con su `motivo_ruido`:
  - las páginas o documentos que son mayoritariamente "certificado de existencia y representación legal"; en ese caso se marcan las páginas y el documento solo si más del 80 % de su texto es eso;
  - los duplicados exactos por sha256.
- **Faltantes**: roles obligatorios: `acta_reparto_2a`, `escrito_tutela`, `auto_admisorio`, `fallo_a_quo`, `impugnacion`, `auto_concede_impugnacion`. Cada rol ausente se agrega a `faltantes`.
- **Metadatos**: se extraen con regex. CUI 1a y 2a: el sufijo 00 o 01 son los dos últimos dígitos. Fechas en letras o cifras de los autos y actas, normalizadas a ISO cuando se pueda. El accionante y la accionada salen de las líneas "Accionante:" / "Accionado:" / "Demandado:" del acta de reparto de 2a. Lo que no se pueda extraer queda en `None`, y lo completa el LLM.
- `texto_para_llm(ing: Ingesta, roles: set[str] | None = None, max_chars: int) -> str`: concatena los documentos que no son ruido ni ajenos (los de `docs_revisar` sí van, con la línea `AVISO_REVISAR` antes del texto). Cada documento va con su encabezado `### DOC <doc_id> | <rol> | <nombre>`, y cada página con `[p. N]`. Si un documento supera `max_chars`, se trunca con la marca `[... TRUNCADO ...]` y se agrega una alerta.
- `doc_id`: `"{instancia}-{indice:03d}"`, en orden alfabético de ruta.

### `tutela2/citas.py` (determinista + HTTP con caché)

- `normalizar_sentencia(s: str) -> tuple[tipo, numero, anio4] | None`: acepta `T-048/10`, `T-048 de 2010`, `SU-082/95`, `SU082-95`, `C 321 de 2022`.
- `clave_dataset(tipo, numero, anio) -> str`: formato `T-048/10`, con número de 3 dígitos y año de 2 dígitos.
- `cargar_dataset(cfg) -> dict[str, dict]`: descarga `cfg.dataset_csv_url` a `cache_dir/cc_sentencias.csv` si no existe o tiene más de 30 días. Si no hay red y existe la caché, la usa. Si no hay ninguna de las dos, levanta un error claro. Para los tests se puede copiar `/tmp/claude-1000/-home-sebastian-versioned-code-atomatizacion-legal/ded163ec-ef84-42dc-8161-08f30a500a94/scratchpad/datos/cc_sentencias.csv` a una carpeta temporal.
- `url_relatoria(tipo, numero, anio) -> str`: patrones verificados:
  - `https://www.corteconstitucional.gov.co/relatoria/{anio}/T-{nnn}-{aa}.htm`
  - `.../C-{nnn}-{aa}.htm`
  - `.../SU{nnn}-{aa}.htm` (SU sin guion)
- `texto_relatoria(url, cfg) -> str | None`:
  - usa caché en `cache_dir/relatoria/` y `urllib` con un User-Agent de navegador;
  - una respuesta de menos de 20.000 bytes es soft-404 y devuelve `None`;
  - decodifica en utf-8 y, si falla, en windows-1252; quita el HTML y normaliza.
- `normalizar_texto(s) -> str`: NFKD sin diacríticos, minúsculas, elimina `(...)`, `[...]` y `…`, reemplaza todo lo que no sea `[a-z0-9ñ]` por un espacio y colapsa los espacios.
- `cobertura(cita, texto_norm, n=cfg.ngram) -> float | None`: fracción de los n-gramas de la cita que aparecen en el texto.
- `verificar_citas(citas: list[CitaPropuesta], cfg, dataset) -> list[CitaVerificada]`:
  - comprueba existencia, M.P. y fecha en el dataset, la página por contenido, la cobertura y la sección de la relatoría en que está el pasaje (`separar_secciones`: mayoría, votos separados, notas y anexos), y aplica las reglas de longitud mínima (`cfg.min_palabras_cita`) y de texto normativo (4-gramas contra `assets/normas_citables.json`, con umbral `cfg.cobertura_ok`);
  - `estado`: `ok` si cobertura ≥ `cobertura_ok`; `alerta` si está entre `cobertura_alerta` y `cobertura_ok`, o si el pasaje no se puede atribuir a la mayoría (`seccion` `desconocida`); `rechazada` si es menor, si la sentencia no existe, si la página no se encontró, si la cita tiene menos de `min_palabras_cita` palabras, si reproduce texto normativo o si el pasaje solo aparece en un voto separado (`seccion` `salvamento`);
  - `CitaVerificada` lleva `n_palabras` y `seccion` (`mayoria`, `salvamento` o `desconocida`; `None` si el pasaje no se llegó a ubicar, por ejemplo sin verificar la relatoría);
  - si `cfg.verificar_relatoria` es falso, solo se comprueba la existencia en el dataset y el estado queda en `alerta`, salvo que la longitud o el texto normativo la rechacen;
  - los `motivos` van en español y son legibles; cuando una regla rechaza la cita, el último motivo enuncia la regla (`regla_de_citas(cfg)`) y no solo porcentajes.
- `sentencias_en_texto(texto) -> set[str]`: claves de dataset de toda mención T-, SU- o C- que aparezca en el texto.
- `formatear_referencia(cv: CitaVerificada) -> str`: `"Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas"`. El género sale de una lista corta de nombres femeninos frecuentes (Gloria, Diana, Clara, María, Cristina, Natalia, Paola) y por defecto es "Magistrado". Si no hay M.P., se omite la parte de la ponencia.

### `tutela2/lint.py` (determinista)

Cada función devuelve una lista de mensajes en español; si está vacía, todo está bien. Cada mensaje empieza por `BLOQUEA:` o `ALERTA:`.

- `lint_prosa(texto, campo, permitir_listas=False)`: viñetas (`-`, `•`, `*`, `1.` al inicio de una línea), encabezados markdown, `**` y rótulos como "Argumento del despacho:", "Hechos:", "Nota:", "TODO".
- `anclas_literales(apertura: AperturaLLM, ing: Ingesta)`: cada `cita_literal` de la cronología y de los reparos debe aparecer en el texto normalizado de su `doc_id`, con cobertura de 6-gramas ≥ 0,8. Si no, es `BLOQUEA`.
- `datos_ajenos(texto, ing: Ingesta)`: cada número de 23 dígitos, cédula o NIT de 6 o más dígitos y fecha numérica que aparece en la prosa debe existir en el texto de algún documento del caso. Si no, es `BLOQUEA`.
- `guardia_p3(consideraciones: ConsideracionesLLM, metadatos: Metadatos)`: el nombre del accionante, de las accionadas, de las vinculadas y los CUIs no pueden aparecer en las consideraciones (comparación normalizada; nombres de 2 palabras o más). Si aparecen, es `BLOQUEA`.
- `subconjunto_citas(caso: CasoConcretoLLM, citas: list[CitaVerificada])`:
  - los marcadores `[[CITA:id]]` deben existir y estar en estado `ok` o `alerta`;
  - toda mención de T-, SU- o C- fuera de marcador debe estar entre las sentencias verificadas;
  - si no se cumple, es `BLOQUEA`.
- `cita_verificada_en_caso(caso, citas, permitir_alerta)`: al menos un párrafo lleva el marcador de una cita `ok` (también `alerta` si `permitir_alerta`, que es el caso sin `verificar_relatoria`); si no, `BLOQUEA`. Si no hay ninguna cita utilizable, solo `ALERTA`.
- `pasajes_entre_comillas(caso, ing, citas)`: un pasaje entre comillas de 6 palabras o más que no consta en el expediente ni en la decisión (con cobertura de 6-gramas < 0,8) es `BLOQUEA`; si reproduce el texto de una cita, el mensaje indica usar su marcador.
- `marcadores_consideraciones(cons: ConsideracionesLLM)`: cada marcador corresponde a una cita, cada cita se usa y no hay sentencias sueltas fuera de marcador.
- `minimo_citas_ok(citas, minimo, min_palabras)`: `BLOQUEA` si hay menos de `minimo` citas `ok` (las `alerta` y las rechazadas no cuentan; el mensaje trae la regla y el conteo); con `minimo` 0, la falta de citas `ok` es `ALERTA`. El grafo solo la llama con `verificar_relatoria`.
- `jurisprudencia_sin_cita(texto, campo)`: `ALERTA` por cada oración que atribuye una regla a «la jurisprudencia» sin `[[CITA:id]]` en la misma oración.
- `plazos_en_caso(caso, decision)`: `ALERTA` si el caso concreto no menciona el plazo de una orden `ORDENAR` con plazo propio.
- `coherencia_decision(caso: CasoConcretoLLM, decision: Decision)`: la conclusión debe contener la raíz del resultado (`confirm`, `revoc`, `modific`) y de la sustitutiva (`ampar`/`tutel`, `neg`, `improcedent`, `carencia`/`hecho superado`). Si no, es `BLOQUEA`.
- `cobertura_reparos(parrafos_reparo_ids, reparos, decision=None)`: cada reparo que no esté `ABSORBIDO` aparece en algún párrafo o bloque. Si no, es `ALERTA`.
- `extension(texto, rango, campo)` → `ALERTA`.
- `duplicados(parrafos, umbral)`: Jaccard de conjuntos de palabras. Por encima del umbral es `ALERTA`.
- `duplicados_caso(caso, umbral)`: compara problema jurídico, párrafos y conclusión por Jaccard y por contención de trigramas (|A∩B| / mínimo, desde 0,6). Un par casi idéntico es `ALERTA`, salvo la conclusión frente al último párrafo, que es `BLOQUEA`: la conclusión va solo en `conclusion`.
- `residuos(texto)`: párrafos de menos de 40 palabras que empiezan con un infinitivo terminado en `ar`, `er` o `ir`, más `Borrador`, `[`, `TODO`. Es `ALERTA`.
- `contar_palabras(texto) -> int`.

### `tutela2/render.py` (python-docx; todavía no hay .dotx del despacho)

- **Formato común:**
  - fuente Bookman Old Style 12 pt;
  - página de 21,6 × 33,0 cm (oficio) en la Gen A y de 21,1 × 34,1 cm en la Gen B;
  - márgenes de 2,5 cm;
  - títulos de sección en negrita y centrados, con numeración romana automática;
  - pie de página con `cfg.despacho.pie` y el número de página en la Gen B.
- Títulos según `cfg.plantilla_gen`:

  | Sección | A | B |
  |---|---|---|
  | III | FALLO RECURRIDO | LA SENTENCIA IMPUGNADA |
  | IV | IMPUGNACIÓN | LA IMPUGNACIÓN |
  | V | CONSIDERACIONES DEL JUZGADO | CONSIDERACIONES |
  | Fórmula de mérito | "…administrando justicia en nombre del Pueblo y por mandato Constitucional," | "…administrando justicia en nombre de la República y por autoridad de la Ley," |
  | Competencia | En VI | En V |

- Bloques fijos, exactos (Gen B):
  - **Competencia** (un solo párrafo, `COMPETENCIA_1`): "Este Despacho es competente para conocer y resolver el recurso de impugnación interpuesto contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de amparo. En su condición de superior funcional, le corresponde adelantar un examen integral de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina fijada por la Corte Constitucional."
  - **Transición:** "Definido el marco jurídico aplicable y los criterios constitucionales relevantes, procede este Despacho a continuación a examinar la situación fáctica y jurídica específica puesta en conocimiento en este trámite constitucional."
  - **Apertura de I. ASUNTO:** "Procede el Despacho a resolver la impugnación presentada por {impugnante} contra el fallo de tutela de primera instancia proferido el {fecha_larga} por el {juzgado_a_quo}, mediante el cual {cola}." La `cola` depende de `decision_a_quo`.
- `fecha_larga(iso) -> str`: produce "veintiuno (21) de septiembre de dos mil veintiséis (2026)". Usa un conversor de números a letras propio; no se agregan dependencias.
- `render_previo(estado: dict, cfg, ruta: Path)`: produce secciones I a V, el informe de citas (tabla con sentencia, estado, cobertura, palabras, sección, M.P. del dataset, URL, texto citado y motivos) y las alertas por nodo.
- `render_fallo(estado: dict, cfg, ruta: Path)`:
  - **Encabezado:** juzgado, fecha (`hoy`), tabla con Radicado, Accionante, Accionada/o, Vinculada/os (si hay), Procedencia y Decisión. La Decisión sale de `Decision`; por ejemplo "REVOCA" o "REVOCA Y NIEGA".
  - **Cuerpo:** I. ASUNTO, II. ANTECEDENTES DEL CASO (hechos + contestaciones), III, IV, V (competencia + procedibilidad + bloques + transición), VI. CASO CONCRETO (problema jurídico, párrafos y conclusión), VII. OTRAS DETERMINACIONES (solo si hay compulsa), RESUELVE con la fórmula de mérito y "NOTIFÍQUESE Y CÚMPLASE", nombre del juez y "JUEZ".
  - **Marcadores `[[CITA:id]]`:** se reemplazan por `formatear_referencia`. En V, después del párrafo donde aparece por primera vez, se inserta el `texto_citado` entre comillas, en bloque con sangría de 1,5 cm, cursiva y 11 pt. Una cita `rechazada` se renderiza como "⟦CITA NO VERIFICADA: {sentencia_original}⟧" y sin el texto. En VI. CASO CONCRETO el modelo escribe solo marcadores: cada uno se expande a la referencia y, tras el párrafo donde aparece por primera vez en esa sección, al fragmento verificado en modo compacto (hasta 80 palabras en frases completas, con « […]» si se recorta); una cita rechazada o inexistente sale como `⟦FALTA: cita verificada {sentencia}⟧`.
  - **Marcadores `[[IMAGEN ...]]`:** se dejan como párrafo resaltado "⟦INSERTAR IMAGEN: ...⟧".
- `resuelve(decision, metadatos, cfg) -> list[str]`: lista de numerales con ordinales consecutivos (PRIMERO, SEGUNDO, ...).
  - **Primer numeral, verbo de 2a instancia:** "REVOCAR el fallo proferido el {fecha} por el {a quo}…", "CONFIRMAR…" o "MODIFICAR…".
  - **Sustitutiva:** AMPARAR, NEGAR o DECLARAR IMPROCEDENTE / LA CARENCIA ACTUAL DE OBJETO POR {tipo}. No aplica si el resultado es CONFIRMAR.
  - **Órdenes:** núcleo fijo "ORDENAR a {destinatario}, a través de su representante legal y/o quien haga sus veces, que, dentro de las {plazo en letras} ({n}) {unidad} siguientes a la notificación de esta providencia, {conducta}."
  - **Opcionales:** PREVENIR, DESVINCULAR, COMPULSAR COPIAS.
  - **Si están activados en `numerales`:** NOTIFICAR («esta providencia a las partes por el medio más expedito, de conformidad con lo dispuesto en el artículo 30 del Decreto 2591 de 1991») y REMITIR («el expediente a la Honorable Corte Constitucional para su eventual revisión», sin citar artículo).
  - **Artículo 31 o 32 al remitir (convención por confirmar):** el numeral REMITIR no cita artículo y el oficio a la Corte (`documentos/oficio.py`) cita el artículo 31 del D. 2591 de 1991. Los 9 fallos de referencia no tienen una convención única: artículo 31 solo (12001, 40601), artículo 32 solo (37401, 45601, 49501), ambos (45301, 45901), ninguno (53001, 34601); los 3 oficios de referencia citan el 31. Las fuentes secundarias ubican la remisión tras la ejecutoria del fallo de segunda instancia en el artículo 32 y no se verificó el texto primario; el despacho debe confirmar cuál usar. `test_libres_notificar_remitir` y `test_oficio_fija_la_convencion_del_articulo_31` fijan la forma actual.
- `render_informe(estado, cfg, ruta, pendientes=None)`: citas (con el aviso de falta de jurisprudencia verificada si, con `verificar_relatoria`, ninguna quedó `ok`), alertas, errores bloqueantes vigentes (los `errores` del último validador y todo `BLOQUEA:` de las alertas por nodo), «PENDIENTES Y VALORES POR DEFECTO» (`pendientes`: los fijos que calcula `expediente.generar_final` y cada `⟦FALTA…⟧` hallado en los `.docx` generados, con encabezados y pies) y bitácora.
- `render_declaracion_ia(estado, cfg, ruta)`: herramienta («Judicabot») y versión, proveedor, modelo, fechas, prompt_id y sha256 de cada grupo de llamadas (mismo nodo, proveedor, modelo y prompt) con su conteo, mapa sección → origen (plantilla / IA / humano) y decisión humana con su autor y fecha. Cita el art. 10 del Acuerdo PCSJA24-12243.
- `render_autoasume(ing, cfg, ruta)` y `render_requerimiento(ing, cfg, ruta)`: plantillas simples con variables. El requerimiento lista `faltantes`.

### `tutela2/llm.py`

- `class LLMClient(Protocol)`: `def estructurado(self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config) -> tuple[BaseModel, dict]`. El dict son los metadatos para `LlamadaIA`: `modelo_efectivo`, `tokens_entrada`, `tokens_salida`, `stop_reason`.
- **`AnthropicClient`** (SDK oficial `anthropic`):
  - llamada: `client.messages.parse(model=cfg.modelo_para(nodo), max_tokens=cfg.llm.max_tokens, system=system, messages=[{"role": "user", "content": user}], output_format=schema, output_config={"effort": cfg.effort_para(nodo)}, timeout=cfg.llm.timeout_s)`. **No** se envían `temperature` ni `thinking`;
  - con `cfg.llm.fallbacks_default`, agrega `extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"}` y `extra_body={"fallbacks": "default"}`. Si la API responde 400 y el mensaje menciona `fallback`, reintenta una vez sin esos parámetros y lo anota en el log;
  - si `stop_reason == "refusal"` o `parsed_output is None`, levanta `ErrorLLM` con un mensaje claro;
  - el cliente se crea con `anthropic.Anthropic()`, que toma `ANTHROPIC_API_KEY` del entorno.
- **`FakeClient`**: determinista, sin red. Construye salidas válidas del schema a partir del texto de entrada, para que el pipeline completo y la UI se puedan probar sin clave:
  - las citas literales se copian del propio texto de los documentos;
  - las citas de jurisprudencia usan sentencias verificadas reales, T-200/22 y SU-082/95, con fragmentos literales conocidos que se dejan como constantes;
  - el caso concreto cita esas mismas sentencias y su conclusión contiene las raíces de la decisión.
- `cliente_para(cfg) -> LLMClient`.

### `tutela2/prompts/*.md` y `tutela2/prompts.py`

- **Archivos:** `apertura.md` (base: Gem #9), `consideraciones.md` (base: Gem #6, solo en plano doctrinal) y `caso_concreto.md` (base: Gem #8 + Argumentador). El texto de los Gems está en `/tmp/claude-1000/-home-sebastian-versioned-code-atomatizacion-legal/ded163ec-ef84-42dc-8161-08f30a500a94/scratchpad/ctx/` (`manual_maestro_de_prompts_sin_truncar.md`, `argumentador.txt`, `depurador.txt`).
- **Ajustes a los Gems** según el diseño:
  - el LLM no escribe encabezados, fórmulas, competencia, transición ni RESUELVE;
  - las citas van solo como marcadores `[[CITA:id]]` con su `texto_citado` literal;
  - caso concreto: extensión configurable, sin títulos ni viñetas; desarrolla el `eje` y las disposiciones de la decisión humana, no las sustituye;
  - consideraciones: sin hechos del caso ni nombres de las partes.
- `prompt_para(nodo, cfg) -> tuple[str, str]`: devuelve el texto y su id con versión. Si existe, manda `cfg.prompts_override[nodo]`.

### `tutela2/graph.py`

Topología exacta del diseño:

```
apertura → validar_apertura → consideraciones → verificar_consideraciones → decision → caso_concreto → validar_caso → ensamblar → END
```

- **Bucles:** `validar_*` y `verificar_*` vuelven al nodo LLM si hay mensajes `BLOQUEA:` y `intentos[nodo] < cfg.max_intentos`. Al agotar los intentos, sigue con alertas.
- **Pausa:** `decision` llama solo `interrupt(payload)` y valida con `Decision.model_validate`. Si `errores()` no está vacío, se vuelve a interrumpir con los errores en el payload. `rehacer_apertura` o `rehacer_consideraciones` llevan al nodo correspondiente con la instrucción y reinician sus intentos.
- **Routers:** todos anotados con `-> Literal[...]`.
- **Compilación:**
  - `construir(cfg, llm: LLMClient, checkpointer)` devuelve el grafo compilado;
  - `checkpointer = SqliteSaver(sqlite3.connect(caso_dir/"hilo.sqlite", check_same_thread=False))`;
  - `durability="sync"`.
- Los nodos LLM agregan una entrada `LlamadaIA` a `bitacora`. El texto que reciben:
  - `apertura`: `texto_para_llm` de todos los documentos útiles, más los errores del intento previo y la instrucción de rehacer;
  - `consideraciones`: reparos, derechos invocados, `sentencia_impugnada`, `impugnacion` y los límites (bloques temáticos y, con `verificar_relatoria`, mínimo de citas verificadas y de palabras por cita). **No** recibe documentos;
  - `caso_concreto`: apertura completa, consideraciones, citas verificadas (`ok`/`alerta`) con su referencia, la Decisión y las órdenes y demás determinaciones tal como aparecerán en el resuelve (sección `ORDENES`).
- `ensamblar` llama `render_fallo`, `render_informe` y `render_declaracion_ia`.

### `tutela2/api.py` + `tutela2/cli.py`

`tutela2/api.py` expone funciones Python que devuelven dicts JSON-serializables con la forma `{"ok": bool, "estado": str, "payload": dict|None, "salidas": [str], "resumen": dict, "error": str|None}`:

| Función | Qué hace |
|---|---|
| `config_default()` | Devuelve `Config().model_dump()` |
| `prompts_default()` | Devuelve `{nodo: texto}` |
| `nuevo(caso_dir)` | Hace la ingesta, escribe `caso.json` y genera AutoAsume. Si falta alguna pieza, genera el requerimiento y responde `estado="incompleto"`. Si no, crea el hilo, corre hasta la pausa, genera `previo.docx` y responde `estado="esperando_decision"` con el payload |
| `estado(caso_dir)` | Responde `incompleto`, `sin_iniciar`, `esperando_decision`, `terminado` o `error`. Incluye el payload si hay pausa, las salidas que existen y un `resumen` para la UI: textos de la apertura, consideraciones, citas verificadas, caso concreto, alertas por nodo y bitácora |
| `decidir(caso_dir, decision: dict)` | Reanuda con `Command(resume=decision)`. Al terminar responde `terminado`; si vuelve a pausar (rehacer o decisión inválida), responde `esperando_decision` |
| `continuar(caso_dir)` | Ejecuta `invoke(None, cfg)` |

El cliente LLM sale de `llm.cliente_para(cfg)`, con `cfg` leído de `config.json` del caso. Los logs van al logger `tutela2` (`logging`).

`tutela2/cli.py` es una envoltura delgada: `uv run tutela2 <config-default|prompts-default|nuevo|estado|decidir|continuar> --caso DIR [--decision FILE]`. Imprime en stdout el JSON del resultado.

### UI en Python: `tutela2/server.py` + `tutela2/static/`

> La interfaz vigente es la de `frontend/` (Preact, ver `README.md`); `static/` solo contiene `dist/`, su compilación. Las pantallas de abajo describen la primera versión en HTML plano.

- **Arranque:** FastAPI con `uv run tutela2-ui`, que levanta uvicorn en `127.0.0.1:8000`. `CASOS_DIR` vale por defecto `<repo>/casos`.
- **Ejecución en segundo plano:** cada `run` corre en un hilo (`threading.Thread`) con un id de job. Un `logging.Handler` captura el log del job. Las salidas en `jobs[id] = {estado: corriendo|terminado|error, log: [...], resultado}`.
- **API key:** `POST /api/api-key {key}` hace `os.environ["ANTHROPIC_API_KEY"] = key`, solo en memoria del proceso; nunca se escribe a disco ni se devuelve. `GET /api/estado-servidor` responde `{api_key, jev_key, modelo, modelos}`, donde `modelos` son los de `MODELOS` que permite la variable opcional `TUTELA2_MODELOS_PERMITIDOS` (todos si no está definida) y `modelo` puede quedar fuera de esa lista.

| Ruta | Respuesta |
|---|---|
| `GET /` | `static/index.html` (más `app.js` y `styles.css` en `/static`) |
| `GET /api/config-default`, `GET /api/prompts-default` | Lo que devuelve la función homónima |
| `GET /api/casos` | `[{id, estado, n_insumos}]` |
| `POST /api/casos` | Multipart: `nombre` + `files` (varios), donde cada filename trae la ruta relativa de `webkitRelativePath`. Guarda en `casos/<slug>/insumos/<ruta relativa saneada>` |
| `GET /api/casos/{id}/config`, `PUT /api/casos/{id}/config` | Leen y escriben `config.json` (validado con `Config`) |
| `GET /api/casos/{id}/estado` | `api.estado` |
| `POST /api/casos/{id}/run {cmd, decision?}` | `{job_id}` |
| `GET /api/jobs/{id}` | El job |
| `GET /api/casos/{id}/salidas/{archivo}` | `FileResponse`, solo si el archivo existe en `salidas/` y su nombre no lleva `..` |

**Pantallas de `static/`** (HTML, CSS y JS planos, en español, sencillos y limpios; tema claro y oscuro con variables CSS):
1. **Casos:** lista de casos y creación subiendo una carpeta (`<input type=file webkitdirectory multiple>`).
2. **Configuración del caso:** formulario generado desde `config-default`. Texto, número y booleano según el tipo; select para `plantilla_gen`, `llm.proveedor` (`anthropic`/`fake`), `llm.effort` y `llm.modelo` (las opciones son las de `MODELOS`, `claude-sonnet-5-5`, `claude-haiku-5-5` y `claude-opus-5-5`, filtradas por `TUTELA2_MODELOS_PERMITIDOS`; `claude-fable-5-1` ya no se ofrece); JSON para los dict. Una pestaña de prompts con un textarea por nodo, precargado con el prompt por defecto, que guarda en `prompts_override`, y un botón "Restaurar".
3. **Ejecutar:** "Generar borrador previo" (`nuevo`) con log en vivo por polling cada 2 s.
4. **Revisión:** apertura, consideraciones, tabla de citas con chips (ok / alerta / rechazada), cobertura, M.P. del dataset, enlace a la relatoría y alertas por nodo.
5. **Decisión** (formulario por niveles):
   - `resultado`, `sustitutiva` y `eje`: obligatorios;
   - reparos precargados, con un select de disposición cada uno;
   - derechos precargados desde `derechos_invocados`;
   - órdenes: solo si se elige AMPARAR (destinatario, conducta, plazo);
   - "otros numerales", plegado: desvincular, prevenir, compulsa y los interruptores de notificar y remitir;
   - botones "Rehacer apertura" y "Rehacer consideraciones", con su instrucción.

   Los errores de validación de la decisión se muestran en la misma pantalla.
6. **Resultado:** enlaces de descarga de `fallo.docx`, `informe_verificacion.docx`, `declaracion_ia.docx`, `previo.docx` y `AutoAsume.docx`.
7. **Cabecera:** el campo de API key y su estado (configurada o no).
