import type { CasoResumen, EstadoCasoApi } from "../../api/contrato";
import type { VarianteBoton } from "../../ui";

export type TonoFicha = "" | "sello" | "alerta" | "ok" | "trabajando";

export const TRAMOS = ["Documentos", "Borrador", "Decisión", "Fallo"] as const;

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

/** Texto sin tildes y en minúsculas, para comparar sin importar cómo se escribió. */
export const plano = (texto: string) =>
  texto
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();

const compacto = (texto: string) => texto.replace(/[^a-z0-9]/g, "");

/**
 * ¿El caso coincide con la búsqueda? Busca en nombre, id, radicado, accionante, juzgado y accionadas,
 * sin tildes ni mayúsculas; si no aparece tal cual, compara solo letras y números ("2026-00412" = "202600412").
 * Una consulta vacía coincide con todo.
 */
export function coincideBusqueda(caso: CasoResumen, consulta: string): boolean {
  const q = plano(consulta.trim());
  if (!q) return true;
  const texto = plano([caso.nombre, caso.id, caso.radicado, caso.accionante, caso.juzgado_a_quo, ...caso.accionadas].filter(Boolean).join(" "));
  if (texto.includes(q)) return true;
  const qCompacto = compacto(q);
  return qCompacto !== "" && compacto(texto).includes(qCompacto);
}

export function partesDe(caso: Pick<CasoResumen, "nombre" | "accionante" | "accionadas">): string | null {
  const { accionante, accionadas } = caso;
  if (!accionante || plano(caso.nombre).includes(plano(accionante))) return null;
  return accionadas.length > 0 ? `${accionante} c. ${accionadas.join(", ")}` : accionante;
}
