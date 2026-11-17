# Judicabot UI — contrato de API (congelado para la Ola 1)

Base: `/api`. JSON UTF-8. Errores: `{"detail": str}` o `{"detail": {"errores": [{"campo","mensaje"}]}}` (config/formato). Cada endpoint nuevo declara `response_model` pydantic en `backend/tutela2/esquemas.py` (un solo archivo de modelos de respuesta; cada paquete B agrega los suyos sin tocar los ajenos).

## B1 — Casos

`GET /api/casos` → `CasoResumen[]`

```
CasoResumen {
  id: str; nombre: str; radicado: str|null; accionante: str|null; accionadas: str[];
  juzgado_a_quo: str|null;
  estado: "sin_iniciar"|"revision"|"incompleto"|"esperando_decision"|"terminado"|"error"|"corriendo";
  etapa: 0|1|2|3|4;      // 0 documentos, 1 proceso/borrador en curso, 2 decisión, 3 redacción final, 4 fallo listo
  siguiente_paso: str;   // texto para la UI, p. ej. "Revisar borrador"
  n_insumos: int; n_alertas: int; job_activo: str|null; actualizado: str  // ISO 8601 UTC
}
```

`GET /api/casos/{caso_id}/resumen` → `CasoResumen` (la misma fila que `GET /api/casos` para ese caso: mismo cache, y con `estado: "corriendo"`, `etapa` y `job_activo` si hay un job activo). 404 `{"detail": "Caso no encontrado."}` si el caso no existe. Un caso ilegible devuelve 200 con `estado: "error"`, como en la lista.

`POST /api/casos` (multipart: `nombre?` opcional, `files[]`) → `{id, n_insumos}`. Sin `nombre`, se usa la carpeta raíz de los archivos o "caso". Copia el formato global vigente al `config.json` del caso (B2). 400 si dos archivos caen en la misma ruta tras normalizarla (`{"detail": "Hay archivos con la misma ruta: a.pdf, b.pdf."}`) o si un nombre es a la vez archivo y carpeta; en ambos casos no se crea el caso.
Resumen cacheado en `<caso>/.resumen.json` (escritura atómica); se actualiza en cada transición; si falta o está desactualizado (mtime de `caso.json`/`hilo.sqlite`), se reconstruye perezosamente. Al arrancar el servidor, un hilo daemon recorre los casos y calienta esa caché (no bloquea el arranque; un caso que falle se registra y se omite; si `CASOS_DIR` no existe no hace nada).

## B2 — Formato global

`GET /api/formato` → `{ campos: CampoFormato[], valores: Despacho, plantilla_gen: "A"|"B", documentos: {id,nombre}[] }`

```
CampoFormato { clave: str; etiqueta: str; ayuda: str; tipo: "texto"|"texto_largo"|"lista"; grupo: str;
               documentos: str[]  // ids de documentos donde aparece: "fallo","auto","oficio","correos","formato","informe","declaracion_ia","requerimiento"
             }
```

`PUT /api/formato` body `{valores: Despacho, plantilla_gen}` → mismo shape que GET. Guarda `CASOS_DIR/.formato.json`. El cuerpo es estricto: `valores` exige los 19 campos del `Despacho` (sin valores por defecto), se rechazan claves extra (en el cuerpo y en `valores`), cada texto admite hasta 500 caracteres y cada lista hasta 20 líneas de 200 caracteres como máximo; los caracteres de control (p. ej. `\x01`, `\x0b`) se descartan antes de validar y guardar. 422 con `{detail:{errores:[{campo,mensaje}]}}`, un error por campo (`campo` de una lista usa el índice: `pie_fallo.2`). En OpenAPI el cuerpo de `valores` es `DespachoEntrada` (mismos campos y tipos que `Despacho`).
Nuevos campos de `Despacho`: `nombre_corto: str` (nombre sin ciudad, reemplaza el `" DE MEDELLÍN"` fijo) y `firma_correo: list[str]` (líneas de firma de correos). Con los valores por defecto los .docx deben quedar idénticos a hoy.

## B3 — Eventos

```
Evento { n: int; t: str  // ISO; etapa: "ingesta"|"apertura"|"consideraciones"|"verificacion"|"caso_concreto"|"documentos"|"sistema";
         tipo: "lee"|"razona"|"escribe"|"verifica"|"sistema"|"error"; texto: str; datos: object|null }
```

`GET /api/jobs/{id}/eventos` → `text/event-stream`. Cada mensaje: `id: <n>`, `event: evento`, `data: <Evento JSON>`; al terminar el job: `event: fin`, `data: {"estado":"terminado"|"error","error":str|null}`. Reconexión: cabecera `Last-Event-ID` o `?desde=N` (devuelve eventos con `n > N`). Sin SSE disponible: `GET /api/jobs/{id}/eventos?formato=json&desde=N` → `{eventos: Evento[], estado, error}`. Buffer por job acotado (máx. 2000 eventos; descarta los más antiguos y lo señala con un evento `sistema`). `GET /api/jobs/{id}` conserva su forma actual (con `log` recortado a las últimas 200 líneas).

## B4 — Vista previa estructurada

`GET /api/casos/{id}/vista/{borrador|fallo}` → `Vista` (404 si no existe aún). Nunca HTML.

```
Vista { tipo: "borrador"|"fallo"; sha256: str; paginas: Pagina[]; citas: CitaVista[]; indice: {id,titulo}[] }
Pagina { bloques: Bloque[] }
Bloque { id: str; tipo: "titulo"|"encabezado"|"parrafo"|"cita_bloque"|"lista"|"tabla"|"firma"|"pie"|"resuelve_numeral";
         origen: "plantilla"|"modelo"; seccion: str|null; segmentos: Segmento[];
         fuente: Fuente|null  // por defecto null }
Fuente { pieza: str; parrafo: int }  // pieza editable (B7) y posición del párrafo en `PiezaEdicion.parrafos`
Segmento { texto: str; negrita?: bool; cursiva?: bool; cita_id?: str }
CitaVista { id: str; texto: str; fuente: str; cobertura: float|null; estado: "verificada"|"revisar"|"rechazada"; detalle: str|null }
```

`fuente` solo la llevan los bloques de prosa editable de las secciones I a V (y el título de cada bloque de consideraciones, con `parrafo: 0`); vale `null` en plantilla, encabezado, ASUNTO, `cita_bloque`, tablas, caso concreto, resolutiva y pies. El fallo también la lleva en I a V, pero su vista la ignora.

Invariante: concatenar `segmentos[].texto` de todos los bloques de texto reproduce el texto de los párrafos del .docx (prueba de equivalencia).

## B5 — Vista del RESUELVE

`POST /api/casos/{id}/decision/vista` body = decisión **parcial** (campos de `models.Decision`, todos opcionales, tolerante) →

```
{ numerales: {clave: str; texto: str; negritas: str[]}[]; faltantes: {campo: str; mensaje: str}[]; errores: str[] }
```
Nunca 500: entradas inválidas devuelven `errores` y `numerales` vacío o parcial.

## B6 — Preferencias de IA

`GET /api/ia` → `{modelo, modelos[], api_key: bool, jev_key: bool, jev: {modo:"apagado"|"sombra"|"relleno", umbral: float}, effort, max_tokens: int, max_retries: int}`; `PUT /api/ia` con los mismos campos editables (`modelo, jev.modo, jev.umbral, effort, max_tokens, max_retries`) → mismo shape. Se guarda en `.preferencias.json` (se conserva `modelo`) y se aplica a casos nuevos y al ejecutar (como hoy `TUTELA2_MODELO`). `/api/estado-servidor`, `/api/modelo`, `/api/api-key`, `/api/jev-key` se mantienen.

## B7 — Edición in situ del borrador

Diseño: `docs/superpowers/specs/2026-11-17-edicion-in-situ-design.md`. Rutas en `backend/tutela2/rutas_ediciones.py`; esquemas en `esquemas.py`. Una **pieza** es un campo de texto del estado (`apertura.antecedentes_hechos`, `apertura.contestaciones.{i}.texto`, `apertura.sentencia_impugnada`, `apertura.impugnacion`, `consideraciones.procedibilidad`, `consideraciones.bloques.{i}.titulo`, `consideraciones.bloques.{i}.texto`); cualquier otro id es desconocido. El id va en la ruta: el cliente aplica `encodeURIComponent`. Las ediciones no tocan el grafo: viven en `caso_dir/ediciones.json` y se consolidan al decidir.

```
PiezaEdicion { parrafos: str[]; editados: int[]; modificada: bool; avisos: str[] }
  // parrafos: forma editable (citas ⟦cita c2 · T-200 de 2022⟧, imágenes ⟦imagen · desc⟧; el frontend no las convierte)
  // editados: índices de párrafos distintos del texto de la IA (inserciones y reemplazos; un párrafo quitado no tiene índice)
  // modificada: el texto efectivo difiere del de la IA, también cuando solo se quitaron párrafos (en un conflicto vale false)
TrozoOk { tipo: "ok"; parrafos: str[] }
TrozoConflicto { tipo: "conflicto"; mio: str[]; nuevo: str[]; mio_permitido: bool }
ConflictoEdicion { pieza: str; etiqueta: str; huerfana: bool; trozos: (TrozoOk|TrozoConflicto)[] }  // discriminador `tipo`
  // huerfana: la pieza perdió su ancla (contestación por entidad, bloque por título de la IA); trozos = [TrozoOk con el texto del usuario], solo se descarta
EdicionesRespuesta { editable: bool; motivo: str|null; piezas: {[pieza]: PiezaEdicion}; conflictos: ConflictoEdicion[] }
EdicionCuerpo { parrafo: int >= 0; original: str; texto: str }
ResolverCuerpo { elecciones: ("mio"|"nuevo")[] }
```

`GET /api/casos/{id}/ediciones` → `EdicionesRespuesta`. Con un job corriendo o con el caso fuera de `esperando_decision` responde **200** `{editable: false, motivo, piezas: {}, conflictos: []}`, nunca un 4xx. Si es editable, sincroniza con la salida actual de la IA; si la capa cambió, la guarda y regenera `previo.docx`. 404 `{"detail": "Caso no encontrado."}` si el caso no existe.

`PUT /api/casos/{id}/ediciones/{pieza}` body `EdicionCuerpo` → `EdicionesRespuesta`. `original` debe ser `piezas[pieza].parrafos[parrafo]` tal como se recibió (no el texto del bloque de la vista); `texto` puede traer 0 o más párrafos separados por una línea en blanco (0 borra el párrafo). Los títulos (`…titulo`) rechazan cualquier salto de línea.
`DELETE /api/casos/{id}/ediciones/{pieza}` → `EdicionesRespuesta`. Restaura **toda** la pieza al texto de la IA, o descarta la edición de una pieza huérfana.
`POST /api/casos/{id}/ediciones/{pieza}/resolver` body `ResolverCuerpo` → `EdicionesRespuesta`. Una elección por trozo en conflicto, en orden; elegir `"mio"` exige `mio_permitido`. Una pieza huérfana no se resuelve: se descarta con DELETE.

Cada llamada que modifica devuelve la `EdicionesRespuesta` completa y regenera `previo.docx` y la vista del borrador.

Códigos de PUT, DELETE y POST: **404** `{"detail": "No existe la pieza …"}` si la pieza es desconocida (o el caso no existe); **409** si hay un job corriendo, el caso no está en `esperando_decision`, la pieza tiene un conflicto pendiente (PUT) o `original` está desfasado (`"recargue el borrador"`), o no hay conflicto que resolver (POST); **422** si la validación falla (pieza vacía, `[[`/`]]` o fichas ⟦…⟧ alteradas, citas o imágenes distintas de las de la IA, jurisprudencia nueva fuera de ficha, número de elecciones distinto, `"mio"` no permitido o pieza huérfana). Todos los errores son `{"detail": str}` en español, con los motivos unidos por un espacio; los 422 de validación del cuerpo de FastAPI traen una lista.

**Conflictos y decisión.** `POST /api/casos/{id}/run` con `cmd: "decidir"` responde **409** `{"detail": "Hay conflictos de edición sin resolver en el borrador: resuélvalos antes de decidir."}` mientras haya conflictos pendientes, de forma síncrona y sin crear un job (así no aparece un job fallido en la vista del proceso). Vale para toda decisión enviada con ese `cmd`, también las de rehacer apertura o consideraciones. Tras una corrección de la IA, el rebase puede dejar conflictos nuevos: aparecen en el siguiente `GET …/ediciones` y bloquean la siguiente decisión hasta resolverlos.

## Existentes que la UI usa sin cambios

`GET /api/casos/{id}/estado`, `POST /api/casos/{id}/run` (`{cmd, decision?, forzar?}` → `{job_id}`; 409 si hay job), `PUT /api/casos/{id}/revision`, `GET /api/casos/{id}/salidas[/{archivo}]`, `GET /api/casos/{id}/zip`, `/api/estado-servidor`, `/api/api-key`, `/api/jev-key`.

## Propiedad de archivos (Ola 1)

Backend: B1 `resumen_caso.py`, `esquemas.py`(sección casos), tests `test_resumen_caso.py`; B2 `formato_global.py`, `config.py`, `documentos/*`, tests `test_formato_global.py`; B3 `eventos.py`, instrumentación en `graph.py/ingest.py/citas.py`; B4 `render.py`, `vista.py`; B5 `decision_vista.py` + `rutas_decision.py`; B6 `preferencias.py`. `server.py` lo edita **solo un agente a la vez**: cada paquete registra sus rutas con `APIRouter` en su propio módulo (`rutas_casos.py`, `rutas_formato.py`, `rutas_eventos.py`, `rutas_vista.py`, `rutas_ia.py`) y una única línea `app.include_router(...)` en `server.py` agregada por el integrador de la ola.

Frontend: cada vista en `src/vistas/<vista>/` (código, pruebas, fixtures `*.fixture.ts`); primitivas en `src/ui/`; nadie edita `src/api/tipos.ts` (generado) ni `src/rutas/`.
