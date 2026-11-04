import type { EtapaEvento, Evento, FinJob, TipoEvento } from "../../api/contrato";

export type EtapaProceso = Exclude<EtapaEvento, "sistema">;
export type EstadoEtapa = "hecho" | "actual" | "espera" | "error";

export const ETAPAS: readonly { id: EtapaProceso; titulo: string; detalle: string }[] = [
  { id: "ingesta", titulo: "Lectura del expediente", detalle: "Texto de cada PDF y rol de cada documento" },
  { id: "apertura", titulo: "Apertura", detalle: "Antecedentes, sentencia impugnada, impugnación" },
  { id: "consideraciones", titulo: "Consideraciones", detalle: "Marco jurídico y jurisprudencia" },
  { id: "verificacion", titulo: "Verificación de citas", detalle: "Cada sentencia contra la relatoría" },
  { id: "caso_concreto", titulo: "Caso concreto", detalle: "Su decisión aplicada a los hechos" },
  { id: "documentos", titulo: "Documentos", detalle: "Fallo y documentos de apoyo" },
];

export const ETIQUETA_TIPO: Record<TipoEvento, string> = {
  lee: "Lee",
  razona: "Razona",
  escribe: "Redacta",
  verifica: "Verifica",
  sistema: "Sistema",
  error: "Error",
};

export interface Agrupado {
  porEtapa: Record<EtapaProceso, Evento[]>;
  huerfanos: Evento[];
  activa: EtapaProceso | null;
}

export const indiceEtapa = (etapa: EtapaProceso | null): number => (etapa ? ETAPAS.findIndex((e) => e.id === etapa) : -1);

export function datosEtapa(etapa: EtapaProceso) {
  return ETAPAS[indiceEtapa(etapa)] ?? ETAPAS[0]!;
}

export function agrupar(eventos: readonly Evento[]): Agrupado {
  const porEtapa = Object.fromEntries(ETAPAS.map((e) => [e.id, [] as Evento[]])) as Record<EtapaProceso, Evento[]>;
  const huerfanos: Evento[] = [];
  let activa: EtapaProceso | null = null;
  for (const evento of eventos) {
    if (evento.etapa === "sistema") {
      if (activa) porEtapa[activa].push(evento);
      else huerfanos.push(evento);
      continue;
    }
    if (huerfanos.length) {
      porEtapa[evento.etapa].push(...huerfanos);
      huerfanos.length = 0;
    }
    porEtapa[evento.etapa].push(evento);
    activa = evento.etapa;
  }
  return { porEtapa, huerfanos, activa };
}

export function estadoEtapas(activa: EtapaProceso | null, fin: FinJob | null): Record<EtapaProceso, EstadoEtapa> {
  const ia = indiceEtapa(activa);
  return Object.fromEntries(
    ETAPAS.map((e, i): [EtapaProceso, EstadoEtapa] => {
      if (i < ia) return [e.id, "hecho"];
      if (i > ia) return [e.id, "espera"];
      if (!fin) return [e.id, "actual"];
      return [e.id, fin.estado === "error" ? "error" : "hecho"];
    }),
  ) as Record<EtapaProceso, EstadoEtapa>;
}

export function formatearTiempo(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutos = String(Math.floor(total / 60)).padStart(2, "0");
  const segundos = String(total % 60).padStart(2, "0");
  return `${minutos}:${segundos}`;
}

export function marcaDe(evento: Evento, inicio: number): string {
  const t = Date.parse(evento.t);
  return Number.isNaN(t) || Number.isNaN(inicio) ? "" : formatearTiempo(t - inicio);
}

export function duracionEventos(eventos: readonly Evento[]): number {
  const primero = eventos[0];
  const ultimo = eventos[eventos.length - 1];
  if (!primero || !ultimo) return 0;
  const d = Date.parse(ultimo.t) - Date.parse(primero.t);
  return Number.isNaN(d) ? 0 : Math.max(0, d);
}

export function mensajeError(fin: FinJob | null, eventos: readonly Evento[]): string {
  if (fin?.error) return fin.error;
  const ultimo = [...eventos].reverse().find((e) => e.tipo === "error");
  return ultimo?.texto ?? "La ejecución se detuvo antes de terminar.";
}
