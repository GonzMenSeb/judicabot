import { ErrorApi } from "../../api/cliente";
import type { PreferenciasIa, PreferenciasIaCuerpo } from "../../api/contrato";
import type { MockRuta } from "../../api/mock";

let preferencias: PreferenciasIa = {
  modelo: "claude-sonnet-5-5",
  modelos: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
  api_key: true,
  jev_key: false,
  jev: { modo: "apagado", umbral: 0.9 },
  effort: "high",
  max_tokens: 64000,
  max_retries: 1,
};

function errores(cuerpo: PreferenciasIaCuerpo): { campo: string; mensaje: string }[] {
  const lista: { campo: string; mensaje: string }[] = [];
  if (!preferencias.modelos.includes(cuerpo.modelo)) lista.push({ campo: "modelo", mensaje: "debe ser uno de: claude-sonnet-5-5, claude-haiku-5-5 o claude-opus-5-5." });
  if (!(cuerpo.jev.umbral >= 0 && cuerpo.jev.umbral <= 1)) lista.push({ campo: "jev.umbral", mensaje: "debe estar entre 0 y 1." });
  if (!Number.isInteger(cuerpo.max_tokens) || cuerpo.max_tokens < 1 || cuerpo.max_tokens > 64000) lista.push({ campo: "max_tokens", mensaje: "debe estar entre 1 y 64000." });
  if (!Number.isInteger(cuerpo.max_retries) || cuerpo.max_retries < 0 || cuerpo.max_retries > 5) lista.push({ campo: "max_retries", mensaje: "debe estar entre 0 y 5." });
  return lista;
}

const claveDe = (cuerpo: unknown): string => (typeof cuerpo === "object" && cuerpo !== null && "key" in cuerpo ? String(cuerpo.key).trim() : "");

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: "/api/ia", respuesta: () => structuredClone(preferencias) },
  {
    metodo: "PUT",
    ruta: "/api/ia",
    respuesta: ({ cuerpo }) => {
      const nuevo = cuerpo as PreferenciasIaCuerpo;
      const lista = errores(nuevo);
      if (lista.length) throw new ErrorApi(422, { errores: lista }, "Error 422");
      preferencias = { ...preferencias, ...nuevo, jev: { ...nuevo.jev } };
      return structuredClone(preferencias);
    },
  },
  {
    metodo: "POST",
    ruta: "/api/api-key",
    respuesta: ({ cuerpo }) => {
      if (!claveDe(cuerpo)) throw new ErrorApi(422, "La API key no puede estar vacía.", "La API key no puede estar vacía.");
      preferencias = { ...preferencias, api_key: true };
      return { api_key: true };
    },
  },
  {
    metodo: "POST",
    ruta: "/api/jev-key",
    respuesta: ({ cuerpo }) => {
      const clave = claveDe(cuerpo);
      if (!clave) throw new ErrorApi(422, "La clave de Jev no puede estar vacía.", "La clave de Jev no puede estar vacía.");
      if (!/^[\x21-\x7e]+$/.test(clave)) {
        const mensaje = "La clave de Jev solo admite caracteres ASCII visibles, sin espacios ni saltos de línea.";
        throw new ErrorApi(422, mensaje, mensaje);
      }
      preferencias = { ...preferencias, jev_key: true };
      return { jev_key: true };
    },
  },
];
