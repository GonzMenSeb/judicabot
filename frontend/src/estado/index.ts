import { signal } from "@preact/signals";

export interface Preferencias {
  modelo: string | null;
}

export const casoActual = signal<string | null>(null);
export const jobActual = signal<string | null>(null);
export const preferencias = signal<Preferencias>({ modelo: null });
/** Sube cuando los casos del servidor cambian fuera de la lista que se ve (Deshacer, 409 al eliminar): Inicio y la página del proceso recargan. */
export const versionCasos = signal(0);

export { sincronizarDataset } from "./dataset";
export { diaIso, enumerar, fechaCorta, fechaRelativa, nombreModelo, plural, pluralizar, porcentaje, textoDiasRestantes } from "./formato";
export {
  cargarEstadoServidor,
  claveActiva,
  claveDe,
  DATOS_PROVEEDOR,
  errorEstadoServidor,
  estadoServidor,
  proveedorDelCaso,
  proveedorSinClave,
} from "./servidor";
export { tituloVista, useTitulo } from "./titulo";
export { cerrarToast, mostrarToast, toasts } from "./toasts";
export type { AccionToast, OpcionesToast, Toast } from "./toasts";
