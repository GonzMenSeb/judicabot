import { sanear } from "./formulario";
import type { Formulario, PayloadDecision } from "./tipos";

const clave = (caso: string) => `judicabot:decision:${caso}`;

export function leerBorrador(caso: string, payload: PayloadDecision | null): Formulario | null {
  try {
    const crudo = sessionStorage.getItem(clave(caso));
    return crudo ? sanear(JSON.parse(crudo), payload) : null;
  } catch {
    return null;
  }
}

export function guardarBorrador(caso: string, formulario: Formulario): void {
  try {
    sessionStorage.setItem(clave(caso), JSON.stringify(formulario));
  } catch {
    return;
  }
}

export function borrarBorrador(caso: string): void {
  try {
    sessionStorage.removeItem(clave(caso));
  } catch {
    return;
  }
}
