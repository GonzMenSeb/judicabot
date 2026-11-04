import { api, ErrorApi, MENSAJE_RED } from "../../api";
import type { CrearCasoRespuesta } from "../../api/contrato";
import type { ArchivoSeleccionado } from "./carpeta";

export { MENSAJE_RED };

export function cuerpoCaso(archivos: ArchivoSeleccionado[], nombre: string): FormData {
  const datos = new FormData();
  const limpio = nombre.trim();
  if (limpio) datos.append("nombre", limpio);
  for (const { archivo, ruta } of archivos) datos.append("files", archivo, ruta);
  return datos;
}

function textosDe(detalle: unknown): string[] {
  if (typeof detalle === "string") return [detalle];
  if (Array.isArray(detalle)) return detalle.flatMap(textosDe);
  if (typeof detalle === "object" && detalle !== null) {
    const registro = detalle as Record<string, unknown>;
    if (Array.isArray(registro.errores)) return registro.errores.flatMap(textosDe);
    if (typeof registro.mensaje === "string") return [registro.mensaje];
    if (typeof registro.msg === "string") return [registro.msg];
  }
  return [];
}

export function mensajeError(error: unknown, porDefecto: string): string {
  if (error instanceof ErrorApi) {
    if (error.estado === 0) return MENSAJE_RED;
    const textos = textosDe(error.detalle);
    if (textos.length > 0) return textos.join(" ");
    if (error.estado === 409) return "Ya hay una operación en curso para este caso.";
    if (error.estado === 422) return "El servidor no aceptó los datos enviados.";
    if (error.estado >= 500) return "El servidor tuvo un problema. Intente de nuevo en unos instantes.";
    return error.message || porDefecto;
  }
  if (error instanceof TypeError) return MENSAJE_RED;
  return porDefecto;
}

function respuestaJson(texto: string): { detail?: unknown } & Partial<CrearCasoRespuesta> {
  try {
    const valor: unknown = JSON.parse(texto);
    return typeof valor === "object" && valor !== null ? valor : {};
  } catch {
    return {};
  }
}

function simularProgreso(alProgreso: (fraccion: number) => void, signal?: AbortSignal): Promise<void> {
  return new Promise((ok, mal) => {
    let paso = 0;
    const reloj = setInterval(() => {
      paso += 1;
      alProgreso(Math.min(paso / 6, 1));
      if (paso >= 6) {
        clearInterval(reloj);
        ok();
      }
    }, 250);
    signal?.addEventListener("abort", () => {
      clearInterval(reloj);
      mal(new DOMException("Subida cancelada", "AbortError"));
    });
  });
}

export async function subirCaso(
  datos: FormData,
  alProgreso: (fraccion: number) => void,
  signal?: AbortSignal,
): Promise<CrearCasoRespuesta> {
  if (import.meta.env.VITE_MOCK) {
    await simularProgreso(alProgreso, signal);
    return api.post<CrearCasoRespuesta>("/api/casos", datos);
  }
  return new Promise<CrearCasoRespuesta>((ok, mal) => {
    if (signal?.aborted) {
      mal(new DOMException("Subida cancelada", "AbortError"));
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/casos");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.addEventListener("progress", (ev) => {
      if (ev.lengthComputable && ev.total > 0) alProgreso(ev.loaded / ev.total);
    });
    xhr.addEventListener("load", () => {
      const cuerpo = respuestaJson(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300 && typeof cuerpo.id === "string") {
        alProgreso(1);
        ok({ id: cuerpo.id, n_insumos: cuerpo.n_insumos ?? 0 });
        return;
      }
      const detalle = cuerpo.detail ?? null;
      const textos = textosDe(detalle);
      mal(new ErrorApi(xhr.status, detalle, textos.join(" ") || `Error ${xhr.status}`));
    });
    xhr.addEventListener("error", () => mal(new ErrorApi(0, null, MENSAJE_RED)));
    xhr.addEventListener("abort", () => mal(new DOMException("Subida cancelada", "AbortError")));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(datos);
  });
}
