import { plural } from "../../estado";
import type { Vista } from "../../api/contrato";
import type { Alertas, AvisosFallo, AvisoFallo, CitaEstado, CitaResumen, Destino, EstadoCaso, GrupoSalidas, Salida } from "./tipos";

export const CARPETA_PRINCIPAL = "02SegundaInstancia/C01Principal";

const NOMBRES: [RegExp, string][] = [
  [/^\d*ActaRepartoSegunda/, "Acta de reparto de la impugnación"],
  [/^\d*AutoAsumeSegunda/, "Auto que asume el conocimiento"],
  [/^\d*FormatoCalificacion/, "Formato Factor Calidad"],
  [/^OficioRemiteCorteConstitucional/, "Oficio a la Corte Constitucional"],
  [/^NotificacionFalloPartes/, "Notificación del fallo a las partes"],
  [/^EnvioFormatoCalidad/, "Envío del formato de calidad"],
  [/^RemisionCompulsaCopias/, "Remisión de la compulsa de copias"],
  [/^declaracion_ia/, "Declaración de uso de IA"],
  [/^informe_verificacion/, "Informe de verificación de citas"],
  [/^previo\./, "Borrador previo"],
  [/^requerimiento\./, "Requerimiento de documentos"],
];

const GRUPOS: { carpeta: string; titulo: string }[] = [
  { carpeta: CARPETA_PRINCIPAL, titulo: "Para el expediente" },
  { carpeta: "por_radicar", titulo: "Por radicar" },
  { carpeta: "borradores_correo", titulo: "Borradores de correo" },
  { carpeta: "trabajo", titulo: "Documentos de trabajo" },
];

const ETIQUETAS_ALERTA: Record<string, string> = {
  ingesta: "Documentos",
  apertura: "Apertura",
  consideraciones: "Consideraciones",
  caso_concreto: "Caso concreto",
  documentos_caso: "Documentos del caso",
};

const MAX_LISTA = 4;

export const nombreArchivo = (ruta: string): string => ruta.slice(ruta.lastIndexOf("/") + 1);
const carpetaDe = (ruta: string): string => (ruta.includes("/") ? ruta.slice(0, ruta.lastIndexOf("/")) : "");

export function nombreLegible(ruta: string): string {
  const archivo = nombreArchivo(ruta);
  const conocido = NOMBRES.find(([patron]) => patron.test(archivo));
  return conocido ? conocido[1] : archivo.replace(/\.[^.]+$/, "");
}

export const esDescargable = (ruta: string): boolean => {
  const archivo = nombreArchivo(ruta);
  return !archivo.startsWith(".") && !archivo.endsWith(".vista.json");
};

export function rutaFallo(archivos: readonly string[]): string | null {
  const candidatos = archivos.filter((r) => /^\d*FalloSegunda[^/]*\.docx$/.test(nombreArchivo(r)));
  return candidatos.find((r) => carpetaDe(r) === CARPETA_PRINCIPAL) ?? candidatos[0] ?? null;
}

export function urlSalida(caso: string, ruta: string): string {
  return `/api/casos/${encodeURIComponent(caso)}/salidas/${ruta.split("/").map(encodeURIComponent).join("/")}`;
}

export const urlZip = (caso: string): string => `/api/casos/${encodeURIComponent(caso)}/zip`;

export function agruparSalidas(archivos: readonly string[], principal: string | null): GrupoSalidas[] {
  const grupos = new Map<string, GrupoSalidas>();
  for (const { carpeta, titulo } of GRUPOS) grupos.set(carpeta, { clave: carpeta, titulo, salidas: [] });
  for (const ruta of [...archivos].sort()) {
    if (ruta === principal || !esDescargable(ruta)) continue;
    const carpeta = carpetaDe(ruta);
    let grupo = grupos.get(carpeta);
    if (!grupo) {
      grupo = { clave: carpeta, titulo: carpeta || "Otros archivos", salidas: [] };
      grupos.set(carpeta, grupo);
    }
    const salida: Salida = { ruta, archivo: nombreArchivo(ruta), nombre: nombreLegible(ruta) };
    grupo.salidas.push(salida);
  }
  return [...grupos.values()].filter((g) => g.salidas.length > 0);
}

export function citasDeVista(vista: Vista): CitaResumen[] {
  const citadas = new Set<string>();
  for (const pagina of vista.paginas)
    for (const bloque of pagina.bloques)
      for (const segmento of bloque.segmentos) if (segmento.cita_id) citadas.add(segmento.cita_id);
  return vista.citas.filter((c) => citadas.has(c.id)).map((c) => ({ fuente: c.fuente, estado: c.estado }));
}

const ESTADO_CITA: Record<CitaEstado["estado"], CitaResumen["estado"]> = {
  ok: "verificada",
  alerta: "revisar",
  rechazada: "rechazada",
};

export function citasDeEstado(citas: readonly CitaEstado[]): CitaResumen[] {
  return citas.map((c) => ({ fuente: c.sentencia_norm || c.sentencia_original, estado: ESTADO_CITA[c.estado] }));
}

function lista(fuentes: string[]): string {
  const unicas = [...new Set(fuentes)];
  const visibles = unicas.slice(0, MAX_LISTA).join(", ");
  return unicas.length > MAX_LISTA ? `${visibles} y ${unicas.length - MAX_LISTA} más` : visibles;
}

function textoCitas(citas: readonly CitaResumen[], hayInforme: boolean): string | null {
  const rechazadas = citas.filter((c) => c.estado === "rechazada").map((c) => c.fuente);
  const alertas = citas.filter((c) => c.estado === "revisar").map((c) => c.fuente);
  if (rechazadas.length === 0 && alertas.length === 0) return null;
  const verbo = (rechazadas.length || alertas.length) === 1 ? "Quedó" : "Quedaron";
  const partes: string[] = [];
  if (rechazadas.length) {
    const n = rechazadas.length;
    partes.push(`${n === 1 ? "una cita" : `${n} citas`} sin verificar (${lista(rechazadas)})`);
  }
  if (alertas.length) {
    const n = alertas.length;
    const sujeto = rechazadas.length ? (n === 1 ? "una" : `${n}`) : n === 1 ? "una cita" : `${n} citas`;
    partes.push(`${sujeto} con alerta (${lista(alertas)})`);
  }
  const total = rechazadas.length + alertas.length;
  const cierre = hayInforme ? ` El informe de verificación ${total === 1 ? "la detalla" : "las detalla"}.` : "";
  return `${verbo} ${partes.join(" y ")}.${cierre}`;
}

const MENSAJE_DE_CITA = /^(ALERTA|BLOQUEA): La cita /;

function alertasDelProceso(alertas: Alertas): string[] {
  if (!alertas) return [];
  const pares: [string, string][] = Array.isArray(alertas)
    ? alertas.map((m): [string, string] => ["ingesta", m])
    : Object.entries(alertas).flatMap(([origen, mensajes]) => (mensajes ?? []).map((m): [string, string] => [origen, m]));
  const vistos = new Set<string>();
  const salida: string[] = [];
  for (const [origen, mensaje] of pares) {
    if (MENSAJE_DE_CITA.test(mensaje)) continue;
    const limpio = mensaje.replace(/^ALERTA: /, "");
    const linea = `${ETIQUETAS_ALERTA[origen] ?? origen}: ${limpio}`;
    if (vistos.has(linea)) continue;
    vistos.add(linea);
    salida.push(linea);
  }
  return salida;
}

export interface EntradaAvisos {
  citas: readonly CitaResumen[] | null;
  alertas: Alertas;
  archivos: readonly string[];
}

export function calcularAvisos({ citas, alertas, archivos }: EntradaAvisos): AvisosFallo {
  const descargables = archivos.filter(esDescargable);
  const hayInforme = descargables.some((r) => /^informe_verificacion\./.test(nombreArchivo(r)));
  const revise: AvisoFallo[] = [];
  const recuerde: AvisoFallo[] = [];

  const textoDeCitas = citas ? textoCitas(citas, hayInforme) : null;
  if (textoDeCitas) revise.push({ clave: "citas", texto: textoDeCitas });

  const delProceso = alertasDelProceso(alertas);
  if (delProceso.length > 0)
    revise.push({
      clave: "alertas",
      texto: `El proceso registró ${plural(delProceso.length, "alerta")}; revíselas antes de firmar.`,
      detalle: delProceso,
    });

  if (descargables.some((r) => /^declaracion_ia\./.test(nombreArchivo(r))))
    recuerde.push({ clave: "ia", texto: "Adjunte la declaración de uso de IA que exige el Acuerdo PCSJA24-12243." });

  const nombresEn = (carpeta: string) => descargables.filter((r) => carpetaDe(r) === carpeta).sort().map(nombreLegible);
  const porRadicar = nombresEn("por_radicar");
  if (porRadicar.length > 0) recuerde.push({ clave: "radicar", texto: `Quedó por radicar: ${porRadicar.join(", ")}.` });
  const correos = nombresEn("borradores_correo");
  if (correos.length > 0)
    recuerde.push({
      clave: "correos",
      texto: `${correos.length === 1 ? "Hay un borrador de correo" : `Hay ${correos.length} borradores de correo`} para revisar y enviar: ${correos.join(", ")}.`,
    });

  return { revise, recuerde, citasVerificadas: citas ? citas.filter((c) => c.estado === "verificada").length : 0 };
}

export function destinoSinFallo(caso: string, estado: EstadoCaso | null): { texto: string; destino: Destino } {
  const base = `#/segunda/${encodeURIComponent(caso)}`;
  if (!estado) {
    return {
      texto: "Todavía no existe el fallo de este caso.",
      destino: { texto: "Volver a los casos", enlace: "casos", href: "#/segunda" },
    };
  }
  if (estado.job_activo) {
    return {
      texto: "El proceso sigue en curso; el fallo se genera al terminar.",
      destino: { texto: "Ver el avance", enlace: "proceso", href: `${base}/proceso` },
    };
  }
  switch (estado.estado) {
    case "esperando_decision":
      return {
        texto: "El fallo se redacta cuando usted toma la decisión; el caso la está esperando.",
        destino: { texto: "Ir a la decisión", enlace: "decision", href: `${base}/decision` },
      };
    case "error":
      return {
        texto: estado.error ? `El proceso quedó a medias: ${estado.error}` : "El proceso quedó a medias por un error.",
        destino: { texto: "Ver el proceso", enlace: "proceso", href: `${base}/proceso` },
      };
    case "terminado":
      return {
        texto: "El caso figura como terminado, pero no se encontró el fallo entre los archivos generados.",
        destino: { texto: "Ver el proceso", enlace: "proceso", href: `${base}/proceso` },
      };
    default:
      return {
        texto: "El caso todavía no ha pasado por la redacción: primero hay que revisar los documentos e iniciarla.",
        destino: { texto: "Ir a Documentos", enlace: "documentos", href: `${base}/documentos` },
      };
  }
}
