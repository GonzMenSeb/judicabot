import type { Metodo } from "./mock";

export class ErrorApi extends Error {
  readonly estado: number;
  readonly detalle: unknown;

  constructor(estado: number, detalle: unknown, mensaje: string) {
    super(mensaje);
    this.name = "ErrorApi";
    this.estado = estado;
    this.detalle = detalle;
  }
}

export interface Opciones {
  signal?: AbortSignal;
  cuerpo?: unknown;
}

export const esAbortado = (error: unknown): boolean => error instanceof DOMException && error.name === "AbortError";

export const MENSAJE_RED = "No se pudo conectar con el servidor. Revise su conexión e intente de nuevo.";

export const esCasoNoEncontrado = (error: unknown): boolean =>
  error instanceof ErrorApi && error.estado === 404 && typeof error.detalle === "string" && /^Caso no encontrado/i.test(error.detalle);

function mensajeDe(detalle: unknown, estado: number): string {
  if (typeof detalle === "string") return detalle;
  return `Error ${estado}`;
}

export async function peticion<T>(metodo: Metodo, ruta: string, opciones: Opciones = {}): Promise<T> {
  if (import.meta.env.VITE_MOCK) {
    const { resolverMock } = await import("./mock");
    const simulada = resolverMock({ metodo, ruta, cuerpo: opciones.cuerpo });
    if (simulada) return (await simulada) as T;
  }

  const cabeceras: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method: metodo, headers: cabeceras };
  if (opciones.signal) init.signal = opciones.signal;
  if (opciones.cuerpo instanceof FormData) {
    init.body = opciones.cuerpo;
  } else if (opciones.cuerpo !== undefined) {
    cabeceras["Content-Type"] = "application/json";
    init.body = JSON.stringify(opciones.cuerpo);
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(ruta, init);
  } catch (error) {
    if (!esAbortado(error) && error instanceof TypeError) throw new ErrorApi(0, null, MENSAJE_RED);
    throw error;
  }
  if (!respuesta.ok) {
    const cuerpo: unknown = await respuesta.json().catch(() => null);
    const detalle = typeof cuerpo === "object" && cuerpo !== null && "detail" in cuerpo ? cuerpo.detail : null;
    throw new ErrorApi(respuesta.status, detalle, mensajeDe(detalle, respuesta.status));
  }
  if (respuesta.status === 204) return undefined as T;
  return (await respuesta.json()) as T;
}

export const api = {
  get: <T>(ruta: string, opciones?: Opciones) => peticion<T>("GET", ruta, opciones),
  post: <T>(ruta: string, cuerpo?: unknown, opciones?: Opciones) => peticion<T>("POST", ruta, { ...opciones, cuerpo }),
  put: <T>(ruta: string, cuerpo?: unknown, opciones?: Opciones) => peticion<T>("PUT", ruta, { ...opciones, cuerpo }),
  delete: <T>(ruta: string, opciones?: Opciones) => peticion<T>("DELETE", ruta, opciones),
};

export function cancelable(): () => AbortSignal {
  let controlador: AbortController | null = null;
  return () => {
    controlador?.abort();
    controlador = new AbortController();
    return controlador.signal;
  };
}
