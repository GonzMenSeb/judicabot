import type { Termino, TerminoRespuesta, UnidadTermino } from "../../api/contrato";
import { plural } from "../../estado";

export const DIAS_POR_DEFECTO = 20;
export const DIAS_MAXIMO = 365;

/** Lo que el usuario ha cambiado del término; los campos sin tocar no están. dias es el texto del campo. */
export interface EdicionTermino {
  inicio?: string;
  dias?: string;
  unidad?: UnidadTermino;
}

export interface ValoresTermino {
  inicio: string;
  dias: string;
  unidad: UnidadTermino;
}

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const SEMANA = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

/** Los valores que muestra el formulario: lo editado, o si no el término vigente, o si no los de un término nuevo. */
export function valoresTermino(base: Termino | null, edicion: EdicionTermino): ValoresTermino {
  return {
    inicio: edicion.inicio ?? base?.inicio ?? "",
    dias: edicion.dias ?? String(base?.dias ?? DIAS_POR_DEFECTO),
    unidad: edicion.unidad ?? base?.unidad ?? "habiles",
  };
}

/** Un entero de 1 a 365 escrito con dígitos, o null. */
export function diasDe(texto: string): number | null {
  const limpio = texto.trim();
  if (!/^\d{1,3}$/.test(limpio)) return null;
  const n = Number(limpio);
  return n >= 1 && n <= DIAS_MAXIMO ? n : null;
}

export function terminoEditado(base: Termino | null, edicion: EdicionTermino): boolean {
  const actual = valoresTermino(base, edicion);
  const original = valoresTermino(base, {});
  return actual.inicio !== original.inicio || actual.unidad !== original.unidad || actual.dias.trim() !== original.dias;
}

export function errorTermino(valores: ValoresTermino): string | null {
  if (!valores.inicio) return "Indique el día en que se recibió el expediente.";
  if (diasDe(valores.dias) === null) return `El plazo debe ser un número entero de 1 a ${DIAS_MAXIMO} días.`;
  return null;
}

/** El término que se guarda, o null si no se editó o lo editado no es válido (ver errorTermino). */
export function cuerpoTermino(base: Termino | null, edicion: EdicionTermino): Termino | null {
  if (!terminoEditado(base, edicion)) return null;
  const valores = valoresTermino(base, edicion);
  const dias = diasDe(valores.dias);
  return valores.inicio && dias !== null ? { inicio: valores.inicio, dias, unidad: valores.unidad } : null;
}

/** Una fecha AAAA-MM-DD real entre 2000 y 2100 (lo que el servidor acepta como inicio del término), o null. */
export function fechaDeInicio(texto: string | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto ?? "");
  if (!m) return null;
  const [a, mes, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (a < 2000 || a > 2100) return null;
  const dia = new Date(a, mes - 1, d);
  return dia.getFullYear() === a && dia.getMonth() === mes - 1 && dia.getDate() === d ? (texto as string) : null;
}

/**
 * El término tal como lo verá el usuario si guarda: mientras es el propuesto (o no hay), "Recibido el" sigue a la
 * fecha de reparto que se está editando. El vencimiento calculado ya no vale hasta guardar.
 */
export function conRepartoEditado(respuesta: TerminoRespuesta, reparto: string | undefined): TerminoRespuesta {
  const inicio = fechaDeInicio(reparto);
  if (!inicio || !(respuesta.por_defecto || respuesta.termino === null) || respuesta.termino?.inicio === inicio) return respuesta;
  const propio = respuesta.termino;
  return {
    ...respuesta,
    termino: { inicio, dias: propio?.dias ?? DIAS_POR_DEFECTO, unidad: propio?.unidad ?? "habiles" },
    por_defecto: true,
    fecha_reparto: inicio,
    vence: null,
    dias_restantes: null,
  };
}

/** "miércoles 18 de noviembre de 2026", con la fecha como día de calendario local para que no la corra la zona horaria. */
export function fechaLarga(iso: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  const dia = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return `${SEMANA[dia.getDay()]} ${dia.getDate()} de ${MESES[dia.getMonth()]} de ${dia.getFullYear()}`;
}

/** "faltan 2 días hábiles", "vence hoy" o "vencido hace 1 día corrido"; null si el servidor no calculó el plazo. */
export function textoRestantes(respuesta: TerminoRespuesta): string | null {
  const { termino, dias_restantes: n } = respuesta;
  if (!termino || n === null) return null;
  const [uno, varios] = termino.unidad === "habiles" ? ["día hábil", "días hábiles"] : ["día corrido", "días corridos"];
  if (n === 0) return "vence hoy";
  if (n > 0) return `${n === 1 ? "falta" : "faltan"} ${plural(n, uno, varios)}`;
  return `vencido hace ${plural(-n, uno, varios)}`;
}
