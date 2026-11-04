import type { CasoResumen, EstadoCasoApi } from "../../api/contrato";
import type { VarianteBoton } from "../../ui";

export type GrupoCaso = "atencion" | "trabajando" | "terminados";
export type TonoFicha = "" | "sello" | "alerta" | "ok" | "trabajando";

export const GRUPOS: readonly { id: GrupoCaso; titulo: string }[] = [
  { id: "atencion", titulo: "Requieren su atención" },
  { id: "trabajando", titulo: "En redacción" },
  { id: "terminados", titulo: "Terminados" },
];

export const TRAMOS = ["Documentos", "Borrador", "Decisión", "Fallo"] as const;

export function grupoDe(estado: EstadoCasoApi): GrupoCaso {
  if (estado === "corriendo") return "trabajando";
  if (estado === "terminado") return "terminados";
  return "atencion";
}

export function tonoDe(estado: EstadoCasoApi): TonoFicha {
  switch (estado) {
    case "esperando_decision":
      return "sello";
    case "incompleto":
    case "error":
      return "alerta";
    case "corriendo":
      return "trabajando";
    case "terminado":
      return "ok";
    default:
      return "";
  }
}

export function etapaDestino(caso: Pick<CasoResumen, "estado" | "etapa">): string {
  switch (caso.estado) {
    case "esperando_decision":
      return "borrador";
    case "corriendo":
      return "proceso";
    case "terminado":
      return "fallo";
    case "error":
      return caso.etapa === 0 ? "documentos" : "proceso";
    default:
      return "documentos";
  }
}

export const hrefCaso = (caso: Pick<CasoResumen, "id" | "estado" | "etapa">) =>
  `#/segunda/${encodeURIComponent(caso.id)}/${etapaDestino(caso)}`;

const ACCIONES: Record<EstadoCasoApi, string> = {
  sin_iniciar: "Procesar documentos",
  incompleto: "Completar",
  revision: "Revisar documentos",
  esperando_decision: "Decidir",
  terminado: "Ver fallo",
  error: "Ver el error",
  corriendo: "Ver avance",
};

export const accionDe = (estado: EstadoCasoApi) => ACCIONES[estado];

export const varianteDe = (estado: EstadoCasoApi): VarianteBoton => (estado === "esperando_decision" ? "sello" : "secundario");

export type EstadoTramo = "h" | "a" | "";

export const tramosDe = (etapa: number): EstadoTramo[] =>
  TRAMOS.map((_, i): EstadoTramo => (i < etapa ? "h" : i === etapa ? "a" : ""));

export function descripcionAvance(etapa: number): string {
  if (etapa >= TRAMOS.length) return "Avance: completo";
  return `Avance: paso ${etapa + 1} de ${TRAMOS.length}, ${TRAMOS[etapa]}`;
}

const prioridad = (c: CasoResumen) => (c.estado === "esperando_decision" ? 0 : c.estado === "error" || c.estado === "incompleto" ? 1 : 2);

export function ordenar(casos: CasoResumen[]): CasoResumen[] {
  return [...casos].sort((a, b) => prioridad(a) - prioridad(b) || b.actualizado.localeCompare(a.actualizado));
}

export const agrupar = (casos: CasoResumen[]): { id: GrupoCaso; titulo: string; casos: CasoResumen[] }[] => {
  const ordenados = ordenar(casos);
  return GRUPOS.map((g) => ({ ...g, casos: ordenados.filter((c) => grupoDe(c.estado) === g.id) })).filter((g) => g.casos.length > 0);
};

const plano = (texto: string) =>
  texto
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();

const compacto = (texto: string) => texto.replace(/[^a-z0-9]/g, "");

export function filtrar(casos: CasoResumen[], consulta: string): CasoResumen[] {
  const q = plano(consulta.trim());
  if (!q) return casos;
  const qCompacto = compacto(q);
  return casos.filter((c) => {
    const texto = plano([c.nombre, c.id, c.radicado, c.accionante, c.juzgado_a_quo, ...c.accionadas].filter(Boolean).join(" "));
    return texto.includes(q) || (qCompacto !== "" && compacto(texto).includes(qCompacto));
  });
}

export function partesDe(caso: Pick<CasoResumen, "nombre" | "accionante" | "accionadas">): string | null {
  const { accionante, accionadas } = caso;
  if (!accionante || plano(caso.nombre).includes(plano(accionante))) return null;
  return accionadas.length > 0 ? `${accionante} c. ${accionadas.join(", ")}` : accionante;
}
