import type {
  ApoderadosRespuesta,
  ApoderadoVista,
  ConsultaEstado,
  EstadoApoderado,
  EstadoPoder,
  EstadoVigencia,
  EvidenciaVista,
  FaseApoderado,
  OrigenVigencia,
  RolParte,
  TipoPoder,
  Vista,
} from "../../api/contrato";
import { plural } from "../../estado";
import type { TonoChip } from "../../ui";
import type { ItemRevision, NivelRevision, PedidoVisor } from "./tipos";

export const SONDEO_ACTIVO_MS = 3_000;
export const SONDEO_AYUDA_MS = 15_000;
export const SONDEO_ERROR_MS = 30_000;

export const PREFIJO_APODERADO = "apoderado-";

export const ETIQUETA_ESTADO_APODERADO: Record<EstadoApoderado, string> = {
  verificado: "Verificado",
  revisar: "Por revisar",
  no_verificado: "No verificado",
};

export const ETIQUETA_VIGENCIA: Record<EstadoVigencia, string> = {
  vigente: "Vigente",
  vigente_obs: "Vigente con observaciones",
  no_vigente: "No vigente",
  no_inscrito: "No inscrito",
  otra_persona: "Certificado de otra persona",
  ilegible: "Certificado ilegible",
  inaccesible: "Sin respuesta de la Rama Judicial",
  sin_cedula: "Sin cédula en el expediente",
  sin_consultar: "Sin consultar",
};

export const ETIQUETA_PODER: Record<EstadoPoder, string> = {
  hallado: "Poder hallado",
  hallado_reserva: "Poder sin confirmar",
  manual: "Poder señalado a mano",
  sin_poder: "Sin poder",
  ajeno: "Poder de otra parte",
  descartado: "Poder descartado",
};

export const ETIQUETA_FASE: Record<FaseApoderado, string> = {
  en_cola: "En cola",
  consultando: "Consultando…",
  necesita_ayuda: "Necesita su ayuda",
  listo: "Listo",
};

export const ETIQUETA_ROL_PARTE: Record<RolParte, string> = {
  accionante: "Accionante",
  accionada: "Accionada",
  vinculada: "Vinculada",
  otro: "Otra parte",
};

const NIVEL: Record<EstadoApoderado, NivelRevision> = { no_verificado: "mal", revisar: "alerta", verificado: "ok" };

const TARJETA_CORTA: Record<EstadoVigencia, string> = {
  vigente: "Tarjeta vigente",
  vigente_obs: "Tarjeta vigente con observaciones",
  no_vigente: "Tarjeta profesional no vigente",
  no_inscrito: "No inscrito en el Registro Nacional de Abogados",
  otra_persona: "El certificado es de otra persona",
  ilegible: "Certificado ilegible",
  inaccesible: "La Rama Judicial no respondió",
  sin_cedula: "Sin cédula para consultar la tarjeta",
  sin_consultar: "Tarjeta sin consultar",
};

const TIPO_PODER: Record<TipoPoder, string> = {
  poder: "Poder",
  sustitucion: "Sustitución de poder",
  certificado_existencia: "Certificado de existencia",
};

const EN_CURSO: ReadonlySet<FaseApoderado> = new Set(["en_cola", "consultando"]);

/** Lo que dice la fila de un abogado mientras su tarjeta se consulta (mesa Consulta). */
export const TEXTO_CONSULTANDO = "Consultando vigencia en la Rama Judicial…";

/** La vigencia de este abogado está en la cola de consultas o consultándose ahora. */
export const enCurso = (ap: ApoderadoVista): boolean => EN_CURSO.has(ap.vigencia.fase);

const digitos = (texto: string | null | undefined): string => (texto ?? "").replace(/\D/g, "");

const mayuscula = (texto: string): string => (texto ? texto[0]!.toUpperCase() + texto.slice(1) : texto);

function agrupar(caracteres: string[]): string {
  const grupos: string[] = [];
  for (let fin = caracteres.length; fin > 0; fin -= 3) grupos.unshift(caracteres.slice(Math.max(0, fin - 3), fin).join(""));
  return grupos.join(".");
}

export const claveApoderado = (id: string): string => `${PREFIJO_APODERADO}${id}`;

export const idDeClave = (clave: string): string | null => (clave.startsWith(PREFIJO_APODERADO) ? clave.slice(PREFIJO_APODERADO.length) : null);

export function formatoTarjeta(tarjeta: string | null | undefined): string {
  const d = digitos(tarjeta);
  return d ? agrupar([...d]) : "";
}

export function mascaraCedula(cedula: string | null | undefined): string {
  const d = digitos(cedula);
  if (!d) return "";
  const visibles = Math.max(0, d.length - 6);
  return agrupar([...d].map((c, i) => (i < visibles || i >= d.length - 2 ? c : "•")));
}

const formatoHora = new Intl.DateTimeFormat("es-CO", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const formatoDia = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short" });

export function momentoConsulta(iso: string | null | undefined, ahora: number = Date.now()): string {
  if (!iso) return "";
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return "";
  const hoy = new Date(ahora);
  const mismoDia = fecha.getFullYear() === hoy.getFullYear() && fecha.getMonth() === hoy.getMonth() && fecha.getDate() === hoy.getDate();
  const hora = formatoHora.format(fecha);
  return mismoDia ? `hoy ${hora}` : `${formatoDia.format(fecha)} ${hora}`;
}

export const referenciaDoc = (e: EvidenciaVista): string => `Doc. ${e.doc_id}, p. ${e.pagina}`;

export function etiquetaVigencia(ap: ApoderadoVista): string {
  return EN_CURSO.has(ap.vigencia.fase) ? ETIQUETA_FASE[ap.vigencia.fase] : ETIQUETA_VIGENCIA[ap.vigencia.estado];
}

export function lineaVigencia(ap: ApoderadoVista, ahora: number = Date.now()): string {
  const tarjeta = formatoTarjeta(ap.tarjeta ?? ap.vigencia.tarjeta_registro);
  const cedula = mascaraCedula(ap.cedula);
  const cuando = momentoConsulta(ap.vigencia.consultado_en, ahora);
  const partes = [tarjeta && `T.P. ${tarjeta}`, cedula && `C.C. ${cedula}`, cuando && `consultado ${cuando}`].filter(Boolean);
  return partes.length > 0 ? partes.join(" · ") : "No constan la tarjeta profesional ni la cédula en el expediente.";
}

export function lineaPoder(ap: ApoderadoVista): string | null {
  const { poder } = ap;
  if (!poder.evidencia) return null;
  const partes = [`${TIPO_PODER[poder.tipo ?? "poder"]} · ${referenciaDoc(poder.evidencia)}`];
  if (poder.estado === "ajeno" && poder.parte) partes.push(`para ${poder.parte}`);
  const otorgante = poder.cadena?.otorgante || poder.otorgante;
  if (otorgante && poder.estado !== "ajeno") partes.push(`lo otorga ${otorgante}${poder.cadena?.cargo ? `, ${poder.cadena.cargo}` : ""}`);
  return partes.join(" · ");
}

function poderCorto(ap: ApoderadoVista): string {
  const { poder } = ap;
  const ref = poder.evidencia ? ` (${referenciaDoc(poder.evidencia)})` : "";
  const tipo = TIPO_PODER[poder.tipo ?? "poder"].toLowerCase();
  switch (poder.estado) {
    case "hallado":
      return `${tipo}${ref}`;
    case "manual":
      return `poder señalado a mano${ref}`;
    case "hallado_reserva":
      return `${tipo} sin confirmar quién lo otorga${ref}`;
    case "ajeno":
      return `el poder hallado es de otra parte${ref}`;
    case "descartado":
      return "poder descartado en la revisión";
    case "sin_poder":
      return "no se halló poder en el expediente";
  }
}

export function lineaApoderado(ap: ApoderadoVista): string {
  // Mientras se consulta, la tarjeta la cuenta la etiqueta de la fila («En cola», «Consultando…»): la línea queda para el poder.
  if (enCurso(ap)) return mayuscula(poderCorto(ap));
  return `${TARJETA_CORTA[ap.vigencia.estado]} · ${poderCorto(ap)}`;
}

/** El aviso corto de la fila cerrada: en cola, consultando (con giro) o necesita su ayuda. */
function etiquetaFila(ap: ApoderadoVista): ItemRevision["etiqueta"] {
  switch (ap.vigencia.fase) {
    case "en_cola":
      return { texto: ETIQUETA_FASE.en_cola, tono: "neutro" };
    case "consultando":
      return { texto: TEXTO_CONSULTANDO, tono: "info", giro: true };
    case "necesita_ayuda":
      // Sin consulta automática que la resuelva, la tarjeta espera a que el despacho suba el certificado.
      return { texto: ETIQUETA_FASE.necesita_ayuda, tono: "alerta" };
    default:
      return undefined;
  }
}

export function itemsApoderados(datos: ApoderadosRespuesta | null): ItemRevision[] {
  if (!datos) return [];
  return datos.apoderados.map((apoderado) => {
    const etiqueta = etiquetaFila(apoderado);
    return {
      clave: claveApoderado(apoderado.id),
      nivel: NIVEL[apoderado.estado],
      origen: `Apoderado · ${apoderado.parte}`,
      titulo: apoderado.nombre,
      linea: lineaApoderado(apoderado),
      lineaCompleta: false,
      detalle: { tipo: "apoderado", apoderado },
      marca: { tipo: "apoderado", id: apoderado.id },
      grupo: "apoderados",
      ...(etiqueta && { etiqueta }),
    };
  });
}

const RESULTADO_SUBIDA: Partial<Record<EstadoVigencia, (nombre: string) => string>> = {
  vigente: (nombre) => `la tarjeta profesional de ${nombre} está vigente`,
  vigente_obs: (nombre) => `la tarjeta profesional de ${nombre} está vigente, con observaciones`,
  no_vigente: (nombre) => `la tarjeta profesional de ${nombre} no está vigente`,
  no_inscrito: (nombre) => `la cédula de ${nombre} no está inscrita en el Registro Nacional de Abogados`,
  otra_persona: (nombre) => `está a nombre de otra persona, no de ${nombre}`,
  ilegible: (nombre) => `no se pudo leer el estado de la tarjeta de ${nombre}; ábralo y revíselo`,
};

/** Lo que se anuncia al terminar de subir el certificado, con el resultado que devolvió el servidor. */
export function avisoSubida(ap: ApoderadoVista): { texto: string; tipo: "ok" | "alerta" | "info" } {
  const estado = ap.vigencia.estado;
  const resultado = RESULTADO_SUBIDA[estado];
  if (!resultado) return { texto: `Certificado de ${ap.nombre} guardado.`, tipo: "info" };
  return { texto: `Certificado leído: ${resultado(ap.nombre)}.`, tipo: estado === "vigente" ? "ok" : "alerta" };
}

/** La clase de la marca del nombre en el texto: la misma gramática de colores que las citas. */
export const CLASE_MARCA: Record<EstadoApoderado, "verificada" | "revisar" | "rechazada"> = {
  verificado: "verificada",
  revisar: "revisar",
  no_verificado: "rechazada",
};

/** Lo que oye un lector de pantalla después del nombre marcado. */
export const LECTURA_MARCA: Record<EstadoApoderado, string> = {
  verificado: "abogado verificado",
  revisar: "abogado por revisar",
  no_verificado: "abogado no verificado",
};

export const FUENTE_VIGENCIA: Record<OrigenVigencia, string> = {
  extension: "Rama Judicial · Certificado de vigencia",
  directa: "Rama Judicial · Certificado de vigencia",
  manual: "Certificado subido por el despacho",
  fake: "Consulta simulada (modo de prueba)",
};

export const TITULO_PODER: Record<TipoPoder, string> = {
  poder: "Poder especial",
  sustitucion: "Sustitución de poder",
  certificado_existencia: "Certificado de existencia",
};

/** Cédula no inscrita: rojo si la cédula consta en una página del expediente leída sin OCR (lo dice el servidor con
 * `vigencia.grave`); ámbar si pudo leerse o escribirse mal, aunque el abogado quede sin verificar por otra razón. */
export const noInscritoEnRojo = (ap: ApoderadoVista): boolean => ap.vigencia.estado === "no_inscrito" && ap.vigencia.grave;

export function tonoVigencia(ap: ApoderadoVista): TonoChip {
  if (EN_CURSO.has(ap.vigencia.fase)) return "info";
  const { estado } = ap.vigencia;
  if (estado === "vigente") return "ok";
  return estado === "no_vigente" || noInscritoEnRojo(ap) ? "mal" : "alerta";
}

export function tonoPoder(ap: ApoderadoVista): TonoChip {
  const { estado } = ap.poder;
  return estado === "hallado" || estado === "manual" ? "ok" : estado === "ajeno" ? "mal" : "alerta";
}

const SIN_VIGENCIA: ReadonlySet<EstadoVigencia> = new Set(["sin_consultar", "inaccesible", "ilegible", "otra_persona", "sin_cedula"]);

/** La vigencia no se obtuvo (sin consultar, sin respuesta, ilegible o de otra persona) y nada la está consultando: hace falta el certificado. */
export function necesitaCertificado(ap: ApoderadoVista): boolean {
  if (ap.vigencia.fase === "necesita_ayuda") return true;
  return !EN_CURSO.has(ap.vigencia.fase) && SIN_VIGENCIA.has(ap.vigencia.estado);
}

/**
 * Se puede subir el certificado a mano: además de cuando hace falta, cuando el que se leyó no la da por vigente
 * (no vigente o con observaciones), porque uno más reciente lo reemplaza.
 */
export function admiteCertificado(ap: ApoderadoVista): boolean {
  return necesitaCertificado(ap) || (!EN_CURSO.has(ap.vigencia.fase) && ap.vigencia.estado !== "vigente");
}

const MARCAS_DIACRITICAS = /\p{M}/gu;
const PALABRA_NOMBRE = /[\p{L}\p{N}]+/gu;
// Entre dos palabras del nombre: espacios (también el salto de renglón del PDF) o un guion.
const ENTRE_PALABRAS = "[\\s\\u00ad\\-\\u2010\\u2011]+";

export interface PedazoResaltado {
  texto: string;
  marcado: boolean;
}

/** El texto plegado (sin tildes ni mayúsculas) y, para cada carácter plegado, su posición en el original. */
function plegarConMapa(texto: string): { plegado: string; origen: number[] } {
  let plegado = "";
  const origen: number[] = [];
  for (let i = 0; i < texto.length; i++) {
    for (const c of texto[i]!.normalize("NFD").replace(MARCAS_DIACRITICAS, "").toLowerCase()) {
      plegado += c;
      origen.push(i);
    }
  }
  return { plegado, origen };
}

function tramosDelNombre(texto: string, nombre: string): [number, number][] {
  const palabras = nombre.normalize("NFD").replace(MARCAS_DIACRITICAS, "").toLowerCase().match(PALABRA_NOMBRE) ?? [];
  if (!texto || palabras.length === 0) return [];
  const { plegado, origen } = plegarConMapa(texto);
  const patron = new RegExp(`(?<![\\p{L}\\p{N}])${palabras.join(ENTRE_PALABRAS)}(?![\\p{L}\\p{N}])`, "gu");
  const tramos: [number, number][] = [];
  for (const m of plegado.matchAll(patron)) {
    const a = origen[m.index]!;
    let b = origen[m.index + m[0].length - 1]! + 1;
    // Una tilde escrita aparte (NFD) se pliega a nada: se queda con la letra que la lleva.
    while (b < texto.length && /^\p{M}$/u.test(texto[b]!)) b++;
    tramos.push([a, b]);
  }
  return tramos;
}

/**
 * Parte la cita donde aparece el nombre del abogado, sin distinguir mayúsculas, tildes ni espacios, para resaltarlo
 * con nodos de texto: el contenido viene del expediente y nunca se interpreta como HTML.
 */
export function partirResaltado(texto: string, nombre: string): PedazoResaltado[] {
  if (!texto) return [];
  const pedazos: PedazoResaltado[] = [];
  let desde = 0;
  for (const [a, b] of tramosDelNombre(texto, nombre)) {
    if (a > desde) pedazos.push({ texto: texto.slice(desde, a), marcado: false });
    pedazos.push({ texto: texto.slice(a, b), marcado: true });
    desde = b;
  }
  if (desde < texto.length) pedazos.push({ texto: texto.slice(desde), marcado: false });
  return pedazos;
}

const FEMENINO = /\b(?:doctora|apoderada|abogada|suscrita|señora)\b/i;
const MASCULINO = /\b(?:doctor|apoderado|abogado|suscrito|señor)\b/i;

/** «Apoderada» si el expediente la llama doctora, apoderada o abogada justo antes de su nombre; si no, «Apoderado». */
export function tratamiento(ap: ApoderadoVista): "Apoderado" | "Apoderada" {
  for (const evidencia of [ap.poder.evidencia, ap.poder.mencion]) {
    const cita = evidencia?.cita ?? "";
    const [tramo] = tramosDelNombre(cita, ap.nombre);
    if (!tramo) continue;
    const antes = cita.slice(Math.max(0, tramo[0] - 40), tramo[0]);
    if (FEMENINO.test(antes)) return "Apoderada";
    if (MASCULINO.test(antes)) return "Apoderado";
  }
  return "Apoderado";
}

/** «Apoderada de EPS X · accionada», o «Dice ser apoderado de …» cuando no hay poder que lo respalde. */
export function subtituloApoderado(ap: ApoderadoVista): string {
  const quien = tratamiento(ap);
  const rol = ETIQUETA_ROL_PARTE[ap.rol_parte].toLowerCase();
  const respaldado = ap.poder.evidencia !== null && ap.poder.estado !== "ajeno";
  return `${respaldado ? quien : `Dice ser ${quien.toLowerCase()}`} de ${ap.parte} · ${rol}`;
}

export const fuenteEvidencia = (titulo: string, e: EvidenciaVista): string => `${titulo} · Doc. ${e.doc_id} · página ${e.pagina}`;

export type EvidenciaApoderado = "poder" | "certificado" | "escrito";

/** Lo que necesita el visor para abrir una evidencia del apoderado, o null si esa evidencia no existe. */
export function pedidoVisor(ap: ApoderadoVista, cual: EvidenciaApoderado): PedidoVisor | null {
  const { poder } = ap;
  if (cual === "poder") {
    if (!poder.evidencia) return null;
    return {
      apoderado: ap.id,
      evidencia: poder.evidencia,
      titulo: `${TITULO_PODER[poder.tipo ?? "poder"]} · Doc. ${poder.evidencia.doc_id}`,
      subtitulo: `Evidencia de que ${ap.nombre} representa a ${poder.parte || ap.parte}`,
    };
  }
  if (cual === "certificado") {
    const cadena = poder.cadena;
    if (!cadena?.evidencia) return null;
    return {
      apoderado: ap.id,
      evidencia: cadena.evidencia,
      titulo: `Certificado de existencia · Doc. ${cadena.evidencia.doc_id}`,
      subtitulo: cadena.otorgante
        ? `Evidencia de que ${cadena.otorgante} es ${cadena.cargo || "representante"} de ${ap.parte}`
        : `Evidencia de la representación de ${ap.parte}`,
    };
  }
  if (!poder.mencion) return null;
  return {
    apoderado: ap.id,
    evidencia: poder.mencion,
    titulo: `Escrito de ${ap.nombre} · Doc. ${poder.mencion.doc_id}`,
    subtitulo: `Donde ${ap.nombre} dice actuar por ${ap.parte}`,
  };
}

/** Los abogados cuyo nombre quedó marcado en el texto del borrador. */
export function apoderadosEnTexto(vista: Vista): Set<string> {
  const ids = new Set<string>();
  for (const pagina of vista.paginas) {
    for (const bloque of pagina.bloques) {
      for (const segmento of bloque.segmentos) if (segmento.apoderado_id) ids.add(segmento.apoderado_id);
    }
  }
  return ids;
}

export function revisadosDelServidor(datos: ApoderadosRespuesta | null): string[] {
  return (datos?.apoderados ?? []).filter((a) => a.revisado).map((a) => claveApoderado(a.id));
}

export interface ResumenApoderados {
  total: string;
  partes: string[];
}

export function resumenApoderados(datos: ApoderadosRespuesta): ResumenApoderados {
  const cuenta = (estado: EstadoApoderado) => datos.apoderados.filter((a) => a.estado === estado).length;
  const verificados = cuenta("verificado");
  const revisar = cuenta("revisar");
  const noVerificados = cuenta("no_verificado");
  return {
    total: plural(datos.apoderados.length, "apoderado"),
    partes: [
      verificados > 0 && plural(verificados, "verificado"),
      revisar > 0 && `${revisar} por revisar`,
      noVerificados > 0 && plural(noVerificados, "no verificado"),
    ].filter((p): p is string => typeof p === "string"),
  };
}

export function progresoConsulta(datos: ApoderadosRespuesta | null): string | null {
  if (!datos?.consulta.activa || datos.apoderados.length === 0) return null;
  const listos = datos.apoderados.filter((a) => a.fase === "listo").length;
  const consultando = datos.apoderados.some((a) => a.fase === "consultando");
  return `${listos} de ${datos.apoderados.length} ${listos === 1 ? "listo" : "listos"} · ${consultando ? "consultando la Rama Judicial" : "en cola para consultar"}`;
}

export type SegmentoEstado = "s-mal" | "s-alerta" | "s-curso" | "s-ok";

const ORDEN_SEGMENTO: SegmentoEstado[] = ["s-mal", "s-alerta", "s-curso", "s-ok"];

export function segmentosEstado(datos: ApoderadosRespuesta): SegmentoEstado[] {
  const segmento = (a: ApoderadoVista): SegmentoEstado =>
    EN_CURSO.has(a.fase) ? "s-curso" : a.estado === "no_verificado" ? "s-mal" : a.estado === "revisar" ? "s-alerta" : "s-ok";
  return datos.apoderados.map(segmento).sort((a, b) => ORDEN_SEGMENTO.indexOf(a) - ORDEN_SEGMENTO.indexOf(b));
}

export function conRevision(ap: ApoderadoVista, revisado: boolean): ApoderadoVista {
  return { ...ap, revisado, revision_vencida: revisado ? false : ap.revision_vencida, bloquea: ap.estado === "no_verificado" && !revisado };
}

function conApoderados(datos: ApoderadosRespuesta, apoderados: ApoderadoVista[]): ApoderadosRespuesta {
  return { ...datos, apoderados, bloquea_decision: apoderados.some((a) => a.bloquea) };
}

export function aplicarRevisiones(datos: ApoderadosRespuesta, pendientes: ReadonlyMap<string, boolean>): ApoderadosRespuesta {
  if (pendientes.size === 0) return datos;
  return conApoderados(
    datos,
    datos.apoderados.map((ap) => {
      const revisado = pendientes.get(ap.id);
      return revisado === undefined ? ap : conRevision(ap, revisado);
    }),
  );
}

export function reemplazarApoderado(datos: ApoderadosRespuesta, vista: ApoderadoVista): ApoderadosRespuesta {
  return conApoderados(
    datos,
    datos.apoderados.map((ap) => (ap.id === vista.id ? vista : ap)),
  );
}

export const bloqueantes = (datos: ApoderadosRespuesta | null): ApoderadoVista[] => (datos?.apoderados ?? []).filter((a) => a.bloquea);

export function listaNombres(nombres: string[]): string {
  if (nombres.length <= 1) return nombres[0] ?? "";
  return `${nombres.slice(0, -1).join(", ")} y ${nombres[nombres.length - 1]}`;
}

export function mensajeBloqueo(apoderados: ApoderadoVista[]): string | null {
  const nombres = [...new Set(apoderados.map((a) => a.nombre))];
  if (nombres.length === 0) return null;
  return nombres.length === 1
    ? `${nombres[0]} no pudo verificarse. Márquelo como revisado en la pestaña Apoderados para pasar a la decisión.`
    : `${listaNombres(nombres)} no pudieron verificarse. Márquelos como revisados en la pestaña Apoderados para pasar a la decisión.`;
}

export function intervaloSondeo(datos: ApoderadosRespuesta | null, fallo: boolean): number | null {
  if (fallo) return SONDEO_ERROR_MS;
  if (!datos) return null;
  const { consulta } = datos;
  if (consulta.activa) return SONDEO_ACTIVO_MS;
  if (!datos.apoderados.some((a) => a.fase === "necesita_ayuda")) return null;
  // Quien necesita ayuda puede resolverse solo: al conectarse la extensión o al terminar la pausa de la Rama Judicial.
  const sinExtension = consulta.modo === "extension" && consulta.extension !== "conectada";
  return sinExtension || consulta.pausa_hasta !== null ? SONDEO_AYUDA_MS : null;
}

/** La consulta automática de la vigencia está encendida en esta instalación (o en este caso). */
export const consultaAutomatica = (consulta: ConsultaEstado): boolean => consulta.modo !== "apagada";

/**
 * Al abrir el borrador se pide una vez la consulta de quien sigue sin consultar y nada está en curso: así se
 * recupera la cola tras reiniciar el servidor. Con la consulta apagada, o si el caso no admite cambios, no se pide.
 */
export function debeConsultar(datos: ApoderadosRespuesta | null): boolean {
  if (!datos || datos.identificacion !== "lista" || !datos.editable) return false;
  if (!consultaAutomatica(datos.consulta) || datos.consulta.activa) return false;
  return datos.apoderados.some((a) => a.vigencia.estado === "sin_consultar" && !enCurso(a) && digitos(a.cedula) !== "");
}

/**
 * «Reintentar consulta automática»: hay consulta automática que pueda salir ya (desde el navegador, con una extensión
 * conectada que sepa consultar), cédula que consultar y nada en curso. Sin extensión, la cola sigue sola al conectarse.
 */
export function puedeReintentar(ap: ApoderadoVista, consulta: ConsultaEstado | null | undefined): boolean {
  if (!consulta || !consultaAutomatica(consulta)) return false;
  if (consulta.modo === "extension" && consulta.extension !== "conectada") return false;
  return digitos(ap.cedula) !== "" && !enCurso(ap);
}

/** «La Rama Judicial no respondió; se reintenta a las 15:42.», o null sin pausa (o con una hora que no se entiende). */
export function avisoPausa(consulta: ConsultaEstado | null | undefined): string | null {
  if (!consulta?.pausa_hasta) return null;
  const hasta = new Date(consulta.pausa_hasta);
  if (Number.isNaN(hasta.getTime())) return null;
  return `La Rama Judicial no respondió; se reintenta a las ${formatoHora.format(hasta)}.`;
}

/** El poder que se muestra se puede descartar («No es correcto…»). */
export const admiteDescartar = (ap: ApoderadoVista): boolean => ap.poder.evidencia !== null;

/**
 * «Deshacer el descarte» vuelve al poder que halló el código. Si lo descartado era uno señalado a mano sobre un abogado
 * sin poder propio, el servidor ya lo quitó y no hay a qué volver: no se ofrece.
 */
export const admiteDeshacerDescarte = (ap: ApoderadoVista): boolean => ap.poder.estado === "descartado" && ap.poder.hay_hallado;

/** Falta un poder que lo respalde: se puede señalar a mano la página donde está. */
export const admitePoderManual = (ap: ApoderadoVista): boolean => ap.poder.estado !== "hallado" && ap.poder.estado !== "manual";

/** El expediente no trae su cédula: se puede escribir a mano para consultar la tarjeta. */
export const admiteCedula = (ap: ApoderadoVista): boolean => digitos(ap.cedula) === "";

export interface DocumentoConocido {
  doc_id: string;
  documento: string;
  total: number | null;
}

/** Los documentos del expediente que el borrador conoce por las evidencias de los abogados, en orden de doc_id. */
export function documentosConocidos(datos: ApoderadosRespuesta | null): DocumentoConocido[] {
  const vistos = new Map<string, DocumentoConocido>();
  for (const ap of datos?.apoderados ?? []) {
    for (const e of [ap.poder.evidencia, ap.poder.mencion, ap.poder.cadena?.evidencia]) {
      if (e && !vistos.has(e.doc_id)) vistos.set(e.doc_id, { doc_id: e.doc_id, documento: e.documento, total: e.total_paginas });
    }
  }
  return [...vistos.values()].sort((a, b) => a.doc_id.localeCompare(b.doc_id));
}
