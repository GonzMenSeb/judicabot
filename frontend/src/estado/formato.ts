const MINUTO = 60;
const HORA = 3600;
const DIA = 86400;

const fechaLarga = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short" });
const fechaConAnio = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short", year: "numeric" });
const porcentajes = new Map<number, Intl.NumberFormat>();

export function fechaRelativa(iso: string, ahora: number = Date.now()): string {
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return "";
  const segundos = Math.floor((ahora - fecha.getTime()) / 1000);
  if (segundos < 45) return "ahora mismo";
  if (segundos < HORA) return `hace ${Math.max(1, Math.round(segundos / MINUTO))} min`;
  if (segundos < DIA) return `hace ${Math.round(segundos / HORA)} h`;
  const dias = Math.floor(segundos / DIA);
  if (dias === 1) return "ayer";
  if (dias < 7) return `hace ${dias} días`;
  const formato = fecha.getFullYear() === new Date(ahora).getFullYear() ? fechaLarga : fechaConAnio;
  return formato.format(fecha);
}

function pluralAutomatico(palabra: string): string {
  if (/ión$/.test(palabra)) return `${palabra.slice(0, -3)}iones`;
  if (/z$/.test(palabra)) return `${palabra.slice(0, -1)}ces`;
  if (/[aeiouáéíóú]$/.test(palabra)) return `${palabra}s`;
  return `${palabra}es`;
}

export function pluralizar(n: number, singular: string, plural: string = pluralAutomatico(singular)): string {
  return n === 1 ? singular : plural;
}

export function plural(n: number, singular: string, pluralForma?: string): string {
  return `${n} ${pluralizar(n, singular, pluralForma)}`;
}

export function porcentaje(fraccion: number | null | undefined, decimales = 0): string {
  if (fraccion === null || fraccion === undefined || !Number.isFinite(fraccion)) return "—";
  let formato = porcentajes.get(decimales);
  if (!formato) {
    formato = new Intl.NumberFormat("es", {
      style: "percent",
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales,
    });
    porcentajes.set(decimales, formato);
  }
  return formato.format(fraccion);
}

export function nombreModelo(id: string): string {
  const m = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(id);
  if (!m) return id;
  const [, familia = "", mayor = "", menor = ""] = m;
  return `${familia.charAt(0).toUpperCase()}${familia.slice(1)} ${mayor}.${menor}`;
}
