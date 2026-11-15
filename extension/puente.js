export const PREFIJO = "https://www.corteconstitucional.gov.co/relatoria/";
export const DESCARGA_MS = 60_000;
export const LATIDO_MS = 20_000;
export const REINTENTO_MS = 5_000;
export const SERVIDOR_POR_DEFECTO = "https://judicabot.web.vespiridion.org";

const ESQUEMAS_SOCKET = { "https:": "wss:", "http:": "ws:" };
const LATIDO = JSON.stringify({ tipo: "latido" });
const VACIO = new Uint8Array(0);
const TERMINALES = new Set(["rechazada", "bloqueada"]);

export function urlPermitida(url) {
  let destino;
  try {
    destino = new URL(url);
  } catch {
    return false;
  }
  return (
    destino.protocol === "https:" &&
    destino.host === "www.corteconstitucional.gov.co" &&
    destino.username === "" &&
    destino.password === "" &&
    destino.pathname.startsWith("/relatoria/") &&
    !destino.pathname.includes("%")
  );
}

export function urlSocket(servidor) {
  const destino = new URL("/api/extension", servidor);
  const esquema = ESQUEMAS_SOCKET[destino.protocol];
  if (!esquema) throw new Error(`El servidor debe empezar por https:// o http://: ${servidor}`);
  destino.protocol = esquema;
  return destino.href;
}

export function armarEntrega(id, codigo, cuerpo, detalle) {
  const cabecera = new TextEncoder().encode(JSON.stringify({ id, codigo, detalle }) + "\n");
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

  async function traer(url) {
    if (!urlPermitida(url)) return [null, VACIO, "URL fuera de la relatoría"];
    try {
      const respuesta = await descargar(url, {
        credentials: "omit",
        cache: "no-store",
        redirect: "follow",
        referrerPolicy: "no-referrer",
        signal: AbortSignal.timeout(DESCARGA_MS),
      });
      if (!urlPermitida(respuesta.url)) return [null, VACIO, "redirección fuera de la relatoría"];
      return [respuesta.status, new Uint8Array(await respuesta.arrayBuffer()), ""];
    } catch (error) {
      return [null, VACIO, String(error?.message ?? error)];
    }
  }

  async function atender(socket, { id, url }) {
    const [codigo, cuerpo, detalle] = await traer(url);
    if (socket.readyState === 1) socket.send(armarEntrega(id, codigo, cuerpo, detalle));
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
      } else if (mensaje.tipo === "pedido") {
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
