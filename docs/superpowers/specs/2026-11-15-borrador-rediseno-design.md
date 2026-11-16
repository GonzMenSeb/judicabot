# Rediseño de la vista Borrador

Fecha: 2026-11-15. Rama: encima de `feat/enlace-citas-relatoria` (PR #5). Prototipo aprobado: `docs/ui/borrador.html` (panel B, interruptor de plantilla encendido).

## Por qué

El usuario no estaba orgulloso de la vista actual y el riel derecho se desbordaba en horizontal: `.bor-riel` es un grid sin plantilla de columnas y `.bor-lista-rev li` usa `auto 1fr`, así que nombres de archivo y listas sin cortes (`007_007Respuesta…pdf`, `['COMPAÑIA…`) ensanchan la pista y `overflow:auto` añade la barra horizontal. El borrador es la única compuerta humana antes de decidir: leer el texto, ver qué conviene revisar y pasar a la decisión o pedir correcciones.

## Objetivos

- Portar el prototipo a `frontend/src/vistas/borrador` sin cambiar el backend ni el contrato.
- Cero desbordamiento horizontal en 1510, 1180, 900 y 390 px, también con alertas reales largas.
- Conservar todo lo que la vista hace hoy: estados de carga y error, aviso de redacción en curso, Jev, quién redactó, citas, alertas, correcciones, enlace a la relatoría del PR #5.

## No objetivos

- Backend, contrato OpenAPI o `.docx`.
- Las demás vistas, salvo el ancho del lienzo en `Shell.tsx`.
- Persistir lo revisado en el servidor.

## Anti-objetivos

- Que una alerta desconocida desaparezca: todo mensaje que no se reconozca se muestra tal cual.
- Que se enlace a la relatoría una cita que no esté verificada.

## Enfoques considerados

- **A, panel por tipo** (Jev, citas, alertas en tarjetas): descartado por el usuario; con alertas reales queda una pared de tarjetas grises con texto crudo.
- **B, lista de revisión por urgencia** (elegido): filas compactas agrupadas en «Corregir antes de firmar», «Revisar», «Para tener en cuenta» y «Comprobado» (plegado); cada fila se expande con su detalle y se marca como revisada.

## Diseño (lo decidido)

### Disposición

- Lienzo de 1480 px solo en esta vista: `Shell.tsx` añade la clase `lienzo-ancho` al `<main>` cuando la vista mostrada es `borrador`; `base.css` define `.lienzo-ancho { max-width: 1480px; }`.
- Cabecera igual que hoy (migas, título, radicado y juzgado con iconos, pasos). Desaparece la tarjeta de Jev de arriba.
- `.bor-mesa`: tres columnas `13.5rem | minmax(0,1fr) | 25rem` desde 1280 px; `minmax(0,1fr) | 22.5rem` entre 1024 y 1279 (el índice pasa a un popover que abre el botón «Contenido»); una columna bajo 1024 (el panel pasa a cajón lateral que abre el botón «Revisión N»).
- Barra fija inferior (`.bor-dock`) a todo el ancho con el estado a la izquierda y «Pedir correcciones» y «Pasar a la decisión» a la derecha.

### Índice (columna izquierda)

- Título «Contenido»; entradas de `construirIndice`; separador antes de los anexos (entradas cuyo título no empieza por numeral romano: «Informe de citas», «Alertas por nodo»).
- Marcador por entrada con el número de citas no verificadas de esa sección o subsección; rojo si alguna es rechazada, ámbar si no.
- Debajo, «Quién redactó» con `redaccionPorNodo`.
- Espía de desplazamiento: la entrada visible lleva `aria-current="location"`.

### Documento (columna central)

- Barra pegajosa sobre la hoja: sección actual («V. Consideraciones · subtítulo»), interruptor «Marcar texto de plantilla» **encendido por defecto**, botones «Contenido» y «Revisión N» según el ancho.
- Con el interruptor encendido, los bloques de plantilla llevan tinte y una regla en el margen; el texto del modelo queda sin marca.
- Separador entre páginas con la etiqueta «Página i de n» dentro del propio bloque (no en negativo: `content-visibility:auto` recorta lo que sobresale).
- Sello «Borrador · aún no es el fallo» arriba a la derecha.
- Cada cita del texto es `<span role="button" tabindex="0" aria-pressed aria-haspopup="dialog">` y no `<button>`, para que se parta con la línea y no deje el «(» huérfano. Enter y Espacio la activan. Glifo final ✓, ! o ✕ según el estado (no solo color).

### Detalle de la cita (popover)

- Se abre junto a la cita al pulsarla; conserva `id="bor-detalle"`, rol `region` con nombre igual a la fuente, título enfocable que recibe el foco, botón «Cerrar», Escape cierra y devuelve el foco a la cita.
- Contenido: chip de estado, fuente (con mayúscula inicial), fragmento citado, medidor de cobertura, motivos en lista (el `detalle` se parte en `.;␠`), y para las verificadas con `url` un botón a todo el ancho «Abrir en la relatoría» (pestaña nueva, `rel="noopener noreferrer"`, aviso «(se abre en una pestaña nueva)» para lectores de pantalla). La fila «Relatoría» del PR #5 desaparece con el `<dl>`; sus pruebas se ajustan al enlace.
- Se coloca debajo de la cita o encima si no cabe; si aun así no cabe sobre la barra inferior, la página se desplaza lo justo. Bajo 760 px es una hoja fija sobre la barra inferior.

### Panel «Antes de decidir» (columna derecha)

- Cabecera: «Lleva X de N revisados. Nada de esto bloquea la decisión.» y barra segmentada, un segmento por punto, color por nivel, relleno cuando está revisado.
- Grupos por nivel: «Corregir antes de firmar» (citas rechazadas y alertas BLOQUEA), «Revisar» (citas con alerta, Jev que no coincide, alertas ALERTA), «Para tener en cuenta» (alertas de archivo, Jev sin comparar), «Comprobado» plegado (citas verificadas y Jev que coincide).
- Fila: círculo para marcar como revisado (botón `aria-pressed`), etiqueta pequeña de origen, título, una línea de detalle con elipsis; si tiene detalle, la fila es un botón que lo expande (`aria-expanded`). Detalle de cita: fragmento, cobertura, motivos, «Ver en el texto» y, si es verificada con `url`, «Abrir en la relatoría». Detalle de Jev: «El borrador dice» frente a «Jev lee en el expediente» y la ayuda. Detalle de archivo: nombre en monoespaciado que se parte y la nota.
- Duplicados plegados: la alerta `La cita {id} (…) fue rechazada` se omite si existe la cita `{id}`; las alertas `Jev lee …` se omiten si hay filas de Jev.
- Pulsar una cita del texto marca su fila (`activa`) y, desde 1024 px, la desplaza a la vista dentro del panel.
- Lo revisado se guarda en `localStorage` con la clave `judicabot:revisados:{caso}:{sha256 de la vista}` (se reinicia al regenerar el borrador), siempre dentro de `try/catch`.
- Si `/estado` falla, el panel muestra solo las citas y el aviso actual.

### Alertas legibles

Los formatos vienen de `backend/tutela2` (`lint.py:670`, `graph.py:282`, `ingest.py:947` y `:1172`):

| Mensaje (sin prefijo) | Nivel | Título | Detalle |
|---|---|---|---|
| `{doc_id} {nombre}: texto truncado a {n} caracteres para el LLM.` | info | El modelo leyó solo una parte de este documento | archivo + «Se le entregaron los primeros {n} caracteres; lo que sigue no se tuvo en cuenta al redactar.» |
| `{doc_id} {nombre} ({rol}): páginas sin texto legible: {lista}.` | info | Página(s) {lista} sin texto legible | archivo + «El modelo no pudo leer esa(s) página(s).» |
| `{campo}: tiene {n} palabras, por encima del máximo / por debajo del mínimo esperado ({a} a {b}).` | alerta | «Los antecedentes son más largos de lo esperado» (concordancia por campo) | línea: «{n} palabras; se esperaban entre {a} y {b}.» |
| `En metadatos, campo {campo}, la ingesta extrajo {a} y el modelo leyó {b}; se conserva el de la ingesta, verifique cuál es correcto.` | alerta | «{Campo}: dos lecturas distintas» | las dos lecturas (listas de Python partidas en viñetas) |
| cualquier otro | BLOQUEA → mal; si no → alerta | el mensaje completo | — |

La etiqueta de origen es `Archivo {doc_id}` para las de archivo y la del nodo con sus secciones para las demás («Apertura · II a IV», «Consideraciones · V»).

### Corrección

El diálogo conserva lógica, textos de error y pruebas; las dos opciones pasan a tarjetas lado a lado con la sección que rehacen.

## Lo que queda al constructor

Nombres internos de componentes y clases CSS (prefijo `bor-`), reparto de la hoja de estilo por componente, cómo se mide el espacio del popover. Los colores nuevos de texto sobre fondo deben pasar `estilos/contraste.test.ts` (4,5:1 cuando `color` y `background` van en la misma regla).

## Verificación

`pnpm typecheck`, `pnpm test`, `pnpm build`, `pnpm size`, `pnpm e2e` (actualizando `e2e/abierto/02-flujo.spec.ts` al nuevo marcado) y una comprobación con Playwright de desbordamiento horizontal a 1510, 1180, 900 y 390 px con los datos simulados.
