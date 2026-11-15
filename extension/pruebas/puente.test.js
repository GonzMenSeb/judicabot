import { test } from "node:test";
import assert from "node:assert/strict";
import { setImmediate as turno } from "node:timers/promises";
import {
  DESCARGA_MS,
  LATIDO_MS,
  REINTENTO_MS,
  SERVIDOR_POR_DEFECTO,
  armarEntrega,
  crearPuente,
  urlPermitida,
  urlSocket,
} from "../puente.js";

const URL_T200 = "https://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm";

class SocketFalso {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.enviados = [];
    this.cerrado = false;
  }
  send(datos) {
    this.enviados.push(datos);
  }
  close() {
    this.readyState = 3;
    this.cerrado = true;
  }
  abrir() {
    this.readyState = 1;
    this.onopen({});
  }
  recibir(mensaje) {
    this.onmessage({ data: JSON.stringify(mensaje) });
  }
  cerrar(code) {
    this.readyState = 3;
    this.onclose({ code, reason: "" });
  }
  textos() {
    return this.enviados.filter((d) => typeof d === "string").map((d) => JSON.parse(d));
  }
  binarios() {
    return this.enviados.filter((d) => typeof d !== "string").map(leerEntrega);
  }
}

function leerEntrega(bytes) {
  const corte = bytes.indexOf(10);
  return {
    cabecera: JSON.parse(new TextDecoder().decode(bytes.subarray(0, corte))),
    cuerpo: bytes.subarray(corte + 1),
  };
}

function crearReloj() {
  const reloj = { cadas: [], luegos: [], cancelados: [], siguiente: 0 };
  reloj.cada = (ms, fn) => {
    const id = ++reloj.siguiente;
    reloj.cadas.push({ id, ms, fn });
    return id;
  };
  reloj.cancelar = (id) => reloj.cancelados.push(id);
  reloj.luego = (ms, fn) => {
    reloj.luegos.push({ ms, fn });
    return ++reloj.siguiente;
  };
  return reloj;
}

function armar({ servidor = "https://judicabot.example", ficha, descargar = async () => assert.fail("no debía descargar") } = {}) {
  const datos = { servidor, ficha };
  const almacen = {
    guardados: [],
    leer: async () => ({ ...datos }),
    guardar: (parcial) => {
      almacen.guardados.push(parcial);
      Object.assign(datos, parcial);
    },
  };
  const sockets = [];
  const estados = [];
  const reloj = crearReloj();
  const puente = crearPuente({
    crearSocket: (url) => {
      const socket = new SocketFalso(url);
      sockets.push(socket);
      return socket;
    },
    descargar,
    almacen,
    reloj,
    version: "1.0.0",
    alCambiarEstado: (estado, detalle) => estados.push([estado, detalle]),
  });
  return { puente, sockets, estados, reloj, almacen, datos };
}

async function conectado(opciones) {
  const armado = armar({ ficha: "abc", ...opciones });
  await armado.puente.conectar();
  const socket = armado.sockets[0];
  socket.abrir();
  socket.recibir({ tipo: "listo", ficha: "abc" });
  return { ...armado, socket };
}

function respuesta(status, cuerpo, url = URL_T200) {
  return { status, url, arrayBuffer: async () => cuerpo.buffer.slice(0) };
}

test("urlPermitida acepta la relatoría y rechaza el resto", () => {
  assert.equal(urlPermitida(URL_T200), true);
  for (const url of [
    "http://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm",
    "https://corteconstitucional.gov.co/relatoria/2022/T-200-22.htm",
    "https://www.corteconstitucional.gov.co/otra/2022/T-200-22.htm",
    "https://www.corteconstitucional.gov.co/relatoria/../x",
    "https://u:p@www.corteconstitucional.gov.co/relatoria/x",
    "https://evil.com/relatoria/x",
    "no es una url",
    undefined,
  ]) {
    assert.equal(urlPermitida(url), false, url);
  }
});

test("urlSocket convierte el esquema", () => {
  assert.equal(urlSocket("https://judicabot.web.vespiridion.org"), "wss://judicabot.web.vespiridion.org/api/extension");
  assert.equal(urlSocket("http://127.0.0.1:8000"), "ws://127.0.0.1:8000/api/extension");
  assert.equal(SERVIDOR_POR_DEFECTO, "https://judicabot.web.vespiridion.org");
});

test("armarEntrega une cabecera JSON, salto de línea y bytes", () => {
  const entrega = armarEntrega("a1", 200, new Uint8Array([0, 10, 255]), "");
  const { cabecera, cuerpo } = leerEntrega(entrega);
  assert.deepEqual(cabecera, { id: "a1", codigo: 200, detalle: "" });
  assert.deepEqual([...cuerpo], [0, 10, 255]);
  assert.equal(new TextDecoder().decode(entrega.subarray(0, entrega.indexOf(10) + 1)), '{"id":"a1","codigo":200,"detalle":""}\n');
});

test("sin ficha ni contraseña no abre socket", async () => {
  const { puente, sockets, estados } = armar({ ficha: null });
  await puente.conectar();
  assert.equal(sockets.length, 0);
  assert.deepEqual(estados, [["sin_contrasena", ""]]);
  assert.equal(puente.abierto(), false);
});

test("con contraseña manda hola y guarda solo la ficha", async () => {
  const { puente, sockets, estados, almacen } = armar({ ficha: null });
  await puente.conectar("x");
  const socket = sockets[0];
  assert.equal(socket.url, "wss://judicabot.example/api/extension");
  socket.abrir();
  assert.equal(socket.enviados[0], '{"tipo":"hola","version":"1.0.0","contrasena":"x"}');
  socket.recibir({ tipo: "listo", ficha: "f1" });
  assert.deepEqual(almacen.guardados, [{ ficha: "f1" }]);
  assert.deepEqual(estados, [["conectando", ""], ["conectada", ""]]);
  assert.equal(puente.abierto(), true);
  assert.ok(!JSON.stringify(almacen.guardados).includes('"x"'));
});

test("con ficha guardada manda hola con ficha", async () => {
  const { puente, sockets } = armar({ ficha: "abc" });
  await puente.conectar();
  sockets[0].abrir();
  assert.deepEqual(sockets[0].textos()[0], { tipo: "hola", version: "1.0.0", ficha: "abc" });
});

test("la ficha vacía de un servidor sin contraseña también se manda", async () => {
  const { puente, sockets } = armar({ ficha: "" });
  await puente.conectar();
  sockets[0].abrir();
  assert.deepEqual(sockets[0].textos()[0], { tipo: "hola", version: "1.0.0", ficha: "" });
});

test("sin servidor guardado usa el servidor por defecto", async () => {
  const { puente, sockets } = armar({ servidor: null, ficha: "abc" });
  await puente.conectar();
  assert.equal(sockets[0].url, "wss://judicabot.web.vespiridion.org/api/extension");
});

test("cierre 4401 borra la ficha y no reintenta", async () => {
  const { socket, estados, reloj, almacen, datos } = await conectado();
  socket.cerrar(4401);
  assert.deepEqual(estados.at(-1), ["rechazada", ""]);
  assert.deepEqual(almacen.guardados.at(-1), { ficha: null });
  assert.equal(datos.ficha, null);
  assert.equal(reloj.luegos.length, 0);
});

test("cierre 4429 da estado bloqueada y no reintenta", async () => {
  const { socket, estados, reloj } = await conectado();
  socket.cerrar(4429);
  assert.deepEqual(estados.at(-1), ["bloqueada", ""]);
  assert.equal(reloj.luegos.length, 0);
});

test("cierre inesperado reintenta con la ficha", async () => {
  const { puente, socket, sockets, estados, reloj } = await conectado();
  socket.cerrar(1006);
  assert.equal(estados.at(-1)[0], "desconectada");
  assert.equal(puente.abierto(), false);
  assert.equal(reloj.luegos.length, 1);
  assert.equal(reloj.luegos[0].ms, REINTENTO_MS);
  reloj.luegos[0].fn();
  await turno();
  assert.equal(sockets.length, 2);
  sockets[1].abrir();
  assert.deepEqual(sockets[1].textos()[0], { tipo: "hola", version: "1.0.0", ficha: "abc" });
});

test("cierre 4408 también reintenta", async () => {
  const { socket, estados, reloj } = await conectado();
  socket.cerrar(4408);
  assert.equal(estados.at(-1)[0], "desconectada");
  assert.equal(reloj.luegos.length, 1);
});

test("nunca queda más de un reintento pendiente", async () => {
  const { puente, socket, sockets, reloj } = await conectado();
  socket.cerrar(1006);
  await puente.conectar();
  sockets[1].cerrar(1006);
  assert.equal(reloj.luegos.length, 1);
  reloj.luegos[0].fn();
  await turno();
  sockets[2].cerrar(1006);
  assert.equal(reloj.luegos.length, 2);
});

test("un error del socket lo cierra", async () => {
  const { socket } = await conectado();
  socket.onerror({});
  assert.equal(socket.cerrado, true);
});

test("conectar sin contraseña con un socket abierto o conectando no hace nada", async () => {
  const { puente, sockets } = armar({ ficha: "abc" });
  await Promise.all([puente.conectar(), puente.conectar()]);
  assert.equal(sockets.length, 1);
  await puente.conectar();
  assert.equal(sockets.length, 1);
  sockets[0].abrir();
  await puente.conectar();
  assert.equal(sockets.length, 1);
});

test("conectar con contraseña cierra el socket actual sin reintentar", async () => {
  const { puente, socket, sockets, reloj, estados } = await conectado();
  const antes = estados.length;
  await puente.conectar("nueva");
  assert.equal(socket.cerrado, true);
  socket.cerrar(1006);
  assert.equal(reloj.luegos.length, 0);
  assert.equal(reloj.cancelados.length, 1);
  assert.deepEqual(estados.slice(antes), [["conectando", ""]]);
  sockets[1].abrir();
  assert.deepEqual(sockets[1].textos()[0], { tipo: "hola", version: "1.0.0", contrasena: "nueva" });
});

test("pedido permitido responde con código y bytes", async () => {
  const llamadas = [];
  const cuerpo = new Uint8Array([60, 104, 116, 109, 108, 62, 0, 10, 233]);
  const { socket } = await conectado({
    descargar: async (url, opciones) => {
      llamadas.push([url, opciones]);
      return respuesta(200, cuerpo);
    },
  });
  socket.recibir({ tipo: "pedido", id: "p1", url: URL_T200 });
  await turno();
  assert.equal(llamadas.length, 1);
  const [url, { signal, ...opciones }] = llamadas[0];
  assert.equal(url, URL_T200);
  assert.deepEqual(opciones, { credentials: "omit", cache: "no-store", redirect: "follow", referrerPolicy: "no-referrer" });
  assert.ok(signal instanceof AbortSignal);
  assert.equal(DESCARGA_MS, 60_000);
  const [entrega] = socket.binarios();
  assert.deepEqual(entrega.cabecera, { id: "p1", codigo: 200, detalle: "" });
  assert.deepEqual([...entrega.cuerpo], [...cuerpo]);
});

test("pedido fuera de la relatoría no descarga", async () => {
  const { socket } = await conectado();
  socket.recibir({ tipo: "pedido", id: "p2", url: "https://evil.com/relatoria/x" });
  await turno();
  const [entrega] = socket.binarios();
  assert.deepEqual(entrega.cabecera, { id: "p2", codigo: null, detalle: "URL fuera de la relatoría" });
  assert.equal(entrega.cuerpo.length, 0);
});

test("error de red responde codigo null con el mensaje", async () => {
  const { socket } = await conectado({
    descargar: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  socket.recibir({ tipo: "pedido", id: "p3", url: URL_T200 });
  await turno();
  const [entrega] = socket.binarios();
  assert.deepEqual(entrega.cabecera, { id: "p3", codigo: null, detalle: "Failed to fetch" });
  assert.equal(entrega.cuerpo.length, 0);
});

test("redirección fuera de la relatoría no entrega bytes", async () => {
  const { socket } = await conectado({
    descargar: async () => respuesta(200, new Uint8Array([1, 2, 3]), "https://www.corteconstitucional.gov.co/otra/x.htm"),
  });
  socket.recibir({ tipo: "pedido", id: "p4", url: URL_T200 });
  await turno();
  const [entrega] = socket.binarios();
  assert.deepEqual(entrega.cabecera, { id: "p4", codigo: null, detalle: "redirección fuera de la relatoría" });
  assert.equal(entrega.cuerpo.length, 0);
});

test("403 se entrega con su código", async () => {
  const { socket } = await conectado({ descargar: async () => respuesta(403, new Uint8Array([70, 111])) });
  socket.recibir({ tipo: "pedido", id: "p5", url: URL_T200 });
  await turno();
  const [entrega] = socket.binarios();
  assert.deepEqual(entrega.cabecera, { id: "p5", codigo: 403, detalle: "" });
  assert.deepEqual([...entrega.cuerpo], [70, 111]);
});

test("los pedidos se atienden a la vez", async () => {
  let soltarPrimero;
  const primero = new Promise((resolver) => (soltarPrimero = resolver));
  const { socket } = await conectado({
    descargar: (url) => (url.endsWith("T-200-22.htm") ? primero : Promise.resolve(respuesta(200, new Uint8Array([2])))),
  });
  socket.recibir({ tipo: "pedido", id: "lento", url: URL_T200 });
  socket.recibir({ tipo: "pedido", id: "rapido", url: URL_T200.replace("T-200-22", "T-201-22") });
  await turno();
  assert.deepEqual(socket.binarios().map((e) => e.cabecera.id), ["rapido"]);
  soltarPrimero(respuesta(200, new Uint8Array([1])));
  await turno();
  assert.deepEqual(socket.binarios().map((e) => e.cabecera.id), ["rapido", "lento"]);
});

test("si el socket se cerró, la respuesta no se envía", async () => {
  let soltar;
  const pendiente = new Promise((resolver) => (soltar = resolver));
  const { socket } = await conectado({ descargar: () => pendiente });
  socket.recibir({ tipo: "pedido", id: "p6", url: URL_T200 });
  socket.cerrar(1006);
  soltar(respuesta(200, new Uint8Array([1])));
  await turno();
  assert.equal(socket.binarios().length, 0);
});

test("latido cada 20 s mientras está abierto, y se cancela al cerrar", async () => {
  const { socket, reloj } = await conectado();
  assert.equal(LATIDO_MS, 20_000);
  assert.equal(reloj.cadas.length, 1);
  const [{ id, ms, fn }] = reloj.cadas;
  assert.equal(ms, LATIDO_MS);
  fn();
  assert.deepEqual(socket.textos().at(-1), { tipo: "latido" });
  socket.cerrar(1006);
  assert.deepEqual(reloj.cancelados, [id]);
});
