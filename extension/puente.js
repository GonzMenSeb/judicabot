export const PREFIJO = "https://www.corteconstitucional.gov.co/relatoria/";
export const URL_VIGENCIA = "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx";
export const DESCARGA_MS = 60_000;
export const LATIDO_MS = 20_000;
export const REINTENTO_MS = 5_000;
export const SERVIDOR_POR_DEFECTO = "https://judicabot.web.vespiridion.org";

const ESQUEMAS_SOCKET = { "https:": "wss:", "http:": "ws:" };
const LATIDO = JSON.stringify({ tipo: "latido" });
const VACIO = new Uint8Array(0);
const TERMINALES = new Set(["rechazada", "bloqueada"]);
const OPCIONES = Object.freeze({ credentials: "omit", cache: "no-store", redirect: "follow", referrerPolicy: "no-referrer" });
// La página de vigencia está detrás de varios servidores: el GET deja dos cookies de afinidad
// (ApplicationGatewayAffinity y ApplicationGatewayAffinityCORS) y, si el POST no las devuelve, cae en
// otro servidor que no reconoce el formulario y responde un error 500. Por eso, y solo para la vigencia,
// el navegador guarda y devuelve las cookies que esa misma página pone; no hay sesión ni datos personales.
// Sin seguir redirecciones, tampoco en el GET: con las cookies incluidas, seguir una redirección enviaría
// al destino las cookies que el navegador tenga para él antes de poder revisar la dirección.
const OPCIONES_VIGENCIA = Object.freeze({ ...OPCIONES, credentials: "include", redirect: "manual" });

// Las únicas consultas públicas que hace la extensión. Cualquier otra dirección, método o campo se
// rechaza aquí, antes de salir del navegador, aunque lo pida el servidor de judicabot.
export const SERVICIOS = Object.freeze([
  Object.freeze({
    nombre: "relatoria",
    host: "www.corteconstitucional.gov.co",
    prefijo: "/relatoria/",
    metodos: Object.freeze(["GET"]),
  }),
  Object.freeze({
    nombre: "vigencia",
    host: "vigenciaspublicas.ramajudicial.gov.co",
    ruta: "/Certificados.aspx",
    metodos: Object.freeze(["GET", "POST"]),
    // Los tres campos ocultos de la página, abogado (ddlCalidad=1), cédula de ciudadanía
    // (ddlTipoDocumento=1) y el número de cédula. Nada más sale hacia la Rama Judicial.
    campos: Object.freeze({
      __VIEWSTATE: /^[A-Za-z0-9+/=]{1,100000}$/,
      __VIEWSTATEGENERATOR: /^[0-9A-F]{8}$/,
      __EVENTVALIDATION: /^[A-Za-z0-9+/=]{1,20000}$/,
      ddlCalidad: /^1$/,
      ddlTipoDocumento: /^1$/,
      txtDocumento: /^[0-9]{5,10}$/,
      btnTpVigente: /^Generar$/,
    }),
    maxCuerpo: 256_000,
    maxRespuesta: 2_000_000,
    devuelveTipo: true,
  }),
]);

export function servicioDe(url, metodo = "GET") {
  let destino;
  try {
    destino = new URL(url);
  } catch {
    return null;
  }
  if (destino.protocol !== "https:" || destino.username !== "" || destino.password !== "") return null;
  if (destino.pathname.includes("%")) return null;
  const servicio = SERVICIOS.find((s) => s.host === destino.host);
  if (servicio === undefined || !servicio.metodos.includes(metodo)) return null;
  if (servicio.prefijo !== undefined) return destino.pathname.startsWith(servicio.prefijo) ? servicio : null;
  return destino.href === `https://${servicio.host}${servicio.ruta}` ? servicio : null;
}

export function urlPermitida(url) {
  return servicioDe(url)?.nombre === "relatoria";
}

// Devuelve el cuerpo application/x-www-form-urlencoded si el formulario trae exactamente los campos
// del servicio, cada uno con un valor permitido; si no, null.
export function cuerpoPermitido(nombre, formulario) {
  const servicio = SERVICIOS.find((s) => s.nombre === nombre);
  const reglas = servicio?.campos;
  if (reglas === undefined || formulario === null || typeof formulario !== "object" || Array.isArray(formulario)) return null;
  const campos = Object.keys(reglas);
  if (Object.keys(formulario).length !== campos.length || !campos.every((campo) => Object.hasOwn(formulario, campo))) return null;
  if (!campos.every((campo) => typeof formulario[campo] === "string" && reglas[campo].test(formulario[campo]))) return null;
  const cuerpo = new URLSearchParams(campos.map((campo) => [campo, formulario[campo]])).toString();
  return cuerpo.length <= servicio.maxCuerpo ? cuerpo : null;
}

// Qué se descarga y con qué opciones de fetch: [servicio, opciones], o el motivo del rechazo.
export function prepararPedido(mensaje) {
  if (mensaje.tipo === "pedido") {
    // El mensaje de la versión 1.0.0: solo páginas de la relatoría, siempre con GET.
    const servicio = servicioDe(mensaje.url, "GET");
    return servicio?.nombre === "relatoria" ? [servicio, { ...OPCIONES }] : "URL fuera de la relatoría";
  }
  const { servicio: nombre, url, metodo, formulario } = mensaje;
  const servicio = metodo === "GET" || metodo === "POST" ? servicioDe(url, metodo) : null;
  if (servicio === null || servicio.nombre !== nombre) return "pedido fuera de los servicios permitidos";
  const opciones = servicio.nombre === "vigencia" ? OPCIONES_VIGENCIA : OPCIONES;
  if (metodo === "GET") return formulario == null ? [servicio, { ...opciones }] : "formulario no permitido";
  const cuerpo = cuerpoPermitido(nombre, formulario);
  if (cuerpo === null) return "formulario no permitido";
  return [
    servicio,
    {
      ...opciones,
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: cuerpo,
      // Sin seguir redirecciones: un 307 o un 308 reenviaría el formulario a otra dirección antes de revisarla.
      redirect: "manual",
    },
  ];
}

export function urlSocket(servidor) {
  const destino = new URL("/api/extension", servidor);
  const esquema = ESQUEMAS_SOCKET[destino.protocol];
  if (!esquema) throw new Error(`El servidor debe empezar por https:// o http://: ${servidor}`);
  destino.protocol = esquema;
  return destino.href;
}

export function armarEntrega(id, codigo, cuerpo, detalle, extra = {}) {
  const cabecera = new TextEncoder().encode(JSON.stringify({ id, codigo, detalle, ...extra }) + "\n");
  const entrega = new Uint8Array(cabecera.length + cuerpo.length);
  entrega.set(cabecera);
  entrega.set(cuerpo, cabecera.length);
  return entrega;
}

export function crearPuente({ crearSocket, descargar, almacen, reloj, version, alCambiarEstado }) {
  let actual = null;
  let reintentoPendiente = false;
  let turno = 0;
  let enCurso = null;

  const vivo = () => actual !== null && actual.socket.readyState <= 1;

  function pararLatido(conexion) {
    if (conexion.latido === null) return;
    reloj.cancelar(conexion.latido);
    conexion.latido = null;
  }

  function soltar() {
    if (actual === null) return;
    const conexion = actual;
    actual = null;
    pararLatido(conexion);
    conexion.socket.close();
  }

  function reintentar() {
    if (reintentoPendiente) return;
    reintentoPendiente = true;
    reloj.luego(REINTENTO_MS, () => {
      reintentoPendiente = false;
      conectar();
    });
  }

  async function traer(mensaje) {
    const preparado = prepararPedido(mensaje);
    if (typeof preparado === "string") return [null, VACIO, preparado];
    const [servicio, opciones] = preparado;
    const legado = mensaje.tipo === "pedido";
    try {
      const respuesta = await descargar(mensaje.url, { ...opciones, signal: AbortSignal.timeout(DESCARGA_MS) });
      if (respuesta.type === "opaqueredirect" || servicioDe(respuesta.url)?.nombre !== servicio.nombre) {
        return [null, VACIO, legado ? "redirección fuera de la relatoría" : "redirección no permitida"];
      }
      const tope = servicio.maxRespuesta;
      if (tope !== undefined && Number(respuesta.headers?.get("content-length") ?? 0) > tope) {
        return [null, VACIO, "respuesta demasiado grande"];
      }
      const cuerpo = new Uint8Array(await respuesta.arrayBuffer());
      if (tope !== undefined && cuerpo.length > tope) return [null, VACIO, "respuesta demasiado grande"];
      const extra = servicio.devuelveTipo ? { tipo: respuesta.headers?.get("content-type") ?? null } : {};
      return [respuesta.status, cuerpo, "", extra];
    } catch (error) {
      return [null, VACIO, String(error?.message ?? error)];
    }
  }

  async function atender(socket, mensaje) {
    const [codigo, cuerpo, detalle, extra] = await traer(mensaje);
    if (socket.readyState === 1) socket.send(armarEntrega(mensaje.id, codigo, cuerpo, detalle, extra));
  }

  async function abrir(mio, contrasena) {
    const { servidor, ficha, estado } = await almacen.leer();
    if (mio !== turno) return;
    let credencial;
    if (contrasena) credencial = { contrasena };
    else if (typeof ficha === "string") credencial = { ficha };
    else {
      if (!TERMINALES.has(estado)) alCambiarEstado("sin_contrasena", "");
      return;
    }
    alCambiarEstado("conectando", "");
    let socket;
    try {
      socket = crearSocket(urlSocket(servidor || SERVIDOR_POR_DEFECTO));
    } catch (error) {
      alCambiarEstado("desconectada", String(error?.message ?? error));
      return reintentar();
    }
    const conexion = { socket, latido: null };
    actual = conexion;
    socket.onopen = () => {
      socket.send(JSON.stringify({ tipo: "hola", version, ...credencial }));
      conexion.latido = reloj.cada(LATIDO_MS, () => {
        if (socket.readyState === 1) socket.send(LATIDO);
      });
    };
    socket.onmessage = (evento) => {
      if (typeof evento.data !== "string") return;
      const mensaje = JSON.parse(evento.data);
      if (mensaje.tipo === "listo") {
        almacen.guardar({ ficha: mensaje.ficha });
        alCambiarEstado("conectada", "");
      } else if (mensaje.tipo === "pedido" || mensaje.tipo === "pedir") {
        atender(socket, mensaje);
      }
    };
    socket.onerror = () => socket.close();
    socket.onclose = (evento) => {
      pararLatido(conexion);
      if (actual !== conexion) return;
      actual = null;
      if (evento.code === 4401) {
        if ("ficha" in credencial) almacen.guardar({ ficha: null });
        alCambiarEstado("rechazada", "");
      } else if (evento.code === 4429) {
        alCambiarEstado("bloqueada", "");
      } else {
        alCambiarEstado("desconectada", evento.reason ?? "");
        reintentar();
      }
    };
  }

  async function conectar(contrasena) {
    if (contrasena === undefined) {
      if (vivo()) return;
      if (enCurso) return enCurso;
    }
    const mio = ++turno;
    soltar();
    enCurso = abrir(mio, contrasena);
    try {
      await enCurso;
    } finally {
      if (mio === turno) enCurso = null;
    }
  }

  return { conectar, abierto: () => actual !== null && actual.socket.readyState === 1 };
}
