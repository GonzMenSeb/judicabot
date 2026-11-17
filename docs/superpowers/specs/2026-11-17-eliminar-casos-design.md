# Eliminar casos

Fecha: 2026-11-17. Rama: `feat/eliminar-casos`. Prototipo aprobado: `docs/ui/eliminar-casos/` (`Main.dc.html` es la lista con el flujo completo, `Estados.dc.html` los estados de la fila, el diálogo y los avisos, `Movil.dc.html` el teléfono). Son plantillas de lienzo de diseño: se porta el aspecto y el comportamiento, no la sintaxis.

## Por qué

«Mi trabajo» y la página del proceso acumulan casos de prueba, duplicados y casos terminados hace tiempo. Hoy no hay forma de quitarlos desde la interfaz: solo borrando la carpeta en el servidor.

## Objetivos

- Eliminar un caso desde su fila de la lista (`ListaCasos`, en Inicio y en `#/segunda`), en fichas y en compacta.
- Confirmación explícita antes de eliminar y **Deshacer** justo después.
- Que eliminar por error no pierda el trabajo: el caso va a una papelera oculta del servidor durante 30 días.

## No objetivos

- Una página de papelera, o restaurar después de que se cierre el aviso de Deshacer. Durante 30 días el administrador puede devolver la carpeta a mano (ver «Papelera»).
- Eliminar varios casos a la vez.
- Eliminar desde las páginas de un caso (Documentos, Proceso, Borrador, Decisión, Fallo).
- Eliminar documentos sueltos o salidas de un caso.

## Backend

### `DELETE /api/casos/{caso_id}` → 200 `CasoEliminado {id, papelera}`

- Resuelve con `server._dir_caso` (404 «Caso no encontrado.» si no existe, empieza por `.` o se sale de `CASOS_DIR`).
- Dentro de `server._LOCK`: si el caso tiene un job `corriendo`, responde 409 «Hay una ejecución en curso para este caso. Espere a que termine para eliminarlo.». Si no, mueve la carpeta con un solo `rename` a `CASOS_DIR/.papelera/<id>@<sello>`, donde `<sello>` es la hora UTC `AAAAMMDDTHHMMSSffffffZ`. `.papelera` se crea si falta. Como el destino está dentro de `CASOS_DIR`, es el mismo sistema de archivos y el cambio es atómico.
- `papelera` es el nombre de la entrada (`<id>@<sello>`), que es lo que necesita Deshacer.
- Tras eliminar, purga la papelera (ver abajo). Un error al purgar se registra y no cambia la respuesta.
- `.papelera` empieza por `.`, así que `resumen_caso.nombres_de_casos` no la lista y `_dir_caso` no la sirve.

### `POST /api/papelera/{entrada}/restaurar` → 200 `CasoRestaurado {id}`

- `entrada` debe ser un nombre directo de `CASOS_DIR/.papelera` (sin `/`, sin `..`, sin empezar por `.`) con la forma `<id>@<sello>`; si no, o si no existe, 404 «No se encontró el caso en la papelera.».
- El `id` es lo que queda antes del último `@`. Si ya existe `CASOS_DIR/<id>`, 409 «Ya hay otro caso con ese identificador.». Si no, vuelve con un solo `rename`, dentro de `server._LOCK`.

### Identificadores no se reutilizan mientras estén en la papelera

`server._crear_dir_caso` da por ocupado un `<id>` si existe `CASOS_DIR/<id>` **o** alguna entrada `CASOS_DIR/.papelera/<id>@*` (cuenta aunque el sello no se pueda interpretar, por ejemplo una entrada dejada a mano). Así Deshacer no choca con un caso nuevo del mismo nombre y un caso nuevo no hereda el estado que el navegador guardó para el eliminado (`judicabot:decision:<id>` en `sessionStorage`, `judicabot:revisados:<id>:<sha>` en `localStorage`).

### Carreras con otras operaciones

- `POST /api/casos/{id}/run`, `PUT /api/casos/{id}/revision` y las ediciones del borrador (`PUT`/`DELETE`/`POST` de `/api/casos/{id}/ediciones/…`) vuelven a comprobar, dentro de `_LOCK`, que la carpeta del caso existe; si no, 404 «Caso no encontrado.». Así no arranca un job sobre un caso que se acaba de eliminar.
- Si el caso se elimina mientras termina de subirse (`POST /api/casos`), la subida responde 404 «Caso no encontrado.», sea cual sea la escritura que encuentre la carpeta ausente.
- Ninguna escritura tardía puede recrear la carpeta de un caso eliminado: el calentamiento de resúmenes (`resumen_caso.calentar`), la caché (`resumen_caso._escribir`) y los demás que escriben dentro de un caso no hacen `mkdir(parents=True)` de la carpeta del caso. Si alguno lo hace, se corrige.

### Papelera

- Purga: se borran las entradas cuyo `<sello>` tiene más de 30 días (`DIAS_PAPELERA = 30`), al arrancar (en el hilo de calentamiento) y después de cada eliminación. Las entradas con un nombre que no se puede interpretar no se tocan.
- Restaurar a mano: mover `CASOS_DIR/.papelera/<id>@<sello>` a `CASOS_DIR/<id>`. Va en el README, junto a `CASOS_DIR`.

## Frontend

### Contrato

`contrato.ts` gana `CasoEliminado {id, papelera}` y `CasoRestaurado {id}`, comprobados en `contrato.verificacion.ts` contra `schema.d.ts` regenerado (`pnpm gen:tipos`).

### Botón en la fila

- `Ficha` y `FichaCompacta` muestran un botón de icono (papelera, en `iconos.tsx`), variante `fantasma`, con `aria-label="Eliminar: <nombre>"` y `title="Eliminar caso"`. Va en la columna de la acción, después del botón de acción principal, sin competir con él. Objetivo táctil de al menos 32 × 32 px. Sin desbordamiento horizontal a 390 px.
- No se dibuja si el caso tiene `job_activo` (no se puede eliminar mientras se redacta), ni si `ListaCasos` no recibe `alEliminado`. Con `job_activo` queda un hueco invisible del mismo tamaño (`aria-hidden`), para que los botones de acción sigan alineados entre filas.
- Color en reposo `--tenue`; al pasar el puntero, fondo `--mal-fondo` y color `--mal`. En fichas mide 36 px y en compacta 32 px; en el teléfono la fila de acción queda «[acción] [papelera]  hace 2 h».
- La columna de acción de la ficha se ensancha lo justo para que «Revisar documentos» y la papelera quepan en una línea.
- Los nombres accesibles de los enlaces de caso (`${accion}: ${nombre}`) no cambian.

### Confirmación

`ListaCasos` tiene un solo `Dialogo` de confirmación (un `<dialog>` modal es correcto aquí: interrumpe y, mientras está abierto, no se suelta ninguna carpeta):

- Título «¿Eliminar este caso?».
- Cuerpo: un recuadro (borde `--linea`, fondo `#f7f9fa`) con el nombre del caso en negrita y, si lo hay, «Radicado <radicado>» debajo; luego «Se quitará de la lista con sus documentos, el borrador y el fallo. Podrá deshacerlo justo después.».
- Mientras responde el servidor, los dos botones quedan inactivos y el de eliminar dice «Eliminando…» con su indicador (`cargando`).
- Acciones: «Cancelar» (con el foco al abrir) y «Eliminar caso» (`peligro`, `cargando` mientras responde el servidor).

### Después de eliminar

- 200: se cierra el diálogo, `ListaCasos` llama `alEliminado(id)` y el padre quita el caso de su estado sin recargar. El foco va al encabezado de la lista («Mi trabajo» o «Casos», con `tabIndex={-1}`), porque el botón que abrió el diálogo ya no existe. Aviso «Se eliminó «<nombre>».» con la acción **Deshacer**, durante 10 s.
- Deshacer: `POST /api/papelera/<entrada>/restaurar`; al responder, `ListaCasos` sube `versionCasos` (signal de `estado`) y la vista que muestra casos recarga `GET /api/casos`. Es la que se esté viendo, aunque no sea la que eliminó: los avisos siguen abiertos al navegar. El foco, que `Toasts` dejó en `#contenido` al quitar el aviso, vuelve al encabezado de la lista si sigue en pantalla. Aviso «Se restauró «<nombre>».». Si falla, aviso de error con el mensaje del servidor.
- 409 al eliminar: se cierra el diálogo, aviso de alerta con el mensaje del servidor y sube `versionCasos` para recargar (el caso puede haber empezado a correr). El foco va al encabezado de la lista, porque la recarga cambia la papelera por el hueco.
- 404 al eliminar: el caso ya no estaba; `alEliminado(id)` y aviso «El caso ya no existía.».
- Error de red u otro: el diálogo sigue abierto y muestra dentro, sobre los botones, un recuadro de error (`role="alert"`) «No se pudo eliminar el caso» con el mensaje, y el botón disponible para reintentar.
- Si falla Deshacer: aviso de error «No se pudo restaurar el caso. <mensaje>» (los avisos de error no se cierran solos).

### Avisos con acción

`mostrarToast(texto, {tipo, ms, accion})`, con `accion?: {texto: string; alHacer: () => void}`. `Toasts` dibuja la acción como un botón antes de ×; al pulsarla cierra el aviso y llama `alHacer`. Si el botón tenía el foco, antes lo pasa a `#contenido`, para que no caiga en `<body>`. Mientras el foco o el puntero están dentro de un aviso con acción, no se cierra por tiempo (WCAG 2.2.1); al salir vuelve a contar desde cero. El `LEEME.md` de `ui/` lo documenta.

### Padres

Inicio (`vistas/inicio`) y la página del proceso (`vistas/casos/index.tsx`) pasan `alEliminado` (filtran su `casos`) y recargan `GET /api/casos` cuando cambia `versionCasos`. En Inicio, si se elimina el último caso, la lista desaparece como hoy cuando no hay casos.

Una carga de `GET /api/casos` que salió antes de eliminar un caso (por ejemplo, la de Deshacer) puede responder después: la respuesta descarta los casos que el padre quitó mientras ella estaba en curso (`vistas/casos/quitados.ts`); las cargas que empiezan después mandan.

### Mocks

`vistas/casos/mock.ts` responde `DELETE /api/casos/<id>` con `{id, papelera: "<id>@20261117T150000000000Z"}` y `POST /api/papelera/<entrada>/restaurar` con `{id}`.

## Pruebas

- Backend (`backend/tests/test_server.py` o un `test_eliminar.py` nuevo): eliminar mueve la carpeta y la quita de `GET /api/casos`; 404 con id inexistente, con `.papelera` y con `..`; 409 con un job corriendo; restaurar la devuelve; 409 si el id está ocupado; 404 con entradas inválidas; `_crear_dir_caso` no reutiliza un id en la papelera, aunque su sello no se entienda; eliminar durante la subida da 404, también tras copiar el último archivo; la purga borra solo lo vencido y respeta lo que no entiende; `run` y `revision` dan 404 si la carpeta desapareció; OpenAPI exportado al día (`test_openapi_export.py`).
- Frontend (vitest): eliminar desde fichas y desde compacta; Cancelar no llama al servidor; el foco al encabezado; Deshacer llama a restaurar, sube `versionCasos`, recarga la lista visible aunque sea de otra vista y deja el foco en el encabezado (o en `#contenido`); 409 (con el foco en el encabezado) y 404; error dentro del diálogo; sin botón con `job_activo` o sin `alEliminado`; avisos con acción (cierra, llama, no vence con foco).
- E2E (`frontend/e2e/abierto/08-eliminar.spec.ts`): crear un caso, eliminarlo, comprobar que sale de la lista, Deshacer y comprobar que vuelve.

## Riesgos

- **Eliminar por error.** Lo mitigan la confirmación, Deshacer y los 30 días de papelera.
- **Disco.** Los expedientes pesan; la papelera los conserva 30 días.
- **Presupuesto de CSS** (`pnpm size`): el botón y la acción del aviso reutilizan `.btn`; los estilos nuevos son mínimos.
