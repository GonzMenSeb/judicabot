# Edición in situ del borrador (secciones I a V)

Fecha: 2026-11-17. Rama: `in-situ-modifications`, encima de `main` (5adcf0f).

## Por qué

El borrador (secciones I a V) era de solo lectura. Ante un error, las únicas salidas eran "Pedir correcciones" a la IA o corregir el Word al final. Pero el caso concreto se redacta *después* de la decisión leyendo `apertura` y `consideraciones` del estado del grafo, así que un error que no se corrige en el borrador se propaga al fallo. Objetivo: que el despacho corrija la prosa del borrador ahí mismo, con un editor de texto plano, y que esas correcciones lleguen al caso concreto y al fallo.

## Decisiones del usuario

- Hay tres clases de texto. **Plantilla** y **variable** (citas, marcas de imagen, datos de metadatos) no se tocan. Solo se edita el **texto normal**, es decir, la prosa de la IA.
- No se admiten citas nuevas. Los metadatos (encabezado, ASUNTO) quedan para otra feature.
- Modelo tipo git: las ediciones manuales y las correcciones de la IA se fusionan. Si no chocan, la fusión es automática; si chocan, el usuario elige.
- Texto plano, sin formato. Esto reemplaza el "El despacho edita en Word" del spec de 2026-11-02.

## No objetivos

- Editar el encabezado, el ASUNTO, la plantilla, los fragmentos citados (`cita_bloque`), el informe de citas, las alertas o los pies.
- Formato enriquecido (negrita, cursiva).
- Agregar, quitar o cambiar citas.
- Editar el caso concreto o la parte resolutiva (se redactan después de la decisión).

## Anti-objetivos (fracaso aunque funcione)

- Que una cita cambie de sentencia en silencio. Pasa, por ejemplo, si tras una corrección la IA reasigna los ids y el texto humano conserva `[[CITA:c2]]` apuntando a otra sentencia.
- Que una edición humana se pierda en silencio o que una corrección de la IA la pise sin preguntar.
- Que editar cambie la clasificación del caso, el payload de la decisión o dispare llamadas a la IA.

## 1. Piezas editables

Una **pieza** es un campo de texto del estado del grafo. Su id es la ruta del campo:

| Pieza | Sección (`ediciones_humanas`) | Etiqueta |
|---|---|---|
| `apertura.antecedentes_hechos` | `antecedentes` | Antecedentes: hechos |
| `apertura.contestaciones.{i}.texto` | `antecedentes` | Antecedentes: contestación de {entidad} |
| `apertura.sentencia_impugnada` | `sentencia_impugnada` | La sentencia impugnada |
| `apertura.impugnacion` | `impugnacion` | La impugnación |
| `consideraciones.procedibilidad` | `consideraciones` | Consideraciones: procedibilidad |
| `consideraciones.bloques.{i}.titulo` | `consideraciones` | Consideraciones: título del bloque {i+1} |
| `consideraciones.bloques.{i}.texto` | `consideraciones` | Consideraciones: bloque {i+1} ({titulo}) |

`{i}` empieza en 0. El catálogo de un estado sigue el orden del documento: antecedentes, contestaciones, sentencia impugnada, impugnación, procedibilidad y luego título y texto de cada bloque. Solo incluye las piezas que existen. Cualquier otro id es desconocido (404).

Un título ocupa una sola línea: su único párrafo es el título con los espacios colapsados.

### Párrafos

`ediciones.parrafos(texto)` es **la** partición en párrafos. `render._prosa` la recorre, así que el índice `k` de esa lista es el `parrafo` de la `fuente` de los bloques de la vista. La función corta en líneas en blanco (`\n\s*\n`), colapsa los espacios internos (un salto de línea simple pasa a ser un espacio) y descarta los párrafos vacíos.

La forma **normalizada** de un texto es `"\n\n".join(parrafos(texto))`. Toda comparación entre versiones (u, ia, texto, consolidado) se hace entre formas normalizadas, nunca entre cadenas crudas. Así los saltos de línea simples de la IA no disparan rebases falsos.

## 2. Forma editable y fichas

El usuario ve y edita la pieza en **forma editable**. Las marcas de texto variable se muestran como fichas fijas:

| Canónica (estado) | Editable |
|---|---|
| `[[CITA:c2]]` (regex `render._CITA`) | `⟦cita c2 · T-200 de 2022⟧`. La sentencia es la `sentencia_original` de la cita `c2` en `valores["citas"]`; si el id no está, `⟦cita c2⟧` |
| `[[IMAGEN desc]]` (regex `render._IMAGEN`) | `⟦imagen · desc⟧`, con `desc` sin espacios a los lados; si `desc` está vacía, `⟦imagen⟧` |

`a_canonico` hace el camino inverso: `⟦cita ID …⟧` pasa a `[[CITA:ID]]`, y `⟦imagen · desc⟧` pasa a `[[IMAGEN desc]]` (o `[[IMAGEN]]`). Para que una sentencia no pueda romper una ficha, `⟦`, `⟧` y los saltos de línea se reemplazan por espacios. La conversión vive solo en el backend; el frontend nunca la reimplementa.

**Fichas** de un texto editable: el multiconjunto (`Counter`) de `("cita", id, sentencia)` y `("imagen", desc)`. Se compara id **y** sentencia, para no confundir ids reasignados tras una corrección.

**Una sola partición.** La forma editable de una pieza se arma partiendo primero el texto canónico con `parrafos()` y convirtiendo después cada párrafo (`ediciones._editable`), nunca convirtiendo el texto entero y partiendo luego. Así el párrafo `k` editable es siempre el párrafo `k` de la vista (`fuente.parrafo`), aunque la IA haya dejado una marca rota por una línea en blanco (`[[IMAGEN a⏎⏎b]]` queda como dos párrafos de texto, no como una ficha). Por la misma razón una ficha **no cruza una línea en blanco**: `_FICHA` no coincide a través de `\n`. Si el usuario parte una ficha con una línea en blanco (por ejemplo pulsando Enter dos veces con el cursor dentro), sus mitades quedan como `⟦` y `⟧` sueltos y la edición se rechaza (regla 4 de §3). Las fichas que ya están en el texto se compactan al guardar (`⟦cita c1 · T-200 de 2022 ⟧` se guarda sin el espacio sobrante), para que un cambio de espacios dentro de una ficha no cuente como edición.

## 3. Validación (rechazo con 422)

`validar(pieza, nuevo, referencia, crudo)` devuelve la lista de errores (en español). `nuevo` y `referencia` están en forma editable. `referencia` es el texto actual de la IA en el estado (u), en forma editable. `crudo` es el texto que tecleó el usuario, antes de normalizar. La lista vacía significa válido. Rechaza:

1. Una pieza que queda sin párrafos ("no puede quedar vacía").
2. Un título con algún salto de línea en `crudo`.
3. `[[` o `]]` tecleados a mano. Las citas e imágenes solo existen como fichas. También rechaza una marca `[[CITA:id]]` o `[[IMAGEN desc]]` completa en la forma canónica que no sale de una ficha ni estaba ya en `referencia`, aunque se arme con trozos que sí estaban (`[[IMAGEN a` y `b]]` en párrafos distintos).
4. `⟦` o `⟧` sueltos, o una ficha alterada que no se puede leer.

   Las reglas 3 y 4 solo cuentan lo **nuevo** respecto de `referencia`: se rechaza cuando `nuevo` tiene más `[[`, `]]`, `⟦` o `⟧` fuera de fichas que `referencia`. Un resto mal formado que ya traía el texto de la IA (un `[[CITA: c1 c2]]` mal escrito, un `⟦FALTA: fecha⟧` de las fórmulas de apertura) no bloquea la pieza: se puede editar cualquier párrafo, conservarlo o quitarlo, pero no agregar otro. Si se exigiera cero restos en `nuevo`, una pieza así no se podría editar ni resolver (`resolver` y `sincronizar` validan contra la IA) y el único camino sería «Restaurar», que borra todas las ediciones de la pieza.
5. Fichas distintas de las de `referencia`. El mensaje dice cuáles faltan y cuáles sobran.
6. Solo en piezas de consideraciones, jurisprudencia nueva fuera de ficha:
   - una sentencia mencionada sin marcador (`lint._menciones_sueltas` sobre la forma canónica) que no estaba en la referencia;
   - un aumento en el número de oraciones que `lint.jurisprudencia_sin_cita` marca. Se cuenta párrafo por párrafo para no topar con su límite de 5 mensajes.
7. Caracteres de control que el Word no admite en `nuevo`: U+0000 a U+0008, U+000B, U+000C, U+000E a U+001F, sustitutos sueltos, U+FFFE y U+FFFF. `nuevo` ya está normalizado por `parrafos`, que convierte en espacio cualquier espacio en blanco de `str.split` (tabulador, U+000B, U+000C, U+001C a U+001F, U+0085, U+2028): esos nunca llegan a la regla. Sin esta regla, `render_previo` lanzaba `ValueError` ("All strings must be XML compatible") y el caso quedaba sin salida.

Los lints corren siempre sobre la forma canónica, nunca sobre la editable.

Nota: `jurisprudencia_sin_cita` emite `ALERTA:`, no `BLOQUEA:`. El plan original decía "BLOQUEA que antes no estaba". La regla adoptada es "cualquier mensaje nuevo de ese lint rechaza la edición", que es lo que buscaba el plan: no atribuir reglas nuevas a la jurisprudencia sin cita.

### Avisos (no bloquean)

`avisos(pieza, canonico, canonico_ia, ing)` corre los lints offline del pipeline y devuelve solo los mensajes nuevos respecto del texto de la IA (diferencia de conjuntos):
- `lint.lint_prosa`;
- `lint.residuos`;
- `lint.datos_ajenos` (solo en piezas de apertura, como hace `nodo_validar_apertura`).

Los títulos no tienen avisos. Se guardan en la capa y se muestran en línea.

## 4. Capa de ediciones: `caso_dir/ediciones.json`

Editar **no toca el grafo**. El estado sigue siendo la salida de la IA ("upstream", **u**) y la capa guarda los cambios locales.

```json
{
  "version": 1,
  "piezas": {
    "<pieza>": {
      "ia": "<texto de la IA, editable y normalizado>",
      "texto": "<texto humano, editable y normalizado>",
      "consolidado": "<último u visto, editable y normalizado>",
      "ancla": "<entidad de la contestación | título de la IA del bloque> | null",
      "avisos": ["..."]
    }
  },
  "conflictos": {
    "<pieza>": {
      "ia": "<nuevo u, editable y normalizado> | null",
      "huerfana": false,
      "trozos": [
        {"tipo": "ok", "parrafos": ["..."]},
        {"tipo": "conflicto", "mio": ["..."], "nuevo": ["..."]}
      ]
    }
  }
}
```

- `ia` es la base del diff3 y la referencia de "Editado". No cambia al consolidar; solo cambia en un rebase limpio o al resolver.
- `consolidado` corrige un hueco del plan original. Tras consolidar, el estado guarda el texto humano. Si después el usuario restaura (`texto := ia`) o vuelve a editar el mismo párrafo, la regla "sincronizado si u ∈ {ia, texto}" fallaba:
  - al restaurar, el rebase deshacía la restauración;
  - al volver a editar, aparecía un conflicto falso contra su propia edición anterior.

  `consolidado` registra el u que ya se conoce, y "sincronizado" pasa a significar **u ∈ {consolidado, texto, ia}**.
- `ancla` identifica la pieza aunque cambie de índice, porque una apertura rehecha puede reordenar contestaciones y bloques:
  - en una contestación es su `entidad`;
  - en un bloque (`consideraciones.bloques.{i}.titulo` y `.texto`) es el título **de la IA** del bloque al crear la entrada, canónico y en una sola línea. Los dos campos de un bloque comparten ancla y se mueven juntos;
  - en las demás piezas es `null`. Una entrada de bloque sin ancla (capa anterior a este cambio) sigue el índice.

  Un bloque sigue "en su sitio" si su título actual de la IA es el ancla o uno de los títulos (`ia`, `texto`, `consolidado`) de la entrada `.titulo` del mismo bloque y la misma ancla. Así, tras consolidar un título humano, una IA que lo conserva al rehacer no deja huérfanas las ediciones de ese bloque.

  Una entrada de bloque que se crea (al editar o al resolver) hereda el ancla de la entrada del otro campo del mismo bloque si el título actual es "su sitio" para ella. Sin esto, un texto editado después de consolidar un título humano H se anclaba a H mientras el título seguía anclado al de la IA, y la siguiente consolidación lo dejaba huérfano.
- La escritura es atómica: se escribe un temporal y luego `os.replace`, como en `vista.guardar`.
- `api._borrar_hilo` borra `ediciones.json` y `ediciones.jsonl`.
- Auditoría: `caso_dir/ediciones.jsonl` lleva una línea por acción: `{fecha, accion, pieza, ia, texto}`. Las acciones son `editar`, `restaurar`, `resolver`, `rebase`, `conflicto`, `descartar` y `consolidar`.

## 5. Fusión: `backend/tutela2/fusion.py`

Implementa un diff3 por párrafos sobre `difflib.SequenceMatcher(None, a, b, autojunk=False)` de la stdlib. Es una función pura y no depende del resto del paquete. No se usa `merge3` de PyPI porque es GPL-2.0+ y el repo es MIT.

`fusionar(base, mio, nuevo) -> list[dict]` recibe listas de párrafos.

1. Para cada lado S ∈ {mio, nuevo} toma los opcodes de base→S. Cada opcode que no es `equal` es un cambio del rango de base `[i1, i2)` por `S[j1:j2]`. Un `replace` de igual largo en ambos lados se parte en cambios de un párrafo, para que dos ediciones en párrafos vecinos no choquen.
2. Dos cambios de lados distintos **se solapan** en tres casos:
   - sus rangos se intersecan (`a1 < b2 and b1 < a2`);
   - ambos son inserciones en el mismo punto;
   - uno es una inserción estrictamente dentro del rango del otro.

   Una inserción justo en el borde de un rango no se solapa con él. El solapamiento se agrupa de forma transitiva en racimos.
3. Recorre base en orden y emite trozos de grano fino:
   - `{"tipo":"ok","origen":"igual","parrafos":base[...]}` para los tramos sin cambios;
   - un racimo con cambios de un solo lado → `{"tipo":"ok","origen":"mio"|"nuevo","base":[...],"parrafos":[...]}`;
   - un racimo con cambios de ambos lados y el mismo resultado → `ok` con `origen: "ambos"`;
   - un racimo con cambios de ambos lados y resultados distintos → `{"tipo":"conflicto","base":[...],"mio":[...],"nuevo":[...]}`.

   El resultado de un lado en un racimo es `base[lo:hi]` con los cambios de ese lado aplicados.

Funciones auxiliares:
- `hay_conflicto(trozos)`;
- `resultado(trozos, elecciones=None)`: concatena los `ok` y, por cada conflicto en orden, el lado elegido;
- `compactar(trozos)`: funde los `ok` contiguos, quita `origen` y `base`, y deja `{"tipo":"ok","parrafos"}` o `{"tipo":"conflicto","mio","nuevo"}` para guardar y mostrar;
- `escalar(trozos)`: convierte cada `ok` con `origen == "mio"` en `{"tipo":"conflicto","mio":parrafos,"nuevo":base}`. Se usa cuando una fusión limpia descuadra las fichas.

## 6. Funciones puras: `backend/tutela2/ediciones.py`

Ninguna función abre el grafo. Las que reciben `capa` devuelven una copia nueva y no la mutan.

- `parrafos`, `normalizar`.
- `catalogo(valores)`, `es_pieza(pieza)`, `etiqueta(pieza, valores)`, `seccion_de(pieza)`, `es_titulo(pieza)`.
- `obtener(valores, pieza) -> str | None` y `fijar(valores, pieza, texto) -> dict`. `fijar` devuelve una copia profunda de `apertura` o `consideraciones` con el campo cambiado.
- `mapa_citas(valores)`, `a_editable(texto, citas)`, `a_canonico(texto)`, `fichas(texto)`.
- `validar(...)`, `avisos(...)`.
- `leer(caso_dir)`: devuelve la capa vacía si el archivo falta o está corrupto, y registra un warning en el segundo caso. También `guardar(caso_dir, capa)`, `registrar(caso_dir, accion, pieza, ia, texto)` y `hay_conflictos(caso_dir)`.
- `ErrorEdicion(estado: int, mensaje: str)`: excepción que las rutas traducen a HTTP (404, 409 o 422).
- `aplicar(valores, capa) -> dict`: copia de `valores` con cada pieza editada fijada a `a_canonico(texto)`. Hay dos excepciones, en las que la pieza conserva el texto de la IA:
  - las piezas en conflicto;
  - una pieza con `ancla` que ya no está en su sitio (§4): una contestación cuya `entidad` cambió, o un bloque cuyo título actual no es su ancla ni un título de su entrada `.titulo`. El ancla se lee de `valores`, no de la copia que se va fijando, para que un título humano ya aplicado no desancle el texto de su bloque.
- `sincronizar(valores, capa) -> (capa, eventos)`: el rebase (§7). Es idempotente. `eventos` es una lista para el log.
- `consolidar(valores, capa) -> dict`: es el `update` para `Command`. Si no hay entradas, devuelve `{}`. Si hay conflictos, lanza `ErrorEdicion(409)`. Si no, devuelve `{"apertura": …, "consideraciones": …, "ediciones_humanas": …}`:
  - `apertura` y `consideraciones` son los objetos completos de `aplicar`;
  - `ediciones_humanas` es la unión, ordenada, de lo que ya traía el estado y de las secciones con alguna pieza en que `texto ≠ ia`.

  **Nunca** escribe `errores`, `intentos`, `decisiones`, `bitacora` ni `alertas`.
- `editar(valores, capa, pieza, parrafo, original, texto) -> capa`:
  1. Si la pieza está en conflicto, 409. Si no existe, 404.
  2. Toma el texto efectivo (`texto` de la entrada, o u) y sus párrafos.
  3. Responde 409 en dos casos, con el mensaje "recargue el borrador":
     - `parrafo` está fuera de rango;
     - `normalizar(original)` no es igual al párrafo `k`.
  4. Reemplaza el párrafo `k` por `parrafos(texto)`, que pueden ser 0 o más párrafos (0 borra el párrafo).
  5. Llama a `validar` contra u. Si falla, 422.
  6. Si la pieza no tenía entrada, la crea con `ia = consolidado = u` y el `ancla` que corresponda (§4; un bloque hereda la de su otro campo).
  7. Guarda el texto, con las fichas compactadas (§2), y los avisos.
  8. Si queda `texto == ia == consolidado`, borra la entrada.
- `restaurar(valores, capa, pieza) -> capa`:
  - pieza huérfana: borra la entrada y el conflicto;
  - pieza en conflicto: `ia = texto = conflicto.ia` y se quita el conflicto;
  - en otro caso: `texto := ia`, y la entrada se borra solo si `consolidado == ia`. Si no, la entrada se queda hasta la próxima consolidación. Si se borrara, el texto humano que ya se consolidó en u reaparecería.
- `resolver(valores, capa, pieza, elecciones) -> capa`:
  1. Responde 409 si no hay conflicto.
  2. Responde 422 en tres casos:
     - la pieza es huérfana (solo se puede descartar);
     - el número de elecciones no coincide con el de trozos en conflicto;
     - en algún trozo se eligió `"mio"` y sus fichas no son iguales a las del trozo `nuevo`.
  3. Arma el resultado y lo valida contra `conflicto.ia`.
  4. Fija `ia = consolidado = conflicto.ia` y `texto = resultado`, y quita el conflicto. Si `texto == ia`, borra la entrada.
- `respuesta(valores, capa, editable=True, motivo=None) -> dict`: el cuerpo de la API (§8). Para cada pieza del catálogo:
  - `parrafos` son los párrafos editables del texto efectivo. En una pieza en conflicto es el `ia` del conflicto, que es lo que muestra la vista;
  - `editados` son los índices de párrafos de `texto` que no casan con `ia`: los rangos `insert`/`replace` del lado de `texto` en los opcodes de ia→texto. Un párrafo quitado no deja índice;
  - `modificada` es `true` cuando los párrafos de `texto` difieren de los de `ia`, incluso si solo se quitaron párrafos (entonces `editados` es `[]`). Vale `false` sin entrada y en una pieza en conflicto;
  - `avisos`.

  Los trozos en conflicto llevan `mio_permitido = fichas(mio) == fichas(nuevo)`. Una pieza huérfana se guarda con `trozos: []`, pero la respuesta lleva un único trozo `{"tipo": "ok", "parrafos": P(texto)}` con el texto del usuario, para que pueda copiarlo antes de descartarlo; su `etiqueta` es la de su ancla (`Consideraciones: bloque «<título>»`, `Antecedentes: contestación de <entidad>`), porque su índice ya no dice nada. Con `editable=False` devuelve `piezas={}` y `conflictos=[]`.

## 7. Rebase: `sincronizar`

1. **Reanclaje de contestaciones y bloques.** Se hace por grupo (contestaciones por `entidad`; bloques por título, §4). Un sitio es (índice, campo): `titulo` y `texto` de un bloque se reclaman por separado pero, con la misma ancla, caen en el mismo índice. Para cada entrada `apertura.contestaciones.{i}.texto` o `consideraciones.bloques.{i}.{campo}` con `ancla` A:
   - si la contestación (o el bloque) `i` sigue siendo de A, la entrada se queda;
   - si otra `j`, no reclamada por otra entrada, es de A, la entrada y su conflicto pasan a la clave `{j}`;
   - si ninguna es de A, la pieza es huérfana. Conserva su clave salvo que otra entrada se haya movido a ella; entonces pasa a la primera clave libre fuera de la lista (índice ≥ longitud), que no existe en `valores`.

   Para un bloque esto significa: si la IA reordena los bloques, la edición sigue a su bloque sin conflicto; si la IA cambia el título del bloque (y no lo conserva en ningún índice), la edición queda huérfana y solo se puede descartar, en lugar de caer en silencio bajo otro encabezado.

   Primero se busca el ancla exacta (en su índice y luego en otro) y solo después los títulos humanos de la entrada `.titulo`, para que un título humano igual al de otro bloque no le quite el sitio a ese bloque. Las claves nuevas se calculan antes de reconstruir los dicts, para soportar intercambios.
2. Para cada entrada `(pieza, e)`, con u = `_editable(pieza, obtener(valores, pieza), mapa_citas(valores))` (la forma editable normalizada de §2):
   - si la pieza ya no existe (hay menos bloques, desapareció la entidad o falta `apertura` o `consideraciones`): conflicto `{"ia": null, "huerfana": true, "trozos": []}`, que solo permite descartar;
   - si ya hay un conflicto con el mismo `ia == u`: sigue pendiente y no se hace nada (idempotencia);
   - si `u ∈ {e.consolidado, e.texto, e.ia}`: se quita cualquier conflicto viejo y se fija `e.consolidado = u`. Si además `e.texto == e.ia == u`, se borra la entrada;
   - si no, `t = fusion.fusionar(P(e.ia), P(e.texto), P(u))`:
     - sin conflictos: se calcula `m = resultado(t)`. Si `fichas(m) == fichas(u)` y `validar(pieza, m, u)` no da errores, se fija `e.ia = e.consolidado = u` y `e.texto = m`, se recalculan los avisos y se borra la entrada si `m == u`. Si no, es una **fusión limpia con fichas descuadradas**: se guarda el conflicto con `trozos = compactar(escalar(t))`. Pasa, por ejemplo, si el humano movió una cita y la IA cambió ese párrafo;
     - con conflictos: se guarda `{"ia": u, "huerfana": false, "trozos": compactar(t)}`. La entrada queda como estaba.
3. "Editado" y la declaración se comparan contra `ia`, nunca contra u.
4. Los pasos 1 y 2 se repiten hasta que la capa no cambia (con un tope de `len(piezas) + 2` pasadas). Una pasada puede borrar entradas ya sincronizadas y liberar el sitio que reclamaban; una huérfana que podía ocuparlo solo se movería en la pasada siguiente, y `sincronizar` dejaría de ser idempotente (cada GET cambiaría la capa y el previo).
4. Nunca se sincroniza con un job corriendo ni fuera de `esperando_decision`.

## 8. API: `backend/tutela2/rutas_ediciones.py`

La ruta se registra en el bucle de módulos de `server.py`. Sigue el precedente de `PUT /revision`: todo corre bajo `server._LOCK`, revisa JOBS en línea y solo opera en `esperando_decision` sin job corriendo. La lógica va en funciones nuevas de `api.py` que abren `_grafo` solo para leer:
- `ediciones(caso_dir, job_activo)`;
- `editar_pieza(...)`;
- `restaurar_pieza(...)`;
- `resolver_pieza(...)`.

Después de cada cambio de capa, esas funciones (`api._guardar_capa`):
1. regeneran `previo.docx` y la vista con `render.render_previo(ediciones.aplicar(valores, capa), cfg, …/previo.docx)`, usando la capa candidata;
2. solo si el render tuvo éxito, guardan la capa y registran el log.

Así no queda una capa guardada que el previo (y el hash de «Borrador previo (sha256)») no refleje. Si el render falla, no se persiste nada y la petición responde 500; si falla el guardado de la capa, el previo se vuelve a generar con la capa anterior; si falla solo la línea de auditoría, la capa y el previo ya son coherentes y no se deshace nada. Lo mismo vale para el GET que sincroniza.

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| GET | `/api/casos/{id}/ediciones` | — | `EdicionesRespuesta`. Con un job corriendo, sin hilo o fuera de `esperando_decision`: **200** `{editable:false, motivo, piezas:{}, conflictos:[]}`, nunca un 4xx (el fixture `vigilante` del e2e falla con 4xx inesperados). Si es editable, sincroniza, y si la capa cambió, la guarda y regenera el previo |
| PUT | `/api/casos/{id}/ediciones/{pieza}` | `{parrafo, original, texto}` | `EdicionesRespuesta` · 404 si la pieza es desconocida · 409 si hay un job, el estado no es el esperado, la pieza está en conflicto o `original` está desfasado · 422 si la validación falla |
| DELETE | `/api/casos/{id}/ediciones/{pieza}` | — | `EdicionesRespuesta` (restaurar o descartar) |
| POST | `/api/casos/{id}/ediciones/{pieza}/resolver` | `{elecciones: ["mio"\|"nuevo", …]}` | `EdicionesRespuesta` · 409/422 |

Esquemas Pydantic (en `esquemas.py`):
- `PiezaEdicion{parrafos: list[str], editados: list[int], modificada: bool, avisos: list[str]}`;
- `TrozoOk{tipo: Literal["ok"], parrafos}`;
- `TrozoConflicto{tipo: Literal["conflicto"], mio, nuevo, mio_permitido: bool}`;
- `ConflictoEdicion{pieza, etiqueta, huerfana: bool, trozos: list[TrozoOk | TrozoConflicto]}`, con discriminador `tipo`;
- `EdicionesRespuesta{editable: bool, motivo: str | None, piezas: dict[str, PiezaEdicion], conflictos: list[ConflictoEdicion]}`;
- `EdicionCuerpo{parrafo: int ≥ 0, original: str, texto: str}`;
- `ResolverCuerpo{elecciones: list[Literal["mio","nuevo"]]}`.

El detalle de los errores es un string en español. Si hay varios, se unen con un espacio.

Los conflictos pendientes se rechazan de forma síncrona en dos lugares:
- en `POST /run` con `cmd: "decidir"` (409, bajo `_LOCK`), así el rechazo no aparece como un job fallido en la vista del proceso;
- al principio de `api.decidir`, antes de escribir `decision.json` (para la CLI).

## 9. Consolidación al reanudar

`api.decidir`, para **toda** acción válida (decidir y rehacer):
1. Sincroniza la capa (es idempotente).
2. Si hay conflictos, rechaza.
3. Si no:
   - si la decisión es válida (`Decision.model_validate(...).errores()` vacío, la misma validación que hace `nodo_decision`), `update = ediciones.consolidar(valores, capa)`; si no, `update = {}`;
   - si hay update, registra `consolidar` en el log **antes** de invocar. El update se aplica al empezar el paso, así que queda escrito aunque un nodo posterior falle;
   - `g.invoke(Command(update=update, resume=decision) if update else Command(resume=decision), hilo, durability="sync")`.

**Por qué solo con una decisión válida.** Lo descubrió la oleada 2. Una decisión inválida hace que `nodo_decision` vuelva a interrumpir sin cerrar el paso, así que el update queda como escritura pendiente de la tarea nula. Un segundo `Command(update=…)` sobre ese mismo checkpoint lanza `InvalidUpdateError: At key 'apertura': Can receive only one value per step`, y después también falla `get_state`: el caso queda inutilizable. Con una decisión inválida, las ediciones siguen en la capa y se consolidan con la próxima decisión válida.

Se verificó con el grafo real y el `FakeClient` (spike del 2026-11-17, LangGraph 1.2.19). `Command(update, resume)` aplica el update antes de reanudar el nodo `decision`:
- `decidir`: la edición llega al prompt del caso concreto, con una sola llamada nueva a la IA;
- `rehacer_consideraciones` y `rehacer_apertura`: la IA recibe el texto humano como SALIDA ANTERIOR y el grafo vuelve a pausar;
- decisión inválida: el nodo vuelve a armar la pausa, el caso sigue en `esperando_decision` y no hay llamadas. Pero ver arriba: con una decisión inválida no se manda update.

No hace falta el respaldo `update_state(as_node=…)` siempre que se respete la guarda de decisión válida.

`Estado` gana `ediciones_humanas: list[str]`. `estado_inicial` no la incluye: se lee con `.get(..., [])`.

Después de una corrección, `api._leer_estado(regenerar_previo=True)`:
1. llama a `ediciones.sincronizar`;
2. renderiza el previo con `ediciones.aplicar(valores, capa)` (la capa sincronizada);
3. si la capa cambió, la guarda y registra el log, en ese orden (ver §8).

## 10. Declaración de uso de IA

`render._mapa_secciones(gen, hay_compulsa, editadas=frozenset())` marca el origen como **"IA + edición humana"** y agrega a la observación "Corregido por el despacho en el borrador." en las filas cuya sección está en `editadas`:
- ANTECEDENTES (`antecedentes`);
- III (`sentencia_impugnada`);
- IV (`impugnacion`);
- V procedibilidad y bloques (`consideraciones`).

`render_declaracion_ia` pasa `set(estado.get("ediciones_humanas") or [])`.

## 11. Vista

- `vista.Fuente{pieza: str, parrafo: int}`. `Bloque` gana `fuente: Fuente | None = None`, y en el contrato TS queda `fuente?: Fuente | null`.
- `Registro` gana `fuente`, que se fija con `Registro.como(fuente=…)` igual que `origen`. `bloques_cuerpo` la emite; las filas de tabla y los pies llevan `None`.
- `render.prosa`/`_prosa` reciben `pieza: str | None`. Cada párrafo `k` de `parrafos(texto)` emite sus bloques (texto y marcas de imagen) con `fuente={pieza, parrafo: k}`. Los `cita_bloque` de `_bloques_citados` llevan `fuente=None`.
- `_secciones_i_a_v` y `_consideraciones` pasan la pieza a cada prosa. El título de cada bloque se emite con `fuente={pieza: "consideraciones.bloques.{i}.titulo", parrafo: 0}`.
- `fuente` vale `None` en plantilla, encabezado, ASUNTO, `cita_bloque`, caso concreto, resolutiva y pies. El fallo también lleva `fuente` en I a V; su vista la ignora.

## 12. Frontend (`frontend/src/vistas/borrador/`)

- **`index.tsx`**:
  - carga también `GET …/ediciones`. Si esa llamada falla, el borrador queda en solo lectura y no se rompe (los tests con `simularRed` devuelven 404 a rutas desconocidas);
  - agrega el interruptor **"Editar texto"**, apagado por defecto;
  - después de guardar, recarga la vista y las ediciones sin pasar por `fase="cargando"`, para no perder el scroll.
- **`Documento.tsx`**:
  - en modo edición, los bloques con `fuente` muestran un botón **"Editar párrafo"**. El nombre es fijo para no chocar con los selectores de citas en los tests;
  - los bloques consecutivos con la misma fuente (por el corte de `[[IMAGEN]]`) se editan como uno.
- **`EditorParrafo.tsx`** (nuevo): un `<textarea>` con los párrafos editables.
  - "Guardar" (Ctrl+Enter);
  - "Cancelar" (Esc con `preventDefault`, porque el manejador global de Escape solo se salta si `defaultPrevented`);
  - "Restaurar el texto de la IA";
  - muestra el 422 en línea y, ante un 409, avisa y recarga;
  - ayuda: "Deje una línea en blanco entre párrafos. Las fichas ⟦…⟧ son citas e imágenes: no se pueden cambiar.";
  - la marca **"Editado"** y los avisos aparecen en línea;
  - "Restaurar el texto de la IA" se ofrece cuando `modificada` es verdadera, no solo cuando hay `editados`: si lo único que cambió es un párrafo quitado, la pieza lleva la marca **"Con párrafos quitados"** en su primer párrafo y el botón aparece al abrir cualquiera de ellos;
  - tras un 409 el editor conserva lo escrito y recarga. Si el párrafo cambió en el servidor, muestra su versión actual y ofrece **"Guardar sobre la versión actual"** (envía `original` igual a esa versión), de modo que reemplazar lo nuevo sea una decisión explícita. "Guardar" sigue enviando el `original` con el que se abrió: refrescarlo en silencio podría pisar otro párrafo si cambiaron los índices;
  - el texto escrito y sin guardar se protege con `useGuardiaSalida` (diálogo "Hay texto sin guardar", con "Seguir editando" y "Descartar el texto") al apagar "Editar texto" y al navegar a otra ruta. "Cancelar" y Esc descartan sin preguntar porque son un gesto explícito.
- **`DialogoConflictos.tsx`** (nuevo, sobre `Dialogo`):
  - por cada trozo en conflicto muestra "Su versión" y "Versión de la corrección" lado a lado y deja elegir con radio. "Su versión" se desactiva con una explicación cuando `mio_permitido` es falso;
  - una pieza huérfana solo ofrece "Descartar mi edición" (DELETE) y muestra el texto del usuario ("Su texto, por si quiere copiarlo antes de descartarlo:");
  - un aviso arriba del documento abre el diálogo.
- **`estilos.css`**: con la barra del documento en dos filas (hasta 560 px de ancho) `scroll-padding-top` sube a 11 rem para que el título de la sección elegida en el índice no quede tapado.
- **Vista de decisión** (`vistas/decision/index.tsx`): un 409 de `POST /run` muestra el motivo del servidor. Con conflictos de edición pendientes el aviso ofrece "Resolver en el borrador" en lugar de "Ver el proceso".
- **`Dock.tsx`**: con conflictos se desactivan "Pasar a la decisión" y "Pedir correcciones", y se indica el motivo.
- **`DialogoCorrecciones.tsx`**: nota "Sus ediciones se conservan; si la corrección cambia los mismos párrafos, se le pedirá elegir."
- **`datos.ts`**:
  - las claves de "revisado" pasan a depender del contenido: `alerta-${nodo}-${mensaje}` y `cita-${id}-${estado}-${fuente}`. La sentencia (`fuente`) va en la clave porque una corrección de la IA puede reasignar los ids: sin ella, lo revisado de la antigua `c2` valdría para otra sentencia con el mismo estado;
  - la clave de almacenamiento pasa a `judicabot:revisados:${caso}`;
  - se podan las claves que ya no existen;
  - se borran las claves viejas `judicabot:revisados:${caso}:${sha}` solo de ese caso.

  Así guardar una edición ya no borra lo revisado.
- **`mock.ts`**: mocks de los endpoints nuevos.

## 13. Pruebas

- **Backend** (`cd backend && uv run pytest`):
  - `test_fusion.py`: sin cambios, solo mío, solo nuevo, iguales, choque, inserciones y borrados, párrafos adyacentes (se fusionan), inserciones en el mismo punto (conflicto);
  - `test_ediciones.py`:
    - ida y vuelta de fichas;
    - cada rechazo de `validar`;
    - `parrafos()` coincide con los bloques `fuente` de la vista renderizada;
    - casos de `sincronizar`: ids de cita reasignados, fusión limpia con fichas descuadradas (se vuelve conflicto), contestaciones reordenadas, saltos de línea simples (no disparan rebase), restaurar después de consolidar (devuelve el texto de la IA) y volver a editar después de consolidar (sin conflicto falso);
    - en un conflicto, "mio" se rechaza por trozo cuando las fichas no cuadran;
  - integración con `arrancar()` de `tests/test_graph.py` y el `FakeClient`:
    - editar deja el caso en `esperando_decision`;
    - `decidir` lleva el texto editado al caso concreto y al fallo;
    - el conteo de la bitácora prueba que no hubo llamadas de más a la IA;
    - `rehacer_consideraciones` con ediciones hace el rebase;
    - un conflicto bloquea `decidir` hasta resolverlo;
  - rutas:
    - GET con un job corriendo responde 200 `editable:false` y no sincroniza;
    - 409 (job, estado, `original` desfasado);
    - 422;
  - declaración: aparece "IA + edición humana".
- **Frontend:** `cd frontend && pnpm typecheck && pnpm test && pnpm check:tipos && pnpm build && pnpm size` (25 KB gzip por ruta).
- **E2E:** `pnpm e2e` contra el backend real con `TUTELA2_PROVEEDOR=fake`. Escenario:
  1. editar un párrafo;
  2. recargar y ver que persiste;
  3. pasar a la decisión y decidir;
  4. ver el texto editado en la vista del fallo.

  `03-confirmar` sigue igual porque el modo edición está apagado por defecto.
