import { test } from "node:test";
import assert from "node:assert/strict";
import { setImmediate as turno } from "node:timers/promises";
import { readFileSync } from "node:fs";
import {
  DESCARGA_MS,
  LATIDO_MS,
  REINTENTO_MS,
  SERVICIOS,
  SERVIDOR_POR_DEFECTO,
  URL_VIGENCIA,
  armarEntrega,
  crearPuente,
  cuerpoPermitido,
  prepararPedido,
  servicioDe,
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
    alCambiarEstado: (estado, detalle) => {
      estados.push([estado, detalle]);
      datos.estado = estado;
    },
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
    "https://www.corteconstitucional.gov.co/relatoria/..%2f..%2fx",
    "https://www.corteconstitucional.gov.co/relatoria/%2e%2e%5cx",
    "https://www.corteconstitucional.gov.co/relatoria/2022/T%2D200-22.htm",
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

test("cierre 4401 tras una contraseña conserva la ficha guardada", async () => {
  const { puente, sockets, estados, reloj, almacen, datos } = armar({ ficha: "abc" });
  await puente.conectar("mala");
  sockets[0].abrir();
  sockets[0].cerrar(4401);
  assert.deepEqual(estados.at(-1), ["rechazada", ""]);
  assert.deepEqual(almacen.guardados, []);
  assert.equal(datos.ficha, "abc");
  assert.equal(reloj.luegos.length, 0);
});

for (const [codigo, estado] of [
  [4429, "bloqueada"],
  [4401, "rechazada"],
]) {
  test(`el estado ${estado} sobrevive a la vigilia sin credencial`, async () => {
    const { puente, sockets, estados } = armar({ ficha: null });
    await puente.conectar("mala");
    sockets[0].abrir();
    sockets[0].cerrar(codigo);
    await puente.conectar();
    assert.equal(sockets.length, 1);
    assert.deepEqual(estados, [
      ["conectando", ""],
      [estado, ""],
    ]);
  });
}

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

// --- Servicio de vigencia (1.1.0) ----------------------------------------------------------------------

const CEDULA = "52987613";
const FORMULARIO = Object.freeze({
  __VIEWSTATE: "/wEPDwUKLTE5NDQ5ODQ2NA9kFgJmD2QWAgIDD2Q=",
  __VIEWSTATEGENERATOR: "EC7CB15A",
  __EVENTVALIDATION: "/wEdAAYAbrxA3yjlCxnI9ccEY07lO0MZsW5iiFxn+s0P04VVra==",
  ddlCalidad: "1",
  ddlTipoDocumento: "1",
  txtDocumento: CEDULA,
  btnTpVigente: "Generar",
});
const PDF = new Uint8Array([37, 80, 68, 70, 45, 49, 46, 55, 10, 0, 255]);

function respuestaCon(status, cuerpo, { url = URL_VIGENCIA, tipo = null, largo = null, type = "basic" } = {}) {
  const cabeceras = new Headers();
  if (tipo !== null) cabeceras.set("content-type", tipo);
  if (largo !== null) cabeceras.set("content-length", String(largo));
  return { status, url, type, headers: cabeceras, arrayBuffer: async () => cuerpo.buffer.slice(0) };
}

function pedirVigencia(id, metodo = "POST", cambios = {}) {
  return { tipo: "pedir", id, servicio: "vigencia", url: URL_VIGENCIA, metodo, formulario: metodo === "GET" ? null : { ...FORMULARIO, ...cambios } };
}

async function atendido(mensaje, descargar) {
  const { socket } = await conectado({ descargar });
  socket.recibir(mensaje);
  await turno();
  await turno();
  const [entrega] = socket.binarios();
  return entrega;
}

test("la tabla de servicios: relatoría con GET, vigencia con GET y POST a una sola dirección", () => {
  assert.deepEqual(SERVICIOS.map((s) => [s.nombre, [...s.metodos]]), [["relatoria", ["GET"]], ["vigencia", ["GET", "POST"]]]);
  assert.equal(URL_VIGENCIA, "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx");
  assert.deepEqual(Object.keys(SERVICIOS[1].campos), Object.keys(FORMULARIO));
  assert.ok(Object.isFrozen(SERVICIOS) && SERVICIOS.every(Object.isFrozen) && Object.isFrozen(SERVICIOS[1].campos));
});

test("servicioDe acepta la página de vigencia solo con GET o POST", () => {
  assert.equal(servicioDe(URL_VIGENCIA)?.nombre, "vigencia");
  assert.equal(servicioDe(URL_VIGENCIA, "GET")?.nombre, "vigencia");
  assert.equal(servicioDe(URL_VIGENCIA, "POST")?.nombre, "vigencia");
  assert.equal(servicioDe("https://vigenciaspublicas.ramajudicial.gov.co:443/Certificados.aspx", "POST")?.nombre, "vigencia");
  assert.equal(servicioDe(URL_T200)?.nombre, "relatoria");
  assert.equal(urlPermitida(URL_VIGENCIA), false);
});

test("servicioDe rechaza otros métodos, hosts, rutas y direcciones con %", () => {
  const casos = [
    [URL_VIGENCIA, "PUT"],
    [URL_VIGENCIA, "DELETE"],
    [URL_VIGENCIA, "post"],
    [URL_VIGENCIA, ""],
    [URL_T200, "POST"],
    ["http://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx", "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co.evil.com/Certificados.aspx", "POST"],
    ["https://ramajudicial.gov.co/Certificados.aspx", "POST"],
    ["https://evil.com/Certificados.aspx", "POST"],
    ["https://vigenciaspublicas.ramajudicial.gov.co:8443/Certificados.aspx", "POST"],
    ["https://u:p@vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx", "POST"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/certificados.aspx", "POST"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx/x", "POST"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/Otra.aspx", "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/", "GET"],
    [`https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx?txtDocumento=${CEDULA}`, "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx?", "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx#x", "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/Certificados%2Easpx", "POST"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/%43ertificados.aspx", "GET"],
    ["https://vigenciaspublicas.ramajudicial.gov.co/relatoria/x", "GET"],
    ["no es una url", "GET"],
  ];
  for (const [url, metodo] of casos) assert.equal(servicioDe(url, metodo), null, `${metodo} ${url}`);
});

test("cuerpoPermitido arma exactamente los 7 campos en su orden", () => {
  const cuerpo = cuerpoPermitido("vigencia", FORMULARIO);
  assert.equal(typeof cuerpo, "string");
  assert.deepEqual([...new URLSearchParams(cuerpo)], Object.entries(FORMULARIO));
  const desordenado = Object.fromEntries(Object.entries(FORMULARIO).reverse());
  assert.equal(cuerpoPermitido("vigencia", desordenado), cuerpo);
  assert.ok(cuerpo.includes(`txtDocumento=${CEDULA}&`) && cuerpo.includes("ddlTipoDocumento=1&"));
  for (const documento of ["12345", "1234567890"]) {
    assert.notEqual(cuerpoPermitido("vigencia", { ...FORMULARIO, txtDocumento: documento }), null, documento);
  }
});

test("cuerpoPermitido acepta los campos ocultos de la página guardada", () => {
  const html = readFileSync(new URL("../../backend/tests/fixtures/vigencia/formulario.html", import.meta.url), "utf8");
  const ocultos = Object.fromEntries(
    [...html.matchAll(/<input type="hidden" name="(__[A-Z]+)" id="__[A-Z]+" value="([^"]*)"/g)].map((m) => [m[1], m[2]]),
  );
  assert.deepEqual(Object.keys(ocultos).sort(), ["__EVENTVALIDATION", "__VIEWSTATE", "__VIEWSTATEGENERATOR"]);
  assert.notEqual(cuerpoPermitido("vigencia", { ...FORMULARIO, ...ocultos }), null);
});

test("cuerpoPermitido rechaza cualquier otro formulario", () => {
  const sin = (campo) => Object.fromEntries(Object.entries(FORMULARIO).filter(([k]) => k !== campo));
  const casos = {
    "campo extra": { ...FORMULARIO, cedula: CEDULA },
    "campo extra vacío": { ...FORMULARIO, txtNombre: "" },
    "falta un campo": sin("btnTpVigente"),
    "falta la cédula": sin("txtDocumento"),
    "cédula de extranjería": { ...FORMULARIO, ddlTipoDocumento: "2" },
    "PPT": { ...FORMULARIO, ddlTipoDocumento: "4" },
    "licencia temporal": { ...FORMULARIO, ddlCalidad: "4" },
    "otro botón": { ...FORMULARIO, btnTpVigente: "Buscar" },
    "cédula con letra": { ...FORMULARIO, txtDocumento: `${CEDULA}x` },
    "cédula con puntos": { ...FORMULARIO, txtDocumento: "52.987.613" },
    "cédula de ancho completo": { ...FORMULARIO, txtDocumento: "５２９８７６１３" },
    "cédula con salto": { ...FORMULARIO, txtDocumento: `${CEDULA}\n` },
    "cédula corta": { ...FORMULARIO, txtDocumento: "1234" },
    "cédula larga": { ...FORMULARIO, txtDocumento: "12345678901" },
    "cédula numérica": { ...FORMULARIO, txtDocumento: 52987613 },
    "generador en minúsculas": { ...FORMULARIO, __VIEWSTATEGENERATOR: "ec7cb15a" },
    "estado con otro campo": { ...FORMULARIO, __VIEWSTATE: "abc&txtNombre=PEREZ" },
    "estado con espacios": { ...FORMULARIO, __VIEWSTATE: "datos del expediente" },
    "estado enorme": { ...FORMULARIO, __VIEWSTATE: "A".repeat(100_001) },
    "validación enorme": { ...FORMULARIO, __EVENTVALIDATION: "A".repeat(20_001) },
    "cuerpo enorme": { ...FORMULARIO, __VIEWSTATE: "+".repeat(90_000) },
    "nulo": null,
    "lista": Object.entries(FORMULARIO),
    "texto": new URLSearchParams(FORMULARIO).toString(),
  };
  for (const [nombre, formulario] of Object.entries(casos)) {
    assert.equal(cuerpoPermitido("vigencia", formulario), null, nombre);
  }
  assert.notEqual(cuerpoPermitido("vigencia", { ...FORMULARIO, __VIEWSTATE: "A".repeat(100_000) }), null);
  assert.equal(cuerpoPermitido("relatoria", FORMULARIO), null);
  assert.equal(cuerpoPermitido("otro", FORMULARIO), null);
  const contaminado = JSON.parse(`{"__proto__": {"x": 1}, ${JSON.stringify(FORMULARIO).slice(1)}`);
  assert.equal(cuerpoPermitido("vigencia", contaminado), null);
});

test("POST de vigencia: solo los 7 campos, con las cookies de la página y sin redirecciones, y devuelve el tipo", async () => {
  const llamadas = [];
  const entrega = await atendido(pedirVigencia("v1"), async (url, opciones) => {
    llamadas.push([url, opciones]);
    return respuestaCon(200, PDF, { tipo: "application/pdf" });
  });
  assert.equal(llamadas.length, 1);
  const [url, { signal, body, ...opciones }] = llamadas[0];
  assert.equal(url, URL_VIGENCIA);
  assert.deepEqual(opciones, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    credentials: "include",
    cache: "no-store",
    redirect: "manual",
    referrerPolicy: "no-referrer",
  });
  assert.ok(signal instanceof AbortSignal);
  assert.deepEqual([...new URLSearchParams(body)], Object.entries(FORMULARIO));
  assert.deepEqual(entrega.cabecera, { id: "v1", codigo: 200, detalle: "", tipo: "application/pdf" });
  assert.deepEqual([...entrega.cuerpo], [...PDF]);
});

test("GET de vigencia: con las cookies de la página, sin seguir redirecciones y con el tipo de la respuesta", async () => {
  const llamadas = [];
  const html = new TextEncoder().encode("<html>formulario</html>");
  const entrega = await atendido(pedirVigencia("v2", "GET"), async (url, opciones) => {
    llamadas.push([url, opciones]);
    return respuestaCon(200, html, { tipo: "text/html; charset=utf-8" });
  });
  const [url, { signal, ...opciones }] = llamadas[0];
  assert.equal(url, URL_VIGENCIA);
  assert.deepEqual(opciones, { credentials: "include", cache: "no-store", redirect: "manual", referrerPolicy: "no-referrer" });
  assert.deepEqual(entrega.cabecera, { id: "v2", codigo: 200, detalle: "", tipo: "text/html; charset=utf-8" });
  assert.deepEqual([...entrega.cuerpo], [...html]);
});

test("opciones de fetch por servicio: solo la vigencia lleva las cookies de su propia página", () => {
  const relatoria = { credentials: "omit", cache: "no-store", redirect: "follow", referrerPolicy: "no-referrer" };
  for (const mensaje of [
    { tipo: "pedido", id: "r1", url: URL_T200 },
    { tipo: "pedir", id: "r2", servicio: "relatoria", url: URL_T200, metodo: "GET", formulario: null },
  ]) {
    const [servicio, opciones] = prepararPedido(mensaje);
    assert.equal(servicio.nombre, "relatoria");
    assert.deepEqual(opciones, relatoria);
  }
  const [, get] = prepararPedido(pedirVigencia("v1", "GET"));
  assert.deepEqual(get, { ...relatoria, credentials: "include", redirect: "manual" });
  const [, { body, headers, ...post }] = prepararPedido(pedirVigencia("v2"));
  assert.deepEqual(post, { credentials: "include", cache: "no-store", redirect: "manual", referrerPolicy: "no-referrer", method: "POST" });
  assert.deepEqual(headers, { "Content-Type": "application/x-www-form-urlencoded" });
  assert.equal(typeof body, "string");
});

test("un error de la Rama Judicial se entrega con su código y su tipo", async () => {
  const entrega = await atendido(pedirVigencia("v3"), async () => respuestaCon(500, new Uint8Array([60]), { tipo: "text/html" }));
  assert.deepEqual(entrega.cabecera, { id: "v3", codigo: 500, detalle: "", tipo: "text/html" });
  const sinTipo = await atendido(pedirVigencia("v4"), async () => respuestaCon(200, PDF));
  assert.deepEqual(sinTipo.cabecera, { id: "v4", codigo: 200, detalle: "", tipo: null });
});

test("la relatoría nunca devuelve el tipo, aunque la respuesta lo traiga", async () => {
  for (const mensaje of [
    { tipo: "pedido", id: "r1", url: URL_T200 },
    { tipo: "pedir", id: "r1", servicio: "relatoria", url: URL_T200, metodo: "GET", formulario: null },
  ]) {
    const entrega = await atendido(mensaje, async () => respuestaCon(200, new Uint8Array([1]), { url: URL_T200, tipo: "text/html" }));
    assert.deepEqual(entrega.cabecera, { id: "r1", codigo: 200, detalle: "" });
  }
});

test("una redirección fuera de la página de vigencia no entrega bytes", async () => {
  for (const url of [
    "https://vigenciaspublicas.ramajudicial.gov.co/Error.aspx",
    "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx?aspxerrorpath=/",
    URL_T200,
    "https://evil.com/Certificados.aspx",
  ]) {
    const entrega = await atendido(pedirVigencia("v5", "GET"), async () => respuestaCon(200, PDF, { url, tipo: "application/pdf" }));
    assert.deepEqual(entrega.cabecera, { id: "v5", codigo: null, detalle: "redirección no permitida" }, url);
    assert.equal(entrega.cuerpo.length, 0);
  }
  const opaca = await atendido(pedirVigencia("v6"), async () => respuestaCon(0, new Uint8Array(0), { type: "opaqueredirect" }));
  assert.deepEqual(opaca.cabecera, { id: "v6", codigo: null, detalle: "redirección no permitida" });
});

test("una redirección del GET de vigencia se rechaza sin seguirla", async () => {
  const llamadas = [];
  const entrega = await atendido(pedirVigencia("v9", "GET"), async (url, opciones) => {
    llamadas.push([url, opciones.redirect, opciones.credentials]);
    return respuestaCon(0, new Uint8Array(0), { type: "opaqueredirect" });
  });
  assert.deepEqual(llamadas, [[URL_VIGENCIA, "manual", "include"]]);
  assert.deepEqual(entrega.cabecera, { id: "v9", codigo: null, detalle: "redirección no permitida" });
  assert.equal(entrega.cuerpo.length, 0);
});

test("una respuesta de vigencia de más de 2 MB no se entrega", async () => {
  const declarada = await atendido(pedirVigencia("v7"), async () =>
    respuestaCon(200, PDF, { tipo: "application/pdf", largo: 2_000_001 }),
  );
  assert.deepEqual(declarada.cabecera, { id: "v7", codigo: null, detalle: "respuesta demasiado grande" });
  const real = await atendido(pedirVigencia("v8"), async () => respuestaCon(200, new Uint8Array(2_000_001), { tipo: "application/pdf" }));
  assert.deepEqual(real.cabecera, { id: "v8", codigo: null, detalle: "respuesta demasiado grande" });
  assert.equal(real.cuerpo.length, 0);
});

test("pedidos de vigencia fuera de la lista no descargan nada", async () => {
  const casos = {
    "con el mensaje de 1.0.0": [{ tipo: "pedido", id: "x", url: URL_VIGENCIA }, "URL fuera de la relatoría"],
    "servicio cambiado": [{ ...pedirVigencia("x", "GET"), servicio: "relatoria" }, "pedido fuera de los servicios permitidos"],
    "servicio desconocido": [{ ...pedirVigencia("x", "GET"), servicio: "otro" }, "pedido fuera de los servicios permitidos"],
    "método PUT": [{ ...pedirVigencia("x"), metodo: "PUT" }, "pedido fuera de los servicios permitidos"],
    "sin método": [{ ...pedirVigencia("x", "GET"), metodo: undefined }, "pedido fuera de los servicios permitidos"],
    "otro host": [{ ...pedirVigencia("x"), url: "https://evil.com/Certificados.aspx" }, "pedido fuera de los servicios permitidos"],
    "% en la ruta": [{ ...pedirVigencia("x"), url: "https://vigenciaspublicas.ramajudicial.gov.co/Certificados%2Easpx" }, "pedido fuera de los servicios permitidos"],
    "POST a la relatoría": [{ ...pedirVigencia("x"), servicio: "relatoria", url: URL_T200 }, "pedido fuera de los servicios permitidos"],
    "GET con formulario": [{ ...pedirVigencia("x"), metodo: "GET" }, "formulario no permitido"],
    "campo extra": [pedirVigencia("x", "POST", { cedula: CEDULA }), "formulario no permitido"],
    "cédula de extranjería": [pedirVigencia("x", "POST", { ddlTipoDocumento: "2" }), "formulario no permitido"],
    "cédula con letras": [pedirVigencia("x", "POST", { txtDocumento: "5298761A" }), "formulario no permitido"],
    "cuerpo enorme": [pedirVigencia("x", "POST", { __VIEWSTATE: "+".repeat(90_000) }), "formulario no permitido"],
    "POST sin formulario": [{ ...pedirVigencia("x"), formulario: null }, "formulario no permitido"],
  };
  for (const [nombre, [mensaje, detalle]] of Object.entries(casos)) {
    const entrega = await atendido(mensaje, async () => assert.fail(`no debía descargar: ${nombre}`));
    assert.deepEqual(entrega.cabecera, { id: "x", codigo: null, detalle }, nombre);
    assert.equal(entrega.cuerpo.length, 0, nombre);
  }
});

test("el manifiesto: versión 1.1.0, solo la relatoría y la página exacta de vigencia, sin permisos nuevos", () => {
  const manifiesto = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
  assert.equal(manifiesto.version, "1.1.0");
  assert.deepEqual(manifiesto.host_permissions, [
    "https://www.corteconstitucional.gov.co/relatoria/*",
    "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx",
  ]);
  assert.deepEqual(manifiesto.permissions, ["alarms", "storage"]);
  assert.ok(manifiesto.name.length <= 75 && manifiesto.description.length <= 132);
});
