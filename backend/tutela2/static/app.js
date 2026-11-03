(() => {
'use strict';

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const enc = encodeURIComponent;

const VISTAS = [
  ['casos', 'Casos'],
  ['documentos', 'Documentos'],
  ['config', 'Configuración'],
  ['ejecutar', 'Ejecutar'],
  ['revision', 'Revisión'],
  ['decision', 'Decisión'],
  ['resultado', 'Resultado'],
];

const ESTADOS = {
  sin_iniciar: ['Sin iniciar', 'neutro'],
  incompleto: ['Incompleto', 'alerta'],
  revision: ['Revisión de documentos', 'info'],
  esperando_decision: ['Esperando decisión', 'info'],
  terminado: ['Terminado', 'ok'],
  error: ['Error', 'mal'],
  corriendo: ['En ejecución', 'info'],
  ok: ['ok', 'ok'],
  alerta: ['alerta', 'alerta'],
  rechazada: ['rechazada', 'mal'],
};

const NODOS = { apertura: 'Apertura', consideraciones: 'Consideraciones', caso_concreto: 'Caso concreto' };

const ETIQUETAS = {
  plantilla_gen: ['Plantilla', 'Generación A o B: cambia los títulos de sección, la fórmula de mérito y el tamaño de página.'],
  despacho: ['Despacho', ''],
  'despacho.nombre': ['Nombre (encabezado)', ''],
  'despacho.nombre_cuerpo': ['Nombre (cuerpo)', ''],
  'despacho.ciudad': ['Ciudad', ''],
  'despacho.juez': ['Juez', ''],
  'despacho.cargo_juez': ['Cargo del juez', ''],
  'despacho.escribiente': ['Escribiente', ''],
  'despacho.cargo_escribiente': ['Cargo del escribiente', ''],
  'despacho.firmante_oficio': ['Firmante del oficio', ''],
  'despacho.cargo_firmante_oficio': ['Cargo del firmante del oficio', ''],
  'despacho.cargo_evaluador': ['Cargo del evaluador (formato de calidad)', ''],
  'despacho.pie': ['Pie de página', ''],
  'despacho.correo': ['Correo', ''],
  'despacho.telefono_correo': ['Teléfono y extensión (correos)', ''],
  'despacho.cierre_fallo': ['Cierre del fallo', ''],
  'despacho.cierre_auto': ['Cierre del auto', ''],
  'despacho.pie_fallo': ['Pie del fallo (un renglón por línea)', 'Cada línea es un renglón del pie.'],
  'despacho.pie_auto': ['Pie del auto (un renglón por línea)', 'Cada línea es un renglón del pie.'],
  llm: ['Modelo de lenguaje', ''],
  'llm.proveedor': ['Proveedor', 'Simulado produce salidas de prueba sin red ni API key.'],
  'llm.effort': ['Esfuerzo', ''],
  'llm.max_tokens': ['Máximo de tokens de salida', ''],
  'llm.timeout_s': ['Tiempo máximo por llamada (s)', ''],
  'llm.fallbacks_default': ['Usar fallbacks del servidor', ''],
  'llm.modelo_por_nodo': ['Modelo por nodo (JSON)', 'Vacío: todos los nodos usan el modelo elegido arriba a la derecha. Ejemplo: {"apertura": "claude-haiku-5-5"}'],
  'llm.effort_por_nodo': ['Esfuerzo por nodo (JSON)', 'Ejemplo: {"caso_concreto": "max"}'],
  jev: ['Jev (segunda opinión)', ''],
  'jev.modo': ['Modo', 'Apagado: no sale ninguna petición. Sombra: Jev opina y solo deja alertas. Relleno: además asigna el rol a los documentos que el código no pudo clasificar. En sombra y en relleno se envían fragmentos del expediente a un tercero.'],
  'jev.umbral_confianza': ['Umbral de confianza', 'Entre 0 y 1 (0,9, no 90). Solo se actúa con opiniones de Jev iguales o superiores a este valor; también define los colores de los porcentajes. Lo ya calculado conserva el umbral con el que se calculó.'],
  'jev.timeout_s': ['Tiempo máximo por petición (s)', 'Mayor que 0. Es la espera máxima de la respuesta de Jev. Si la petición falla por cualquier motivo (error de Jev, de conexión o tiempo agotado) se reintenta una sola vez, así que la espera total puede llegar al doble.'],
  'jev.max_chars_cabecera': ['Caracteres de cabecera por documento', 'Fragmento inicial del documento que se envía a Jev para opinar sobre su rol y sobre el impugnante.'],
  'jev.max_chars_sentido': ['Caracteres finales del fallo de 1.ª instancia', 'Cola del fallo que se envía a Jev para verificar el sentido de la decisión.'],
  'jev.concurrencia': ['Peticiones simultáneas', ''],
  max_intentos: ['Intentos máximos por nodo', ''],
  ocr: ['Aplicar OCR a páginas sin texto', ''],
  verificar_relatoria: ['Verificar citas contra la relatoría', ''],
  cobertura_ok: ['Cobertura mínima para "ok"', ''],
  cobertura_alerta: ['Cobertura mínima para "alerta"', ''],
  ngram: ['Tamaño del n-grama', ''],
  exigir_mp: ['Exigir magistrado ponente', ''],
  max_bloques_tematicos: ['Máximo de bloques temáticos', ''],
  permitir_listas_caso: ['Permitir listas en el caso concreto', ''],
  jaccard_duplicados: ['Umbral de párrafos duplicados (Jaccard)', ''],
  rango_palabras: ['Rango de palabras por sección (JSON)', 'Pares [mínimo, máximo] por sección.'],
  max_chars_documento: ['Máximo de caracteres por documento', ''],
  dataset_csv_url: ['URL del dataset de sentencias', ''],
  cache_dir: ['Carpeta de caché', ''],
};

const OPCIONES = {
  plantilla_gen: [['A', 'Generación A'], ['B', 'Generación B']],
  'llm.proveedor': [['anthropic', 'Anthropic'], ['fake', 'Simulado (fake)']],
  'llm.effort': ['low', 'medium', 'high', 'xhigh', 'max'],
  'jev.modo': [['apagado', 'Apagado'], ['sombra', 'Sombra (solo alertas)'], ['relleno', 'Relleno (asigna roles sin rasgos)']],
};
const NOMBRES_MODELO = {
  'claude-sonnet-5-5': 'Sonnet 5.5',
  'claude-haiku-5-5': 'Haiku 5.5 (más barato)',
  'claude-opus-5-5': 'Opus 5.5 (más caro)',
};

const RESULTADOS = [['', 'Seleccione…'], ['CONFIRMAR', 'Confirmar'], ['REVOCAR', 'Revocar'], ['MODIFICAR', 'Modificar']];
const SUSTITUTIVAS = [
  ['', 'Seleccione…'],
  ['AMPARAR', 'Amparar'],
  ['NEGAR', 'Negar'],
  ['IMPROCEDENTE', 'Declarar improcedente'],
  ['CARENCIA_HECHO_SUPERADO', 'Carencia actual de objeto: hecho superado'],
  ['CARENCIA_DANO_CONSUMADO', 'Carencia actual de objeto: daño consumado'],
  ['CARENCIA_SOBREVINIENTE', 'Carencia actual de objeto: situación sobreviniente'],
];
const DISPOSICIONES_REPARO = [
  ['ACOGE', 'Acoge'],
  ['DESESTIMA', 'Desestima'],
  ['ACOGE_PARCIAL', 'Acoge parcialmente'],
  ['REFORMULA', 'Reformula'],
  ['ABSORBIDO', 'Absorbido por otro reparo'],
];
const DISPOSICIONES_DERECHO = [['AMPARA', 'Ampara'], ['NIEGA', 'Niega'], ['SIN_PRONUNCIAMIENTO', 'Sin pronunciamiento']];
const VERBOS = ['ORDENAR', 'PREVENIR', 'ADVERTIR'];
const UNIDADES = [['horas_habiles', 'horas hábiles'], ['dias_habiles', 'días hábiles'], ['horas', 'horas'], ['dias', 'días']];

const ROLES = [
  ['acta_reparto_1a', 'Acta de reparto (1.ª instancia)'],
  ['acta_reparto_2a', 'Acta de reparto (impugnación)'],
  ['escrito_tutela', 'Escrito de tutela'],
  ['auto_admisorio', 'Auto admisorio'],
  ['auto_vinculacion', 'Auto de vinculación'],
  ['contestacion', 'Contestación'],
  ['fallo_a_quo', 'Fallo de primera instancia'],
  ['impugnacion', 'Impugnación'],
  ['auto_concede_impugnacion', 'Auto que concede la impugnación'],
  ['notificacion', 'Notificación'],
  ['correo', 'Correo'],
  ['memorial', 'Memorial'],
  ['indice', 'Índice'],
  ['anexo', 'Anexo'],
  ['producto_despacho', 'Producto del despacho'],
  ['otro', 'Otro'],
];
const ETIQUETA_ROL = Object.fromEntries(ROLES);

const ETIQUETA_SENTIDO = { ampara: 'Ampara', niega: 'Niega', improcedente: 'Improcedente', carencia_actual_de_objeto: 'Carencia actual de objeto', otro: 'Otro' };
const ETIQUETA_IMPUGNANTE = { accionante: 'Accionante', accionada: 'Accionada', vinculada: 'Vinculada', otro: 'Otro' };
const PREGUNTAS_JEV = [
  ['sentido_fallo', 'Sentido del fallo, según su parte resolutiva', 'sentido', ETIQUETA_SENTIDO],
  ['sentido_clausula', 'Sentido, según la cláusula decision_a_quo', 'sentido', ETIQUETA_SENTIDO],
  ['rol_impugnante', 'Calidad de quien impugna', 'rol_impugnante', ETIQUETA_IMPUGNANTE],
];
const NODOS_JEV = { roles: 'roles de los documentos', metadatos: 'verificación de metadatos' };

const NUMERALES_FIJOS = {
  resultado: 'Resultado',
  sustitutiva: 'Decisión sustitutiva',
  prevenir: 'Prevenciones',
  desvincular: 'Desvinculaciones',
  compulsa: 'Compulsa de copias',
  notificar: 'Notificar',
  remitir: 'Remitir a la Corte Constitucional',
};

const ARCHIVOS_SALIDA = [
  [/ActaRepartoSegunda/, 'Acta de reparto de la impugnación'],
  [/AutoAsumeSegunda|AutoAsume\.docx$/, 'Auto que asume el conocimiento'],
  [/FalloSegunda|(^|\/)fallo\.docx$/, 'Fallo de segunda instancia'],
  [/FormatoCalificacion/, 'Formato Factor Calidad'],
  [/OficioRemiteCorteConstitucional/, 'Oficio de remisión a la Corte Constitucional'],
  [/NotificacionFalloPartes/, 'Correo: notificación del fallo a las partes'],
  [/EnvioFormatoCalidad/, 'Correo: envío del formato de calidad'],
  [/RemisionCompulsaCopias/, 'Correo: remisión de la compulsa de copias'],
  [/previo\.docx$/, 'Borrador previo (secciones I a V e informe de citas)'],
  [/informe_verificacion/, 'Informe de verificación'],
  [/declaracion_ia/, 'Declaración de uso de IA'],
  [/requerimiento/, 'Requerimiento de documentos faltantes'],
];
const GRUPOS_SALIDA = [
  ['02SegundaInstancia/C01Principal', 'Carpeta del expediente (02SegundaInstancia/C01Principal)'],
  ['por_radicar', 'Por radicar'],
  ['borradores_correo', 'Borradores de correo'],
  ['trabajo', 'Documentos de trabajo'],
];

const S = { caso: null, vista: 'casos', estado: null, job: null, timer: null, token: 0, paneles: new Set(), apiKey: false, jevKey: false };

function h(tag, attrs, ...hijos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k !== 'list' && k in el) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  if (!el.name && /^(input|select|textarea)$/.test(tag)) el.name = el.id || el.getAttribute('aria-label') || '';
  el.append(...hijos.flat(Infinity).filter((x) => x != null && x !== false));
  return el;
}

function selectDe(opciones, valor, attrs) {
  return h('select', attrs, opciones.map((o) => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return h('option', { value: v, selected: v === valor }, t);
  }));
}

const humanizar = (k) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const lineas = (texto) => texto.split('\n').map((l) => l.trim()).filter(Boolean);
const leer = (obj, ruta) => ruta.reduce((o, k) => (o == null ? undefined : o[k]), obj);
const esObjeto = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const esDict = (v) => esObjeto(v) && (Object.keys(v).length === 0 || Object.values(v).every(Array.isArray));
const urlSegura = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null);
const etiquetaNodo = (n) => NODOS[n] || humanizar(n);

function escribir(obj, ruta, valor) {
  leer(obj, ruta.slice(0, -1))[ruta.at(-1)] = valor;
}

function salidasDe(estado) {
  const s = estado?.salidas;
  return (Array.isArray(s) ? s : Object.keys(s || {})).map(String);
}

const urlSalida = (ruta) => `${rutaCaso('/salidas/')}${ruta.split('/').map(enc).join('/')}`;
const hoyISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

class ErrorApi extends Error {
  constructor(mensaje, status) {
    super(mensaje);
    this.status = status;
  }
}

function mensajeError(datos, respuesta) {
  const d = datos?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('\n');
  if (d?.errores) return d.errores.map((e) => `${e.campo}: ${e.mensaje}`).join('\n');
  return `Error ${respuesta.status} del servidor.`;
}

async function api(ruta, { metodo = 'GET', cuerpo, formData } = {}) {
  const opciones = { method: metodo };
  if (cuerpo !== undefined) {
    opciones.headers = { 'Content-Type': 'application/json' };
    opciones.body = JSON.stringify(cuerpo);
  } else if (formData) {
    opciones.body = formData;
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new ErrorApi('No hay conexión con el servidor.', 0);
  }
  const texto = await respuesta.text();
  let datos = null;
  try {
    datos = texto ? JSON.parse(texto) : null;
  } catch {
    datos = null;
  }
  if (!respuesta.ok) throw new ErrorApi(mensajeError(datos, respuesta), respuesta.status);
  return datos;
}

const rutaCaso = (sufijo = '') => `/api/casos/${enc(S.caso)}${sufijo}`;

function aviso(texto, tipo = 'info') {
  const el = h('div', { class: `aviso aviso-${tipo}`, role: tipo === 'error' ? 'alert' : 'status' },
    h('span', null, texto),
    h('button', { type: 'button', class: 'cerrar', 'aria-label': 'Cerrar', onclick: () => el.remove() }, '×'));
  $('#avisos').append(el);
  setTimeout(() => el.remove(), tipo === 'error' ? 9000 : 5000);
}

const chip = (clave, texto) => {
  const [etiqueta, clase] = ESTADOS[clave] || [clave, 'neutro'];
  return h('span', { class: `chip chip-${clase}` }, texto || etiqueta);
};

const tarjeta = (titulo, ...contenido) => h('section', { class: 'tarjeta' }, titulo ? h('h2', null, titulo) : null, ...contenido);
const parrafo = (texto, clase) => h('p', { class: clase }, texto);

function hashDe(vista, caso = S.caso) {
  return vista === 'casos' || !caso ? 'casos' : `${vista}/${enc(caso)}`;
}

function leerHash() {
  const [v, c] = location.hash.slice(1).split('/');
  const vista = VISTAS.some(([id]) => id === v) ? v : 'casos';
  let caso = null;
  try {
    caso = c ? decodeURIComponent(c) : null;
  } catch {
    caso = null;
  }
  return vista !== 'casos' && !caso ? { vista: 'casos', caso: null } : { vista, caso: vista === 'casos' ? null : caso };
}

function navegar(vista, caso = S.caso) {
  const destino = `#${hashDe(vista, caso)}`;
  if (location.hash === destino) render();
  else location.hash = destino;
}

function pintarNav() {
  $('#nav').replaceChildren(...VISTAS.map(([id, texto]) => {
    const bloqueada = id !== 'casos' && !S.caso;
    return h(bloqueada ? 'span' : 'a', {
      class: `tab${S.vista === id ? ' activa' : ''}`,
      href: bloqueada ? null : `#${hashDe(id)}`,
      'aria-current': S.vista === id ? 'page' : null,
      'aria-disabled': bloqueada ? 'true' : null,
    }, texto);
  }));
  pintarBarraCaso();
}

function pintarBarraCaso() {
  const barra = $('#barra-caso');
  barra.hidden = !S.caso;
  if (!S.caso) return;
  const corriendo = S.job && S.job.caso === S.caso && S.job.estado === 'corriendo';
  const estado = corriendo ? 'corriendo' : S.estado?.estado;
  barra.replaceChildren(...[h('span', null, 'Caso: ', h('strong', null, S.caso)), estado ? chip(estado) : null].filter(Boolean));
}

async function cargarEstado() {
  S.estado = await api(rutaCaso('/estado'));
  if (S.estado.job_activo && S.job?.id !== S.estado.job_activo) iniciarJob(S.estado.job_activo, S.caso, '', (job) => { if (job.caso === S.caso) render(); });
  pintarBarraCaso();
  return S.estado;
}

async function render() {
  const { vista, caso } = leerHash();
  if (caso !== S.caso) {
    S.caso = caso;
    S.estado = null;
  }
  S.vista = vista;
  pintarNav();
  const token = ++S.token;
  const contenedor = $('#vista');
  contenedor.replaceChildren(parrafo('Cargando…', 'vacio'));
  let contenido;
  try {
    contenido = await VISTA_FN[vista]();
  } catch (e) {
    contenido = h('div', { class: 'errores', role: 'alert' }, `No se pudo mostrar esta pantalla: ${e.message}`);
  }
  if (token !== S.token) return;
  contenedor.replaceChildren(contenido);
  document.title = `${VISTAS.find(([id]) => id === vista)[1]} · Tutela 2ª instancia`;
}

/* ---------- Jobs ---------- */

function iniciarJob(id, caso, cmd, despues) {
  clearTimeout(S.timer);
  S.job = { id, caso, cmd, estado: 'corriendo', log: [], resultado: null, error: null, despues };
  pintarBarraCaso();
  sondear();
}

async function sondear() {
  const job = S.job;
  if (!job) return;
  try {
    Object.assign(job, await api(`/api/jobs/${job.id}`));
  } catch (e) {
    if (S.job !== job) return;
    job.log.push(`No se pudo consultar el job: ${e.message}`);
    if (e.status === 404) job.estado = 'error';
  }
  if (S.job !== job) return;
  pintarPaneles();
  if (job.estado === 'corriendo') {
    S.timer = setTimeout(sondear, 2000);
    return;
  }
  if (job.caso === S.caso) {
    try {
      await cargarEstado();
    } catch {
      pintarBarraCaso();
    }
  }
  if (job.estado === 'error') aviso(job.error || 'La ejecución falló.', 'error');
  else aviso('La ejecución terminó.', 'ok');
  pintarPaneles();
  if (job.despues) job.despues(job);
}

function pintarPaneles() {
  for (const p of S.paneles) {
    if (p.el.isConnected) p.actualizar(S.job);
    else S.paneles.delete(p);
  }
}

function panelJob() {
  const titulo = h('strong');
  const estado = h('span');
  const error = h('div', { class: 'errores', role: 'alert', hidden: true });
  const log = h('pre', { class: 'log', tabindex: '0', 'aria-label': 'Registro de la ejecución' });
  const forzar = h('div', { class: 'acciones', hidden: true },
    h('button', {
      type: 'button',
      class: 'btn btn-sec',
      onclick: async () => {
        try {
          await lanzar('continuar', null, () => { if (leerHash().vista === 'ejecutar') render(); }, true);
          render();
        } catch (e) {
          aviso(e.message, 'error');
        }
      },
    }, 'Reintentar de todos modos'));
  const el = h('section', { class: 'tarjeta' }, h('div', { class: 'fila-titulo' }, titulo, estado), error, forzar, log);
  const actualizar = (job) => {
    const nombres = { nuevo: 'Procesar expediente', iniciar: 'Iniciar redacción', decidir: 'Aplicar decisión', continuar: 'Continuar ejecución' };
    titulo.textContent = nombres[job.cmd] || 'Ejecución';
    estado.replaceChildren(chip(job.estado === 'error' ? 'error' : job.estado === 'corriendo' ? 'corriendo' : 'terminado'));
    error.hidden = !job.error;
    error.textContent = job.error || '';
    forzar.hidden = !(job.estado === 'error' && job.resultado?.tope_intentos);
    const alFinal = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
    log.textContent = job.log.length ? job.log.join('\n') : 'Esperando el primer mensaje…';
    if (alFinal) log.scrollTop = log.scrollHeight;
  };
  S.paneles.add({ el, actualizar });
  actualizar(S.job);
  return el;
}

const AYUDA_DATOS_NUEVOS = 'Los datos que no constan en el expediente de 1.ª instancia (p. ej. consultas de esta instancia) escríbalos aquí para que el caso concreto pueda usarlos.';

async function lanzar(cmd, decision, despues, forzar) {
  const cuerpo = { cmd };
  if (decision) cuerpo.decision = decision;
  if (forzar) cuerpo.forzar = true;
  const { job_id: id } = await api(rutaCaso('/run'), { metodo: 'POST', cuerpo });
  iniciarJob(id, S.caso, cmd, despues);
}

const jobDeEsteCaso = () => (S.job && S.job.caso === S.caso ? S.job : null);

/* ---------- Casos ---------- */

function leerLote(lector) {
  return new Promise((ok, mal) => lector.readEntries(ok, mal));
}

function archivoDe(entrada) {
  return new Promise((ok, mal) => entrada.file(ok, mal));
}

async function recorrerEntrada(entrada, salida) {
  if (entrada.isFile) {
    const archivo = await archivoDe(entrada);
    salida.push({ archivo, ruta: entrada.fullPath.replace(/^\/+/, '') || archivo.name });
    return;
  }
  if (!entrada.isDirectory) return;
  const lector = entrada.createReader();
  for (;;) {
    const lote = await leerLote(lector);
    if (!lote.length) break;
    for (const hija of lote) await recorrerEntrada(hija, salida);
  }
}

async function archivosSoltados(dataTransfer) {
  const entradas = [...(dataTransfer.items || [])]
    .filter((i) => i.kind === 'file')
    .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
  const salida = [];
  if (entradas.length && entradas.every(Boolean)) {
    for (const e of entradas) await recorrerEntrada(e, salida);
  } else {
    for (const f of dataTransfer.files) salida.push({ archivo: f, ruta: f.webkitRelativePath || f.name });
  }
  return salida;
}

async function vistaCasos() {
  const casos = await api('/api/casos');
  let seleccion = [];
  const nombre = h('input', { type: 'text', id: 'nuevo-nombre', required: true, placeholder: 'Ej.: Tutela 2025-00123', autocomplete: 'off' });
  const carpeta = h('input', { type: 'file', id: 'nuevo-carpeta', webkitdirectory: true, multiple: true });
  const resumen = h('p', { class: 'ayuda', role: 'status', 'aria-live': 'polite' });
  const boton = h('button', { type: 'submit', class: 'btn btn-primario' }, 'Crear caso y revisar documentos');

  const fijar = (lista) => {
    seleccion = lista.filter((x) => !x.ruta.split('/').some((p) => p.startsWith('.')));
    const raiz = seleccion[0]?.ruta.split('/')[0] || '';
    const mb = seleccion.reduce((t, x) => t + x.archivo.size, 0) / 1048576;
    resumen.textContent = seleccion.length ? `${seleccion.length} archivos (${mb.toFixed(1)} MB) en «${raiz}».` : 'No se encontraron archivos.';
    if (!nombre.value.trim() && raiz && !/^0?1\s*Primera/i.test(raiz) && !/^C\d+/i.test(raiz)) nombre.value = raiz;
  };

  carpeta.addEventListener('change', () => {
    fijar([...carpeta.files].map((f) => ({ archivo: f, ruta: f.webkitRelativePath || f.name })));
  });

  const zona = h('div', { class: 'zona-soltar', tabindex: '0', role: 'group', 'aria-label': 'Zona para soltar la carpeta 01PrimeraInstancia' },
    h('strong', null, 'Arrastre aquí la carpeta 01PrimeraInstancia'),
    h('span', { class: 'ayuda' }, 'También se acepta la carpeta del caso; 02SegundaInstancia se ignora.'));
  zona.addEventListener('dragover', (ev) => { ev.preventDefault(); zona.classList.add('activa'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('activa'));
  zona.addEventListener('drop', async (ev) => {
    ev.preventDefault();
    zona.classList.remove('activa');
    resumen.textContent = 'Leyendo la carpeta…';
    try {
      fijar(await archivosSoltados(ev.dataTransfer));
    } catch (e) {
      resumen.textContent = '';
      aviso(`No se pudo leer la carpeta: ${e.message}`, 'error');
    }
  });

  const formulario = h('form', { class: 'pila', onsubmit: async (ev) => {
    ev.preventDefault();
    if (!seleccion.length) return aviso('Suelte o seleccione la carpeta con los insumos del expediente.', 'error');
    const datos = new FormData();
    datos.append('nombre', nombre.value.trim());
    for (const x of seleccion) datos.append('files', x.archivo, x.ruta);
    boton.disabled = true;
    boton.textContent = 'Subiendo…';
    try {
      const r = await api('/api/casos', { metodo: 'POST', formData: datos });
      aviso(`Caso «${r.id}» creado con ${r.n_insumos} archivos.`, 'ok');
      S.caso = r.id;
      S.estado = null;
      try {
        await lanzar('nuevo', null, () => { if (leerHash().vista === 'documentos') render(); });
      } catch (e) {
        aviso(e.message, 'error');
      }
      navegar('documentos', r.id);
    } catch (e) {
      aviso(e.message, 'error');
      boton.disabled = false;
      boton.textContent = 'Crear caso y revisar documentos';
    }
  } },
  campo('nuevo-nombre', 'Nombre del caso', nombre),
  zona,
  campo('nuevo-carpeta', 'O seleccione la carpeta', carpeta, 'Se conservan las subcarpetas.'),
  resumen,
  h('div', { class: 'acciones' }, boton));

  const filas = casos.map((c) => h('tr', null,
    h('td', null, h('strong', null, c.id)),
    h('td', null, chip(c.estado)),
    h('td', { class: 'num' }, String(c.n_insumos)),
    h('td', { class: 'num' }, h('a', { class: 'btn btn-sec', href: `#${c.estado === 'revision' || c.estado === 'incompleto' ? 'documentos' : 'ejecutar'}/${enc(c.id)}` }, 'Abrir'))));

  return h('div', { class: 'pila' },
    tarjeta('Nuevo caso', formulario),
    tarjeta('Casos', casos.length
      ? h('div', { class: 'tabla-scroll' }, h('table', { class: 'tabla' },
        h('thead', null, h('tr', null, h('th', null, 'Caso'), h('th', null, 'Estado'), h('th', { class: 'num' }, 'Insumos'), h('th'))),
        h('tbody', null, filas)))
      : parrafo('Aún no hay casos. Cree uno soltando la carpeta 01PrimeraInstancia.', 'vacio')));
}

function campo(id, etiqueta, control, ayuda, clase = '') {
  return h('div', { class: `campo ${clase}`.trim() },
    id ? h('label', { for: id }, etiqueta) : h('span', { class: 'etiqueta' }, etiqueta), control, ayuda ? parrafo(ayuda, 'ayuda') : null);
}

/* ---------- Jev ---------- */

function tonoConfianza(c, umbral) {
  if (typeof c !== 'number' || typeof umbral !== 'number' || c < umbral) return 'conf-0';
  const tercio = (1 - umbral) / 3;
  if (c >= umbral + 2 * tercio) return 'conf-3';
  return c >= umbral + tercio ? 'conf-2' : 'conf-1';
}

function pctJev(c, umbral) {
  const detalle = typeof c === 'number'
    ? `Confianza de Jev: ${c.toFixed(3)}.${typeof umbral === 'number' ? ` Umbral aplicado: ${umbral}.` : ''}`
    : null;
  return h('span', { class: `conf ${tonoConfianza(c, umbral)}`, title: detalle }, porcentaje(c));
}

function leyendaConfianza(umbral) {
  const base = 'Los porcentajes son la confianza de Jev.';
  if (typeof umbral !== 'number') return parrafo(base, 'ayuda');
  return parrafo(`${base} Desde el umbral aplicado (${Number((umbral * 100).toFixed(1))} %) se pintan en tres tonos de verde, más intensos cuanto mayor es la confianza; por debajo van en gris y Jev no actúa.`, 'ayuda');
}

function insigniaJev(rol, confianza, umbral, discrepa) {
  return h('div', { class: `ayuda jev-linea${discrepa ? ' jev-discrepa' : ''}` },
    `Jev: ${ETIQUETA_ROL[rol] || rol} · `, pctJev(confianza, umbral),
    discrepa ? h('span', { class: 'chip chip-alerta', title: 'Jev propone un rol distinto del vigente.' }, 'Discrepa') : null);
}

function comparacionJev(coincide) {
  if (coincide === true) return chip('ok', 'coincide');
  if (coincide === false) return chip('alerta', 'discrepa');
  return h('span', { class: 'chip chip-neutro', title: 'No se pudo comparar: la confianza de Jev quedó por debajo del umbral o falta el valor del modelo.' }, 'sin comparar');
}

function tarjetaJev(jm) {
  if (!esObjeto(jm)) return null;
  const umbral = jm.umbral;
  const preguntas = esObjeto(jm.preguntas) ? jm.preguntas : {};
  const coincide = esObjeto(jm.coincide) ? jm.coincide : {};
  const filas = PREGUNTAS_JEV.filter(([id]) => esObjeto(preguntas[id])).map(([id, texto, clave, etiquetas]) => {
    const { choice, confidence } = preguntas[id];
    return h('tr', null,
      h('td', null, texto),
      h('td', null, h('strong', null, Object.hasOwn(etiquetas, choice) ? etiquetas[choice] : String(choice))),
      h('td', { class: 'num' }, pctJev(confidence, umbral)),
      h('td', null, comparacionJev(coincide[clave])));
  });
  if (!filas.length) return null;
  return h('div', { class: 'pila-chica' },
    parrafo('Jev contesta preguntas cerradas sobre las mismas fuentes y se compara su respuesta con lo que escribió el modelo en la apertura. Solo genera alertas: no cambia el fallo.', 'ayuda'),
    leyendaConfianza(umbral),
    h('div', { class: 'tabla-scroll' }, h('table', { class: 'tabla' },
      h('caption', { class: 'solo-lectores' }, 'Respuestas de Jev sobre los metadatos de la apertura'),
      h('thead', null, h('tr', null, ['Pregunta', 'Respuesta de Jev', 'Confianza', 'Comparación'].map((t, i) => h('th', { scope: 'col', class: i === 2 ? 'num' : '' }, t)))),
      h('tbody', null, filas))),
    jm.modelo ? parrafo(`Modelo de Jev: ${jm.modelo}`, 'ayuda') : null);
}

/* ---------- Documentos ---------- */

const cuentaPaginas = (v) => (Array.isArray(v) ? v.length : Number(v) || 0);
const listaPaginas = (v) => (Array.isArray(v) ? v.join(', ') : '');

function enlacesAuto(estado) {
  const rutas = salidasDe(estado);
  const acta = rutas.find((r) => /ActaRepartoSegunda/.test(r));
  const auto = rutas.find((r) => /AutoAsumeSegunda/.test(r));
  const requerimiento = rutas.find((r) => /requerimiento/.test(r));
  return [
    ['Acta de reparto (001)', acta],
    ['Auto que asume el conocimiento', auto],
    ['Requerimiento de documentos faltantes', requerimiento],
  ].filter(([, ruta]) => ruta).map(([texto, ruta]) =>
    h('a', { class: 'btn btn-sec', href: urlSalida(ruta), download: ruta.split('/').pop() }, `Descargar: ${texto}`));
}

function tablaDocumentos(documentos, cambios, alCambiar, editable) {
  const filas = documentos.map((d) => {
    const selector = selectDe(ROLES, d.rol, { 'aria-label': `Rol de ${d.nombre}`, disabled: !editable });
    selector.addEventListener('change', () => {
      if (selector.value === d.rol && !d.ajeno) delete cambios[d.doc_id];
      else cambios[d.doc_id] = selector.value;
      alCambiar();
    });
    const conservar = d.ajeno && editable
      ? h('label', { class: 'ayuda' },
        h('input', { type: 'checkbox', 'aria-label': `No es ajeno: conservar ${d.nombre}`, onchange: (e) => {
          if (e.target.checked) cambios[d.doc_id] = d.rol;
          else if (selector.value === d.rol) delete cambios[d.doc_id];
          else cambios[d.doc_id] = selector.value;
          alCambiar();
        } }),
        ' No es ajeno: conservar')
      : null;
    const ciegas = cuentaPaginas(d.paginas_sin_texto);
    return h('tr', null,
      h('td', null, h('strong', null, d.nombre), d.ruta && d.ruta !== d.nombre ? h('div', { class: 'ayuda ruta' }, d.ruta) : null, h('div', { class: 'ayuda' }, d.doc_id)),
      h('td', null, selector,
        d.rol_origen === 'usuario' ? h('div', { class: 'ayuda' }, 'Asignado por usted') : null,
        d.rol_origen === 'jev'
          ? h('div', { class: 'ayuda' }, typeof d.jev_confianza === 'number' ? ['Sugerido por Jev · ', pctJev(d.jev_confianza, d.jev_umbral)] : 'Sugerido por Jev')
          : null,
        d.jev_rol && d.rol_origen !== 'jev' ? insigniaJev(d.jev_rol, d.jev_confianza, d.jev_umbral, d.jev_rol !== d.rol) : null,
        conservar),
      h('td', { class: 'evidencia' }, d.evidencia || '—'),
      h('td', { class: 'num' }, String(cuentaPaginas(d.paginas))),
      h('td', null, ciegas ? h('span', { class: 'chip chip-alerta' }, `${ciegas}${listaPaginas(d.paginas_sin_texto) ? `: ${listaPaginas(d.paginas_sin_texto)}` : ''}`) : '—'),
      h('td', null, h('div', { class: 'etiquetas' },
        d.ajeno ? h('span', { class: 'chip chip-mal' }, 'Ajeno') : null,
        d.ruido ? h('span', { class: 'chip chip-neutro' }, 'Ruido') : null,
        !d.ajeno && !d.ruido ? '—' : null)));
  });
  return h('div', { class: 'tabla-scroll' }, h('table', { class: 'tabla tabla-docs' },
    h('caption', { class: 'solo-lectores' }, 'Documentos del expediente y su clasificación'),
    h('thead', null, h('tr', null, ['Documento', 'Rol', 'Evidencia', 'Páginas', 'Sin texto', 'Estado'].map((t, i) => h('th', { scope: 'col', class: i === 3 ? 'num' : '' }, t)))),
    h('tbody', null, filas)));
}

async function vistaDocumentos() {
  const [estado, config] = await Promise.all([cargarEstado(), api(rutaCaso('/config'))]);
  const sinClave = config.llm?.proveedor === 'anthropic' && !S.apiKey;
  const job = jobDeEsteCaso();
  const corriendo = job?.estado === 'corriendo';
  const contenido = h('div', { class: 'pila' });
  if (corriendo || job?.estado === 'error') contenido.append(panelJob());
  const resumen = estado.ingesta || estado.resumen || {};
  const documentos = Array.isArray(resumen.documentos) ? resumen.documentos : null;
  const editable = ['revision', 'incompleto'].includes(estado.estado) && !corriendo;

  if (!documentos) {
    contenido.append(tarjeta('Documentos',
      parrafo(corriendo
        ? 'Procesando el expediente…'
        : 'Este caso aún no tiene la revisión de documentos. Procese el expediente en la pestaña Ejecutar.', 'vacio'),
      corriendo ? null : h('div', { class: 'acciones' }, h('a', { class: 'btn btn-sec', href: `#ejecutar/${enc(S.caso)}` }, 'Ir a ejecutar'))));
    return contenido;
  }

  const cambios = {};
  const autoInicial = { fecha: resumen.auto?.fecha || '', fecha_reparto: resumen.auto?.fecha_reparto || '', accionante: resumen.auto?.accionante || '', accionada: resumen.auto?.accionada || '' };
  const fecha = h('input', { type: 'date', id: 'auto-fecha', value: autoInicial.fecha });
  const fechaReparto = h('input', { type: 'date', id: 'auto-fecha-reparto', value: autoInicial.fecha_reparto });
  const accionante = h('input', { type: 'text', id: 'auto-accionante', value: autoInicial.accionante });
  const accionada = h('input', { type: 'text', id: 'auto-accionada', value: autoInicial.accionada });
  const guardar = h('button', { type: 'button', class: 'btn btn-primario', disabled: true }, 'Guardar cambios');
  const iniciarBtn = h('button', { type: 'button', class: 'btn btn-primario', disabled: !editable || estado.estado !== 'revision' || sinClave, title: sinClave ? 'Falta la API key' : null }, 'Iniciar redacción');
  const nota = h('p', { class: 'ayuda', role: 'status', 'aria-live': 'polite' });
  const errores = h('div', { class: 'errores', role: 'alert', hidden: true });

  const cambiosAuto = () => {
    const c = {};
    for (const [k, el] of [['fecha', fecha], ['fecha_reparto', fechaReparto], ['accionante', accionante], ['accionada', accionada]]) {
      const v = el.value.trim();
      if (v !== autoInicial[k]) c[k] = v || null;
    }
    return c;
  };
  const sucio = () => Object.keys(cambios).length > 0 || Object.keys(cambiosAuto()).length > 0;
  const refrescar = () => {
    guardar.disabled = !editable || !sucio();
    iniciarBtn.disabled = !editable || estado.estado !== 'revision' || sinClave || sucio();
    nota.textContent = sucio() ? 'Hay cambios sin guardar. Guárdelos antes de iniciar la redacción.' : '';
  };
  for (const el of [fecha, fechaReparto, accionante, accionada]) {
    el.disabled = !editable;
    el.addEventListener('input', refrescar);
  }

  guardar.addEventListener('click', async () => {
    guardar.disabled = true;
    errores.hidden = true;
    const cuerpo = {};
    if (Object.keys(cambios).length) cuerpo.roles = { ...cambios };
    const a = cambiosAuto();
    if (Object.keys(a).length) cuerpo.auto = a;
    try {
      S.estado = await api(rutaCaso('/revision'), { metodo: 'PUT', cuerpo });
      pintarBarraCaso();
      aviso('Cambios guardados.', 'ok');
      render();
    } catch (e) {
      errores.hidden = false;
      errores.textContent = e.message;
      aviso(e.message, 'error');
      refrescar();
    }
  });

  iniciarBtn.addEventListener('click', async () => {
    iniciarBtn.disabled = true;
    try {
      await lanzar('iniciar', null, () => { if (['documentos', 'ejecutar'].includes(leerHash().vista)) render(); });
      navegar('ejecutar');
    } catch (e) {
      errores.hidden = false;
      errores.textContent = e.message;
      refrescar();
    }
  });

  const faltantes = Array.isArray(resumen.faltantes) ? resumen.faltantes : [];
  const esperados = Array.isArray(resumen.esperados_faltantes) ? resumen.esperados_faltantes : [];
  const alertas = Array.isArray(resumen.alertas) ? resumen.alertas : [];
  const nombreRol = (r) => ETIQUETA_ROL[r] || r;
  const umbralJev = documentos.find((d) => typeof d.jev_umbral === 'number')?.jev_umbral;

  contenido.append(
    tarjeta('Estado de la revisión',
      h('div', { class: 'fila-titulo' }, chip(estado.estado), h('span', { class: 'ayuda' }, `${documentos.length} documentos`)),
      faltantes.length
        ? h('div', { class: 'errores', role: 'alert' }, h('strong', null, 'Faltan piezas obligatorias'), h('ul', null, faltantes.map((f) => h('li', null, nombreRol(f)))))
        : parrafo('Están las piezas obligatorias.', 'ayuda'),
      esperados.length
        ? h('div', { class: 'ambar' }, h('strong', null, 'No se encontró (se continúa sin ello)'), h('ul', null, esperados.map((f) => h('li', null, nombreRol(f)))))
        : null,
      alertas.length
        ? h('div', { class: 'pila-chica' }, h('strong', null, 'Alertas'), h('ul', null, alertas.map((x) => h('li', null, String(x)))))
        : null),
    tarjeta('Documentos',
      editable ? null : parrafo('La redacción ya inició; la clasificación no se puede cambiar.', 'ayuda'),
      documentos.some((d) => d.jev_rol) ? leyendaConfianza(umbralJev) : null,
      tablaDocumentos(documentos, cambios, refrescar, editable)),
    tarjeta('Auto que asume el conocimiento',
      h('div', { class: 'rejilla' },
        campo('auto-fecha-reparto', 'Fecha de reparto (segunda instancia)', fechaReparto),
        campo('auto-fecha', 'Fecha del auto', fecha),
        campo('auto-accionante', 'Accionante', accionante),
        campo('auto-accionada', 'Accionada', accionada)),
      parrafo('Si deja vacía la fecha del auto, se propone el siguiente día hábil después del reparto (sin fines de semana ni festivos) al guardar.', 'ayuda'),
      enlacesAuto(estado).length ? h('div', { class: 'acciones' }, enlacesAuto(estado)) : null),
    errores,
    ...(sinClave ? [h('div', { class: 'errores', role: 'alert' }, 'No hay API key configurada y el proveedor del caso es Anthropic. Ingrésela arriba o cambie el proveedor a Simulado en la configuración para iniciar la redacción.')] : []),
    nota,
    h('div', { class: 'acciones barra-fija' }, guardar, iniciarBtn));
  return contenido;
}

/* ---------- Configuración ---------- */

let cacheDefaults = null;

async function cargarDefaults() {
  if (!cacheDefaults) {
    const [config, prompts] = await Promise.all([api('/api/config-default'), api('/api/prompts-default')]);
    cacheDefaults = { config, prompts };
  }
  return cacheDefaults;
}

function controlConfig(ruta, defecto, valor, registro) {
  const clave = ruta.join('.');
  const id = `cfg-${ruta.join('-')}`;
  let el;
  let tipo = 'texto';
  if (OPCIONES[clave]) {
    el = selectDe(OPCIONES[clave], valor, { id });
  } else if (typeof defecto === 'boolean') {
    el = h('input', { type: 'checkbox', id, checked: !!valor });
    tipo = 'bool';
  } else if (typeof defecto === 'number') {
    el = h('input', { type: 'number', step: 'any', id, value: valor });
    tipo = 'numero';
  } else if (typeof defecto === 'string') {
    el = h('input', { type: 'text', id, value: valor });
  } else if (Array.isArray(defecto) && defecto.length && defecto.every((x) => typeof x === 'string')) {
    el = h('textarea', { id, rows: Math.max(3, defecto.length + 1), value: (Array.isArray(valor) ? valor : defecto).join('\n') });
    tipo = 'lineas';
  } else {
    el = h('textarea', { id, rows: 6, class: 'codigo', value: JSON.stringify(valor, null, 2) });
    tipo = 'json';
  }
  registro.push({ ruta, tipo, el });
  return { el, tipo };
}

function panelClaveJev() {
  const estado = h('span', { role: 'status' });
  const pintar = () => {
    estado.className = `chip chip-${S.jevKey ? 'ok' : 'alerta'}`;
    estado.textContent = S.jevKey ? 'Clave de Jev configurada' : 'Sin clave de Jev';
  };
  const entrada = h('input', { type: 'password', id: 'jev-key', placeholder: 'Clave de Jev', autocomplete: 'off' });
  pintar();
  return h('form', { class: 'clave-jev', autocomplete: 'off', onsubmit: async (ev) => {
    ev.preventDefault();
    const key = entrada.value.trim();
    if (!key) return;
    try {
      const r = await api('/api/jev-key', { metodo: 'POST', cuerpo: { key } });
      S.jevKey = r.jev_key;
      entrada.value = '';
      pintar();
      aviso('Clave de Jev guardada solo en la memoria del servidor.', 'ok');
    } catch (e) {
      aviso(e.message, 'error');
    }
  } },
  campo('jev-key', 'Clave de Jev', entrada, 'Se guarda solo en la memoria del proceso: no se escribe a disco y se pierde al reiniciar el servidor. Sin clave no sale ninguna petición, aunque el modo no sea Apagado.'),
  h('div', { class: 'acciones' }, h('button', { type: 'submit', class: 'btn btn-sec' }, 'Usar'), estado));
}

function camposConfig(defecto, actual, ruta, registro) {
  const nodos = [];
  for (const [clave, valorDef] of Object.entries(defecto)) {
    const r = [...ruta, clave];
    const id = r.join('.');
    if (id === 'prompts_override' || id === 'llm.modelo' || id === 'jev.modelo') continue;
    const valor = actual?.[clave] ?? valorDef;
    const [etiqueta, ayuda] = ETIQUETAS[id] || [humanizar(clave), ''];
    if (esObjeto(valorDef) && !esDict(valorDef)) {
      nodos.push(h('fieldset', { class: 'grupo' }, h('legend', null, etiqueta), id === 'jev' ? panelClaveJev() : null, camposConfig(valorDef, valor, r, registro)));
      continue;
    }
    const { el, tipo } = controlConfig(r, valorDef, valor, registro);
    if (tipo === 'bool') {
      nodos.push(h('div', { class: 'campo campo-check' }, el, h('label', { for: el.id }, etiqueta)));
    } else {
      nodos.push(campo(el.id, etiqueta, el, ayuda, tipo === 'json' || tipo === 'lineas' ? 'ancho' : ''));
    }
  }
  return h('div', { class: 'rejilla' }, nodos);
}

function recogerConfig(registro, base) {
  const cfg = structuredClone(base);
  const errores = [];
  for (const { ruta, tipo, el } of registro) {
    el.classList.remove('invalido');
    const nombre = ETIQUETAS[ruta.join('.')]?.[0] || ruta.join('.');
    let valor;
    if (tipo === 'bool') {
      valor = el.checked;
    } else if (tipo === 'numero') {
      valor = el.value.trim() === '' ? NaN : Number(el.value);
      if (Number.isNaN(valor)) {
        errores.push(`${nombre}: debe ser un número.`);
        el.classList.add('invalido');
        continue;
      }
    } else if (tipo === 'lineas') {
      valor = lineas(el.value);
    } else if (tipo === 'json') {
      try {
        valor = JSON.parse(el.value);
      } catch (e) {
        errores.push(`${nombre}: JSON inválido (${e.message}).`);
        el.classList.add('invalido');
        continue;
      }
    } else {
      valor = el.value;
    }
    escribir(cfg, ruta, valor);
  }
  return { cfg, errores };
}

function panelPrompts(prompts, override, registro) {
  return h('div', { class: 'pila' }, Object.entries(prompts).map(([nodo, original]) => {
    const area = h('textarea', { id: `prompt-${nodo}`, class: 'codigo prompt', rows: 16, value: override?.[nodo] ?? original });
    const marca = h('span', { class: 'chip chip-info' }, 'Modificado');
    const actualizar = () => { marca.hidden = area.value === original; };
    area.addEventListener('input', actualizar);
    actualizar();
    registro[nodo] = { area, original };
    return h('section', { class: 'tarjeta' },
      h('div', { class: 'fila-titulo' },
        h('h3', null, h('label', { for: area.id }, etiquetaNodo(nodo))),
        marca,
        h('button', { type: 'button', class: 'btn btn-sec', onclick: () => { area.value = original; actualizar(); } }, 'Restaurar')),
      area);
  }));
}

async function vistaConfig() {
  const [{ config: defecto, prompts }, actual] = await Promise.all([cargarDefaults(), api(rutaCaso('/config'))]);
  const registro = [];
  const registroPrompts = {};
  const panelParametros = h('div', { class: 'pila' }, camposConfig(defecto, actual, [], registro));
  const panelPromptsEl = panelPrompts(prompts, actual.prompts_override, registroPrompts);
  panelPromptsEl.hidden = true;
  const errores = h('div', { class: 'errores', role: 'alert', hidden: true });

  const pestanas = [['Parámetros', panelParametros], ['Prompts', panelPromptsEl]].map(([texto, panel], i) => {
    const boton = h('button', { type: 'button', class: `subtab${i === 0 ? ' activa' : ''}`, role: 'tab', 'aria-selected': String(i === 0) }, texto);
    boton.addEventListener('click', () => {
      for (const [b, p] of pestanas) {
        b.classList.toggle('activa', b === boton);
        b.setAttribute('aria-selected', String(b === boton));
        p.hidden = p !== panel;
      }
    });
    return [boton, panel];
  });

  const guardar = h('button', { type: 'button', class: 'btn btn-primario', onclick: async () => {
    const { cfg, errores: fallos } = recogerConfig(registro, actual);
    cfg.prompts_override = {};
    for (const [nodo, { area, original }] of Object.entries(registroPrompts)) {
      if (area.value !== original) cfg.prompts_override[nodo] = area.value;
    }
    errores.hidden = fallos.length === 0;
    errores.textContent = fallos.join('\n');
    if (fallos.length) return;
    try {
      Object.assign(actual, await api(rutaCaso('/config'), { metodo: 'PUT', cuerpo: cfg }));
      aviso('Configuración guardada.', 'ok');
    } catch (e) {
      errores.hidden = false;
      errores.textContent = e.message;
    }
  } }, 'Guardar configuración');

  return h('div', { class: 'pila' },
    h('div', { class: 'subtabs', role: 'tablist' }, pestanas.map(([b]) => b)),
    errores,
    ...pestanas.map(([, p]) => p),
    h('div', { class: 'acciones barra-fija' }, guardar, h('a', { class: 'btn btn-sec', href: `#ejecutar/${enc(S.caso)}` }, 'Ir a ejecutar')));
}

/* ---------- Ejecutar ---------- */

async function vistaEjecutar() {
  const [estado, config] = await Promise.all([cargarEstado(), api(rutaCaso('/config'))]);
  const job = jobDeEsteCaso();
  const corriendo = job?.estado === 'corriendo';
  const despues = () => { if (leerHash().vista === 'ejecutar') render(); };

  const iniciar = async (cmd) => {
    if (cmd === 'nuevo' && estado.estado !== 'sin_iniciar'
      && !confirm('Procesar el expediente de nuevo vuelve a leer los documentos y descarta el borrador (apertura y consideraciones), la decisión registrada y los documentos generados. Se conservan los roles que corrigió y los datos del auto que editó. ¿Desea continuar?')) return;
    try {
      await lanzar(cmd, null, despues);
      render();
    } catch (e) {
      aviso(e.message, 'error');
    }
  };

  const sinClave = config.llm?.proveedor === 'anthropic' && !S.apiKey;
  const proximo = [];
  if (!corriendo) {
    if (estado.estado === 'revision') {
      proximo.push(parrafo('El expediente está procesado. Revise la clasificación de los documentos antes de iniciar la redacción.'),
        h('div', { class: 'acciones' }, h('a', { class: 'btn btn-primario', href: `#documentos/${enc(S.caso)}` }, 'Revisar documentos')));
    } else if (estado.estado === 'esperando_decision') {
      proximo.push(parrafo('El borrador previo está listo.'),
        h('div', { class: 'acciones' },
          h('a', { class: 'btn btn-primario', href: `#revision/${enc(S.caso)}` }, 'Revisar borrador'),
          h('a', { class: 'btn btn-sec', href: `#decision/${enc(S.caso)}` }, 'Ir a la decisión')));
    } else if (estado.estado === 'terminado') {
      proximo.push(parrafo('El fallo ya fue generado.'),
        h('div', { class: 'acciones' }, h('a', { class: 'btn btn-primario', href: `#resultado/${enc(S.caso)}` }, 'Ver resultado')));
    } else if (estado.estado === 'incompleto') {
      const faltantes = estado.resumen?.faltantes;
      proximo.push(parrafo('Faltan piezas del expediente. Se generó un requerimiento con la lista.'),
        Array.isArray(faltantes) && faltantes.length ? h('ul', null, faltantes.map((f) => h('li', null, ETIQUETA_ROL[f] || String(f)))) : null,
        h('div', { class: 'acciones' },
          h('a', { class: 'btn btn-primario', href: `#documentos/${enc(S.caso)}` }, 'Revisar documentos'),
          h('a', { class: 'btn btn-sec', href: `#resultado/${enc(S.caso)}` }, 'Ver documentos generados')));
    } else if (estado.estado === 'error' && estado.error) {
      proximo.push(h('div', { class: 'errores', role: 'alert' }, estado.error));
    }
  }

  return h('div', { class: 'pila' },
    tarjeta('Procesar expediente y redactar',
      parrafo('Procesar lee y clasifica los documentos, y genera el auto que asume. Iniciar redacción, ya revisados los documentos, redacta apertura y consideraciones, verifica las citas y se detiene antes del caso concreto para esperar su decisión.', 'ayuda'),
      sinClave ? h('div', { class: 'errores', role: 'alert' }, 'No hay API key configurada y el proveedor del caso es Anthropic. Ingrésela arriba o cambie el proveedor a Simulado en la configuración.') : null,
      h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'btn btn-sec', disabled: corriendo || estado.estado === 'error', title: estado.estado === 'error' ? 'El caso quedó a medias: use Continuar ejecución para no perder el trabajo' : null, onclick: () => iniciar('nuevo') }, 'Procesar expediente'),
        h('button', { type: 'button', class: 'btn btn-primario', disabled: corriendo || estado.estado !== 'revision', title: 'Disponible tras la revisión de documentos', onclick: () => iniciar('iniciar') }, 'Iniciar redacción'),
        h('button', { type: 'button', class: `btn ${estado.estado === 'error' ? 'btn-primario' : 'btn-sec'}`, disabled: corriendo, title: 'Reanuda un hilo interrumpido', onclick: () => iniciar('continuar') }, 'Continuar ejecución'))),
    job ? panelJob() : null,
    proximo.length ? tarjeta('Siguiente paso', ...proximo) : null);
}

/* ---------- Revisión ---------- */

function renderValor(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'string') return h('div', { class: 'texto' }, v.split(/\n{2,}/).map((p) => parrafo(p)));
  if (typeof v === 'boolean') return h('span', null, v ? 'Sí' : 'No');
  if (typeof v !== 'object') return h('span', null, String(v));
  if (Array.isArray(v)) {
    if (!v.length) return null;
    if (v.every((x) => typeof x !== 'object')) return h('ul', null, v.map((x) => h('li', null, String(x))));
    return h('div', { class: 'pila-chica' }, v.map((x) => h('div', { class: 'item' }, renderValor(x))));
  }
  const pares = Object.entries(v).flatMap(([k, x]) => {
    const contenido = renderValor(x);
    return contenido ? [h('dt', null, humanizar(k)), h('dd', null, contenido)] : [];
  });
  return pares.length ? h('dl', { class: 'datos' }, pares) : null;
}

const porcentaje = (c) => (typeof c === 'number' ? `${Math.round(c * 100)} %` : '—');

function tablaCitas(citas) {
  const cuenta = (e) => citas.filter((c) => c.estado === e).length;
  const filas = citas.map((c) => {
    const url = urlSegura(c.url);
    return h('tr', null,
      h('td', null, h('strong', null, c.sentencia_original || c.id),
        c.sentencia_norm ? h('div', { class: 'ayuda' }, c.sentencia_norm) : null,
        c.texto_citado ? h('details', null, h('summary', null, 'Ver fragmento citado'), parrafo(c.texto_citado, 'cita')) : null),
      h('td', null, chip(c.estado)),
      h('td', { class: 'num' }, porcentaje(c.cobertura)),
      h('td', null, c.mp_dataset || '—', c.fecha_dataset ? h('div', { class: 'ayuda' }, c.fecha_dataset) : null),
      h('td', null, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, 'Relatoría') : '—'),
      h('td', null, c.motivos?.length ? h('ul', null, c.motivos.map((m) => h('li', null, m))) : '—'));
  });
  return h('div', null,
    parrafo(`${cuenta('ok')} ok · ${cuenta('alerta')} con alerta · ${cuenta('rechazada')} rechazadas`, 'ayuda'),
    h('div', { class: 'tabla-scroll' }, h('table', { class: 'tabla' },
      h('thead', null, h('tr', null, ['Sentencia', 'Estado', 'Cobertura', 'M.P. (dataset)', 'Enlace', 'Motivos'].map((t, i) => h('th', { class: i === 2 ? 'num' : '' }, t)))),
      h('tbody', null, filas))));
}

function tablaBitacora(entradas) {
  const nodo = (e) => (e.proveedor === 'jev' ? `Jev: ${NODOS_JEV[e.nodo] || humanizar(e.nodo || '')}` : etiquetaNodo(e.nodo || ''));
  const filas = entradas.map((e) => h('tr', null,
    h('td', null, nodo(e)),
    h('td', { class: 'num' }, String(e.intento ?? '')),
    h('td', null, e.modelo_efectivo || e.modelo_pedido || '—'),
    h('td', { class: 'num' }, e.tokens_entrada ?? '—'),
    h('td', { class: 'num' }, e.tokens_salida ?? '—'),
    h('td', null, e.fecha || '—'),
    h('td', null, e.error || '')));
  return h('div', { class: 'tabla-scroll' }, h('table', { class: 'tabla' },
    h('thead', null, h('tr', null, ['Nodo', 'Intento', 'Modelo', 'Tokens entrada', 'Tokens salida', 'Fecha', 'Error'].map((t) => h('th', null, t)))),
    h('tbody', null, filas)));
}

function buscarCitas(estado) {
  for (const origen of [estado.resumen, estado.payload]) {
    for (const clave of ['citas', 'citas_verificadas', 'informe_citas']) {
      if (Array.isArray(origen?.[clave])) return { clave, citas: origen[clave], origen };
    }
  }
  return null;
}

const SECCIONES = {
  apertura: 'Apertura',
  jev_metadatos: 'Verificación de Jev',
  consideraciones: 'Consideraciones',
  citas: 'Citas verificadas',
  caso_concreto: 'Caso concreto',
  decision: 'Decisión registrada',
  errores: 'Errores bloqueantes vigentes',
  alertas: 'Alertas por nodo',
  metadatos: 'Metadatos',
  bitacora: 'Bitácora de llamadas a la IA',
};
const CLAVES_CITAS = ['citas', 'citas_verificadas', 'informe_citas'];
const ORDEN_RESUMEN = ['apertura', 'jev_metadatos', 'consideraciones', 'citas', 'caso_concreto', 'decision', 'errores', 'alertas'];
const RESUMEN_APARTE = ['metadatos', 'bitacora', 'salidas', ...CLAVES_CITAS];

async function vistaRevision() {
  const estado = await cargarEstado();
  const resumen = estado.resumen || {};
  const citas = buscarCitas(estado)?.citas;
  const bitacora = resumen.bitacora;
  const piezas = [
    ...ORDEN_RESUMEN.map((k) => [
      SECCIONES[k],
      k === 'citas' ? (citas?.length ? tablaCitas(citas) : null)
        : k === 'jev_metadatos' ? tarjetaJev(resumen.jev_metadatos)
          : renderValor(resumen[k]),
      true,
    ]),
    ...Object.keys(resumen)
      .filter((k) => !ORDEN_RESUMEN.includes(k) && !RESUMEN_APARTE.includes(k))
      .map((k) => [humanizar(k), renderValor(resumen[k]), true]),
    [SECCIONES.metadatos, renderValor(resumen.metadatos), false],
    [SECCIONES.bitacora, Array.isArray(bitacora) && typeof bitacora[0] === 'object' ? tablaBitacora(bitacora) : renderValor(bitacora), false],
  ].filter(([, contenido]) => contenido);

  return h('div', { class: 'pila' },
    tarjeta('Estado del borrador',
      h('div', { class: 'fila-titulo' }, chip(estado.estado), estado.error ? h('span', { class: 'ayuda' }, estado.error) : null),
      piezas.length ? null : parrafo('Aún no hay un borrador para revisar. Genérelo en la pestaña Ejecutar.', 'vacio'),
      estado.estado === 'esperando_decision'
        ? h('div', { class: 'acciones' }, h('a', { class: 'btn btn-primario', href: `#decision/${enc(S.caso)}` }, 'Ir a la decisión'))
        : null),
    ...piezas.map(([titulo, contenido, abierta]) =>
      h('details', { class: 'tarjeta acordeon', open: abierta }, h('summary', null, h('h2', null, titulo)), contenido)));
}

/* ---------- Decisión ---------- */

function filaOrden(alQuitar) {
  const destinatario = h('input', { type: 'text', 'aria-label': 'Destinatario', placeholder: 'Entidad o persona a quien se ordena' });
  const conducta = h('textarea', { rows: 3, 'aria-label': 'Conducta', placeholder: 'Qué debe hacer' });
  const plazo = h('input', { type: 'number', min: '1', value: 48, 'aria-label': 'Plazo' });
  const unidad = selectDe(UNIDADES, 'horas_habiles', { 'aria-label': 'Unidad del plazo' });
  const verbo = selectDe(VERBOS, 'ORDENAR', { 'aria-label': 'Verbo' });
  const condicion = h('input', { type: 'text', 'aria-label': 'Condición', placeholder: 'Opcional' });
  const sufijo = Math.random().toString(36).slice(2);
  const via = h('input', { type: 'checkbox', checked: true, id: `via-${sufijo}` });
  const mismo = h('input', { type: 'checkbox', id: `mismo-${sufijo}` });
  const sincronizarPlazo = () => {
    plazo.disabled = mismo.checked;
    unidad.disabled = mismo.checked;
  };
  mismo.addEventListener('change', sincronizarPlazo);
  const el = h('div', { class: 'orden' },
    h('div', { class: 'rejilla' },
      campo('', 'Destinatario', destinatario, 'Incluya el artículo: «el BANCO X», «la EPS Y».'),
      campo('', 'Plazo', h('div', { class: 'par' }, plazo, unidad)),
      h('div', { class: 'campo campo-check' }, mismo, h('label', { for: mismo.id }, 'Mismo término de la orden anterior'))),
    campo('', 'Conducta', conducta),
    h('details', null, h('summary', null, 'Más opciones'),
      h('div', { class: 'rejilla' },
        campo('', 'Verbo', verbo),
        campo('', 'Condición', condicion),
        h('div', { class: 'campo campo-check' }, via, h('label', { for: via.id }, 'A través de su representante legal')))),
    h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'btn btn-sec', onclick: alQuitar }, 'Quitar orden')));
  return {
    el,
    etiqueta: () => destinatario.value.trim(),
    leer: () => ({
      mismo_termino: mismo.checked,
      verbo: verbo.value,
      destinatario: destinatario.value.trim(),
      via_representante: via.checked,
      conducta: conducta.value.trim(),
      plazo: { n: Number(plazo.value), unidad: unidad.value },
      condicion: condicion.value.trim(),
    }),
  };
}

function formularioDecision(estado, config, bloqueado) {
  const payload = estado.payload || {};
  const reparos = Array.isArray(payload.reparos) ? payload.reparos : [];
  const derechosIniciales = payload.derechos_invocados ?? payload.metadatos?.derechos_invocados ?? [];

  const errores = h('div', { class: 'errores', role: 'alert', hidden: true });
  const mostrarErrores = (lista) => {
    errores.hidden = !lista.length;
    errores.replaceChildren(...lista.map((e) => h('div', null, e)));
    if (lista.length) errores.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  mostrarErrores(Array.isArray(payload.errores) ? payload.errores : []);

  const resultado = selectDe(RESULTADOS, '', { id: 'dec-resultado', required: true });
  const sustitutiva = selectDe(SUSTITUTIVAS, '', { id: 'dec-sustitutiva' });
  const eje = h('textarea', { id: 'dec-eje', rows: 5, required: true, placeholder: 'De 2 a 5 líneas: el porqué de la decisión.' });
  const decididoPor = h('input', { type: 'text', id: 'dec-por', value: config.despacho?.juez || '' });

  const filasReparo = reparos.map((r) => {
    const disposicion = selectDe(DISPOSICIONES_REPARO, 'ACOGE', { 'aria-label': `Disposición del reparo ${r.id}` });
    const nota = h('input', { type: 'text', placeholder: 'Nota (opcional)', 'aria-label': `Nota del reparo ${r.id}` });
    const ayuda = parrafo(AYUDA_DATOS_NUEVOS, 'ayuda');
    return {
      id: r.id,
      leer: () => ({ reparo_id: r.id, disposicion: disposicion.value, nota: nota.value.trim() }),
      el: h('div', { class: 'reparo' },
        h('div', null, h('strong', null, r.id), r.sintesis ? parrafo(r.sintesis, 'texto-reparo') : null),
        h('div', { class: 'par' }, disposicion, nota),
        ayuda),
    };
  });

  const filasDerecho = [];
  const listaDerechos = h('div', { class: 'pila-chica' });
  const agregarDerecho = (nombre) => {
    const disposicion = selectDe(DISPOSICIONES_DERECHO, 'AMPARA', { 'aria-label': `Disposición del derecho ${nombre}` });
    const fila = {
      leer: () => ({ derecho: nombre, disposicion: disposicion.value }),
      el: h('div', { class: 'reparo' }, h('strong', null, nombre), disposicion),
    };
    filasDerecho.push(fila);
    listaDerechos.append(fila.el);
  };
  derechosIniciales.forEach(agregarDerecho);
  const nuevoDerecho = h('input', { type: 'text', placeholder: 'Otro derecho', 'aria-label': 'Otro derecho' });
  const botonDerecho = h('button', { type: 'button', class: 'btn btn-sec', onclick: () => {
    const t = nuevoDerecho.value.trim();
    if (t) { agregarDerecho(t); nuevoDerecho.value = ''; }
  } }, 'Agregar derecho');

  const derechosAplican = () => sustitutiva.value === 'AMPARAR' || sustitutiva.value === 'NEGAR';
  const bloqueDerechos = h('div', { class: 'pila-chica', hidden: true },
    h('h3', null, 'Derechos invocados'),
    parrafo('Solo se piden cuando la decisión sustitutiva es Amparar o Negar.', 'ayuda'),
    derechosIniciales.length ? null : parrafo('No se recibieron derechos extraídos.', 'vacio'),
    listaDerechos,
    h('div', { class: 'par' }, nuevoDerecho, botonDerecho));

  const filasOrden = [];
  const listaOrdenes = h('div', { class: 'pila' });
  const agregarOrden = () => {
    const fila = filaOrden(() => {
      filasOrden.splice(filasOrden.indexOf(fila), 1);
      fila.el.remove();
      refrescarNumerales();
    });
    filasOrden.push(fila);
    listaOrdenes.append(fila.el);
    refrescarNumerales();
  };
  const bloqueOrdenes = h('fieldset', { class: 'grupo', hidden: true },
    h('legend', null, '3. Órdenes'),
    parrafo('Solo se piden cuando se ampara.', 'ayuda'),
    listaOrdenes,
    h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'btn btn-sec', onclick: agregarOrden }, 'Agregar orden')));
  sustitutiva.addEventListener('change', () => {
    bloqueDerechos.hidden = !derechosAplican();
    bloqueOrdenes.hidden = sustitutiva.value !== 'AMPARAR';
    if (!bloqueOrdenes.hidden && !filasOrden.length) agregarOrden();
    refrescarNumerales();
  });

  const desvincular = h('textarea', { id: 'dec-desvincular', rows: 3, placeholder: 'Una entidad por línea' });
  const prevenir = h('textarea', { id: 'dec-prevenir', rows: 3, placeholder: 'Un destinatario por línea' });
  const notificar = h('input', { type: 'checkbox', id: 'dec-notificar', checked: true });
  const remitir = h('input', { type: 'checkbox', id: 'dec-remitir', checked: true });
  const compulsar = h('input', { type: 'checkbox', id: 'dec-compulsar' });
  const organo = h('input', { type: 'text', id: 'dec-organo', placeholder: 'Por defecto: Comisión Seccional de Disciplina Judicial de Antioquia' });
  const respectoDe = h('input', { type: 'text', id: 'dec-respecto' });
  const hechosRef = h('textarea', { id: 'dec-hechos', rows: 2 });
  const bloqueCompulsa = h('div', { class: 'rejilla', hidden: true },
    campo('dec-organo', 'Órgano', organo),
    campo('dec-respecto', 'Respecto de', respectoDe),
    campo('dec-hechos', 'Hechos de referencia', hechosRef, '', 'ancho'));
  compulsar.addEventListener('change', () => { bloqueCompulsa.hidden = !compulsar.checked; });

  const generarFormato = h('input', { type: 'checkbox', id: 'dec-formato' });
  const fechaFallo = h('input', { type: 'date', id: 'dec-fecha-fallo', value: hoyISO() });
  const fechaOficio = h('input', { type: 'date', id: 'dec-fecha-oficio' });
  const etiquetaEncabezado = h('input', { type: 'text', id: 'dec-etiqueta' });

  const filasLibres = [];
  const listaLibres = h('div', { class: 'pila-chica' });
  const agregarLibre = () => {
    const area = h('textarea', { rows: 2, 'aria-label': 'Texto del numeral libre' });
    const fila = { area };
    fila.el = h('div', { class: 'fila-libre' }, area,
      h('button', { type: 'button', class: 'btn btn-sec', onclick: () => {
        filasLibres.splice(filasLibres.indexOf(fila), 1);
        fila.el.remove();
        refrescarNumerales();
      } }, 'Quitar'));
    filasLibres.push(fila);
    listaLibres.append(fila.el);
    area.focus();
    refrescarNumerales();
  };

  let clavesOrden = [];
  let reordenado = false;
  const listaNumerales = h('ol', { class: 'numerales', 'aria-label': 'Orden de los numerales del RESUELVE' });
  const estadoNumerales = h('p', { class: 'ayuda', role: 'status', 'aria-live': 'polite' });

  const clavesVigentes = () => {
    const k = ['resultado'];
    if (resultado.value && resultado.value !== 'CONFIRMAR') k.push('sustitutiva');
    if (sustitutiva.value === 'AMPARAR') filasOrden.forEach((_, i) => k.push(`orden:${i}`));
    if (lineas(prevenir.value).length) k.push('prevenir');
    if (lineas(desvincular.value).length) k.push('desvincular');
    if (compulsar.checked) k.push('compulsa');
    filasLibres.forEach((_, i) => k.push(`libre:${i}`));
    if (notificar.checked) k.push('notificar');
    if (remitir.checked) k.push('remitir');
    return k;
  };

  const etiquetaNumeral = (k) => {
    if (NUMERALES_FIJOS[k]) return NUMERALES_FIJOS[k];
    const [pref, i] = k.split(':');
    if (pref === 'orden') return `Orden ${Number(i) + 1}${filasOrden[i]?.etiqueta() ? `: ${filasOrden[i].etiqueta()}` : ''}`;
    const texto = filasLibres[i]?.area.value.trim() || '';
    return `Texto libre ${Number(i) + 1}${texto ? `: ${texto.length > 50 ? `${texto.slice(0, 50)}…` : texto}` : ''}`;
  };

  const pintarNumerales = (enfocar) => {
    listaNumerales.replaceChildren(...clavesOrden.map((k, i) => {
      const nombre = etiquetaNumeral(k);
      const mover = (d) => {
        [clavesOrden[i], clavesOrden[i + d]] = [clavesOrden[i + d], clavesOrden[i]];
        reordenado = true;
        pintarNumerales({ k, d });
        estadoNumerales.textContent = `${nombre}: posición ${i + d + 1} de ${clavesOrden.length}.`;
      };
      return h('li', null,
        h('span', { class: 'numeral-nombre' }, nombre),
        h('button', { type: 'button', class: 'btn btn-sec', 'data-k': k, 'data-d': '-1', 'aria-label': `Subir: ${nombre}`, disabled: i === 0, onclick: () => mover(-1) }, '↑'),
        h('button', { type: 'button', class: 'btn btn-sec', 'data-k': k, 'data-d': '1', 'aria-label': `Bajar: ${nombre}`, disabled: i === clavesOrden.length - 1, onclick: () => mover(1) }, '↓'));
    }));
    if (enfocar) {
      const preferido = listaNumerales.querySelector(`button[data-k="${enfocar.k}"][data-d="${enfocar.d}"]:not(:disabled)`)
        || listaNumerales.querySelector(`button[data-k="${enfocar.k}"]:not(:disabled)`);
      preferido?.focus();
    }
  };

  function refrescarNumerales() {
    const vigentes = clavesVigentes();
    clavesOrden = reordenado
      ? [...clavesOrden.filter((k) => vigentes.includes(k)), ...vigentes.filter((k) => !clavesOrden.includes(k))]
      : vigentes;
    pintarNumerales();
  }

  const instruccion = h('textarea', { id: 'dec-instruccion', rows: 3, placeholder: 'Qué debe corregir o reforzar la IA' });

  const leerDecision = () => {
    const amparar = sustitutiva.value === 'AMPARAR';
    const compulsa = compulsar.checked
      ? { respecto_de: respectoDe.value.trim(), hechos_ref: hechosRef.value.trim(), ...(organo.value.trim() ? { organo: organo.value.trim() } : {}) }
      : null;
    return {
      accion: 'decidir',
      resultado: resultado.value || null,
      sustitutiva: sustitutiva.value || null,
      eje: eje.value.trim(),
      por_reparo: filasReparo.map((f) => f.leer()),
      derechos: derechosAplican() ? filasDerecho.map((f) => f.leer()) : [],
      ordenes: amparar ? filasOrden.map((f) => f.leer()) : [],
      desvincular: lineas(desvincular.value),
      prevenir: lineas(prevenir.value),
      compulsa,
      numerales: { notificar: notificar.checked, remitir_corte: remitir.checked },
      decidido_por: decididoPor.value.trim(),
      generar_formato: generarFormato.checked,
      fecha_fallo: fechaFallo.value || null,
      fecha_oficio: fechaOficio.value || null,
      etiqueta_encabezado: etiquetaEncabezado.value.trim(),
      numerales_libres: filasLibres.map((f) => f.area.value.trim()),
      orden_numerales: reordenado ? [...clavesOrden] : [],
    };
  };

  const validar = (d) => {
    const e = [];
    if (!d.resultado) e.push('Falta el resultado (CONFIRMAR, REVOCAR o MODIFICAR).');
    if (!d.sustitutiva && d.resultado !== 'CONFIRMAR') e.push('Falta la decisión sustitutiva (AMPARAR, NEGAR, ...).');
    if (!d.eje) e.push('Falta el eje: 2 a 5 líneas con el porqué de la decisión.');
    if (d.sustitutiva === 'AMPARAR' && !d.ordenes.length) e.push('Si se ampara, hay que indicar al menos una orden.');
    if (d.ordenes.some((o) => !o.destinatario || !o.conducta)) e.push('Cada orden necesita destinatario y conducta.');
    if (d.ordenes.some((o) => !(o.plazo.n > 0))) e.push('El plazo de cada orden debe ser mayor que cero.');
    if (d.numerales_libres.some((t) => !t)) e.push('Hay un numeral libre vacío.');
    if (d.compulsa && !d.compulsa.respecto_de) e.push('La compulsa de copias necesita indicar respecto de quién.');
    return e;
  };

  const ranura = h('div');
  let bloqueable;

  const enviarJob = async (decision, alTerminar) => {
    bloqueable.disabled = true;
    try {
      await lanzar('decidir', decision, alTerminar);
      ranura.replaceChildren(panelJob());
    } catch (e) {
      bloqueable.disabled = false;
      mostrarErrores([e.message]);
    }
  };

  const enviar = () => {
    if (config.llm?.proveedor === 'anthropic' && !S.apiKey) {
      mostrarErrores(['Falta la API key de Anthropic: péguela arriba a la derecha antes de enviar la decisión.']);
      return;
    }
    const decision = leerDecision();
    const fallos = validar(decision);
    mostrarErrores(fallos);
    if (fallos.length) return;
    enviarJob(decision, async (job) => {
      if (leerHash().vista !== 'decision' || job.caso !== S.caso) return;
      if (job.estado === 'terminado' && job.resultado?.estado === 'terminado') return navegar('resultado');
      try {
        const nuevo = await cargarEstado();
        if (nuevo.estado === 'error') {
          mostrarErrores([`La decisión quedó guardada, pero la redacción falló: ${nuevo.error || job.error || 'error desconocido'}`,
            'Corrija la causa y use "Continuar ejecución" en la pestaña Ejecutar; no hace falta volver a enviar la decisión.']);
          return;
        }
        mostrarErrores(job.error ? [job.error] : (nuevo.payload?.errores ?? []));
      } catch (e) {
        mostrarErrores([e.message]);
      }
      bloqueable.disabled = false;
    });
  };

  const rehacer = (accion) => {
    const texto = instruccion.value.trim();
    if (!texto) return mostrarErrores(['Para rehacer hay que escribir una instrucción.']);
    if (JSON.stringify(leerDecision()) !== inicialDecision
      && !confirm('El formulario de decisión tiene datos escritos y se vaciará al rehacer. ¿Desea continuar?')) return;
    mostrarErrores([]);
    enviarJob({ accion, instruccion: texto, decidido_por: decididoPor.value.trim() }, () => {
      if (leerHash().vista === 'decision') render();
    });
  };

  const contexto = [];
  const impugnantes = Array.isArray(payload.impugnantes) ? payload.impugnantes.filter(Boolean) : [];
  if (impugnantes.length > 1) {
    contexto.push(h('div', null, h('strong', null, 'Impugnantes'), parrafo(impugnantes.join(', '))));
  } else if (payload.impugnante) {
    contexto.push(h('div', null, h('strong', null, 'Impugnante'), parrafo([payload.impugnante, payload.impugnante_rol && `(${payload.impugnante_rol})`].filter(Boolean).join(' '))));
  }
  if (payload.decision_a_quo) contexto.push(h('div', null, h('strong', null, 'Decisión del a quo'), renderValor(payload.decision_a_quo)));
  if (Array.isArray(payload.pruebas_nuevas_2a) && payload.pruebas_nuevas_2a.length) {
    contexto.push(h('div', null, h('strong', null, 'Pruebas nuevas en segunda instancia'), renderValor(payload.pruebas_nuevas_2a)));
  }

  const formulario = h('form', {
    class: 'pila',
    novalidate: true,
    onsubmit: (ev) => { ev.preventDefault(); enviar(); },
    oninput: () => refrescarNumerales(),
    onchange: () => refrescarNumerales(),
  },
    tarjeta('1. Decisión',
      h('div', { class: 'rejilla' },
        campo('dec-resultado', 'Resultado', resultado),
        campo('dec-sustitutiva', 'Decisión sustitutiva', sustitutiva, 'No se pide cuando el resultado es Confirmar.')),
      campo('dec-eje', 'Eje de la decisión', eje, `Obligatorio. Las consideraciones del caso concreto desarrollan este eje. ${AYUDA_DATOS_NUEVOS}`),
      campo('dec-por', 'Decidido por', decididoPor, 'Queda en la declaración de uso de IA.')),
    tarjeta('2. Reparos y derechos',
      reparos.length
        ? h('div', { class: 'pila-chica' }, filasReparo.map((f) => f.el))
        : parrafo('No se recibieron reparos extraídos.', 'vacio'),
      bloqueDerechos),
    bloqueOrdenes,
    h('details', { class: 'tarjeta' },
      h('summary', null, h('h2', null, '4. Otros numerales')),
      h('div', { class: 'pila' },
        campo('dec-desvincular', 'Desvincular', desvincular),
        campo('dec-prevenir', 'Prevenir', prevenir),
        h('div', { class: 'campo campo-check' }, compulsar, h('label', { for: 'dec-compulsar' }, 'Compulsar copias')),
        bloqueCompulsa,
        h('div', { class: 'campo campo-check' }, notificar, h('label', { for: 'dec-notificar' }, 'Notificar (art. 30 del Decreto 2591 de 1991)')),
        h('div', { class: 'campo campo-check' }, remitir, h('label', { for: 'dec-remitir' }, 'Remitir a la Corte Constitucional (art. 32 del Decreto 2591 de 1991)')))),
    tarjeta('5. Formato, fechas y numerales',
      h('div', { class: 'campo campo-check' }, generarFormato, h('label', { for: 'dec-formato' }, 'Generar el Formato Factor Calidad')),
      h('div', { class: 'rejilla' },
        campo('dec-fecha-fallo', 'Fecha del fallo', fechaFallo, 'Por defecto, la de hoy.'),
        campo('dec-fecha-oficio', 'Fecha del oficio a la Corte', fechaOficio, 'Opcional.'),
        campo('dec-etiqueta', 'Etiqueta del encabezado', etiquetaEncabezado, 'Opcional. Reemplaza la etiqueta calculada de la decisión.')),
      h('h3', null, 'Numerales de texto libre'),
      listaLibres,
      h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'btn btn-sec', onclick: agregarLibre }, 'Agregar numeral libre')),
      h('h3', null, 'Orden de los numerales del RESUELVE'),
      parrafo('Si no se cambia, se usa el orden por defecto.', 'ayuda'),
      listaNumerales,
      estadoNumerales),
    h('div', { class: 'acciones barra-fija' }, h('button', { type: 'submit', class: 'btn btn-primario' }, 'Enviar decisión')));
  refrescarNumerales();
  const inicialDecision = JSON.stringify(leerDecision());

  const tarjetaRehacer = tarjeta('Rehacer una parte del borrador',
    parrafo('Si el borrador no sirve, indique qué corregir y se rehace la apertura o las consideraciones.', 'ayuda'),
    campo('dec-instruccion', 'Instrucción', instruccion),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'btn btn-sec', onclick: () => rehacer('rehacer_apertura') }, 'Rehacer apertura'),
      h('button', { type: 'button', class: 'btn btn-sec', onclick: () => rehacer('rehacer_consideraciones') }, 'Rehacer consideraciones')));

  bloqueable = h('fieldset', { class: 'sin-borde pila', disabled: bloqueado }, formulario, tarjetaRehacer);

  return h('div', { class: 'pila' }, errores, contexto.length ? tarjeta('Contexto', ...contexto) : null, ranura, bloqueable);
}

const MENSAJES_SIN_DECISION = {
  terminado: 'La decisión ya fue enviada y el fallo está generado.',
  error: 'El proceso quedó a medias. Use "Continuar ejecución" en la pestaña Ejecutar.',
};

async function vistaDecision() {
  const [estado, config] = await Promise.all([cargarEstado(), api(rutaCaso('/config'))]);
  const job = jobDeEsteCaso();
  const corriendo = job?.estado === 'corriendo';
  const contenido = h('div', { class: 'pila' });
  if (corriendo || job?.estado === 'error') contenido.append(panelJob());
  if (estado.estado !== 'esperando_decision') {
    contenido.append(tarjeta('Decisión',
      parrafo(MENSAJES_SIN_DECISION[estado.estado] || 'No hay una decisión pendiente. Genere primero el borrador previo.', 'vacio'),
      h('div', { class: 'acciones' }, h('a', { class: 'btn btn-sec', href: `#${estado.estado === 'terminado' ? 'resultado' : 'ejecutar'}/${enc(S.caso)}` },
        estado.estado === 'terminado' ? 'Ver resultado' : 'Ir a ejecutar'))));
    return contenido;
  }
  contenido.append(formularioDecision(estado, config, corriendo));
  return contenido;
}

/* ---------- Resultado ---------- */

const descripcionSalida = (ruta) => ARCHIVOS_SALIDA.find(([re]) => re.test(ruta))?.[1] || ruta.split('/').pop();

function agruparSalidas(rutas) {
  const grupos = new Map(GRUPOS_SALIDA.map(([dir]) => [dir, []]));
  for (const ruta of [...rutas].sort()) {
    const dir = ruta.includes('/') ? ruta.slice(0, ruta.lastIndexOf('/')) : '';
    if (!grupos.has(dir)) grupos.set(dir, []);
    grupos.get(dir).push(ruta);
  }
  return [...grupos].filter(([, lista]) => lista.length)
    .map(([dir, lista]) => [GRUPOS_SALIDA.find(([d]) => d === dir)?.[1] || dir || 'Otros', lista]);
}

async function vistaResultado() {
  const estado = await cargarEstado();
  const rutas = salidasDe(estado);

  if (!rutas.length) {
    return tarjeta('Documentos del caso', parrafo('Aún no hay documentos generados. El fallo y sus anexos se generan cuando se envía la decisión.', 'vacio'));
  }

  const grupos = agruparSalidas(rutas).map(([titulo, lista]) => h('section', { class: 'tarjeta' },
    h('h2', null, titulo),
    h('ul', { class: 'lista-descargas' }, lista.map((ruta) => h('li', { class: 'descarga' },
      h('a', { class: 'btn btn-sec', href: urlSalida(ruta), download: ruta.split('/').pop() }, 'Descargar'),
      h('span', null, h('strong', null, descripcionSalida(ruta)), h('div', { class: 'ayuda ruta' }, ruta.split('/').pop())))))));

  return h('div', { class: 'pila' },
    h('div', { class: 'acciones' }, h('a', { class: 'btn btn-primario', href: rutaCaso('/zip'), download: `${S.caso}.zip` }, 'Descargar todo (.zip)')),
    estado.estado === 'terminado' ? null : parrafo('El fallo y sus anexos se generan cuando se envía la decisión.', 'ayuda'),
    ...grupos);
}

const VISTA_FN = {
  casos: vistaCasos,
  documentos: vistaDocumentos,
  config: vistaConfig,
  ejecutar: vistaEjecutar,
  revision: vistaRevision,
  decision: vistaDecision,
  resultado: vistaResultado,
};

/* ---------- Cabecera ---------- */

function pintarClave() {
  const el = $('#chip-key');
  el.textContent = S.apiKey ? 'API key configurada' : 'Sin API key';
  el.className = `chip chip-${S.apiKey ? 'ok' : 'alerta'}`;
}

async function iniciar() {
  $('#form-key').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const campoClave = $('#api-key');
    const key = campoClave.value.trim();
    if (!key) return;
    try {
      const r = await api('/api/api-key', { metodo: 'POST', cuerpo: { key } });
      S.apiKey = r.api_key;
      campoClave.value = '';
      pintarClave();
      aviso('API key guardada solo en la memoria del servidor.', 'ok');
    } catch (e) {
      aviso(e.message, 'error');
    }
  });
  const selector = $('#modelo');
  let servidor = { api_key: false, jev_key: false, modelo: '', modelos: [] };
  try {
    servidor = await api('/api/estado-servidor');
  } catch {
    selector.disabled = true;
  }
  S.apiKey = servidor.api_key;
  S.jevKey = !!servidor.jev_key;
  for (const m of servidor.modelos) selector.append(h('option', { value: m }, NOMBRES_MODELO[m] || m));
  selector.value = servidor.modelo;
  let modeloVigente = servidor.modelo;
  selector.addEventListener('change', async () => {
    try {
      modeloVigente = (await api('/api/modelo', { metodo: 'POST', cuerpo: { modelo: selector.value } })).modelo;
      aviso(`Modelo: ${NOMBRES_MODELO[modeloVigente] || modeloVigente}. Se usa desde la próxima ejecución.`, 'ok');
    } catch (e) {
      selector.value = modeloVigente;
      aviso(e.message, 'error');
    }
  });
  pintarClave();
  window.addEventListener('hashchange', render);
  render();
}

iniciar();
})();
