import { SERVIDOR_POR_DEFECTO } from "./puente.js";

const TEXTOS = {
  conectada: (servidor) => `Conectada a ${servidor}.`,
  conectando: (servidor) => `Conectando con ${servidor}…`,
  sin_contrasena: () => "Escriba la contraseña de judicabot para conectar.",
  rechazada: () => "El servidor rechazó la contraseña.",
  bloqueada: () => "Demasiados intentos. Espere unos minutos.",
  desconectada: (servidor) => `Sin conexión con ${servidor}; se reintenta sola.`,
};

const formulario = document.getElementById("formulario");
const campoServidor = document.getElementById("servidor");
const campoContrasena = document.getElementById("contrasena");
const boton = document.getElementById("conectar");
const linea = document.getElementById("estado");

async function mostrarEstado() {
  const { servidor, estado, detalle } = await chrome.storage.local.get(["servidor", "estado", "detalle"]);
  const texto = TEXTOS[estado]?.(servidor || SERVIDOR_POR_DEFECTO) ?? "";
  linea.textContent = estado === "desconectada" && detalle ? `${texto} (${detalle})` : texto;
}

formulario.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  boton.disabled = true;
  try {
    await chrome.runtime.sendMessage({
      tipo: "configurar",
      servidor: new URL(campoServidor.value).origin,
      contrasena: campoContrasena.value,
    });
    campoContrasena.value = "";
  } finally {
    boton.disabled = false;
  }
});

chrome.storage.onChanged.addListener((_cambios, area) => {
  if (area === "local") mostrarEstado();
});

const { servidor } = await chrome.storage.local.get("servidor");
campoServidor.value = servidor || SERVIDOR_POR_DEFECTO;
mostrarEstado();
