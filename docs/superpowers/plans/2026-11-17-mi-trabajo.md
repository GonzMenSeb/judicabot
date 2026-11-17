# «Mi trabajo»: lista de casos compartida y filtrable — plan de implementación

**Spec:** `docs/superpowers/specs/2026-11-17-mi-trabajo-design.md`. Prototipo aprobado: `docs/ui/mi-trabajo/` (`Lista.dc.html` tiene la lógica a portar en su `<script>`: `ESTADOS`, `TERMINOS`, `FECHAS`, `PROPIAS`, `FILA`, `pasa(c, omitir)`, orden y agrupación).

## Contexto

Hoy Inicio muestra «Para continuar», una lista con solo los 2 casos que más urgen (`frontend/src/vistas/inicio/index.tsx:115-124`). La página de segunda instancia tiene su propia lista, aparte (`frontend/src/vistas/casos/index.tsx:51-100`), que solo ofrece búsqueda de texto y agrupación fija.

El prototipo aprobado reemplaza ambas por **un componente compartido**:

- **Pestañas de proceso** en Inicio.
- **Una franja de estados** cuyos tramos miden según su número de casos.
- **Baldosas de Plazos.**
- **Dos carriles de filtros:** «Generales» y un carril teñido «Propios de <proceso>», siempre visible.
- **Pastillas de filtro:** cada una está plegada hasta que se toca y entonces abre un popover con el control adecuado: lista de casillas, lista con buscador, pasos, rango de fechas con histograma o un interruptor.
- **Una barra de resultados:** conteo, Limpiar/Deshacer, Ordenar, Agrupar, Fichas/Compacta.
- **Chips resaltados en cada fila** que repiten los filtros activos.
- **Un estado vacío** que sugiere qué filtro quitar.

Faltan varios datos: el tipo de proceso, los campos propios de segunda en la lista de casos y el término (plazo). De ahí los tres PR por fases.

## Decisiones

- **Entrega.** Tres PR, fusionados en orden. Cada uno es utilizable solo. PR2 y PR3 regeneran `frontend/openapi.json` y `src/api/schema.d.ts`, así que no pueden correr en paralelo.
- **El estado de los filtros vive en la consulta de la URL** (decisión suya), por ejemplo `#/?e=decidir,error&f=semana&s.juzgado=…&o=vence`.
  - Se escribe con `history.replaceState`, así que filtrar no añade entradas al historial.
  - Atrás desde un caso restaura la vista filtrada y los enlaces se pueden guardar como marcador.
  - Lo único que se guarda en `localStorage` es la preferencia de densidad, dentro de `try/catch`.
- **Datos del término (su respuesta: «agréguelo al dato y empiece a recopilarlo»).** Cada caso guarda su término como dato:
  - Campos: `termino = {inicio, dias, unidad}`.
  - Se rellena de antemano desde `fecha_reparto` (el valor de `auto.json`, y si no, el acta de reparto de 2ª), 20 días, `habiles`.
  - El usuario lo confirma o edita en **Documentos**, junto al campo «Fecha de reparto» (`vistas/documentos/FormAuto.tsx:7`).
  - Los casos nuevos también empiezan a registrar `proceso` y `creado`.
  - Los casos creados antes de este cambio reciben valores por defecto: `proceso="segunda"`, `creado=null` y un término derivado de `fecha_reparto`.
  - Los días hábiles restantes se calculan en vivo en el servidor con `backend/tutela2/festivos.py`. Nunca se guardan en la caché indexada por mtime.
- **Un solo proceso (el caso de hoy).** Inicio muestra igual las pestañas de todos los procesos, con «Todos» elegida; mientras todos los casos sean de 2ª instancia, «Todos» muestra el carril Propios de 2ª. Las pestañas de los procesos sin casos se pueden elegir y muestran «Todavía no hay casos de <proceso>.».
- **Nombres accesibles estables** para limitar el cambio en las pruebas:
  - El buscador sigue siendo «Buscar casos».
  - Los enlaces de caso conservan el nombre `${accion}: ${nombre}`.
  - El texto de búsqueda sin resultados conserva el prefijo «Ningún caso coincide».
- **Terminados queda oculto por defecto.** Un tramo rayado «Terminados · ocultos» los trae de vuelta con un toque. Cuando todos los casos están terminados: `Vacio` «No hay casos abiertos» con un botón «Ver los terminados (N)».
- **Ubicación del código.**
  - El código de la lista vive en `frontend/src/vistas/casos/`, junto a `Ficha` y `agrupar`, que `inicio` ya importa, de modo que Vite construye un solo chunk compartido.
  - El primitivo del popover va en `frontend/src/ui/`.
  - Convenciones: interfaz en español con «usted», sin anclas `href="#seccion"` (`ui/LEEME.md`), Conventional Commits en español, ramas `feat/<kebab>`.

## Arquitectura compartida (se construye en el PR1 y se amplía después)

```
ui/Desplegable.tsx           popover no modal: nunca un <dialog>, porque vistas/casos/soltar.ts:5 trata dialog[open]
                             como modal y bloquearía soltar archivos; disparador con aria-expanded; Escape + clic en
                             una superposición; el foco vuelve al disparador; hoja inferior a ≤960px
vistas/casos/facetas.ts      registro: PROCESOS, procesoDe, ESTADOS (7 estados de la API → 6 grupos de la interfaz),
                             generales(proc, casos), PROPIAS{segunda…}, FILA{segunda…} (chips con clave/valor para el
                             eco), PLAZOS (PR3)
vistas/casos/filtros.ts      motor puro, sin DOM: tipo Filtros, predicados, pasa/contar (conteos facetados),
                             elegirEstado, alternar, limpiar/deshacer, sugerencia, presets de fecha, actividad
                             (histograma), ordenarPor, agruparPor, serializar/deserializar (URL), validar
vistas/casos/ListaCasos.tsx  conexión: cabecera + buscador, pestañas, Tablero, barra de resultados, grupos,
                             Ficha/FichaCompacta, «Mostrar más»
vistas/casos/Tablero.tsx     franja de estados, baldosas de Plazos (PR3), carriles, PastillaMenu, Interruptor, ListaOpciones
vistas/casos/FiltroFecha.tsx presets con conteos + histograma de 30 días + Desde/Hasta
vistas/casos/lista.css
```

Forma de una faceta (lo único que varía por proceso):

```ts
{ clave, etiqueta, corto, tipo: "varias"|"buscable"|"pasos"|"interruptor", activo?, opciones, valor(c) }
```

Cada conteo ignora el filtro al que pertenece:

| Conteo | Ignora |
|---|---|
| Opciones de una pastilla | la clave de esa pastilla |
| Franja de estados | estado |
| Pestañas | proceso y todas las claves `ex:*` |
| Baldosas de Plazos | plazo |

Los conteos de las opciones se calculan solo mientras su popover está abierto.

**Código a reutilizar:**

- De `vistas/casos/agrupar.ts`: `tonoDe`, `etapaDestino`, `hrefCaso`, `accionDe`, `varianteDe`, `tramosDe`, `descripcionAvance`, `partesDe`, `TRAMOS`. Extraer `plano` y un nuevo `coincideBusqueda` de `filtrar`.
- `IconoProceso`, `IconoLupa` y `TipoProceso` de `vistas/casos/iconos.tsx`.
- `fechaRelativa` y `plural` de `estado/formato.ts`.
- `Boton`, `Chip`, `Vacio`, `Aviso`, `Cargando` y `cx` de `ui/`.
- `bloquearFondo` de `ui/modal.ts` (exportarlo).
- Para los patrones de Escape y clic fuera, seguir `vistas/borrador/PopoverCita.tsx` y `vistas/borrador/index.tsx:229-249`.

---

## PR1: `feat/mi-trabajo-lista` (frontend + URL; datos que ya existen)

1. **Consulta en el router**, en `frontend/src/rutas/router.ts`:
   - `separar(hash) → [camino, consulta]`. `coincidir` interpreta solo el `camino`, así que `#/segunda?…` ya no cae en Inicio.
   - Una señal `consulta`, asignada en `sincronizar`.
   - `reemplazarConsulta(q)` llama a `history.replaceState(history.state, "", hashDe(ruta.value) + (q ? "?" + q : ""))`. No dispara `hashchange`, así que no hay remontaje ni desplazamiento.
   - `rutas/Configuracion.tsx:24`: `cerrar` debe volver a `hashDe(ruta.value)` más la consulta recordada de la página. Si no, `sincronizar` reasignaría el hash y perdería la consulta.
   - Revisar cómo `vistas/formato/guardia.ts` compara hashes crudos.
   - Exportar las piezas nuevas desde `rutas/index.ts` y añadir una regla corta a `ui/LEEME.md`.
2. **`ui/Desplegable.tsx`**, con estilos en `estilos/ui.css`:
   - Exportarlo desde `ui/index.ts` y documentarlo en `ui/LEEME.md`.
   - Exportar `bloquearFondo` de `ui/modal.ts`, solo para la hoja en móvil. Proteger `matchMedia`, que no existe en jsdom.
   - El disparador es un `<button ref>` simple, porque `Boton` no reenvía refs.
3. **`estado/formato.ts`:** añadir `diaIso(date)` y `fechaCorta(iso)` (es-CO «19 oct.»). Exportar ambas.
4. **`vistas/casos/agrupar.ts`:**
   - Exportar `plano` y `coincideBusqueda`.
   - Borrar `GRUPOS`, `grupoDe`, `ordenar` y `agrupar`. Su trabajo pasa a `facetas`/`filtros`.
5. **`facetas.ts` y `filtros.ts`** como se describió arriba:
   - `procesoDe` devuelve `"segunda"` por ahora.
   - `PROPIAS` y `FILA` empiezan vacíos.
   - Generales: Trabajado, Juzgado (con la etiqueta «Juzgado de 1ª inst.» en segunda), Entidad accionada, Con alertas.
   - Órdenes: prioridad, reciente, antiguo, radicado.
   - Agrupaciones: ninguna, estado.
   - Las claves de la URL son cortas (`q`, `p`, `e`, `f`/`d`/`h`, `s.<clave>`, `o`, `g`). `validar` descarta claves o valores desconocidos.
6. **`Ficha.tsx` y `ficha.css`:**
   - Quitar la prop `compacta`.
   - Añadir `mostrarProceso?` (la línea superior) y `datos?` (chips, con el resaltado `eco`; se usa desde el PR2).
   - Añadir `FichaCompacta`, una fila de una línea.
7. **Nuevos `ListaCasos.tsx`, `Tablero.tsx`, `FiltroFecha.tsx` y `lista.css`:**
   - Props: `{casos, proceso?, aviso?, vacio?}`.
   - h2 de la cabecera: «Mi trabajo» en Inicio, «Casos» en la página del proceso.
   - Agrupación por defecto: estado en la página del proceso, ninguna en Inicio.
   - Tamaño de página: 10, con «Mostrar más».
   - En el PR1 no se dibujan las baldosas de Plazos ni el carril Propios.
8. **`vistas/casos/index.tsx`:**
   - Reemplazar las líneas 51-100 por `<ListaCasos casos proceso="segunda" aviso vacio>`.
   - Quitar `consulta`, `filtrar` y `agrupar`.
   - Borrar `.herramientas`, `.buscar`, `.grupo-casos` y `.vacio-busqueda` de `estilos.css`.
9. **`vistas/inicio/index.tsx`:**
   - Quitar `continuar`.
   - `abiertos` pasa a ser `estado !== "terminado"`.
   - Dibujar `<ListaCasos casos>` bajo las tarjetas de proceso, solo cuando haya al menos un caso.
   - Reemplazar `.continuar*` en `estilos.css`.
10. **`src/pruebas/preparar.ts`:** limpiar `localStorage` y reiniciar el hash después de cada prueba.
11. **Prototipo:** copiarlo a `docs/ui/mi-trabajo/`, porque el directorio temporal es efímero.
12. **Documentación:**
    - README, «Uso» y la tabla de estados: añadir `sin_iniciar` y `corriendo`, y las etiquetas de la interfaz.
    - Nuevos `docs/superpowers/specs/2026-11-17-mi-trabajo-design.md` y `docs/superpowers/plans/2026-11-17-mi-trabajo.md`.

**Pruebas del PR1:**

- **Nuevo `ui/Desplegable.test.tsx`:**
  - atributos ARIA y foco al abrir;
  - Escape cierra y devuelve el foco;
  - un clic en la superposición cierra;
  - no se crea ningún `dialog[open]`.
- **Nuevo `vistas/casos/filtros.test.ts`:**
  - el mapeo de estados y `elegirEstado` (desde el valor por defecto, el primer toque muestra solo ese estado; los siguientes alternan; Terminados alterna; una selección vacía vuelve al valor por defecto);
  - conteos facetados;
  - presets de fecha, rango e histograma con un `hoy` fijo;
  - órdenes y agrupaciones;
  - limpiar/deshacer y sugerencia;
  - el viaje de ida y vuelta de serializar/deserializar la URL y `validar`.
- **Nuevo `vistas/casos/ListaCasos.test.tsx`:**
  - franja y pastillas;
  - conteos del popover, «Listo · N casos» y la ✕ de una pastilla;
  - el interruptor Con alertas;
  - clic en un preset de Trabajado y en un día del histograma (`vi.setSystemTime`);
  - estado vacío y sugerencia; Limpiar y Deshacer;
  - Ordenar y Agrupar;
  - el modo compacto conserva los mismos nombres de enlace;
  - filtros restaurados desde `location.hash`.
- **`router.test.tsx`:**
  - la consulta se ignora al coincidir rutas;
  - `reemplazarConsulta` no añade historial ni remonta;
  - la consulta sobrevive a abrir y cerrar el panel de configuración.
- **Actualizar:**
  - `casos.test.tsx`: nuevos encabezados de grupo «Por decidir», «Faltan documentos», «Por preparar», «En redacción». Hacer clic en «Terminados» antes de comprobar los casos terminados. «ceiba» ya no muestra a Duque por defecto.
  - `inicio.test.tsx`: la región ahora es «Mi trabajo» y cambia el orden de los h3. «Mi trabajo» no aparece cuando no hay casos.
  - `agrupar.test.ts`: las pruebas pasan a `filtros.test.ts`.
  - e2e `01-inicio.spec.ts:14`: región «Mi trabajo».
  - e2e `02-flujo.spec.ts:312-319`: hacer clic primero en «Terminados».

---

## PR2: `feat/mi-trabajo-propios-segunda` (filtros de segunda en el dato)

**Backend:**

1. **`models.py`:** extraer los alias `ResultadoDecision` y `SustitutivaDecision` de `Decision`.
2. **`esquemas.py`:**
   - Nuevo `DatosSegunda`:
     - `decision_a_quo`: Literal de los `SENTIDOS` de jev (ampara, niega, improcedente, carencia_actual_de_objeto, otro), o None;
     - `impugnante`: accionante, accionada, vinculada, otro, varios o None;
     - `resultado`, `sustitutiva`, `derechos`, `pruebas_nuevas`, `n_citas_revisar`, `jev_discrepa`.
   - `CasoResumen` gana `proceso: Literal["segunda"]` y `segunda: DatosSegunda | None`.
3. **Nuevo `resumen_segunda.py`:** `datos(estado, resumen)`. Debe tolerar `resumen == {}`.
   - **Clasificación de `decision_a_quo`.** Buscar primero el verbo inicial, en este orden: `declar… carencia`, luego `declar… improcedente`, luego `neg|nieg|deneg`, luego `ampar|tutel|conced`.
     - Si nada coincide al inicio, buscar en todo el texto en el mismo orden.
     - Luego recurrir a `jev_metadatos.preguntas.sentido_fallo` con confianza igual o superior al umbral.
     - El texto que no coincide con nada pasa a `otro`. Plegar tildes.
     - No usar `lint._SUSTITUTIVA` tal cual: «negó el amparo» contiene «ampar».
   - **`impugnante`:** «varios» si hay más de un impugnante; si no, el rol.
   - **`resultado`:** solo cuando `decision.accion == "decidir"`.
   - **`pruebas_nuevas`:** `bool(apertura.pruebas_nuevas_2a)` cuando existe la apertura.
   - **`n_citas_revisar`** (alerta + rechazada) y **`jev_discrepa`** (algún `coincide is False`): se informan mientras el caso está en `esperando_decision`.
   - **`derechos`:** recortados y sin duplicados sin distinguir mayúsculas.
4. **`resumen_caso.py`:**
   - Añadir `proceso` y `segunda` a `CLAVES`; `VERSION = 2`. Las cachés se reconstruyen mediante `_leer_cache` y el `calentar` del arranque.
   - `campos_desde_estado` asigna ambos campos.
   - Actualizar el docstring.

**Frontend:**

5. Ejecutar `pnpm gen:tipos` y luego actualizar `api/contrato.ts` (`DatosSegunda`, los campos nuevos) y `api/contrato.verificacion.ts`.
6. **`facetas.ts`:**
   - `procesoDe = c => c.proceso`.
   - `PROPIAS.segunda`:
     - Decisión 1ª inst. (selección múltiple);
     - Impugnó (selección múltiple);
     - Sentido 2ª inst. (selección múltiple);
     - Derecho (con buscador);
     - Por revisar (selección múltiple);
     - Con pruebas nuevas (interruptor).
   - Chips de `FILA.segunda`: «1ª inst.: …», «Impugna: …», «Fallo: revoca y ampara», «Pruebas nuevas en 2ª», «N citas por revisar», «Jev discrepa».
7. **`Tablero.tsx`:** el carril «Propios de 2ª instancia», con el icono del proceso y el conteo de filtros aplicados.
8. **`ListaCasos.tsx`:** pasar a `Ficha` los chips con el resaltado `eco`.
9. **Mocks:** añadir los campos nuevos a `vistas/casos/mock.ts` (`satisfies CasoResumen[]`, datos variados), `vistas/documentos/mock.ts:102` y `vistas/fallo/mock.ts:147`.

**Pruebas del PR2:**

- Nuevo `backend/tests/test_resumen_segunda.py`:
  - clasificación de frases, parametrizada;
  - el recurso a Jev por encima y por debajo del umbral;
  - varios;
  - qué estados informan cada campo;
  - `{}`;
  - el Literal coincide con `jev_metadatos.SENTIDOS`.
- `test_resumen_caso.py`:
  - ampliar la prueba de metadatos;
  - `CAMPOS` se actualiza solo;
  - la lista de 200 casos en caliente debe quedar por debajo de 50 ms;
  - `test_openapi_export.py` debe seguir en verde.
- Frontend, `filtros.test.ts` y `ListaCasos.test.tsx`:
  - el carril Propios;
  - conteos en el popover de Decisión 1ª inst.;
  - resaltado `.dato.eco`;
  - el interruptor de pruebas.
- Documentación: actualizar B1 en `docs/superpowers/specs/2026-11-03-judicabot-ui-contrato.md` y el README.

---

## PR3: `feat/mi-trabajo-plazos` (recopilar el término y luego los filtros de Plazos)

**Backend:**

1. **Empezar a recopilar datos del caso.**
   - En `POST /api/casos` (`rutas_casos.py:60-102`), escribir `.datos_caso.json` con `{proceso: "segunda", creado: <ISO>, termino: null}`.
   - Añadir el archivo a `RASTREADOS` en `resumen_caso.py`, junto con `auto.json`, para que editar la fecha de reparto invalide la caché.
   - Si el archivo falta, `proceso` es «segunda» y `creado` es null.
2. **Nuevo `termino.py`:**
   - `ZONA = UTC-5`. El contenedor corre en UTC.
   - `hoy()`.
   - `efectivo(caso_dir, respuesta)` combina el `termino` guardado con los valores por defecto: inicio = el primer día hábil después de `fecha_reparto`, 20 días, `habiles`.
   - `plazo(termino, estado, hoy)` devuelve `{vence, dias_restantes}`, con `lru_cache` indexado por `(termino, hoy)`. Devuelve None para casos terminados o cuando no hay fecha.
3. **`festivos.py`:** añadir `sumar_habiles(dia, n)` y `habiles_entre(a, b)`. Los existentes `es_habil` y `siguiente_habil` se conservan.
4. **Endpoints:**
   - `GET`/`PUT /api/casos/{id}/termino` (`esquemas.Termino {inicio, dias, unidad: "habiles"|"calendario"}`).
   - El PUT valida la entrada y escribe `.datos_caso.json`.
5. **`resumen_caso.py`:**
   - `CLAVES` gana `creado` y `termino` (los hechos en caché); `VERSION = 3`.
   - `_completo()` añade `vence` y `dias_restantes` en vivo, mediante `termino.plazo`. Todas las rutas pasan por `_completo`, así que nada que dependa de la fecha se guarda en caché.
6. **`esquemas.py`:** `CasoResumen` gana `creado`, `termino`, `vence` y `dias_restantes`.
7. **`server.py`:** `EstadoServidor` gana `festivos: list[str]` (el año anterior, el actual y el siguiente), para que el histograma raye los festivos sin lógica de festivos en el frontend.

**Frontend:**

8. Ejecutar `pnpm gen:tipos`, actualizar `contrato.ts` y añadir los `festivos` por defecto a `api/mock.ts`.
9. **Documentos** (`vistas/documentos/FormAuto.tsx` e `index.tsx`):
   - Un grupo «Término para fallar» junto a «Fecha de reparto»: Recibido el (fecha), Plazo (número), unidad (hábiles/calendario).
   - Se rellena con los valores efectivos y se marca «por defecto» hasta que se guarde.
   - Se guarda con `PUT …/termino`.
   - Si falta la fecha de reparto, muestra un aviso («Sin fecha de reparto no se puede calcular el plazo»).
10. **Lista:**
    - `facetas.PLAZOS`: vencido, pronto, semana, despues, sin.
    - `plazoDe` y `textoPlazo`.
    - `filtros`: el predicado de plazo; la prioridad pone primero los vencidos y los que vencen hoy; nuevo orden «Vence primero»; nueva agrupación «Por plazo».
    - `Tablero`: tres baldosas de Plazos, visibles cuando algún caso del alcance tiene término.
    - `Ficha`/`FichaCompacta`: un chip de término con el título «Recibido el …; vence el …».
    - `FiltroFecha`: rayas de fines de semana y festivos desde `estadoServidor.value.festivos`.

**Pruebas del PR3:**

- Nuevo `test_termino.py`:
  - una fecha que cruza el festivo del 2026-11-16;
  - fines de semana;
  - el signo de `dias_restantes`;
  - días calendario frente a hábiles;
  - un `hoy` simulado con monkeypatch.
- `test_resumen_caso.py`:
  - la precedencia del término efectivo;
  - editar `auto.json` o `.datos_caso.json` invalida la caché;
  - cambiar `hoy` cambia `dias_restantes` sin reconstruir (comprobar con `llamadas_estado`);
  - la prueba de rendimiento sigue pasando.
- `test_server.py`: `festivos` en estado-servidor y el viaje de ida y vuelta del PUT del término.
- Frontend:
  - las cubetas de `filtros` y el nuevo orden y agrupación;
  - las baldosas de Plazos;
  - el chip de término;
  - el formulario de término de Documentos (`documentos.test.tsx`).

---

## Verificación (en cada PR)

- **Frontend:** `cd frontend && pnpm check:tipos && pnpm typecheck && pnpm test && pnpm build && pnpm size`. Revisar el presupuesto de CSS, que es ≤25 KB gz en total; borrar el CSS reemplazado y reutilizar `.btn`, `.chip` y `Vacio`.
- **Backend:** `cd backend && uv run pytest`.
- **e2e:** `cd frontend && pnpm e2e`, a mano porque la CI no lo corre. Usa el backend real con el LLM falso, y `capturar()` comprueba el desbordamiento a 390 px.
- **Comprobación manual:** `VITE_MOCK=1 pnpm dev` y recorrer:
  - filtrar en Inicio y en `#/segunda`;
  - Atrás desde un caso conserva los filtros;
  - abrir y cerrar el panel de configuración conserva la consulta de la URL;
  - el teclado en los popovers (Escape, retorno del foco);
  - la hoja inferior a ≤960 px;
  - arrastrar una carpeta a la página de casos sigue funcionando con un popover abierto.

## Riesgos

- **El presupuesto de CSS es justo.** El prototipo suma unos 4,5 KB gz. Quitar los estilos reemplazados; subir el presupuesto solo si usted está de acuerdo.
- **Las facetas de texto libre se fragmentan.** Las variantes de juzgado, entidad y derecho salen como opciones separadas; `plano` solo pliega tildes y mayúsculas.
- **Ocultar Terminados por defecto** cambia lo que ven los usuarios. El tramo rayado y el estado vacío «Ver los terminados» lo compensan.
- **«Trabajado» es la última actividad sobre los archivos (`actualizado`).** Incluye el trabajo hecho por el sistema, y el título del popover lo dice. Un registro de quién trabajó en qué queda fuera de alcance.
- **Las subidas de `VERSION` de la caché** (PR2 y PR3) reconstruyen cada resumen una vez, en el calentamiento del arranque.
- **Las vacaciones judiciales no se modelan en el término.** Los días se cuentan sobre los datos por caso del despacho, y el título del chip muestra la regla.
