import { vi } from "vitest";

export type Respuestas = Record<string, () => Response | Promise<Response>>;

export const json = (cuerpo: unknown, estado = 200) =>
  new Response(JSON.stringify(cuerpo), { status: estado, headers: { "Content-Type": "application/json" } });

export function simularFetch(respuestas: Respuestas) {
  const llamadas: { metodo: string; ruta: string; cuerpo: unknown }[] = [];
  const falso = vi.fn(async (ruta: string, init?: RequestInit) => {
    const metodo = init?.method ?? "GET";
    llamadas.push({ metodo, ruta, cuerpo: typeof init?.body === "string" ? JSON.parse(init.body) : init?.body });
    const manejador = respuestas[`${metodo} ${ruta}`];
    if (!manejador) throw new TypeError(`Sin respuesta simulada para ${metodo} ${ruta}`);
    return manejador();
  });
  vi.stubGlobal("fetch", falso);
  return llamadas;
}

type Oyente = (ev: Event) => void;

export class XhrFalso {
  static ultimo: XhrFalso | null = null;
  readonly upload = new EventTarget();
  status = 0;
  responseText = "";
  metodo = "";
  url = "";
  cuerpo: unknown = null;
  abortado = false;
  private oyentes = new Map<string, Oyente[]>();

  constructor() {
    XhrFalso.ultimo = this;
  }

  open(metodo: string, url: string) {
    this.metodo = metodo;
    this.url = url;
  }

  setRequestHeader() {}

  addEventListener(tipo: string, oyente: Oyente) {
    this.oyentes.set(tipo, [...(this.oyentes.get(tipo) ?? []), oyente]);
  }

  send(cuerpo: unknown) {
    this.cuerpo = cuerpo;
  }

  abort() {
    this.abortado = true;
    this.emitir("abort");
  }

  progreso(cargado: number, total: number) {
    this.upload.dispatchEvent(new ProgressEvent("progress", { lengthComputable: true, loaded: cargado, total }));
  }

  responder(estado: number, cuerpo: unknown) {
    this.status = estado;
    this.responseText = typeof cuerpo === "string" ? cuerpo : JSON.stringify(cuerpo);
    this.emitir("load");
  }

  fallarRed() {
    this.emitir("error");
  }

  private emitir(tipo: string) {
    this.oyentes.get(tipo)?.forEach((o) => o(new Event(tipo)));
  }
}

export function archivoDe(ruta: string, contenido = "x"): File {
  const nombre = ruta.split("/").pop() ?? ruta;
  const archivo = new File([contenido], nombre, { type: "application/pdf" });
  Object.defineProperty(archivo, "webkitRelativePath", { value: ruta.includes("/") ? ruta : "" });
  return archivo;
}
