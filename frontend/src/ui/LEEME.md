# Primitivas de UI, estado y mocks

Importar siempre desde `../../ui` (barrel `src/ui/index.ts`), `../../estado` y `../../api`. Estilos globales ya cargados por `main.tsx` (`estilos/{tokens,base,ui}.css`); cada vista importa solo el CSS propio.

## Reglas del shell (obligatorias)

1. **Un solo `<main>`.** El shell (`rutas/Shell.tsx`) renderiza `<main id="contenido" class="lienzo" tabIndex={-1}>` (max 1180 px, padding inferior de 7rem para barras fijas). Las vistas renderizan un `<div data-vista="nombre">` (o `<section>`) como raíz y **nunca** `<main>`.
2. **Sin anclas hash para saltos internos.** `href="#seccion"` lo lee el router como ruta y vuelve a Inicio. Para saltar dentro de la página usar `<button>` + `elemento.scrollIntoView()`.
3. **Foco y título.** Al navegar, el shell mueve el foco a `<main>`, sube al inicio y pone `document.title` por vista ("Borrador · caso-7 · Judicabot"). Para un título propio: `useTitulo("Borrador · Quintero c. EPS")` (de `../../estado`); el shell agrega " · Judicabot".
4. **Transición sin animación.** Mientras carga el chunk de la vista siguiente se sigue mostrando la anterior (`<main aria-busy="true">`); no hay fundidos ni deslizamientos.
5. Enlaces internos con `href="#/segunda/..."`, o `navegar("#/...")` de `../../rutas`. Codificar el caso con `encodeURIComponent`.
6. Comentarios al mínimo; texto de UI en español.

## Primitivas (`../../ui`)

`children` es opcional en todas salvo donde se indique. Todas aceptan `class?: string` salvo `Topbar`, `Migas` y `Pasos`.

| Componente | Props |
|---|---|
| `Boton` | `variante?: "primario"\|"secundario"\|"peligro"\|"fantasma"\|"sello"` (def. secundario; `sello` = burdeos, para decisión), `grande?`, `cargando?` (deshabilita, `aria-busy`, spinner), `disabled?`, `type?: "button"\|"submit"\|"reset"` (def. `button`), `href?` (renderiza `<a class="btn">`; inactivo pierde el href), `download?: string\|boolean`, más atributos HTML (`onClick`, `aria-*`, `title`...) |
| `Chip` | `tono?: "neutro"\|"ok"\|"alerta"\|"mal"\|"info"\|"sello"`, `title?` |
| `Aviso` | `tipo?: "info"\|"alerta"\|"error"\|"ok"` (error usa `role="alert"`, el resto `status`), `titulo?`, `acciones?: ComponentChildren` (botones a la derecha) |
| `Dialogo` | `abierto: boolean`, `titulo: string`, `onCerrar: () => void`, `acciones?: ComponentChildren` (pie con botones), `children`. Controlado: el padre pone `abierto=false` en `onCerrar`. Usa `<dialog>.showModal()`, atrapa Tab/Shift+Tab, Escape y clic en el fondo llaman `onCerrar`, enfoca `[autofocus]`/`[data-enfoque]` o el primer control, devuelve el foco al cerrar al elemento enfocado al abrir (si el disparador se deshabilita antes de abrir, el navegador ya le quitó el foco: no lo deshabilite hasta que el diálogo abra). Mientras haya alguno abierto pone la clase `dialogo-abierto` en `<html>` (`overflow: hidden`) y la quita al cerrar o desmontar. Los hijos solo se montan abierto |
| `Hoja` | `etiqueta?: string` (aria-label). `<article class="hoja">`: papel claro, serif Bookman, párrafos justificados. Solo para documentos |
| `VisorPagina` | `numero?: number`, `total?: number`. Página de fallo con proporción 21.1:34.1, ancho máx 40rem y `content-visibility: auto`. Muestra "n / total" |
| `Cargando` | `texto?: string` (def. "Cargando…"), `role="status"` |
| `Vacio` | `titulo: string`, `accion?: ComponentChildren`, `children` (detalle) |
| `CasoNoEncontrado` | sin props de contenido. `Vacio` con «No se encontró el caso» y el enlace «Volver a los casos» a `#/segunda`. Las vistas de un caso lo muestran cuando la API responde 404 «Caso no encontrado» (`esCasoNoEncontrado(error)` de `../../api`), en vez de «Reintentar» |
| `Migas` | `items: {texto: string; href?: string}[]`. El último es la página actual (sin enlace, `aria-current="page"`) |
| `Pasos` | `caso: string`, `actual: EtapaPaso`, `limite?: EtapaPaso`, `detalles?: Partial<Record<EtapaPaso, string>>` |
| `Topbar` | `seccion?: "inicio"\|"formato"\|"ia"\|null`, `clave: boolean\|null`, `modelo?: string\|null`. Lo monta el shell; las vistas no lo usan |
| `Toasts` | sin props; lo monta el shell |
| `cx(...partes)` | une clases ignorando falsos |

### Pasos

`EtapaPaso = "documentos"|"proceso"|"borrador"|"decision"|"fallo"` (mismos ids que `Etapa` de rutas). Cada paso enlaza a `#/segunda/<caso>/<etapa>`.
- `actual`: etapa que se está viendo.
- `limite`: etapa más avanzada alcanzada por el caso (def. `actual`). Pasos antes de `actual` o de `limite` salen "hecho"; el paso `limite` si no es el actual sale "disponible" (enlace, sin check); los posteriores salen "bloqueado" (texto sin enlace).
- `decision` lleva siempre la variante burdeos cuando es la actual.
- La vista decide el mapeo desde `CasoResumen.etapa` (0-4); la primitiva no lo deriva.
- `PASOS` exporta ids, títulos y detalle por defecto.

## Estado (`../../estado`)

| Export | Uso |
|---|---|
| `estadoServidor` (signal `EstadoServidor\|null`), `cargarEstadoServidor(forzar?)`, `errorEstadoServidor` | `GET /api/estado-servidor`; el shell lo carga una vez. Tras guardar una clave: `await cargarEstadoServidor(true)` |
| `mostrarToast(texto, {tipo?, ms?}) => id` | `tipo` como `Aviso` (def. info); desaparece a los 3500 ms; `ms: 0` o `tipo: "error"` persiste hasta `cerrarToast(id)` |
| `toasts`, `cerrarToast(id)` | lista reactiva |
| `useTitulo(texto)` | título del documento de la vista |
| `casoActual`, `jobActual`, `preferencias` | signals existentes |
| `fechaRelativa(iso, ahora?)` | "ahora mismo", "hace 5 min", "hace 3 h", "ayer", "hace 4 días", luego "15 de sept" (con año si es otro año); `""` si inválida |
| `plural(n, singular, plural?)` → "3 casos"; `pluralizar(n, singular, plural?)` → solo la palabra | auto: vocal +s, consonante +es, "-ión" → "-iones", "z" → "ces" |
| `porcentaje(fraccion, decimales = 0)` | fracción 0-1 → "97 %" (con espacio duro); `null`/NaN → "—" |
| `nombreModelo(id)` | "claude-sonnet-5-5" → "Sonnet 5.5" |

## Mocks (`VITE_MOCK=1`)

Cada vista puede tener `src/vistas/<vista>/mock.ts` con `export const mocks: MockRuta[]` (importar el tipo con `import type { MockRuta } from "../../api/mock"`; nunca valores, para evitar ciclos). `api/mock.ts` los agrega solo con `import.meta.glob`.

```ts
{ metodo: "GET", ruta: "/api/casos", respuesta: [...] }                       // string: coincide exacto, ignora ?consulta
{ metodo: "POST", ruta: /^\/api\/casos\/([^/]+)\/run$/, respuesta: (p) => ({ job_id: "j1" }) }
```
- `ruta` string se compara con la ruta sin `?consulta`; `RegExp` se prueba contra la ruta completa (con consulta).
- `respuesta` puede ser un valor (se clona en cada llamada) o `(peticion: {metodo, ruta, cuerpo}) => valor | Promise`. Para simular un error lanzar `new ErrorApi(estado, detalle, mensaje)`.
- Gana el primer mock que coincide: los de las vistas van antes que el de `/api/estado-servidor` por defecto, así que una vista puede sobrescribirlo.
- Las peticiones sin mock caen al `fetch` real (proxy a `127.0.0.1:8000`).
