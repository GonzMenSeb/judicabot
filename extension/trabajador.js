import { crearPuente } from "./puente.js";

const puente = crearPuente({
  crearSocket: (url) => {
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    return socket;
  },
  descargar: (url, opciones) => fetch(url, opciones),
  almacen: {
    leer: () => chrome.storage.local.get(["servidor", "ficha", "estado"]),
    guardar: (parcial) => chrome.storage.local.set(parcial),
  },
  reloj: {
    cada: (ms, fn) => setInterval(fn, ms),
    cancelar: (id) => clearInterval(id),
    luego: (ms, fn) => setTimeout(fn, ms),
  },
  version: chrome.runtime.getManifest().version,
  alCambiarEstado: (estado, detalle) => {
    chrome.storage.local.set({ estado, detalle });
    chrome.action.setBadgeText({ text: estado === "conectada" ? "" : "!" });
  },
});

chrome.runtime.onStartup.addListener(() => puente.conectar());
chrome.runtime.onInstalled.addListener(() => puente.conectar());
chrome.alarms.onAlarm.addListener((alarma) => {
  if (alarma.name === "vigilia") puente.conectar();
});

chrome.runtime.onMessage.addListener((mensaje, _remitente, responder) => {
  if (mensaje?.tipo !== "configurar") return false;
  chrome.storage.local
    .get("servidor")
    .then(({ servidor }) =>
      chrome.storage.local.set(servidor === mensaje.servidor ? { servidor } : { servidor: mensaje.servidor, ficha: null }),
    )
    .then(() => puente.conectar(mensaje.contrasena))
    .then(
      () => responder({ ok: true }),
      (error) => responder({ ok: false, detalle: String(error?.message ?? error) }),
    );
  return true;
});

chrome.alarms.get("vigilia").then((alarma) => {
  if (!alarma) chrome.alarms.create("vigilia", { periodInMinutes: 0.5 });
});

puente.conectar();
