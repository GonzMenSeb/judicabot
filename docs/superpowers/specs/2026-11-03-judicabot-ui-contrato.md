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
         origen: "plantilla"|"modelo"; seccion: str|null; segmentos: Segmento[] }
Segmento { texto: str; negrita?: bool; cursiva?: bool; cita_id?: str }
CitaVista { id: str; texto: str; fuente: str; cobertura: float|null; estado: "verificada"|"revisar"|"rechazada"; detalle: str|null }
```

Invariante: concatenar `segmentos[].texto` de todos los bloques de texto reproduce el texto de los párrafos del .docx (prueba de equivalencia).

## B5 — Vista del RESUELVE

`POST /api/casos/{id}/decision/vista` body = decisión **parcial** (campos de `models.Decision`, todos opcionales, tolerante) →

```
{ numerales: {clave: str; texto: str; negritas: str[]}[]; faltantes: {campo: str; mensaje: str}[]; errores: str[] }
```
Nunca 500: entradas inválidas devuelven `errores` y `numerales` vacío o parcial.

## B6 — Preferencias de IA

`GET /api/ia` → `{modelo, modelos[], api_key: bool, jev_key: bool, jev: {modo:"apagado"|"sombra"|"relleno", umbral: float}, effort, max_tokens: int, max_retries: int}`; `PUT /api/ia` con los mismos campos editables (`modelo, jev.modo, jev.umbral, effort, max_tokens, max_retries`) → mismo shape. Se guarda en `.preferencias.json` (se conserva `modelo`) y se aplica a casos nuevos y al ejecutar (como hoy `TUTELA2_MODELO`). `/api/estado-servidor`, `/api/modelo`, `/api/api-key`, `/api/jev-key` se mantienen.

## Existentes que la UI usa sin cambios

`GET /api/casos/{id}/estado`, `POST /api/casos/{id}/run` (`{cmd, decision?, forzar?}` → `{job_id}`; 409 si hay job), `PUT /api/casos/{id}/revision`, `GET /api/casos/{id}/salidas[/{archivo}]`, `GET /api/casos/{id}/zip`, `/api/estado-servidor`, `/api/api-key`, `/api/jev-key`.

## Propiedad de archivos (Ola 1)

Backend: B1 `resumen_caso.py`, `esquemas.py`(sección casos), tests `test_resumen_caso.py`; B2 `formato_global.py`, `config.py`, `documentos/*`, tests `test_formato_global.py`; B3 `eventos.py`, instrumentación en `graph.py/ingest.py/citas.py`; B4 `render.py`, `vista.py`; B5 `decision_vista.py` + `rutas_decision.py`; B6 `preferencias.py`. `server.py` lo edita **solo un agente a la vez**: cada paquete registra sus rutas con `APIRouter` en su propio módulo (`rutas_casos.py`, `rutas_formato.py`, `rutas_eventos.py`, `rutas_vista.py`, `rutas_ia.py`) y una única línea `app.include_router(...)` en `server.py` agregada por el integrador de la ola.

Frontend: cada vista en `src/vistas/<vista>/` (código, pruebas, fixtures `*.fixture.ts`); primitivas en `src/ui/`; nadie edita `src/api/tipos.ts` (generado) ni `src/rutas/`.
