# Extensión de la relatoría: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que judicabot en producción (VPS en Singapur, 403 del WAF de la relatoría) verifique las citas contra el texto de la relatoría, pidiendo las páginas a una extensión de Chrome/Edge instalada en un navegador en Colombia.

**Architecture:** la extensión (MV3) abre un WebSocket autenticado a `/api/extension` y lo mantiene vivo con latidos. Cuando `consultar_relatoria` no encuentra la página en caché y la descarga directa falla, `extension.pedir_pagina(url)` manda el pedido por ese socket y espera el código HTTP y los bytes crudos; la clasificación, la validación y la caché siguen en `citas.py`. Sin extensión, o sin respuesta a tiempo, la cita queda "para revisar" y el aviso dice por qué.

**Tech Stack:** FastAPI/Starlette WebSocket (uvicorn 0.54 + `websockets`), pytest con `TestClient.websocket_connect`; extensión MV3 en JavaScript plano (sin bundler) probada con `node --test` (Node 24).

**Spec:** `docs/superpowers/specs/2026-11-15-extension-relatoria-requisitos.md`

**Context.** Desde el PR #2 (`c359046`, desplegado hoy en el VPS) una página inaccesible deja la cita para revisar; en producción eso pasa con todas porque el WAF responde 403. El navegador no puede leer las `.htm` (no hay CORS); una extensión con `host_permissions` sí.

## Decisiones tomadas (el usuario pidió resolverlas desde el código y la documentación)

1. **Un WebSocket por extensión, también para los bytes.** Desde Chrome 116 el tráfico de un WebSocket reinicia el temporizador de inactividad (30 s) del service worker; el ejemplo oficial manda un mensaje cada 20 s. `chrome.alarms` cada 30 s (Chrome 120+) reabre la conexión si el worker murió. Traefik 3.6 del VPS no tiene middlewares ni límite de cuerpo en el router de judicabot y su `readTimeout` (60 s) no aplica a conexiones ya actualizadas; uvicorn acepta mensajes de hasta 16 MiB y hace ping cada 20 s. La página más grande vista pesa 4,6 MB.
2. **Autenticación por contraseña cambiada por una ficha, no por la cookie.** Chrome documenta que las peticiones de una extensión con permiso de host cuentan como mismo sitio solo para `fetch`, y no cuando el usuario bloquea cookies de terceros; para el handshake del WebSocket no está confirmado. Además `acceso.compuerta` es middleware `http` y no corre en conexiones WebSocket. Por eso el endpoint valida por su cuenta: la extensión manda la contraseña una vez y recibe `ficha = HMAC(JUDICABOT_PASSWORD, "judicabot-extension")`. Cambiar la contraseña revoca la ficha, y los intentos de contraseña comparten el límite de `/login` (`acceso._fallos`). Cumple el requisito 7.
3. **La extensión no necesita permiso sobre el servidor de judicabot** (un WebSocket no pasa por CORS ni por `host_permissions`). Su único permiso de host es la relatoría, y la dirección del servidor se configura en la ventana de la extensión (por defecto `https://judicabot.web.vespiridion.org`), lo que permite probarla contra `http://127.0.0.1:8000`.
4. **Sin cambios en el frontend de judicabot.** El estado de conexión se ve en el ícono y la ventana de la extensión; el porqué de cada cita llega en los motivos y en el aviso, que la UI ya muestra (`Seguimiento.tsx` pinta `evento.texto`; `Riel.tsx` muestra `cita.detalle`). Las rutas nuevas no entran al esquema OpenAPI (WebSocket e `include_in_schema=False`), así que `frontend/openapi.json` no cambia.
5. **Endpoint de diagnóstico `GET /api/relatoria?sentencia=…`.** El socket vive en el proceso de uvicorn, así que `docker exec … python` no vería la extensión; los criterios de aceptación ("`consultar_relatoria` sobre URLs conocidas da…") solo se pueden comprobar dentro del servidor. Recibe una sentencia, no una URL, para que nadie pueda pedir URLs arbitrarias.
6. **Si la extensión no responde a tiempo, el servidor cierra ese socket.** Los pedidos siguientes no esperan otros 120 s cada uno: dan "no conectada" de inmediato hasta que la extensión se reconecte, lo que hace sola en unos segundos si sigue viva.
7. **Distribución por modo de desarrollador por ahora** (indicación del usuario, 2026-11-15): se carga la carpeta `extension/` descomprimida en `chrome://extensions` o `edge://extensions`. Publicar como no listada en la Chrome Web Store (requisito 1) queda para después; el manifiesto ya respeta sus límites (ícono de 128 px, descripción de 132 caracteres o menos). Sin el permiso `background`: el requisito es que funcione con el navegador abierto.

## Global Constraints

- Base: `origin/main` en `c359046`. La rama actual (`feat/jev-rol-nombre-archivo`) y el `main` local están atrasados.
- La extensión solo descarga URLs bajo `https://www.corteconstitucional.gov.co/relatoria/` y rechaza cualquier otra (req. 2). El servidor tampoco manda otra cosa: `pedir_pagina` lanza `ValueError` si la URL no empieza por `citas.BASE_RELATORIA + "/"` (req. 8).
- Orden de consulta: caché → descarga directa (`_bajar_pagina`) → extensión, y la extensión solo cuando la descarga directa no trae bytes (`crudo is None`) (req. 5).
- Clasificación, `_es_pagina_de` y escritura en caché siguen siendo el código actual de `consultar_relatoria` (req. 4).
- Ninguna ruta nueva funciona sin la contraseña cuando `JUDICABOT_PASSWORD` está definida (req. 7). Sin contraseña configurada (uso local), todo abierto, igual que `compuerta`.
- Chrome y Edge 120 o más (`minimum_chrome_version: "120"`).
- Identificadores, mensajes y textos en español; comentarios al mínimo absoluto; commits `feat:`/`fix:`/`docs:` con texto en español.
- Pruebas contra servicios externos solo con el caso sintético. `ssh vps` solo lectura. `test_sdk_real_sin_clave_da_error_claro` ya falla en `main`; no es de este trabajo.

## Protocolo extensión ↔ servidor (`/api/extension`)

| Dirección | Mensaje |
|---|---|
| ext → srv, primer mensaje, texto, antes de 10 s | `{"tipo":"hola","version":"1.0.0","ficha":"<hex>"}` o `{"tipo":"hola","version":"1.0.0","contrasena":"…"}` |
| srv → ext, texto | `{"tipo":"listo","ficha":"<hex>"}` (`""` si el servidor no tiene contraseña) |
| srv cierra | `4401` credencial ausente o inválida · `4429` demasiados intentos (`acceso._bloqueado`) · `4408` no respondió un pedido a tiempo |
| srv → ext, texto | `{"tipo":"pedido","id":"<uuid4 hex>","url":"https://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm"}` |
| ext → srv, binario | cabecera JSON UTF-8 `{"id":"…","codigo":200,"detalle":""}` + `\n` + bytes crudos del cuerpo (`codigo` es `null` si el `fetch` falló; el cuerpo puede ir vacío) |
| ext → srv, texto, cada 20 s | `{"tipo":"latido"}` (el servidor lo ignora) |

Mapeo en el servidor a `extension.Entrega(estado, cuerpo, detalle)`:

| Caso | `estado` | `cuerpo` | `detalle` |
|---|---|---|---|
| `codigo == 200` | `"ok"` | bytes | `""` |
| otro `codigo` | `"rechazo"` | `None` | `f"HTTP {codigo}"` |
| `codigo is None` | `"sin_respuesta"` | `None` | el `detalle` de la extensión, o `"la extensión no pudo descargar la página"` |
| nadie conectado | `"no_conectada"` | `None` | `"la extensión de judicabot no estaba conectada"` |
| vence `espera_s` | `"sin_respuesta"` | `None` | `"la extensión no respondió a tiempo"` |
| se cae el socket con el pedido pendiente | `"sin_respuesta"` | `None` | `"la extensión se desconectó"` |

## Review Focus

1. **El portátil se suspende o se cierran las ventanas a mitad de una ejecución**: el pedido vence, el servidor suelta el socket y los pedidos siguientes dan `no_conectada` al instante, sin sumar 120 s por cita. Prueba: `test_sin_respuesta_a_tiempo_suelta_la_conexion` (tarea 1).
2. **Dos ejecuciones a la vez usan la misma extensión**: los pedidos se cruzan en el socket y cada respuesta llega a quien la pidió. Prueba: `test_pedidos_concurrentes_se_responden_por_id` (tarea 1).
3. **Respuesta tardía después del vencimiento**: se descarta sin romper la conexión ni resolver otro pedido. Prueba: `test_entrega_tardia_se_ignora` (tarea 1).
4. **Se cambia `JUDICABOT_PASSWORD` y la extensión guarda una ficha vieja**: el servidor cierra con 4401, la extensión borra la ficha y pide la contraseña en vez de reintentar sin fin. Pruebas: `test_ficha_vieja_tras_cambiar_la_contrasena_cierra_con_4401` (tarea 1) y `cierre 4401 borra la ficha y no reintenta` (tarea 4).
5. **Despliegue o reinicio del servidor**: la extensión se reconecta sola con la ficha guardada. Prueba: `cierre inesperado reintenta con la ficha` (tarea 4).

---

### Tarea 1: puente en el servidor (WebSocket, autenticación, pedidos)

**Files:**
- Create: `backend/tutela2/extension.py`, `backend/tutela2/rutas_extension.py`, `backend/tests/test_extension.py`, `docs/superpowers/plans/2026-11-15-extension-relatoria.md` (copia de este plan)
- Modify: `backend/tutela2/acceso.py`, `backend/tutela2/server.py:479` (agregar `"rutas_extension"` a la tupla de routers), `backend/pyproject.toml` + `backend/uv.lock` (`websockets` como dependencia directa; hoy solo llega por `langgraph-sdk`/`langsmith`)
- Commit también: `docs/superpowers/specs/2026-11-15-extension-relatoria-requisitos.md` (hoy sin seguimiento)

**Interfaces:**
- Produces, `acceso.py`:
  - `verificar_contrasena(cliente: str, enviada: str, pw: str) -> Literal["ok", "mal", "bloqueado"]`, extraída de `_login` (que pasa a usarla) con la misma lógica de `_fallos`/`_bloqueado`/`compare_digest`.
  - `ficha_extension(pw: str) -> str`: `hmac.new(pw.encode(), b"judicabot-extension", hashlib.sha256).hexdigest()`.
  - `_cliente(conexion: HTTPConnection)` (antes `Request`), para usarla también con `WebSocket`.
- Produces, `extension.py`:
  - `ESPERA_S = 120.0` (60 s de descarga en la extensión, igual a `citas.TIMEOUT_S`, más la subida de hasta ~5 MB a Singapur), `ESPERA_HOLA_S = 10.0`.
  - `class Entrega(NamedTuple): estado: Literal["ok", "no_conectada", "sin_respuesta", "rechazo"]; cuerpo: bytes | None = None; detalle: str = ""`
  - `conectada() -> bool`
  - `async def atender(socket: WebSocket, version: str) -> None`: registra la conexión (bucle de eventos actual, pendientes `dict[str, concurrent.futures.Future]`, `asyncio.Lock` para los envíos), recibe hasta la desconexión y al salir la quita y resuelve sus pendientes con `"la extensión se desconectó"`. Registra con `log.info` la conexión (con la versión) y la desconexión.
  - `pedir_pagina(url: str, espera_s: float = ESPERA_S) -> Entrega`: síncrona, para el hilo de la ejecución. Usa la conexión más reciente, envía con `asyncio.run_coroutine_threadsafe` y espera el futuro. Si vence, cierra ese socket con 4408 y lo saca del registro. Nunca se llama desde el hilo del bucle de eventos (las rutas que la usan son `def`, no `async def`).
  - Importa `BASE_RELATORIA` de `citas`; por eso `citas` importará `extension` dentro de `consultar_relatoria` (tarea 2), no arriba del módulo.
- Produces, `rutas_extension.py`: `router = APIRouter()`, `@router.websocket("/api/extension") async def socket_extension(socket: WebSocket) -> None`: `accept`, espera el `hola` con `asyncio.wait_for(…, ESPERA_HOLA_S)` y autoriza así: sin contraseña configurada, sí; `ficha` igual (`compare_digest`) a `ficha_extension(pw)`, sí; `contrasena` → `verificar_contrasena(_cliente(socket), …)`, y `"bloqueado"` cierra con 4429. Cualquier otra cosa cierra con 4401. Si autoriza, manda `listo` y llama a `extension.atender`.

- [ ] **Paso 1: rama y documentos.** `git fetch origin && git switch -c feat/extension-relatoria origin/main`. El cambio sin confirmar de `.gitignore` (`notebook-agents/…`) es del usuario: no se toca ni se agrega. Copiar este plan a `docs/superpowers/plans/2026-11-15-extension-relatoria.md`.
- [ ] **Paso 2: escribir `backend/tests/test_extension.py`.** Fixture `cliente`: `monkeypatch.setenv("JUDICABOT_PASSWORD", "clave-de-prueba")`, `acceso._fallos.clear()`, registro de `extension` vacío, `TestClient(server.app, base_url="http://127.0.0.1")`. Helpers: `_hola(ws, **campos)` y `_entrega(id, codigo, cuerpo=b"", detalle="") -> bytes`. Para pedir mientras la prueba hace de extensión: `ThreadPoolExecutor().submit(extension.pedir_pagina, URL)`, después `ws.receive_json()` y `ws.send_bytes(…)`. Pruebas:
  - `test_hola_sin_credencial_cierra_con_4401`, `test_contrasena_incorrecta_cierra_con_4401`: `WebSocketDisconnect` con `.code == 4401`.
  - `test_contrasena_correcta_entrega_la_ficha`: `ws.receive_json() == {"tipo": "listo", "ficha": acceso.ficha_extension("clave-de-prueba")}`, y la misma ficha reconecta.
  - `test_ficha_vieja_tras_cambiar_la_contrasena_cierra_con_4401`.
  - `test_demasiados_intentos_cierra_con_4429`: tras `acceso.MAX_FALLOS` contraseñas malas, la siguiente, aunque sea correcta, cierra con 4429.
  - `test_sin_contrasena_configurada_acepta`: con `delenv`, `listo` con `ficha == ""`.
  - `test_pedir_pagina_sin_extension_no_espera`: `Entrega("no_conectada", None, "la extensión de judicabot no estaba conectada")` en menos de 1 s.
  - `test_pedir_pagina_rechaza_urls_fuera_de_la_relatoria`: `ValueError` para `https://example.com/x.htm`, `https://www.corteconstitucional.gov.co/otra/x.htm` y `http://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm`.
  - `test_pedir_pagina_devuelve_los_bytes_que_entrega_la_extension`: tras un `latido`, el pedido llega con `{"tipo": "pedido", "url": URL}` e `id` de 32 hex, y la respuesta 200 da `Entrega("ok", cuerpo, "")`.
  - `test_codigo_http_de_error_es_rechazo` (403 → `Entrega("rechazo", None, "HTTP 403")`) y `test_error_de_la_extension_es_sin_respuesta` (`codigo` `None`, `detalle` "Failed to fetch").
  - `test_sin_respuesta_a_tiempo_suelta_la_conexion`: con `espera_s=0.2` da `sin_respuesta` con "no respondió a tiempo", luego `extension.conectada() is False`, el socket recibe el cierre 4408 y un `pedir_pagina` nuevo da `no_conectada`.
  - `test_entrega_tardia_se_ignora`: una entrega con un `id` vencido no rompe nada y el pedido siguiente se resuelve bien.
  - `test_pedidos_concurrentes_se_responden_por_id`: dos pedidos respondidos en orden inverso; cada uno recibe su cuerpo.
  - `test_desconexion_con_pedido_pendiente_es_sin_respuesta`: "la extensión se desconectó".
  - `test_paginas_de_varios_megabytes_pasan`: 5 MiB llegan íntegros.
- [ ] **Paso 3:** `cd backend && uv run pytest tests/test_extension.py -v`. Esperado: FALLA (no existen los módulos).
- [ ] **Paso 4:** implementar `acceso.py`, `extension.py`, `rutas_extension.py`, registrar el router y `uv add websockets` (versión del lock, 17.4).
- [ ] **Paso 5:** `uv run pytest tests/test_extension.py tests/test_acceso.py tests/test_server.py -v`. Esperado: PASA.
- [ ] **Paso 6: humo con uvicorn real** (TestClient no ejercita la implementación WebSocket de uvicorn): `JUDICABOT_PASSWORD=clave-local-1234 uv run tutela2-ui` y, en otra terminal, `node -e` con el `WebSocket` global de Node 24: conectar a `ws://127.0.0.1:8000/api/extension`, mandar el `hola` con la contraseña y comprobar el `listo` con ficha; con una contraseña mala, el cierre debe ser 4401.
- [ ] **Paso 7:** `uv run --extra ocr pytest`. Todo pasa, salvo el `test_sdk_real_sin_clave_da_error_claro` ya conocido. Commit `feat: puente WebSocket para que una extensión del navegador descargue la relatoría`.

### Tarea 2: `consultar_relatoria` recurre a la extensión y el aviso dice por qué falta

**Files:**
- Modify: `backend/tutela2/citas.py` (`Relatoria`, `consultar_relatoria` 252-267, `verificar_citas` 1100-1107, `_motivo_sin_relatoria` 1226-1237)
- Test: `backend/tests/test_citas.py`

**Interfaces:**
- Consumes: `extension.pedir_pagina`, `extension.Entrega` (tarea 1).
- Produces: `class Relatoria(NamedTuple): texto; estado; detalle: str = ""; extension: Literal["no_conectada", "sin_respuesta", "rechazo"] | None = None`.
- `consultar_relatoria`: si `_bajar_pagina` devuelve `None`, llama a `extension.pedir_pagina(url)` (importada dentro de la función). Con `ok`, los bytes siguen el camino actual: `_clasificar_pagina`, `_es_pagina_de` y escritura en caché. Si no, devuelve `Relatoria(None, "inaccesible", detalle, entrega.estado)`, con `detalle` igual al error de la descarga directa (p. ej. `"HTTP 403"`) cuando el estado es `no_conectada`, y el `detalle` de la entrega en los demás casos. La caché y la descarga directa que funciona no tocan la extensión.

Textos fijos (`_motivo_sin_relatoria`, según `relatoria.extension`):
- `None`: el texto actual, sin cambios.
- `"no_conectada"`: `f"No se pudo consultar la relatoría de la Corte Constitucional desde el servidor ({causa}){bloqueo} y la extensión de judicabot no estaba conectada; la cita no se pudo verificar y esto no indica que la sentencia no exista. Verifique el pasaje en {cv.url}."`
- `"rechazo"`: `f"La relatoría de la Corte Constitucional rechazó la petición de la extensión de judicabot ({relatoria.detalle}); la cita no se pudo verificar y esto no indica que la sentencia no exista. Verifique el pasaje en {cv.url}."`
- `"sin_respuesta"`: `f"La extensión de judicabot no trajo la página de la relatoría ({relatoria.detalle}); la cita no se pudo verificar y esto no indica que la sentencia no exista. Verifique el pasaje en {cv.url}."`

Aviso de `verificar_citas`: un evento `("verificacion", "verifica", texto, {"sin_acceso": lista, "extension": clave})` por cada grupo no vacío. La clave sale de `paginas[cv.url].extension`; `lista` es la de sentencias, ordenada y unida con `", "`.
- `None`: el texto actual.
- `"no_conectada"`: `f"La relatoría de la Corte no respondió desde el servidor para {lista} y la extensión de judicabot no estaba conectada: esas citas quedan para revisar, no rechazadas."`
- `"rechazo"`: `f"La relatoría de la Corte rechazó la petición de la extensión de judicabot para {lista}: esas citas quedan para revisar, no rechazadas."`
- `"sin_respuesta"`: `f"La extensión de judicabot no trajo a tiempo la relatoría para {lista}: esas citas quedan para revisar, no rechazadas."`

`render.py` (`⟦FALTA…⟧`) y `lint.py` no cambian: siguen marcando `relatoria == "inaccesible"` como hoy.

- [ ] **Paso 1: pruebas nuevas en `test_citas.py`.** Helper `_extension(monkeypatch, entrega) -> list[str]`: reemplaza `extension.pedir_pagina` y registra las URLs. Usar `_red(monkeypatch, error=urllib.error.HTTPError(URL_T200, 403, "Forbidden", {}, None))` para la descarga directa.
  - `test_consultar_relatoria_sin_extension_conectada_lo_dice`: `r == Relatoria(None, "inaccesible", "HTTP 403", "no_conectada")`, sin `relatoria/` en la caché.
  - `test_consultar_relatoria_usa_la_extension_cuando_el_servidor_no_puede`: `Entrega("ok", _pagina("T-200/22"))` da `r.estado == "ok"`, `r.extension is None`, y `cache/relatoria/T-200-22.htm` tiene esos bytes.
  - `test_consultar_relatoria_no_pide_a_la_extension_si_la_descarga_directa_funciona` y `..._si_esta_en_cache`: lista de llamadas vacía.
  - `test_consultar_relatoria_shell_desde_la_extension_es_no_publicada`: `SHELL_ANGULAR` da `Relatoria(None, "no_publicada", "")` y nada en caché.
  - `test_consultar_relatoria_pagina_de_otra_sentencia_desde_la_extension_no_se_guarda`.
  - `test_consultar_relatoria_rechazo_de_la_relatoria_a_la_extension`: `Relatoria(None, "inaccesible", "HTTP 403", "rechazo")`. Y `..._extension_sin_respuesta`: `detalle == "la extensión no respondió a tiempo"`.
  - `test_verificar_motivo_dice_que_la_extension_no_estaba_conectada`: el motivo contiene "No se pudo consultar la relatoría", "HTTP 403", "bloquear", "la extensión de judicabot no estaba conectada" y `cv.url`. Más un caso por cada uno de `rechazo` y `sin_respuesta` con sus frases fijas.
  - `test_verificar_aviso_distingue_extension_no_conectada_de_rechazo`: buffer con `eventos.crear("prueba")` + `eventos.activar(buffer)`, dos citas de sentencias distintas, una `no_conectada` y otra `rechazo`. Los textos de `buffer.leer(0)[0]` incluyen "no estaba conectada" y "rechazó la petición de la extensión", con `datos["extension"]` respectivos.
- [ ] **Paso 2:** `uv run pytest tests/test_citas.py -v`. Esperado: FALLAN las nuevas.
- [ ] **Paso 3:** implementar los cambios en `citas.py`.
- [ ] **Paso 4:** `uv run --extra ocr pytest`. Esperado: PASA, incluidas las existentes de `test_citas.py` (791-806), `test_graph.py` (1619-1648), `test_lint.py` y `test_render.py`, sin tocarlas. Commit `feat: la verificación de citas pide la relatoría a la extensión cuando el servidor no puede`.

### Tarea 3: consulta de diagnóstico `GET /api/relatoria`

**Files:**
- Modify: `backend/tutela2/rutas_extension.py`, `backend/tests/test_extension.py`

**Interfaces:**
- Consumes: `citas.normalizar_sentencia`, `citas.url_relatoria`, `citas.consultar_relatoria`, `extension.conectada`, `Config()` (como `rutas_dataset.py`).
- Produces: `@router.get("/api/relatoria", include_in_schema=False) def consulta_relatoria(sentencia: str) -> dict`. Es `def` y no `async def`, porque bloquea esperando a la extensión. Responde `{"sentencia", "url", "estado", "detalle", "extension", "caracteres", "extension_conectada"}`, donde `caracteres = len(texto)` o `None`. Si la sentencia no se puede interpretar, 422. La protege `compuerta`, como todo `/api`.

- [ ] **Paso 1: pruebas.** Importar `_pagina` y `SHELL_ANGULAR` con `from test_citas import …` (`backend/tests` no tiene `__init__.py`; pytest lo pone en `sys.path`). `TUTELA2_CACHE_DIR` en `tmp_path`; `urllib.request.urlopen` levanta `HTTPError` 403.
  - `test_consulta_relatoria_exige_sesion`: con contraseña y sin cookie, 401.
  - `test_consulta_relatoria_sentencia_invalida`: `?sentencia=xyz`, 422.
  - `test_consulta_relatoria_por_la_extension_queda_en_cache`: cookie vía `POST /login`, socket con contraseña, `GET /api/relatoria?sentencia=T-200/22` en otro hilo. La prueba responde el pedido con `_pagina("T-200/22")`. Resultado: `estado == "ok"`, `extension_conectada is True` y el archivo `relatoria/T-200-22.htm` existe. Con `SHELL_ANGULAR` para `SU-319/26`, `estado == "no_publicada"`.
  - `test_consulta_relatoria_sin_extension_es_inaccesible`: `estado == "inaccesible"`, `extension == "no_conectada"`, `extension_conectada is False`.
  - `test_openapi_json_versionado_esta_al_dia` sigue pasando sin regenerar `frontend/openapi.json`.
- [ ] **Paso 2:** correr y ver que fallan. **Paso 3:** implementar. **Paso 4:** `uv run --extra ocr pytest`, que pasa. Commit `feat: consulta de diagnóstico de la relatoría desde el servidor`.

### Tarea 4: núcleo de la extensión (`puente.js`) con pruebas en Node

**Files:**
- Create: `extension/puente.js`, `extension/pruebas/puente.test.js`, `extension/package.json` (`{"private": true, "type": "module"}`, solo para que Node trate los `.js` como módulos; no va en el zip)

**Interfaces:**
- Produces, `puente.js` (sin APIs `chrome.*`; todo se inyecta):
  - `PREFIJO = "https://www.corteconstitucional.gov.co/relatoria/"`, `DESCARGA_MS = 60_000`, `LATIDO_MS = 20_000`, `REINTENTO_MS = 5_000`, `SERVIDOR_POR_DEFECTO = "https://judicabot.web.vespiridion.org"`.
  - `urlPermitida(url: string) -> boolean`: `new URL` con `protocol === "https:"`, `host === "www.corteconstitucional.gov.co"`, sin usuario ni contraseña y `pathname` que empieza por `/relatoria/` (después de la normalización de `URL`, así que `..` no escapa).
  - `urlSocket(servidor: string) -> string`: `https:` → `wss:`, `http:` → `ws:`, ruta `/api/extension`.
  - `armarEntrega(id: string, codigo: number | null, cuerpo: Uint8Array, detalle: string) -> Uint8Array`, con el formato del protocolo.
  - `crearPuente({ crearSocket, descargar, almacen, reloj, version, alCambiarEstado }) -> { conectar(contrasena?: string): Promise<void>, abierto(): boolean }`.
    - `almacen` tiene `leer()`, que devuelve `{servidor, ficha}`, y `guardar(parcial)`.
    - `reloj` tiene `cada(ms, fn)`, `cancelar(id)` y `luego(ms, fn)`.
    - `alCambiarEstado(estado, detalle)` recibe uno de `"conectada" | "conectando" | "sin_contrasena" | "rechazada" | "bloqueada" | "desconectada"`.
  - La contraseña nunca se guarda: solo viaja en el `hola` y se cambia por la ficha.
- `descargar(url, opciones)` es `fetch`, con `{credentials: "omit", cache: "no-store", redirect: "follow", referrerPolicy: "no-referrer", signal: AbortSignal.timeout(DESCARGA_MS)}`. Si `respuesta.url` no pasa `urlPermitida`, se responde `codigo: null, detalle: "redirección fuera de la relatoría"`. Si no, se envía `respuesta.status` y los bytes, sea cual sea el código.

- [ ] **Paso 1: `extension/pruebas/puente.test.js`** (`node:test`, `node:assert/strict`, con socket, reloj y almacén falsos):
  - `urlPermitida acepta la relatoría y rechaza el resto`: acepta `…/relatoria/2022/T-200-22.htm` y rechaza `http://…/relatoria/…`, `https://corteconstitucional.gov.co/relatoria/…`, `https://www.corteconstitucional.gov.co/otra/…`, `https://www.corteconstitucional.gov.co/relatoria/../x`, `https://u:p@www.corteconstitucional.gov.co/relatoria/x` y `https://evil.com/relatoria/x`.
  - `urlSocket convierte el esquema`: `https://judicabot.web.vespiridion.org` → `wss://judicabot.web.vespiridion.org/api/extension`, y `http://127.0.0.1:8000` → `ws://127.0.0.1:8000/api/extension`.
  - `sin ficha ni contraseña no abre socket`: estado `sin_contrasena`.
  - `con contraseña manda hola y guarda solo la ficha`: el primer envío es `{"tipo":"hola","version":…,"contrasena":"x"}`; tras `listo`, `almacen.guardar({ficha})`, estado `conectada` y ningún `guardar` con la contraseña.
  - `con ficha guardada manda hola con ficha`.
  - `cierre 4401 borra la ficha y no reintenta`: estado `rechazada` y ningún `luego`. `cierre 4429` da estado `bloqueada`.
  - `cierre inesperado reintenta con la ficha`: código 1006, luego `luego(REINTENTO_MS, …)`, y al dispararse sale un `hola` con la ficha.
  - `pedido permitido responde con código y bytes`: `descargar` recibe las opciones de arriba y el envío binario se decodifica a cabecera `{"id","codigo":200,"detalle":""}` + bytes.
  - `pedido fuera de la relatoría no descarga`: `descargar` no se llama y la respuesta es `codigo: null` con detalle "URL fuera de la relatoría".
  - `error de red responde codigo null con el mensaje`, `redirección fuera de la relatoría no entrega bytes` y `403 se entrega con su código`.
  - `latido cada 20 s mientras está abierto, y se cancela al cerrar`.
- [ ] **Paso 2:** `node --test extension/pruebas/`. Esperado: FALLA. **Paso 3:** implementar `puente.js`. **Paso 4:** `node --test extension/pruebas/`, que pasa. Commit `feat: núcleo de la extensión de la relatoría`.

### Tarea 5: envoltura MV3, ventana, íconos y prueba manual local

**Files:**
- Create: `extension/manifest.json`, `extension/trabajador.js`, `extension/ventana.html`, `extension/ventana.js`, `extension/iconos/{16,32,48,128}.png`, `extension/LEEME.md`

**Interfaces:**
- Consumes: `crearPuente`, `SERVIDOR_POR_DEFECTO` (tarea 4).
- `manifest.json`:
  - `manifest_version: 3`, `name: "Judicabot: relatoría de la Corte Constitucional"`, `version: "1.0.0"`.
  - `description: "Descarga para judicabot las sentencias de la relatoría de la Corte Constitucional desde este navegador."`
  - `minimum_chrome_version: "120"`, `permissions: ["alarms", "storage"]`, `host_permissions: ["https://www.corteconstitucional.gov.co/relatoria/*"]`.
  - `background: {service_worker: "trabajador.js", type: "module"}`, `action: {default_popup: "ventana.html", default_title: "Judicabot: relatoría", default_icon}`, `icons`.
- `trabajador.js` conecta las APIs de Chrome con `crearPuente` y no tiene lógica propia:
  - `almacen` = `chrome.storage.local`.
  - `crearSocket(url) => new WebSocket(url)` con `binaryType` en `"arraybuffer"`.
  - `reloj` usa `setInterval`/`setTimeout`.
  - `alCambiarEstado` guarda `{estado, detalle}` en `chrome.storage.local` y pone el ícono: texto `""` si `conectada`, `"!"` si no.
  - Llama a `conectar()` en el nivel superior y en `runtime.onStartup`, `runtime.onInstalled` y `alarms.onAlarm` (`"vigilia"`, `periodInMinutes: 0.5`, creada si falta al iniciar el worker), siempre que no haya un socket abierto.
  - `runtime.onMessage` con `{tipo: "configurar", servidor, contrasena}` guarda `servidor`, borra la ficha y llama a `conectar(contrasena)`.
- `ventana.html`/`ventana.js`:
  - Campos "Servidor" (por defecto `SERVIDOR_POR_DEFECTO`) y "Contraseña de judicabot", y el botón "Conectar".
  - Una línea de estado que se actualiza con `chrome.storage.onChanged`. Textos:
    - `conectada`: "Conectada a {servidor}."
    - `conectando`: "Conectando con {servidor}…"
    - `sin_contrasena`: "Escriba la contraseña de judicabot para conectar."
    - `rechazada`: "El servidor rechazó la contraseña."
    - `bloqueada`: "Demasiados intentos. Espere unos minutos."
    - `desconectada`: "Sin conexión con {servidor}; se reintenta sola."
  - Sin scripts en línea (CSP de MV3).
- Íconos: redimensionar `frontend/public/icono-512.png` con Pillow (`uv run --project backend --extra ocr python -c …`).
- `LEEME.md`:
  - Qué hace y qué no envía: solo URLs públicas de la relatoría, nunca datos del expediente (Acuerdo PCSJA24-12243, art. 8.6).
  - Instalación en modo de desarrollador en Chrome (`chrome://extensions`) y Edge (`edge://extensions`): activar "Modo de desarrollador", "Cargar descomprimida", elegir la carpeta, abrir la ventana, escribir la contraseña.
  - Cómo actualizar: reemplazar la carpeta y pulsar "Volver a cargar".
  - Cómo empaquetar la carpeta para repartirla: `cd extension && zip -r /tmp/judicabot-relatoria-1.0.0.zip manifest.json trabajador.js puente.js ventana.html ventana.js iconos`.
  - Que debe quedar el navegador abierto.
  - Que en equipos con políticas que bloquean el modo de desarrollador no se puede instalar así.

- [ ] **Paso 1:** escribir los archivos y `node --test extension/pruebas/`, que sigue pasando.
- [ ] **Paso 2: prueba manual local con Chrome**, forzando el camino de la extensión. urllib respeta `https_proxy`, así que la descarga directa falla al instante:
  - `cd backend && JUDICABOT_PASSWORD=clave-local-1234 https_proxy=http://127.0.0.1:9 uv run tutela2-ui`.
  - Cargar `extension/` descomprimida.
  - En la ventana, servidor `http://127.0.0.1:8000` (origen confiable, admite `ws:`) y la contraseña. Ver "Conectada".
  - Entrar a judicabot y abrir `http://127.0.0.1:8000/api/relatoria?sentencia=T-200/22`. Esperado: `estado: "ok"` y `~/.cache/tutela2/relatoria/T-200-22.htm` creado.
  - Con `SU-319/26`, `no_publicada`. Si la descarga de la extensión falla por el patrón de `host_permissions` con ruta, ampliarlo a `https://www.corteconstitucional.gov.co/*` (la restricción de ruta la sigue aplicando `urlPermitida`) y anotarlo en el LEEME.
  - Quitar la extensión y repetir con otra sentencia no cacheada: `inaccesible`, `extension: "no_conectada"`.
  - En el panel del service worker, comprobar que tras unos minutos inactivo sigue `Conectada` (los latidos lo mantienen vivo) y que reiniciar el servidor la reconecta sola.
  - Repetir la carga y la conexión en Edge.
- [ ] **Paso 3:** commit `feat: extensión MV3 de la relatoría para Chrome y Edge`.

### Tarea 6: CI y documentación

**Files:**
- Modify: `infra/jenkins/Jenkinsfile`, `README.md`

- [ ] **Paso 1: Jenkinsfile.**
  - En `testPaths` agregar `extension\/`: `~/^(backend\/tests\/|backend\/scripts\/|infra\/jenkins\/|extension\/)/`.
  - En el stage Frontend (`node:24-slim`), agregar `node --test ../extension/pruebas/` después de `pnpm size`, desde `frontend/`.
  - `extension/` queda fuera de la imagen porque `.dockerignore` es una lista blanca.
- [ ] **Paso 2: README.**
  - Línea 21 (Requisitos): las páginas de relatoría las descarga el servidor y, si la Corte lo bloquea, la extensión.
  - Línea 36 (variables): sin variables nuevas; mencionar que `JUDICABOT_PASSWORD` también autoriza la extensión.
  - Línea 137 (Verificación de citas): el orden caché → servidor → extensión y los tres motivos nuevos.
  - "Estructura": `extension/` con enlace a `extension/LEEME.md`.
  - Línea 303 (Limitaciones): reemplazar el párrafo de "Mientras el servidor no tenga salida desde una IP colombiana…" por el funcionamiento con la extensión y su condición (navegador abierto en Colombia).
  - Privacidad: la extensión solo recibe URLs públicas de sentencias.
- [ ] **Paso 3:** `cd backend && uv run --extra ocr pytest` y `node --test extension/pruebas/`; los dos pasan. Commit `docs: extensión de la relatoría en el README y pruebas de la extensión en Jenkins`.

## Verificación

**Antes de abrir el PR:**
- `cd backend && uv run --extra ocr pytest`: todo pasa salvo `test_sdk_real_sin_clave_da_error_claro`, que ya falla.
- `node --test extension/pruebas/` pasa.
- `cd frontend && pnpm check:tipos && pnpm typecheck && pnpm test` pasa, para confirmar que el contrato no cambió.
- Prueba manual de la tarea 5 en Chrome y en Edge.

**En producción, tras fusionar en `main` y el despliegue de Jenkins**, con la extensión cargada en un navegador con conexión colombiana:
1. **Antes de que se llene la caché**, con el navegador cerrado: `GET https://judicabot.web.vespiridion.org/api/relatoria?sentencia=T-200/22` y `…?sentencia=SU-319/26` desde otro equipo con sesión iniciada. Esperado: `inaccesible`, `extension: "no_conectada"`, respuesta inmediata. Hoy `T-200-22.htm` no está en `/opt/judicabot/casos/.cache/relatoria` (solo `T-225-93` y `T-377-00`).
2. Con el navegador abierto y la extensión "Conectada", las mismas consultas. `T-200/22` da `ok` y `ssh vps ls -l /opt/judicabot/casos/.cache/relatoria/T-200-22.htm` muestra el archivo. `SU-319/26` da `no_publicada`.
3. `ssh vps 'docker logs judicabot --since 30m 2>&1 | grep -i extensi'` muestra la conexión con su versión.
4. Caso sintético. `caso_sintetico.py` corre en el mismo proceso, en local, y no está en la imagen. Por eso:
   - generar los PDF con `uv run python scripts/caso_sintetico.py generar /tmp/caso_sintetico`;
   - subirlos como caso nuevo en la interfaz de producción, con la clave de Anthropic cargada en la vista IA;
   - correr el flujo.
   Esperado: en "Proceso", las citas de la Corte Constitucional quedan verificadas o rechazadas por el texto, no "para revisar" por relatoría inaccesible.
5. Sin extensión, el backend en una máquina en Colombia sigue descargando directo: lo cubren `test_consultar_relatoria_no_pide_a_la_extension_si_la_descarga_directa_funciona` y la tarea 5 sin `https_proxy`.

## Pendiente del usuario (fuera de este plan)

- Cuenta de la Chrome Web Store y publicación no listada, cuando se decida.
- Confirmar que el PC del usuario final permite el modo de desarrollador. En equipos del juzgado puede estar bloqueado por política.
