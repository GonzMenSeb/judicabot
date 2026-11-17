# Edición in situ del borrador: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que el despacho corrija la prosa de las secciones I a V directamente en el borrador, en texto plano y con las citas e imágenes como fichas fijas, y que esas correcciones lleguen al caso concreto y al fallo sin perderse ni pisar a la IA en silencio.

**Architecture:** las ediciones no tocan el grafo. Una capa por caso (`ediciones.json`) guarda el texto humano de cada pieza junto con el texto de la IA del que partió; `fusion.py` hace un diff3 por párrafos para fusionar ediciones y correcciones de la IA (rebase), y `ediciones.py` reúne las funciones puras (validación, fichas, rebase, consolidación). `rutas_ediciones.py` expone cuatro endpoints bajo `server._LOCK`. Al decidir, `api.decidir` consolida la capa en el estado con `Command(update=…, resume=…)`. La vista marca cada bloque editable con `fuente: {pieza, parrafo}` y el frontend edita por párrafo.

**Tech Stack:** Python 3.12, FastAPI, LangGraph (`Command`), `difflib` de la stdlib, pytest con `FakeClient`; Preact + `@preact/signals`, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-edicion-in-situ-design.md`. Contrato de API: `docs/superpowers/specs/2026-11-03-judicabot-ui-contrato.md` (B7).

**Context.** Hasta ahora el borrador era de solo lectura: ante un error, las salidas eran pedir correcciones a la IA o retocar el Word al final. Pero el caso concreto se redacta después de la decisión leyendo `apertura` y `consideraciones` del estado del grafo, así que un error que no se corrige en el borrador se propaga al fallo.

## Global Constraints

- Solo se edita el **texto normal** (prosa de la IA) de las piezas del spec §1. Plantilla, variables (citas, marcas de imagen, metadatos), encabezado, ASUNTO, `cita_bloque`, caso concreto y resolutiva no se editan.
- No se admiten citas nuevas ni cambios de cita: las fichas del texto nuevo deben ser el mismo multiconjunto (`id`, sentencia) que las de la IA. La conversión canónica/editable vive solo en el backend.
- Una cita no puede cambiar de sentencia en silencio, y una edición humana no se pierde ni la pisa una corrección de la IA sin preguntar.
- Editar no cambia la clasificación del caso, no toca `decisiones`, `errores`, `intentos`, `bitacora` ni `alertas`, y no dispara llamadas a la IA.
- Toda comparación entre versiones se hace entre formas normalizadas (`"\n\n".join(parrafos(texto))`), no entre cadenas crudas.
- `GET …/ediciones` nunca responde 4xx por estado del caso: con un job corriendo o fuera de `esperando_decision` responde 200 `{editable:false, …}` (el fixture `vigilante` del e2e falla con 4xx inesperados).
- `fusion.py` usa solo `difflib`: no se usa `merge3` de PyPI porque es GPL-2.0+ y el repo es MIT.
- Frontend: Preact y CSS por componente con prefijo `bor-`, tokens de `estilos/tokens.css`, textos en español de Colombia con trato de «usted», presupuestos de `pnpm size` (chunk de ruta ≤ 25 KB gz). Comentarios al mínimo.
- Baseline conocido: en `frontend` falla una prueba de vitest ajena (`src/estado/dataset.test.ts`, «si no está vigente lo descarga…»: Node 22 en lugar de 24); en `backend`, 17 fallas de `test_ingest` por `pypdfium2` ausente. Ninguna es de este trabajo.

## Ejecución

El trabajo se corrió en cuatro oleadas sobre la rama `in-situ-modifications`, sin commits intermedios. Cada oleada tuvo un dueño por archivo para evitar choques, y la siguiente partió de la salida de la anterior.

### Oleada 1: núcleo de fusión y ediciones, y `fuente` en la vista

**Files:** Create `backend/tutela2/fusion.py`, `backend/tutela2/ediciones.py`, `backend/tests/test_fusion.py`, `backend/tests/test_ediciones.py`; Modify `backend/tutela2/vista.py`, `backend/tutela2/render.py`, `backend/tests/test_vista.py`, `backend/tests/test_render.py`.

**Interfaces — Produces:**
- `fusion.fusionar(base, mio, nuevo)`, `hay_conflicto`, `resultado`, `compactar`, `escalar` (spec §5).
- `ediciones`: `parrafos`, `normalizar`, `catalogo`, `es_pieza`, `etiqueta`, `seccion_de`, `es_titulo`, `obtener`, `fijar`, `mapa_citas`, `a_editable`, `a_canonico`, `fichas`, `validar`, `avisos`, `leer`, `guardar`, `registrar`, `hay_conflictos`, `ErrorEdicion`, `aplicar`, `sincronizar`, `consolidar`, `editar`, `restaurar`, `resolver`, `respuesta` (spec §6 y §7). Ninguna abre el grafo.
- `vista.Fuente{pieza, parrafo}`; `Bloque.fuente: Fuente | None = None`; `Registro.como(fuente=…)`; `render.prosa`/`_prosa` reciben `pieza` y emiten `fuente` por párrafo (spec §11).

- [x] **Step 1:** `test_fusion.py`: sin cambios, solo mío, solo nuevo, iguales, choque, inserciones y borrados, párrafos adyacentes (se fusionan), inserciones en el mismo punto (conflicto).
- [x] **Step 2:** `test_ediciones.py`: ida y vuelta de fichas; cada rechazo de `validar`; `parrafos()` coincide con los bloques `fuente` de la vista renderizada; casos de `sincronizar` (ids de cita reasignados, fusión limpia con fichas descuadradas que pasa a conflicto, contestaciones reordenadas, saltos de línea simples que no disparan rebase, restaurar después de consolidar, volver a editar después de consolidar); `mio` rechazado por trozo cuando las fichas no cuadran.
- [x] **Step 3:** Implementar `fusion.py`, `ediciones.py` y la `fuente` de la vista; ajustar `test_vista.py` y `test_render.py`.
- [x] **Step 4:** `cd backend && uv run pytest -q -p no:cacheprovider` verde salvo las 17 fallas de `test_ingest`.

### Oleada 2: API, consolidación y declaración

**Files:** Create `backend/tutela2/rutas_ediciones.py`, `backend/tests/test_ediciones_api.py`, `backend/tests/test_rutas_ediciones.py`; Modify `backend/tutela2/api.py`, `backend/tutela2/esquemas.py`, `backend/tutela2/models.py`, `backend/tutela2/server.py`, `backend/tutela2/render.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts`, `frontend/src/api/contrato.ts`, `frontend/src/api/contrato.verificacion.ts`.

**Interfaces — Produces:**
- `GET /api/casos/{id}/ediciones`, `PUT` y `DELETE /api/casos/{id}/ediciones/{pieza}`, `POST /api/casos/{id}/ediciones/{pieza}/resolver`, todos con `EdicionesRespuesta` (spec §8); `rutas_ediciones` se registra en el bucle de módulos de `server.py`.
- `api.ediciones`, `api.editar_pieza`, `api.restaurar_pieza`, `api.resolver_pieza`; `api._leer_estado(regenerar_previo=True)` sincroniza, guarda la capa si cambió y renderiza el previo con `ediciones.aplicar`.
- `Estado.ediciones_humanas: list[str]`, leída con `.get(..., [])`.
- `render._mapa_secciones(gen, hay_compulsa, editadas)`: «IA + edición humana» y «Corregido por el despacho en el borrador.» (spec §10).
- Rechazo de conflictos pendientes en `POST /run` con `cmd: "decidir"` (409 síncrono bajo `_LOCK`) y al principio de `api.decidir`.

- [x] **Step 1:** `test_ediciones_api.py` con `arrancar()` de `tests/test_graph.py` y el `FakeClient`: editar deja el caso en `esperando_decision`; `decidir` lleva el texto editado al caso concreto y al fallo; el conteo de la bitácora prueba que no hubo llamadas de más a la IA; `rehacer_consideraciones` con ediciones hace el rebase; un conflicto bloquea `decidir` hasta resolverlo.
- [x] **Step 2:** `test_rutas_ediciones.py`: GET con un job corriendo responde 200 `editable:false` y no sincroniza; 409 (job, estado, `original` desfasado); 422; declaración con «IA + edición humana».
- [x] **Step 3:** Implementar rutas, `api.py`, esquemas y consolidación; `pnpm gen:tipos` y tipos escritos a mano en `contrato.ts`.
- [x] **Step 4:** `uv run pytest -q -p no:cacheprovider` verde salvo `test_ingest`; `pnpm check:tipos` verde.

### Oleada 3: frontend, e2e y documentación

**Files:** Create `frontend/src/vistas/borrador/EditorParrafo.tsx`, `DialogoConflictos.tsx` y sus pruebas y estilos; Modify `index.tsx`, `Documento.tsx`, `Dock.tsx`, `DialogoCorrecciones.tsx`, `datos.ts`, `mock.ts`, `frontend/e2e/…`; Docs: `README.md`, `docs/superpowers/specs/2026-11-02-tutela2-primera-a-segunda-design.md`, `docs/superpowers/specs/2026-11-03-judicabot-ui-contrato.md`, este plan.

**Interfaces — Consumes:** los tipos de `contrato.ts` (`Fuente`, `PiezaEdicion`, `TrozoOk`, `TrozoConflicto`, `ConflictoEdicion`, `EdicionesRespuesta`, `EdicionCuerpo`, `ResolverCuerpo`) y los cuatro endpoints. La pieza va en la ruta con `encodeURIComponent`.

- [x] **Step 1:** `index.tsx` carga también `GET …/ediciones` (si falla, el borrador queda en solo lectura), agrega el interruptor «Editar texto» (apagado por defecto) y recarga vista y ediciones tras guardar sin pasar por `fase="cargando"`.
- [x] **Step 2:** `Documento.tsx` muestra «Editar párrafo» en los bloques con `fuente`, y edita como uno los bloques consecutivos con la misma fuente. `EditorParrafo.tsx`: `<textarea>`, Guardar (Ctrl+Enter), Cancelar (Esc con `preventDefault`), «Restaurar el texto de la IA», 422 en línea, 409 con aviso y recarga, marca «Editado» y avisos. `original` es `piezas[pieza].parrafos[parrafo]` tal como llegó, no el texto del bloque renderizado.
- [x] **Step 3:** `DialogoConflictos.tsx` sobre `Dialogo`: «Su versión» y «Versión de la corrección» lado a lado con radio; «Su versión» deshabilitada cuando `mio_permitido` es falso; una pieza huérfana solo ofrece «Descartar mi edición» (DELETE). Aviso sobre el documento que lo abre; `Dock.tsx` desactiva «Pasar a la decisión» y «Pedir correcciones» con conflictos y dice por qué; nota en `DialogoCorrecciones.tsx`.
- [x] **Step 4:** `datos.ts`: las claves de «revisado» pasan a depender del contenido (`alerta-${nodo}-${mensaje}`, `cita-${id}-${estado}-${fuente}`), la clave de almacenamiento a `judicabot:revisados:${caso}`, se podan las claves que ya no existen y se borran las viejas `judicabot:revisados:${caso}:${sha}` de ese caso, para que guardar una edición no borre lo revisado.
- [x] **Step 5:** mocks de los endpoints en `mock.ts`; prueba e2e (`pnpm e2e`, `TUTELA2_PROVEEDOR=fake`): editar un párrafo, recargar y ver que persiste, pasar a la decisión y decidir, ver el texto editado en la vista del fallo. `03-confirmar` no cambia porque el modo edición está apagado por defecto.
- [x] **Step 6:** `cd frontend && pnpm typecheck && pnpm test && pnpm check:tipos && pnpm build && pnpm size` verde (salvo la prueba de `dataset.test.ts` ya conocida).
- [x] **Step 7:** documentación: se reemplaza «El despacho edita en Word» del spec de 2026-11-02, se agregan los endpoints y `Bloque.fuente` al contrato B7, y el README describe el modo de edición.

### Oleada 4: revisión adversarial

Revisión del conjunto desde varios ángulos. Foco de cada revisor:

- **Citas:** que ninguna ruta (edición, rebase, resolución de conflictos, restauración) deje una cita apuntando a otra sentencia ni acepte jurisprudencia nueva fuera de ficha.
- **Pérdida de datos:** que una edición humana no se pierda en silencio ni la pise una corrección de la IA; restaurar y volver a editar después de consolidar; contestaciones reordenadas por una apertura rehecha.
- **Concurrencia y estado:** GET con job corriendo, PUT sin `esperando_decision`, `original` desfasado, escritura atómica de `ediciones.json`, caso inutilizable tras una decisión inválida.
- **Frontend:** foco y teclado del editor (Esc con `preventDefault`, Ctrl+Enter), roles y nombres accesibles, 409 y 422 mostrados sin romper la vista, pérdida de scroll al guardar, claves de «revisado».
- **Contrato:** que `openapi.json`, `schema.d.ts` y `contrato.ts` coincidan con el servidor.

Cualquier decisión que el spec no resuelve se deja anotada para el usuario en lugar de inventarla.

## Desviaciones respecto del plan original

1. **Campo `consolidado` en la capa.** El plan guardaba solo `ia` y `texto` por pieza y consideraba una pieza sincronizada si u ∈ {ia, texto}. Pero tras consolidar, el estado guarda el texto humano: si luego el usuario restauraba (`texto := ia`), el rebase deshacía la restauración, y si volvía a editar el mismo párrafo aparecía un conflicto falso contra su propia edición anterior. `consolidado` registra el último u ya conocido y «sincronizado» pasa a ser u ∈ {consolidado, texto, ia}. Además, `restaurar` solo borra la entrada si `consolidado == ia`; si no, la deja hasta la próxima consolidación, porque borrarla haría reaparecer el texto humano ya consolidado en u.
2. **Consolidar solo con una decisión válida.** El plan consolidaba con toda acción de `api.decidir`. LangGraph lo impide: una decisión inválida hace que `nodo_decision` vuelva a interrumpir sin cerrar el paso, y el `update` queda como escritura pendiente de la tarea nula. Un segundo `Command(update=…)` sobre ese checkpoint lanza `InvalidUpdateError: At key 'apertura': Can receive only one value per step`, y luego también falla `get_state`: el caso queda inutilizable. Por eso `api.decidir` valida la decisión (`Decision.model_validate(...).errores()`, igual que `nodo_decision`) y solo con una decisión válida manda `Command(update=…, resume=…)`; con una inválida manda solo `Command(resume=…)` y las ediciones siguen en la capa hasta la próxima decisión válida. Con esa guarda no hace falta el respaldo `update_state(as_node=…)`. La verificación se hizo con el grafo real y el `FakeClient` (spike del 2026-11-17, LangGraph 1.2.19).

3. **Render antes de guardar.** El plan guardaba la capa, registraba el log y luego regeneraba el previo. Si el render fallaba, la edición quedaba persistida con el previo sin ella, y `decidir` calculaba el hash sobre ese previo desfasado. `api._guardar_capa` invierte el orden: renderiza con la capa candidata y solo entonces guarda y registra (también en el GET que sincroniza).
4. **Caracteres de control.** `validar` rechaza con 422 los caracteres que el Word no admite (regla 7 del spec). Antes, un `\x1b` pegado en el texto pasaba la validación, se guardaba en la capa y rompía `render_previo` y luego `ensamblar`.

5. **Párrafos quitados, 409, texto sin guardar y clave de citas** (revisión de la oleada 4). `PiezaEdicion` gana `modificada` porque una pieza a la que solo se le quitaron párrafos no tenía `editados` y no se podía restaurar desde la UI. El editor ofrece «Guardar sobre la versión actual» tras un 409 con el párrafo cambiado. El texto sin guardar se protege con `useGuardiaSalida`. La clave de «revisado» de una cita incluye su sentencia. La vista de decisión muestra el motivo del 409 de `POST /run`. Detalle en el spec, §6 y §12.

6. **Bloques anclados por título** (decisión del usuario tras la oleada 4). El plan solo anclaba las contestaciones; los bloques de consideraciones iban por índice. Una apertura rehecha que reordenaba los bloques hacía un rebase limpio y el párrafo humano caía en silencio bajo otro encabezado, en el previo, en el prompt del caso concreto y en el fallo. Ahora las piezas de bloque se anclan al título de la IA (spec §4 y §7): si el bloque se mueve, la edición lo sigue; si su título desaparece, la edición queda huérfana y solo se puede descartar, y el diálogo muestra el texto del usuario para copiarlo. Un título humano ya consolidado que la IA conserva no deja huérfano al bloque. Las entradas de bloque sin ancla siguen el índice. Una revisión adversarial de este cambio encontró dos defectos, ya corregidos: un texto editado tras consolidar un título humano se anclaba a ese título y quedaba huérfano en la siguiente consolidación (ahora hereda el ancla de la entrada `.titulo`), y `sincronizar` podía necesitar una segunda pasada (ahora repite hasta que la capa no cambia). Además, el ancla exacta gana a los títulos humanos al buscar el bloque.

## Mediciones

- `render_previo` cuesta unos 155 ms de mediana por guardado en el caso `fake` (cada PUT, DELETE y POST de resolver lo regenera, igual que un GET que cambia la capa). El spec lo regenera en cada guardado, bajo `server._LOCK`.

## Review Focus

- Una decisión inválida con ediciones pendientes no escribe nada en el grafo y deja el caso en `esperando_decision`, utilizable.
- `decidir` y `rehacer_*` con ediciones: el texto humano llega al prompt del caso concreto o es la SALIDA ANTERIOR que recibe la IA, con una sola llamada nueva y sin llamadas de más en la bitácora.
- `POST /run` con `decidir` y conflictos pendientes responde 409 sin crear un job.
- Un conflicto de fichas (`mio_permitido: false`) nunca se puede resolver con «Su versión», ni por la UI ni por la API (422).
- `parrafos()` es la única partición en párrafos: el índice de `fuente.parrafo` de la vista coincide siempre con `piezas[pieza].parrafos`.
