# Diseño: de la carpeta de primera instancia a la carpeta de segunda instancia

Fecha: 2026-11-02. Reemplaza lo que contradiga a `docs/diseno-tutela-2a-instancia.md` y a `docs/CONTRATO_IMPLEMENTACION.md`. El resto de esos documentos sigue vigente.

## 1. Propósito

El despacho (Juzgado Tercero Penal del Circuito con Función de Conocimiento de Medellín) recibe por reparto la impugnación de un fallo de tutela. El expediente que llega es la carpeta `01PrimeraInstancia`, que ya contiene todo lo ocurrido: escrito de tutela, auto admisorio, respuestas de las entidades, fallo de primera instancia, impugnación y auto que la concede.

El programa recibe **solo esa carpeta**, arrastrada a la ventana, y entrega la carpeta `02SegundaInstancia` con sus archivos numerados. El documento central es el borrador del fallo de segunda instancia en Word, que el Oficial Mayor y el juez editan y firman.

Exigir la carpeta de segunda instancia como entrada fue un error del diseño anterior: esa carpeta es el producto, no el insumo.

## 2. Objetivos, no objetivos y antiobjetivos

**Objetivos**
- Entrada: la carpeta `01PrimeraInstancia`, arrastrada y soltada en la interfaz. También se acepta la carpeta del caso que la contiene; si trae `02SegundaInstancia`, esa subcarpeta se ignora con una alerta.
- Salida: `02SegundaInstancia/C01Principal/` con archivos numerados (sección 6) y, fuera de ella, los borradores de los correos por enviar.
- Cada documento Word es una copia visual de los modelos reales. El fallo copia los dos fallos más recientes: 12001 (20-oct-2026) y 53001 (21-oct-2026).
- El paso humano se mantiene. El flujo se detiene para que el juez decida si la tutela procede y en qué sentido, y solo después se redacta el caso concreto.

**No objetivos**
- No se firma nada ni se incrustan imágenes de firma: cada firma queda como espacio reservado.
- No se envían correos ni se radica nada en plataformas.
- No hay salida en PDF ni en LaTeX. El despacho edita en Word; se descartó LaTeX por eso.
- El fallo no lleva párrafo de declaración de uso de IA y queda idéntico a los modelos. La declaración del art. 10 del Acuerdo PCSJA24-12243 sigue como documento aparte (`declaracion_ia.docx`), por decisión del despacho del 2026-11-02.

**Antiobjetivos (fracaso aunque funcione)**
- Fabricar constancias de hechos ajenos o futuros: actas de reparto, impresiones de correos enviados o memoriales de partes. Un PDF de "correo enviado" que no se envió es un documento falso en un expediente judicial.
- Que el programa decida el problema jurídico. Acuerdo PCSJA24-12243, art. 8.3: la decisión es del juez.
- Bloquear un caso porque un archivo tiene un nombre inesperado.

## 3. Material de referencia

Todo está en `referencia/`, que está en `.gitignore` porque tiene datos personales de casos reales:
- `referencia/casos/<radicado>/`: copia de los 9 casos de Drive (carpeta pública `1Yg-ujyB-GdOcWlIM9EU4CsVaGSI3zG73`), con `01PrimeraInstancia` y `02SegundaInstancia` (en 45901 está escrita `02SegundaInstacia`).
- `referencia/analisis/`. Los informes citan rutas de una carpeta temporal: `.../scratchpad/drive/` equivale a `referencia/casos/`.

| Archivo | Contenido |
|---|---|
| `format_spec.md` | Medidas tipográficas de los fallos 12001 y 53001. Ahí REF1 = 12001 y REF2 = 53001. La §12 es una receta para python-docx. |
| `format_spec_check.md` | Verificación independiente de `format_spec.md`: 26 valores corregidos. Donde ambos difieren, manda la verificación. |
| `render_diff.md` | Lo que genera hoy el prototipo frente al fallo real 53001. Ahí "ref 1" = 53001 y "ref 2" = 12001. |
| `fallo_structure.md` | Estructura de los 9 fallos, fórmulas fijas literales de 12001 y 53001 (§3) y 34 diferencias con `render.py` (§4). |
| `catalogo.md` | Catálogo de los documentos de las 9 carpetas `02SegundaInstancia`: quién los produce, numeración, texto fijo, campos variables y de dónde salen. |
| `gems_calificacion.md` | Gems del papá sobre calificación y estructura real del Formato Factor Calidad. |
| `ground_truth_1a.json` | Tipo correcto de cada documento de las 9 carpetas de 1.ª instancia, con evidencia citada del contenido. |
| `inventory_*.json` | Inventario detallado de cada archivo de segunda instancia. |

- `referencia/assets/`: logo de la Rama Judicial extraído de los fallos, en la resolución original.
- Gems del papá: `/home/sebastian/Downloads/ayuda_papa/manual_maestro_de_prompts_sin_truncar.md`. Las Gems #9, #6 y #8 son las tres etapas del fallo que ya implementa el grafo.

## 4. Flujo

```
arrastrar 01PrimeraInstancia
  → ingesta y clasificación por contenido
  → revisión de documentos (el usuario corrige tipos si hace falta)
  → apertura (I–IV) → consideraciones (V)
  → [DECISIÓN DEL JUEZ]
  → caso concreto (VI) → ensamblado
  → carpeta 02SegundaInstancia + borradores de correo
```

El grafo LangGraph, los prompts por etapa, la verificación de citas y el lint se mantienen. Lo que cambia está en las secciones 5 a 8.

## 5. Ingesta y clasificación

**Problema medido.** Con solo la 1.ª instancia, la ingesta actual bloquea 7 de 9 casos:
- Exige `acta_reparto_2a`.
- Clasifica por nombre de archivo y no reconoce `007_007Fallo`, `009_007Fallo`, `010_010SentenciaTutela…`, `001_002DemandaTutela` ni `025ImpugancionAccionante` (mal escrito).
- En 34601 marca como ajeno el escrito de tutela, por la verificación de CUI, y no reconoce la impugnación real.

**Requisitos**
1. Clasificar por **contenido**: el texto de las primeras páginas. El nombre del archivo es solo una pista.
2. Rasgos de contenido observados en los casos (`ground_truth_1a.json`, campo `evidence`):
   - El acta de la impugnación contiene `ACTA INDIVIDUAL DE REPARTO` y `CLASE PROCESO: IMPUGNACIÓN TUTELA`.
   - El acta de la tutela tiene la misma cabecera con otra clase.
   - El fallo de 1.ª instancia lleva cabecera del juzgado de origen y parte resolutiva, y su radicado coincide con el del caso.
3. Documentos que el clasificador debe distinguir:
   - Una sentencia vieja de otro proceso adjunta como prueba (`022SentenciaTutela02072024` en 34601) no es el fallo de primera instancia.
   - Un correo de notificación del juzgado que contiene la impugnación (`025` en 34601) es una impugnación.
   - Puede haber varias impugnaciones (40601: la accionante y Savia Salud) y ampliaciones (34601 `030`).
4. **Obligatorios** (bloquean): escrito de tutela, fallo de 1.ª instancia y al menos una impugnación. **Esperados** (generan alerta, no bloquean): auto admisorio, auto que concede la impugnación (falta en 40601) y acta de reparto de la impugnación (falta en 40601). Nada de la 2.ª instancia es obligatorio.
5. El radicado de 2.ª instancia se deriva del de 1.ª: los mismos 21 dígitos con sufijo `01`.
6. El juzgado de origen se deriva del radicado (dígitos 6–12):
   - `4009NNN` = Juzgado NNN Penal Municipal con Función de Conocimiento.
   - `4088NNN` = Juzgado NNN Penal Municipal con Función de Control de Garantías.

   Es una regla observada en los 9 casos. Se contrasta con el texto del fallo y, si no coinciden, se alerta.
7. La lógica de "documento ajeno" no debe descartar un documento obligatorio por traer CUIs de otros procesos dentro de sus anexos.
8. Pantalla de revisión: tabla con cada documento, su tipo y la evidencia (frase citada). El usuario puede cambiar el tipo antes de ejecutar.
9. **OCR.** En 53001, sin OCR se pierden 10 páginas del escrito y 14 de la impugnación. Tesseract en español es un requisito (sección 11). Si una pieza obligatoria tiene páginas escaneadas sin texto y no hay OCR, la alerta lo dice con nombre y páginas.

**Método.** Primero reglas deterministas sobre el contenido. Si con reglas no se cumple la prueba de aceptación (sección 10), se permite un paso de clasificación con el modelo sobre las primeras páginas de los documentos dudosos. El constructor documenta cuál usó y por qué.

## 6. Carpeta de salida

`salidas/02SegundaInstancia/C01Principal/` contiene:

| N.º | Archivo | Origen | Condición |
|---|---|---|---|
| 001 | `001ActaRepartoSegunda.pdf` | Copia byte a byte del acta de reparto de la impugnación hallada en 1.ª instancia | Si existe (8 de 9 casos). Si no existe, no se genera y la numeración sigue sin hueco. |
| 002 | `002AutoAsumeSegunda<YYYYNNNNN>.docx` | Generado | Siempre |
| 003 | `003FalloSegunda<YYYYNNNNN>.docx` | Generado | Siempre |
| 004 | `004FormatoCalificacion<YYYYNNNNN>.docx` | Generado | Solo si el juez lo pide en la decisión |

- La numeración es secuencial de 3 dígitos, sin huecos. Si no hay acta, el auto es 001.
- `YYYYNNNNN` son los dígitos 13 a 21 del radicado, por ejemplo `202600530`.
- Los nombres van en CamelCase y sin tildes, como en las carpetas reales (`catalogo.md` §2).

**Fuera de la numeración**, en `salidas/por_radicar/`:
- `OficioRemiteCorteConstitucional.docx`. Se genera siempre, porque los 9 fallos ordenan la remisión. Va sin número porque antes de él se radican las impresiones de los correos de notificación, y su posición depende de eso.

En `salidas/borradores_correo/` va un documento por correo con asunto, destinatarios propuestos, cuerpo y la tabla de 3 celdas que usa el despacho (`catalogo.md` T6–T9):
- Notificación del fallo a las partes. Destinatarios propuestos: los del último correo de notificación del juzgado de origen en 1.ª instancia, que el usuario confirma.
- Envío del formato de calidad al juzgado de origen, si hay formato.
- Remisión de la compulsa de copias, si el RESUELVE la ordena.

Estos borradores no son constancias. El usuario envía el correo y radica la impresión real con el número siguiente.

En `salidas/trabajo/` quedan los documentos de trabajo que ya existen y no se radican:
- `previo.docx`;
- `informe_verificacion.docx`;
- `declaracion_ia.docx`;
- `requerimiento.docx`, cuando falta una pieza obligatoria.

Así no se confunden con el expediente.

**Momento de entrega.** En la realidad el auto que asume se dicta de 1 a 5 días después del reparto, semanas antes del fallo. Por eso 001 y 002 se pueden descargar apenas termina la revisión de documentos, y los mismos archivos se incluyen después en la carpeta final (decisión del diseño). Los campos editables del auto (fecha, accionante, accionada) van en la pantalla Documentos. La fecha del oficio va en el formulario de decisión.

La interfaz descarga todo como `.zip`.

## 7. Documentos generados

Reglas comunes:
- Todo en `.docx` con python-docx, sin firmas.
- La firma es un espacio del tamaño de la imagen real con el nombre y el cargo debajo.
- Los datos que no se pueden extraer quedan como marcador visible `⟦FALTA: …⟧`, como hoy.

### 7.1 Fallo (003)

**Formato.** Copia visual de 12001 y 53001. Si las dos referencias difieren, manda **53001**, la más reciente. Esa regla es una decisión del diseño, no algo que pidió el papá. Las especificaciones están en `format_spec.md` §12, corregida por `format_spec_check.md`. Lo más visible que hay que corregir, según `render_diff.md` §2:
1. Encabezado con el logo de la Rama Judicial centrado, de 7,02 × 2,33 cm, en todas las páginas.
2. Pie de página de tres líneas centradas en Cambria cursiva 8 pt:
   - "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín"
   - "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19"
   - "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co"

   El número de página va en Times New Roman 10 pt en la posición medida.
3. Interlineado de 1,5 líneas y espaciado entre párrafos medido. Hoy son 1,15 líneas y 8 pt.
4. Márgenes, sangrías laterales por acápite y tamaño de página. La página de la generación B (21,1 × 34,1 cm) ya es correcta.
5. Tabla de partes con bordes de ½ pt y sangrada, con el ancho de columnas medido y la etiqueta concordada en género y número: "Accionado", "Accionada", "Vinculados"… Nunca "Accionada/o".
6. Títulos de acápite en romanos con tabulación entre el numeral y el título, y el espaciado medido.
7. Citas jurisprudenciales en Bookman cursiva 11 pt **subrayada**, con las sangrías medidas.
8. Escala de caracteres (114 %, 109 %, 104 %…), donde `format_spec_check.md` la confirma.
9. Nombre del juzgado en negrilla en la fórmula de mérito.
10. En el RESUELVE, el ordinal y el verbo van en negrilla ("**PRIMERO: REVOCAR**"), con una línea en blanco entre numerales.
11. Bloque de firma con el espacio de la firma, el nombre y "JUEZ" en interlineado sencillo.

**Texto fijo.** Corregir las diferencias de `fallo_structure.md` §4 donde 12001 y 53001 coinciden. Puntos clave:
- **ASUNTO**: "…contra el fallo de tutela emitido el … por el …, por medio del cual se …". Identifica al impugnante con su calidad (accionante, vinculada, a través de apoderado) y su documento. Admite plural cuando hay varias impugnaciones.
- **CONSIDERACIONES**:
  - Subtítulo "Presupuestos Generales de Procedibilidad de la Acción de Tutela".
  - Los párrafos P1 y P2 de `fallo_structure.md` §3.6 salen de plantilla.
  - Inmediatez, subsidiariedad y perjuicio irremediable los redacta el modelo en plano dogmático, sin valorar el caso. El acápite V corre antes de la decisión del juez y la Gem #6 prohíbe resolver el caso ahí. Los párrafos P3–P7 de 12001 sirven de ejemplo de estilo. La verificación de procedibilidad aplicada a los hechos va en el caso concreto, después de la decisión (Gem #8, regla 2). Decisión del diseño: en 53001 esa adaptación al caso aparece en V, pero hacerla antes de la decisión inclinaría el resultado.
  - El párrafo de competencia y la transición ya coinciden.
- **RESUELVE**:
  - PRIMERO: "REVOCAR la sentencia … proferida el …", describiendo lo que decidió el juez de origen.
  - La fórmula sustitutiva, ORDENAR ("al"), PREVENIR con conducta libre, NOTIFICAR y REMITIR se redactan según `fallo_structure.md` §4, ítems 18–26.
  - El formulario de decisión debe admitir además un **numeral de texto libre**, para lo que las plantillas no cubren (`fallo_structure.md` §4, ítem 27).
- **Firma**: el nombre del juez es configurable y por defecto es la forma de 53001, "SANTIAGO ALEJANDRO CADAVID DUQUE".
- **Fechas en letras**: el día va con cero, por ejemplo "seis (06)".

### 7.2 Auto que asume (002)

Familia B de `catalogo.md` T2: constancia secretarial, logo, auto, firma y pie del despacho.
- **Modelo visual**: los autos 002 de 12001 y 53001.
- **Texto fijo**: el literal del catálogo.
- **Campos**:
  - Fecha de recibo: la FECHA REPARTO del acta.
  - Juzgado de origen: del radicado, verificado.
  - Accionante y accionada: de 1.ª instancia, editables.
  - Fecha del auto: por defecto el día siguiente al reparto, editable.
  - Firmante de la constancia y fórmula de cierre: configurables.

### 7.3 Formato Factor Calidad (004)

Formato del CSJ, Acuerdo PSAA16-10618, art. 30. Estructura en `gems_calificacion.md` §4 y `catalogo.md` T5.
- Primero buscar la plantilla oficial del CSJ en Word o Excel. Si no se consigue, reconstruirla con los 5 formatos reales como modelo visual.
- **Prellenado**:
  - Fecha de evaluación: la fecha del fallo de 2.ª instancia.
  - Juez evaluado: quien firmó el fallo de origen.
  - Despacho, fecha de admisión, fecha de la providencia y tipo de proceso.
  - Código único: el radicado con sufijo `00`.
  - Evaluador.
- **En blanco para el juez**: puntajes y motivación. Son evaluación de un funcionario y el programa no los propone.

### 7.4 Oficio a la Corte Constitucional (por radicar)

`catalogo.md` T10.
- **Modelo visual**: los oficios de 45601 y 45901, en Verdana y tamaño oficio.
- **Texto fijo**: el literal del catálogo.
- **Campos**: fecha (editable), radicado `…01`, accionante y accionado.

## 8. Decisión del juez (paso humano)

Se mantiene el formulario actual con estos agregados:
- Si se genera el Formato Factor Calidad.
- Fecha del fallo, por defecto la del día.
- Numerales de texto libre.
- Orden de los numerales editable.

El caso concreto se redacta después de la decisión. La restricción de la Gem #8 se mantiene: no citar en el caso concreto sentencias que no estén en las consideraciones.

## 9. Interfaz

- **Pantalla Casos**: una zona para arrastrar y soltar que recorre carpetas anidadas (`DataTransfer.items` + `webkitGetAsEntry`). Se conserva el botón de selección de carpeta como alternativa.
- **Pantalla Documentos** (nueva): la revisión de la clasificación de la sección 5, punto 8.
- **Pantalla Resultado**: muestra el árbol de `02SegundaInstancia` y los borradores de correo, con descarga `.zip`.
- **Configuración del despacho**: juez, firmante de constancias y oficios, y textos del pie, con los valores por defecto de las referencias.

## 10. Prueba de aceptación

1. **Ingesta**, con solo `01PrimeraInstancia` de cada caso en `referencia/casos/`:
   - Ningún caso de los 9 queda bloqueado.
   - Fallo de origen, impugnaciones, escrito de tutela, auto admisorio, auto que concede y acta de la impugnación coinciden con `ground_truth_1a.json` en los 9 casos.
   - Se cumplen las trampas de la sección 5, punto 3.
2. **De punta a punta en modo `fake`** para los 9 casos, con decisiones que reflejen el fallo real: se produce la carpeta completa con la numeración de la sección 6.
3. **Formato**. Pruebas automáticas que lean el `.docx` generado y comprueben, contra los números de `format_spec_check.md` y `format_spec.md`:
   - tamaño de página y márgenes;
   - encabezado con imagen;
   - las tres líneas del pie;
   - bordes y anchos de la tabla;
   - fuente, tamaño, interlineado y espaciado del cuerpo;
   - estilo de las citas;
   - negrillas del RESUELVE.

   Además, una comparación visual lado a lado (docx → PDF con LibreOffice → PNG) de las páginas 1, una de citas y la última contra 12001 y 53001, que queda en `salidas/` para revisión humana. Sin la fuente Bookman Old Style la comparación visual solo vale para la geometría, no para los cortes de línea.
4. **Texto fijo**: las fórmulas de la sección 7.1 coinciden literalmente con 53001, o con 12001 donde 53001 no tiene la pieza.
5. Las pruebas existentes siguen pasando, salvo las que fijan comportamiento que este diseño reemplaza. Esas se actualizan:
   - textos de `test_render.py`;
   - `acta_reparto_2a` obligatoria y clasificación por nombre en `test_ingest.py`;
   - conjuntos de archivos de salida en `test_graph.py`.

   La generación A sigue disponible, pero los cambios de texto y formato de este diseño se exigen solo en la B, que pasa a ser la predeterminada (decisión del diseño).

## 11. Precondiciones

- Instalar `tesseract-ocr` y `tesseract-ocr-spa` (`sudo apt install tesseract-ocr tesseract-ocr-spa`) y ejecutar `uv sync --extra ocr`. La prueba de aceptación 1 no puede pasar sin OCR: el escrito de tutela de 37401 está escaneado en todas sus páginas.
- Opcional, para una comparación visual fiel: los archivos de la fuente Bookman Old Style y Cambria de un equipo con Office, solo para pruebas locales.

## 12. Lo que queda a criterio del constructor

- Reglas concretas de clasificación y si hace falta el paso con el modelo (sección 5).
- Cómo replicar en python-docx la escala de caracteres y la posición del número de página.
- Estructura interna del código de las plantillas nuevas (auto, formato, oficio, borradores de correo).
- Formato de los borradores de correo (`.docx` o `.txt`).
