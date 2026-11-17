# «Mi trabajo»: lista de casos compartida y filtrable

Fecha: 2026-11-17. Rama del primer PR: `feat/mi-trabajo-lista`. Prototipo aprobado: `docs/ui/mi-trabajo/` (`Lista.dc.html` es el componente; `Main.dc.html` es Inicio, `Segunda.dc.html` es la página del proceso y `Facetas.dc.html` es el mapa de cada filtro a su dato). Son plantillas de lienzo de diseño (`{{huecos}}`, `sc-for`, `sc-if`): se porta el comportamiento y el aspecto, no la sintaxis.

## Por qué

Inicio muestra «Para continuar», con solo los 2 casos que más urgen (`frontend/src/vistas/inicio/index.tsx`), y la página de segunda instancia tiene otra lista, aparte, con solo búsqueda de texto y agrupación fija (`frontend/src/vistas/casos/index.tsx`). Con decenas de casos, el juez no puede responder «qué me toca hoy», «qué trabajé esta semana» ni «qué casos de tal juzgado tengo». Dos listas distintas tampoco crecen bien cuando lleguen otros procesos.

## Objetivos

- Un solo componente, `ListaCasos`, montado en Inicio («Mi trabajo») y en la página del proceso («Casos»), con la misma lista y los mismos filtros.
- Filtrar, ordenar y agrupar por lo que existe hoy en el contrato, sin tocar el backend en el primer PR.
- Que una vista filtrada sea un enlace: Atrás desde un caso la conserva y se puede guardar como marcador.
- Que la estructura admita los filtros propios de cada proceso y los plazos sin rehacer el componente.

## No objetivos

- Backend, contrato OpenAPI y `.docx` en el PR1.
- Filtros propios de segunda instancia y plazos en el PR1 (PR2 y PR3).
- Otros procesos (primera instancia, desacato, penal): el prototipo los dibuja para fijar la forma de la faceta, pero hoy no hay casos de ellos.
- Un registro de quién trabajó qué.

## Anti-objetivos

- Que un filtro oculte casos sin que se note: toda faceta activa se ve como pastilla con su ✕ y en la barra de resultados.
- Que «Terminados» desaparezca sin rastro: el tramo rayado «Terminados · ocultos» los trae de vuelta con un toque.
- Que un `<dialog>` modal bloquee soltar archivos en la página de casos.

## Diseño

### El componente compartido

`ListaCasos` recibe `{casos, proceso?, aviso?, vacio?}`.

- **Inicio** lo monta bajo las tarjetas de proceso, solo si hay al menos un caso. Título h2 «Mi trabajo». Sin agrupar por defecto. Sin `proceso`, se comporta como si «2ª instancia» estuviera elegida.
- **Página del proceso** (`#/segunda`) lo monta con `proceso="segunda"`. Título h2 «Casos». Agrupa por estado por defecto. Conserva su aviso y su estado vacío.
- Páginas de 10 con «Mostrar más».
- Con un solo proceso con casos no se muestran las pestañas de proceso; aparecen cuando un segundo proceso tenga casos.
- Nombres accesibles estables: el buscador sigue siendo «Buscar casos», los enlaces de caso siguen llamándose `${accion}: ${nombre}` y el texto de búsqueda sin resultados conserva el prefijo «Ningún caso coincide».

### Franja de estados

La franja reemplaza a una pastilla de estado: sus tramos miden según su número de casos y cada uno filtra con un toque. Los siete estados de la API se agrupan en seis:

| Estado de la API | Grupo en la interfaz | Acción de la ficha |
|---|---|---|
| `esperando_decision` | Por decidir | Decidir |
| `incompleto` | Faltan documentos | Completar |
| `error` | Con error | Ver el error |
| `sin_iniciar`, `revision` | Por preparar | Revisar documentos |
| `corriendo` | En redacción | Ver avance |
| `terminado` | Terminados | (ninguna) |

- Por defecto están activos todos menos Terminados.
- `elegirEstado`: desde el valor por defecto, el primer toque muestra solo ese estado; los siguientes alternan; Terminados alterna aparte; una selección vacía vuelve al valor por defecto.
- Orden de prioridad («Lo que me toca primero»): desde el PR3, primero los vencidos y los que vencen hoy; luego Por decidir, Faltan documentos y Con error, Por preparar, En redacción y Terminados; dentro de cada estado, el vencimiento más cercano y después lo trabajado más reciente.
- La franja cuenta ignorando el propio filtro de estado.

### Carriles de filtros

Dos carriles, uno al lado del otro y nunca uno bajo el otro; en pantallas angostas se apilan.

- **Generales** (todos los procesos): Trabajado, Juzgado, Entidad accionada y Con alertas. Los plazos no son pastilla: son baldosas junto a la franja de estados (ver «Plazos»).
- **Propios de <proceso>**: carril teñido, siempre visible cuando el proceso está fijo, con su icono y el número de filtros aplicados. Es el único lugar que cambia entre procesos (`PROPIAS` en `facetas.ts`); cada fila de la lista muestra además los datos que más pesan en ese proceso (`FILA`). En el PR1 este carril no se dibuja; desde el PR2 se dibuja el de segunda instancia, a la derecha de Generales y algo más ancho (pasa debajo a 960 px o menos), también en Inicio mientras todos los casos sean de segunda. Sin carril propio a la vista (Inicio con varios procesos, pestaña «Todos») las fichas tampoco muestran datos propios. El número de filtros aplicados se lee en voz alta como «N filtros propios aplicados».

Cada filtro es una pastilla plegada que muestra su valor y su ✕; al tocarla abre un popover con el control que le corresponde:

| Tipo de faceta | Control |
|---|---|
| `varias` | lista de casillas con conteos |
| `buscable` | lista de casillas con buscador (listas largas) |
| `pasos` | pasos en orden procesal |
| `interruptor` | un toque, sin popover |
| fecha | presets con conteo, histograma de 30 días y Desde/Hasta |

Un filtro sin datos para los casos visibles se oculta.

### Filtros y su dato

| Filtro | Control | Dato | Estado |
|---|---|---|---|
| Estado | franja | `estado` (7 valores en 6 grupos) | existe hoy |
| Trabajado | fecha: Cualquier fecha, Hoy, Ayer, Últimos 7 días, Este mes, Mes pasado, Desde/Hasta | `actualizado` (última modificación de los archivos del caso), en hora de Colombia, no en UTC | existe hoy |
| Juzgado | casillas con buscador | `juzgado_a_quo`; en 2ª instancia se llama «Juzgado de 1ª inst.» | existe hoy |
| Entidad accionada | casillas con buscador | `accionadas[]`, normalizadas sin tildes ni mayúsculas | existe hoy |
| Con alertas | interruptor | `n_alertas` | existe hoy |
| Buscar | texto | radicado, partes, juzgado y accionadas; `coincideBusqueda` de `agrupar.ts`, sin tildes y con radicado compacto | existe hoy |
| Ordenar | menú | prioridad (lo que me toca primero), vence primero (PR3), reciente, antiguo, radicado | existe hoy |
| Agrupar | menú | sin agrupar, por estado, por plazo (PR3) | existe hoy |
| Densidad | Fichas / Compacta | preferencia local | existe hoy |
| Propios de segunda | casillas, buscador e interruptor | Decisión 1ª inst., Impugnó, Sentido 2ª inst., Derecho, Por revisar, Con pruebas nuevas | PR2 (dato nuevo) |
| Plazos | baldosas | `vence`, `dias_restantes` | PR3 (dato nuevo) |
| Ordenar «Vence primero» y agrupar «Por plazo» | menús | `vence` | PR3 |

Los propios de segunda leen `CasoResumen.segunda` (`DatosSegunda`); con `segunda` en `null` ningún filtro falla, solo no coincide (o cae en «Sin dato»/«Sin decidir»):

| Pastilla (clave) | Opciones | Dato | Chip de la fila |
|---|---|---|---|
| Decisión 1ª inst. (`aquo`) | Amparó, Negó el amparo, Declaró improcedente, Carencia actual de objeto, Otra; «Sin dato» si algún caso no la trae | `decision_a_quo` | «1ª inst.: Negó el amparo» |
| Impugnó (`impugna`) | Accionante, Accionada, Vinculada, Otro, Varios | `impugnante` | «Impugna: accionada» |
| Sentido 2ª inst. (`sentido`) | Confirma, Revoca, Modifica; «Sin decidir» si algún caso no tiene fallo | `resultado` (y `sustitutiva` en el chip) | «Fallo: revoca y ampara» o «Fallo: revoca y declara hecho superado», solo con fallo |
| Derecho (`derecho`, con buscador) | los de los casos, sin repetir variantes; basta con uno | `derechos` | — |
| Por revisar (`revisar`) | Citas por revisar, Jev discrepa | `n_citas_revisar > 0`, `jev_discrepa` | «2 citas por revisar», «Jev discrepa» |
| Con pruebas nuevas (`pruebas`, interruptor) | — | `pruebas_nuevas === true` | «Pruebas nuevas en 2ª» |

«Trabajado» es la última actividad sobre los archivos, incluida la del sistema; el título del popover lo dice. Su histograma raya los fines de semana y los festivos; los festivos los publica el servidor en `/api/estado-servidor` (`festivos`, del año anterior al siguiente, de `festivos.py`), así que el frontend no calcula festivos. Cada barra se lee como «lunes, 16 de noviembre, festivo: 1 caso» o «sábado, 14 de noviembre, fin de semana: 0 casos».

### Plazos (PR3)

El término para fallar de cada caso (`termino = {inicio, dias, unidad}`) se confirma o edita en **Documentos** («Término para fallar», junto a «Fecha de reparto»); mientras no se guarde, se propone desde la fecha de reparto: 20 días hábiles. El servidor calcula en cada respuesta `vence` y `dias_restantes` (en la unidad del término: 0 vence hoy, negativo vencido; `null` para los terminados y sin fecha). La lista solo los lee (`facetas.PLAZOS`, `plazoDe`, `textoPlazo`, `tituloPlazo`):

| Cubeta (`pl=`) | `dias_restantes` | Etiqueta |
|---|---|---|
| `vencido` | < 0 | Vencidos |
| `pronto` | 0 o 1 | Vencen hoy o en 1 día |
| `semana` | 2 a 5 | Vencen en 2 a 5 días |
| `despues` | 6 o más | Vencen en 6 días o más |
| `sin` | `null` o terminado | Sin término calculado |

- **Baldosas**: las tres primeras cubetas, junto a la franja (debajo a 960 px o menos), con su conteo; un toque alterna el filtro (`aria-pressed`). Solo se dibujan si algún caso del alcance (página o pestaña) tiene vencimiento. Las etiquetas dicen «días» sin unidad porque cada caso cuenta en la suya.
- **Chip de la fila** (fichas y compacta): «Venció hace 2 días hábiles», «Vence hoy», «Vence mañana» (solo si vence al día siguiente; un viernes con vencimiento el lunes dice «Falta 1 día hábil»), «Faltan 3 días hábiles»; en días calendario, «Faltan 14 días calendario» (el mismo texto que Documentos, de `textoDiasRestantes`). Tono de su baldosa: rojo si venció o vence hoy, ámbar si faltan de 1 a 5 días, neutro después. El título dice la regla: «Recibido el 21 de octubre de 2026; vence el 20 de noviembre de 2026 (20 días hábiles)».
- **Vence primero**: por `vence` ascendente; sin vencimiento al final y, entre ellos, los terminados detrás. **Por plazo** agrupa en el orden de la tabla.

### Conteos facetados

Cada opción cuenta los casos que quedarían con los demás filtros aplicados, ignorando el filtro al que pertenece:

| Conteo | Ignora |
|---|---|
| Opciones de una pastilla | la clave de esa pastilla |
| Franja de estados | estado |
| Pestañas | proceso y todas las claves propias (`<proceso>.<clave>`) |
| Baldosas de plazo (PR3) | plazo |

Las opciones en 0 se atenúan pero no desaparecen, para que la lista no salte. Los conteos de opciones se calculan solo mientras su popover está abierto. El popover de una pastilla muestra «Listo · N casos».

### Estado en la URL

- Los filtros viven en la consulta del hash, por ejemplo `#/segunda?e=decidir,error&f=semana&pl=vencido,pronto&s.juzgado=…&o=vence&g=plazo`. Claves cortas: `q`, `p`, `e`, `f`/`d`/`h`, `pl` (plazo), `s.<clave>`, `o`, `g`; las propias llevan el proceso delante (`s.segunda.aquo=niega,sin_dato`). Una clave o un valor desconocido se descarta (`validar`), y también una clave propia de un proceso cuyo carril no se ve (la misma regla que al cambiar de pestaña) y, en un interruptor, cualquier valor que no sea el que enciende (`s.alertas=sin`).
- Se escribe con `history.replaceState`: filtrar no añade entradas al historial, no dispara `hashchange`, no remonta ni desplaza la página. Atrás desde un caso restaura la vista; el enlace sirve de marcador.
- `coincidir` interpreta solo el camino, así que `#/segunda?…` no cae en Inicio. El panel de Configuración, al cerrarse, vuelve a la ruta de fondo con su consulta.
- Solo la densidad se guarda en `localStorage`, siempre dentro de `try/catch`.

### Estado vacío y sugerencia

- Si ningún caso coincide, la lista dice «Ningún caso coincide…» y propone quitar el filtro que más casos devolvería: «Quitar «X» muestra N casos».
- **Limpiar** vuelve a los valores por defecto y ofrece **Deshacer** hasta el siguiente cambio.
- Si todos los casos están terminados: «No hay casos abiertos», con el botón «Ver los terminados (N)».
- Chips resaltados en cada fila repiten los filtros activos (`eco`), desde el PR2; la vista compacta muestra solo el primero de los resaltados, para seguir en una línea.

### Terminados, ocultos por defecto

La lista muestra los casos abiertos. El tramo rayado «Terminados · ocultos» de la franja los trae con un toque. Cambia lo que los usuarios ven al abrir la página; la franja rayada y el estado vacío «Ver los terminados» lo compensan.

### Accesibilidad

- El popover (`ui/Desplegable.tsx`) nunca es un `<dialog>`: `vistas/casos/soltar.ts` trata `dialog[open]` como modal y bloquearía soltar archivos con un popover abierto.
- El disparador es un `<button>` con `aria-expanded` y `aria-controls`. Al abrir, el foco entra en el popover; Escape y un clic en la superposición lo cierran y el foco vuelve al disparador.
- Hasta 960 px el popover es una hoja inferior (con `bloquearFondo`, y `matchMedia` protegido porque jsdom no lo tiene).
- Ningún `href="#seccion"` (ver `frontend/src/ui/LEEME.md`): los enlaces de caso usan `hrefCaso`.
- Cada regla con `color` y `background` pasa 4,5:1 (`contraste.test.ts`). Las tonalidades de la franja y las pastillas no dependen solo del color: llevan texto y conteo.
- Sin desbordamiento horizontal a 390 px.

## Entrega en tres PR

Se fusionan en orden; cada uno es utilizable solo. PR2 y PR3 regeneran `frontend/openapi.json` y `src/api/schema.d.ts`, así que no corren en paralelo.

1. **PR1, `feat/mi-trabajo-lista`**: frontend y URL, con los datos que existen hoy. Router con consulta, `Desplegable`, motor de filtros, `ListaCasos`, Inicio y página del proceso, prototipo y documentación. Sin carril propio ni baldosas de plazo.
2. **PR2, `feat/mi-trabajo-propios-segunda`**: filtros propios de segunda en el dato. `DatosSegunda` (`decision_a_quo`, `impugnante`, `resultado`, `sustitutiva`, `derechos`, `pruebas_nuevas`, `n_citas_revisar`, `jev_discrepa`) y `proceso` en `CasoResumen`; nuevo `resumen_segunda.py`; carril «Propios de 2ª instancia» y chips de fila.
3. **PR3, `feat/mi-trabajo-plazos`**: se empieza a guardar el término (`.datos_caso.json` con `proceso`, `creado`, `termino`), se calcula en vivo con `festivos.py` (nunca en la caché), se edita en **Documentos** junto a «Fecha de reparto» y se añaden las baldosas de Plazos, el orden «Vence primero», la agrupación «Por plazo» y el chip de término.

Los casos creados antes quedan con `proceso="segunda"`, `creado=null` y un término derivado de `fecha_reparto` (20 días hábiles).

## Riesgos

- **Presupuesto de CSS.** El prototipo suma unos 4,5 KB gz; el tope total es 25 KB gz. Se borran los estilos reemplazados (`.herramientas`, `.buscar`, `.grupo-casos`, `.vacio-busqueda`, `.continuar*`) y se reutilizan `.btn`, `.chip` y `Vacio`.
- **Facetas de texto libre se fragmentan.** Variantes de juzgado, entidad y derecho salen como opciones distintas; `plano` solo pliega tildes y mayúsculas.
- **Ocultar Terminados** cambia lo que ve el usuario.
- **«Trabajado» incluye la actividad del sistema.** Separar lo que hizo cada persona exige un registro de actividad, fuera de alcance.
- **Subir `VERSION` de la caché** (PR2 y PR3) reconstruye cada resumen una vez, en el calentamiento al arrancar.
- **Las vacaciones judiciales no se modelan** en el término; el título del chip muestra la regla.
- **Decisiones pendientes del despacho** (de `Facetas.dc.html`): desde cuándo corre el término (reparto o recibo, y festivos judiciales); si «Trabajado» basta con la última actividad; el plazo del desacato (referencia jurisprudencial, no término legal); y cómo clasificar el texto libre (`decision_a_quo`, `derechos`: palabras clave, con Jev de apoyo).
- **Popover y soltar archivos.** Verificar a mano que arrastrar una carpeta a la página de casos sigue funcionando con un popover abierto.
- **Router.** Revisar cómo `vistas/formato/guardia.ts` compara hashes crudos, y que Configuración conserve la consulta.
