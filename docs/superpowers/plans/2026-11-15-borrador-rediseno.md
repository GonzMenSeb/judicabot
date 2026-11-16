# Rediseño de la vista Borrador — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portar el prototipo aprobado `docs/ui/borrador.html` (panel B) a la vista Borrador real.

**Architecture:** Preact + CSS por componente dentro de `frontend/src/vistas/borrador`. La lógica pura vive en `datos.ts`; los componentes `Documento`, `PopoverCita`, `PanelRevision`, `Indice`, `Dock` y `DialogoCorrecciones` reciben datos ya preparados; `index.tsx` guarda el estado y compone. Los tipos compartidos ya están en `tipos.ts` (contrato fijo; no cambiarlos sin necesidad).

**Tech Stack:** Preact 10, TypeScript 5.9, Vitest + Testing Library (jsdom), Playwright, Vite 8, pnpm.

**Spec:** `docs/superpowers/specs/2026-11-15-borrador-rediseno-design.md`. Referencia visual y de comportamiento: `docs/ui/borrador.html` (abrirlo y leer su CSS y JS: es la fuente de las medidas, colores, textos y la colocación del popover).

## Global Constraints

- Sin cambios en `backend/`, `frontend/openapi.json`, `frontend/src/api/`.
- Comentarios: los mínimos imprescindibles (preferiblemente ninguno).
- Clases CSS con prefijo `bor-`; tokens de `estilos/tokens.css`; cada regla con `color` y `background` en la misma declaración debe pasar 4,5:1 (`src/estilos/contraste.test.ts`).
- Puntos de corte: `max-width: 1279px` (índice en popover), `1023px` (panel en cajón), `760px` (móvil: popover como hoja inferior, barra apilada).
- Textos en español de Colombia, trato de «usted», como el prototipo.
- Toda lectura/escritura de `localStorage` dentro de `try/catch`.
- Presupuestos de `pnpm size`: chunk de ruta ≤ 25 KB gz, CSS total ≤ 25 KB gz.
- Ningún elemento con desbordamiento horizontal en 1510, 1180, 900 y 390 px (salvo la caja de tabla ancha con `role="region"`).

## Review Focus

- Alerta con formato desconocido o lista (no dict) de alertas: debe verse completa como fila «Revisar»/«Corregir», nunca perderse.
- Nombre de archivo o lista de Python larga sin espacios: se parte dentro del panel, sin barra horizontal.
- `localStorage` bloqueado o con JSON corrupto: la vista funciona y nada lanza.
- Cita con `cobertura: null` o sin `fuente`: fila y popover muestran «—»/el id sin romperse.
- `/estado` falla: el panel muestra solo citas y el aviso «No se pudieron leer las alertas del caso; se muestran solo las citas.»

---

### Task 1: Datos de revisión (`datos.ts`)

**Files:** Modify `frontend/src/vistas/borrador/datos.ts`, `datos.test.ts`, `mock.ts`.

**Interfaces — Produces** (tipos en `tipos.ts`):
- `dividirMotivos(detalle: string | null): string[]` — parte en `/(?<=\.);\s+/`, descarta vacíos.
- `humanizarAlerta(nodo: string, mensaje: string, bloquea: boolean): AlertaLegible` — `mensaje` ya sin prefijo `ALERTA:`/`BLOQUEA:`; tabla de la spec, sección «Alertas legibles». Origen de archivo `Archivo {doc_id}`; si no, `ETIQUETA_NODO` + `" · II a IV"` (apertura) o `" · V"` (consideraciones). Concordancia de extensión: antecedentes «Los antecedentes son más largos/cortos», sentencia_impugnada «La sentencia impugnada es más larga/corta», impugnacion «La impugnación es…», consideraciones «Las consideraciones son más largas/cortas», «caso concreto» «El caso concreto es más largo/corto»; otro campo: `"{Campo}: {n} palabras"`. Campos de metadatos: juzgado_a_quo «Juzgado de primera instancia», accionante, accionadas, vinculadas, impugnante, impugnante_rol «Calidad de quien impugna»; título `"{Campo}: dos lecturas distintas"`, línea «Se conservó la que se extrajo del expediente.», lecturas «Extraído del expediente · se conservó» y «Leído por el modelo» (listas `['a', 'b']` partidas; si no es lista, un solo valor sin comillas). Fallback: nivel `bloquea ? "mal" : "alerta"`, título = mensaje, sin línea ni detalle.
- `seccionesDeCitas(vista: Vista): Record<string, string>` — id de cita → título en oración de la sección (`casoOracion` del título del `indice` cuyo id es `bloque.seccion`), `""` si no hay.
- `marcasDelIndice(vista: Vista): Record<string, MarcaIndice>` — por cada cita no verificada, suma en su `bloque.seccion` y en el último `encabezado` con `seccion` visto desde el último `titulo`; `mal` si alguna es `rechazada`.
- `construirIndice(vista)` añade `anexo: !/^[IVXL]+\./.test(titulo del indice)` a las entradas de título (`false` en subtítulos).
- `construirRevision(citas: CitaVista[], alertas: AlertasApi | null | undefined, jev: FilaJev[], secciones: Record<string, string>): ItemRevision[]` — reemplaza la anterior. Citas: clave `cita-{id}`, nivel rechazada→mal, revisar→alerta, verificada→ok; origen `"Cita · {sección}"` o `"Cita"`; título fuente con mayúscula inicial (o id); línea verificada `"Verificada · cobertura {porcentaje}"`, si no el primer motivo o `ETIQUETA_ESTADO_CITA`; detalle `{tipo:"cita"}`; `cita` = id. Jev: clave `jev-{fila.id}`, difiere→alerta («Jev · no coincide»), sin_comparar→info («Jev · sin comparar»), coincide→ok («Jev · coincide»); título `fila.etiqueta`; línea `"Borrador: {borrador.principal ?? "Sin dato"} · Jev: {jev.principal ?? "Sin lectura"}"`; detalle `{tipo:"jev"}`. Alertas: clave `alerta-{nodo}-{i}` (i = índice en la lista normalizada), omitir `La cita {id} (` cuando existe esa cita y `Jev lee ` cuando `jev.length > 0`. Orden final: mal, alerta, info, ok; dentro de cada nivel citas, Jev, alertas.
- `claveRevisados(caso: string, sha: string): string` → `judicabot:revisados:{caso}:{sha}`; `leerRevisados(clave: string): Set<string>` (vacío si falta, si no es arreglo de strings o si lanza); `guardarRevisados(clave: string, revisados: ReadonlySet<string>): void` (silencioso si lanza).
- Quitar `conteoCitas` y la `construirRevision` vieja.

- [ ] **Step 1: Tests que fallan en `datos.test.ts`**: un `it` por patrón de `humanizarAlerta` con los mensajes exactos de la spec (incluido `"1a-007 007_007Respuesta…_Anexos.pdf: texto truncado a 120000 caracteres para el LLM."` → nota con `120.000` según `toLocaleString("es-CO")`), fallback BLOQUEA y ALERTA; `construirRevision` con `VISTA_BORRADOR`/`ESTADO_BORRADOR`: orden de niveles, plegado de la alerta de cita rechazada y de `Jev lee`, verificada en `ok`, alertas como lista; `marcasDelIndice` (consideraciones y su subtítulo cuentan; `mal` con la rechazada); `anexo` en «Informe de citas»; `dividirMotivos`; `leerRevisados` con JSON corrupto y con `localStorage.getItem` que lanza, ida y vuelta con `guardarRevisados`.
- [ ] **Step 2:** `pnpm test src/vistas/borrador/datos.test.ts` → FAIL.
- [ ] **Step 3:** Implementar. Ampliar `mock.ts` (`ESTADO_BORRADOR.resumen.alertas`) con los mensajes reales del prototipo (truncado, páginas sin texto legible con `(escrito_tutela)`, extensión de antecedentes, metadatos accionadas, `BLOQUEA: La cita c3 (sentencia T-999 de 2019) fue rechazada: …`) y añadir `url` solo a citas verificadas.
- [ ] **Step 4:** `pnpm test src/vistas/borrador/datos.test.ts` → PASS; `pnpm typecheck` puede fallar solo en archivos de otras tareas.
- [ ] **Step 5: Commit** `feat(borrador): datos de la lista de revisión y alertas legibles`.

### Task 2: Documento y popover de la cita

**Files:** Modify `Documento.tsx`; Create `PopoverCita.tsx`, `documento.css`, `documento.test.tsx`.

**Interfaces — Produces:**
- `Documento(props: { vista: Vista; citas: Map<string, CitaVista>; seleccionada: string | null; plantilla: boolean; alCita: (id: string, ancla: HTMLElement) => void })`. `<article class="hoja bor-hoja [bor-con-plantilla]" aria-label="Borrador del fallo, secciones I a V">` vía `Hoja`; sello con el texto «Borrador, aún no es el fallo»; páginas `.bor-pagina[data-pagina="Página i de n"]`; bloques de plantilla con `bor-tpl`; títulos `id="b-{bloque.id}"` como hoy. Cita: `<span role="button" tabIndex={0} class="bor-cita {estado} [sel]" data-cita={id} aria-pressed aria-haspopup="dialog" aria-controls={sel ? "bor-detalle" : undefined}>` con texto solo para lectores `" ({ETIQUETA_ESTADO_CITA})"`; Enter y Espacio llaman `alCita` (con `preventDefault`).
- `PopoverCita(props: { cita: CitaVista; ancla: HTMLElement; contenedor: HTMLElement; titulo: Ref<HTMLHeadingElement>; onCerrar: () => void })` — `<section id="bor-detalle" class="bor-pop" aria-labelledby>` posicionado en absoluto dentro de `contenedor` (que es `position: relative`), recalculado en `scroll`/`resize`; Escape (con `stopPropagation`) y el botón «Cerrar» llaman `onCerrar`. Título `h3` con `tabIndex={-1}`. Contenido según la spec («Detalle de la cita»). Al montarse, en anchos > 760 px, si el borde inferior queda bajo la barra `.bor-dock` y no se pudo voltear arriba, `window.scrollBy` lo justo.
- `documento.css`: hoja, páginas y su separador, sello, marcas de plantilla, citas (subrayados sólido/discontinuo/ondulado + glifo ✓ ! ✕ en `::after`), destello `.bor-cita.destello`, tablas, popover y su versión móvil.

- [ ] **Step 1:** `documento.test.tsx` con: la cita es `role=button` con `aria-pressed`, Enter y Espacio llaman `alCita`; `plantilla` pone `bor-con-plantilla`; la etiqueta de página; el popover tiene región con nombre de la fuente en mayúscula inicial, enfoca su título al montarse si el padre lo pide, Escape y «Cerrar» llaman `onCerrar`, motivos como `li`, enlace «Abrir en la relatoría» con `target="_blank"` y `rel="noopener noreferrer"` solo si `estado === "verificada"` y hay `url`, cobertura `null` muestra «—».
- [ ] **Step 2:** `pnpm test src/vistas/borrador/documento.test.tsx` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(borrador): citas que se parten con la línea y detalle en popover`.

### Task 3: Panel «Antes de decidir»

**Files:** Create `PanelRevision.tsx`, `panel.css`, `panel.test.tsx`.

**Interfaces — Consumes:** `ItemRevision`, `DetalleRevision` de `tipos.ts`. **Produces:**
`PanelRevision(props: { items: ItemRevision[]; revisados: ReadonlySet<string>; alRevisar: (clave: string) => void; abierta: string | null; alAbrir: (clave: string | null) => void; seleccionada: string | null; alVerEnTexto: (citaId: string, desde: HTMLElement) => void; umbralJev?: number; avisoEstado: string | null; abiertoMovil: boolean; onCerrarMovil: () => void })`.
`<aside id="bor-panel" class="bor-panel [abierto]" aria-labelledby>` con `h2` «Antes de decidir», botón «Cerrar la revisión» (visible bajo 1024 px), resumen «Lleva X de N revisados. Nada de esto bloquea la decisión.» (N = ítems no `ok`), barra segmentada con `role="progressbar"`, grupos con `h3` «Corregir antes de firmar», «Revisar», «Para tener en cuenta» y «X de N» pendientes, grupo «Comprobado» plegado por defecto (botón con `aria-expanded`). Fila: botón de revisado `aria-pressed` con nombre «Revisado: {título}»; fila expandible `button[aria-expanded]` si tiene detalle; detalle por tipo según la spec, con «Ver en el texto» y, si la cita es verificada con `url`, «Abrir en la relatoría». La fila de la cita `seleccionada` lleva `bor-fila-activa` y, si `innerWidth >= 1024`, `scrollIntoView({ block: "nearest" })` al cambiar. Sin ítems no `ok`: «Nada pendiente en lo que el sistema pudo comprobar.». `avisoEstado` se muestra bajo la cabecera.

- [ ] **Step 1:** `panel.test.tsx`: títulos de grupo y conteos, `alRevisar` con la clave, `aria-pressed`, expandir muestra detalle y «Ver en el texto» llama `alVerEnTexto`, «Comprobado» plegado y desplegable, enlace a la relatoría solo en la verificada con `url`, vacío y `avisoEstado`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementar. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(borrador): panel de revisión por urgencia`.

### Task 4: Índice, barra inferior y diálogo

**Files:** Create `Indice.tsx`, `Dock.tsx`, `indice.css`, `dock.css`, `indice.test.tsx`; Modify `DialogoCorrecciones.tsx` (solo marcado de las opciones) y mover sus estilos a `dialogo.css`.

**Interfaces — Produces:**
- `Indice(props: { entradas: EntradaIndice[]; marcas: Record<string, MarcaIndice>; activa: string | null; alSeccion: (id: string) => void; redaccion: Redaccion[]; abierto: boolean })` — `<nav id="bor-indice" class="bor-indice [abierto]" aria-label="Contenido del borrador">`, rótulo «Contenido», botones con `aria-current="location"` en la activa, marcador con texto solo para lectores «N cita(s) por revisar», separador antes del primer anexo, sección «Quién redactó» (`h2`) con «Secciones II a IV»/«Sección V», el modelo y «Se pidió X; respondió Y.» cuando difieren.
- `Dock(props: { pendientes: number; revisados: number; total: number; enCurso: boolean; hrefDecision: string; puedeCorregir: boolean; motivoNoCorregir: string | null; alCorregir: () => void })` — `.bor-dock` fija; textos: en curso «Hay una redacción en curso» / «Podrá decidir cuando termine.»; total 0 «El borrador está listo para su decisión» / «Todas las comprobaciones salieron bien.»; todos revisados «Revisó los N puntos» («Revisó el único punto») / «Puede pasar a la decisión.»; si no «Quedan N puntos por revisar» («Queda 1 punto…») / «Lleva X de N. No bloquean la decisión.»; si `motivoNoCorregir` y no en curso, ese texto reemplaza la segunda línea. Botones `Boton` «Pedir correcciones» (`disabled` si `!puedeCorregir`) y `Boton variante="sello" grande href` «Pasar a la decisión» (`disabled` si `enCurso`).
- Diálogo: título «Pedir correcciones al borrador» y nombres de opción «Rehacer la apertura»/«Rehacer las consideraciones» sin cambios; cada opción como tarjeta con rótulo «Secciones II a IV»/«Sección V».

- [ ] **Step 1:** `indice.test.tsx` para `Indice` y `Dock` (cada texto de arriba, marcador y su texto oculto, `aria-current`, botones deshabilitados).
- [ ] **Step 2:** → FAIL. **Step 3:** Implementar. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(borrador): índice con marcas, barra de decisión y diálogo en tarjetas`.

### Task 5: Composición, lienzo ancho y pruebas de extremo a extremo

**Files:** Modify `index.tsx`, `estilos.css`, `borrador.test.tsx`, `rutas/Shell.tsx`, `rutas/Shell.test.tsx`, `estilos/base.css`, `ui/LEEME.md`, `e2e/abierto/02-flujo.spec.ts`; Delete `Riel.tsx`, `TarjetaJev.tsx`.

**Interfaces — Consumes:** todo lo anterior.

- `Shell.tsx`: `<main class={cx("lienzo", (visible ?? destino).vista === "borrador" && "lienzo-ancho")}>`; `base.css`: `.lienzo-ancho { max-width: 1480px; }`; test en `Shell.test.tsx`; actualizar la línea del lienzo en `ui/LEEME.md`.
- `index.tsx`: estado `seleccionada`, `plantilla` (true), `revisados` (de `leerRevisados(claveRevisados(caso, vista.sha256))`, guardado en cada cambio), `abierta`, `indiceAbierto`, `panelAbierto`. Barra pegajosa `.bor-doc-barra` con botón «Contenido» (`aria-controls="bor-indice"`, solo bajo 1280 px), sección actual (de `useEspia`, «Padre · Subtítulo» cuando la activa es subtítulo), interruptor `role="switch"`/checkbox «Marcar texto de plantilla», botón «Revisión N» (`aria-controls="bor-panel"`, solo bajo 1024 px). Velo `.bor-velo` cuando el cajón está abierto. Escape cierra en orden popover → índice → cajón. Clic fuera cierra el popover y el índice. «Ver en el texto» desplaza la cita al centro, la marca con `destello` y cierra el cajón. Estados de carga, error, 404, caso no encontrado y aviso de redacción en curso como hoy.
- `estilos.css`: cabecera, `.bor-mesa` y sus columnas por punto de corte, barra del documento, interruptor, velo, variable `--bor-dock` (4.75rem; 7.2rem bajo 760 px).
- `borrador.test.tsx`: reescribir sobre el nuevo marcado manteniendo la cobertura actual (estados, quién redactó, Jev, correcciones, enlace a la decisión, relatoría) más: revisado persiste en `localStorage` y se reinicia con otro `sha256`; clic en la cita del texto marca la fila; Escape devuelve el foco.
- `02-flujo.spec.ts`: región «Contenido del borrador» en vez de «Secciones», panel «Antes de decidir» en vez de «Qué conviene revisar», interruptor «Marcar texto de plantilla» (encendido por defecto: apagar y volver a encender), `#bor-detalle` igual.

- [ ] **Step 1:** Ajustar las pruebas (unidad y e2e) al nuevo marcado → FAIL.
- [ ] **Step 2:** Componer e implementar.
- [ ] **Step 3:** `pnpm typecheck && pnpm test && pnpm build && pnpm size && pnpm e2e` → todo verde.
- [ ] **Step 4:** Comprobación de desbordamiento con Playwright sobre la app con `VITE_MOCK=1` (o el servidor e2e) a 1510, 1180, 900 y 390 px: 0 elementos con `scrollWidth > clientWidth` fuera de la caja de tabla ancha.
- [ ] **Step 5: Commit** `feat(borrador): nueva composición de la vista y lienzo ancho`.
