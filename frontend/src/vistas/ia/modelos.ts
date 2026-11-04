import { nombreModelo } from "../../estado";
import type { ModoJev } from "../../api/contrato";
import type { OpcionTarjeta } from "./Tarjetas";

const FAMILIAS = ["sonnet", "opus", "haiku"];

const DETALLES: Record<string, string> = {
  sonnet: "Recomendado. Equilibrio entre calidad, tiempo y costo.",
  opus: "El más cuidadoso. Más lento y más costoso.",
  haiku: "El más rápido. Si rechaza una tarea, se reintenta con Sonnet.",
};

const familiaDe = (id: string) => /^claude-([a-z]+)-/.exec(id)?.[1] ?? "";

const posicion = (id: string) => {
  const i = FAMILIAS.indexOf(familiaDe(id));
  return i < 0 ? FAMILIAS.length : i;
};

export function opcionesModelo(ids: readonly string[]): OpcionTarjeta[] {
  return [...ids]
    .sort((a, b) => posicion(a) - posicion(b))
    .map((id) => {
      const detalle = DETALLES[familiaDe(id)];
      return detalle ? { valor: id, titulo: nombreModelo(id), detalle } : { valor: id, titulo: nombreModelo(id) };
    });
}

export const OPCIONES_JEV: readonly (OpcionTarjeta & { valor: ModoJev })[] = [
  { valor: "apagado", titulo: "Apagado", detalle: "No sale ninguna petición." },
  { valor: "sombra", titulo: "Sombra", detalle: "Opina y deja alertas. No cambia nada." },
  { valor: "relleno", titulo: "Relleno", detalle: "Además asigna el rol de documentos que quedaron como «Otro»." },
];
