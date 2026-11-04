import { useEffect, useMemo, useRef, useState } from "preact/hooks";

export interface Evento {
  n: number;
  t: string;
  etapa: "ingesta" | "apertura" | "consideraciones" | "verificacion" | "caso_concreto" | "documentos" | "sistema";
  tipo: "lee" | "razona" | "escribe" | "verifica" | "sistema" | "error";
  texto: string;
  datos: Record<string, unknown> | null;
}

export interface Fin {
  estado: "terminado" | "error";
  error: string | null;
}

export type Conexion = "conectando" | "abierto" | "cerrado" | "fallido";

export interface FuenteEventos {
  eventos: Evento[];
  fin: Fin | null;
  conexion: Conexion;
}

export type Cambio = { evento: Evento } | { fin: Fin } | { conexion: Conexion };

export const MAX_EVENTOS = 2000;
const MAX_FALLOS = 8;
const ESPERA_BASE_MS = 500;
const ESPERA_MAX_MS = 5000;

type Meta = Pick<FuenteEventos, "fin" | "conexion">;

const META_INICIAL: Meta = { fin: null, conexion: "conectando" };

export function conCursor(url: string, ultimo: number): string {
  if (ultimo < 0) return url;
  return `${url}${url.includes("?") ? "&" : "?"}desde=${ultimo}`;
}

function leer<T>(ev: Event): T | null {
  try {
    return JSON.parse((ev as MessageEvent<string>).data) as T;
  } catch {
    return null;
  }
}

export function conectarEventos(url: string, alCambiar: (cambio: Cambio) => void): () => void {
  let ultimo = -1;
  let fallos = 0;
  let cerrado = false;
  let fuente: EventSource | null = null;
  let temporizador: ReturnType<typeof setTimeout> | undefined;

  const cerrar = () => {
    cerrado = true;
    clearTimeout(temporizador);
    fuente?.close();
    fuente = null;
  };

  const abrir = () => {
    const actual = new EventSource(conCursor(url, ultimo));
    fuente = actual;
    actual.addEventListener("open", () => {
      fallos = 0;
      alCambiar({ conexion: "abierto" });
    });
    actual.addEventListener("evento", (ev) => {
      const evento = leer<Evento>(ev);
      if (!evento || evento.n <= ultimo) return;
      ultimo = evento.n;
      alCambiar({ evento });
    });
    actual.addEventListener("fin", (ev) => {
      const fin = leer<Fin>(ev);
      if (fin) alCambiar({ fin });
      alCambiar({ conexion: "cerrado" });
      cerrar();
    });
    actual.addEventListener("error", () => {
      actual.close();
      if (cerrado) return;
      fallos += 1;
      if (fallos > MAX_FALLOS) {
        alCambiar({ conexion: "fallido" });
        return;
      }
      alCambiar({ conexion: "conectando" });
      temporizador = setTimeout(abrir, Math.min(ESPERA_BASE_MS * 2 ** (fallos - 1), ESPERA_MAX_MS));
    });
  };

  abrir();
  return cerrar;
}

export function agregarEvento(buffer: Evento[], evento: Evento): void {
  buffer.push(evento);
  if (buffer.length > MAX_EVENTOS * 2) buffer.splice(0, buffer.length - MAX_EVENTOS);
}

export function useEventos(url: string | null): FuenteEventos {
  const buffer = useRef<Evento[]>([]);
  const [version, setVersion] = useState(0);
  const [meta, setMeta] = useState<Meta>(META_INICIAL);

  useEffect(() => {
    if (buffer.current.length > 0) {
      buffer.current = [];
      setVersion((v) => v + 1);
    }
    setMeta(META_INICIAL);
    if (!url) return undefined;
    return conectarEventos(url, (cambio) => {
      if ("evento" in cambio) {
        agregarEvento(buffer.current, cambio.evento);
        setVersion((v) => v + 1);
      } else if ("fin" in cambio) {
        setMeta((previo) => ({ ...previo, fin: cambio.fin }));
      } else {
        setMeta((previo) => ({ ...previo, conexion: cambio.conexion }));
      }
    });
  }, [url]);

  const eventos = useMemo(() => buffer.current.slice(-MAX_EVENTOS), [version]);
  return useMemo(() => ({ eventos, fin: meta.fin, conexion: meta.conexion }), [eventos, meta]);
}
