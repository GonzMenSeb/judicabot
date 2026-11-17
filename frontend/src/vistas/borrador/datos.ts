import type { ApoderadoVista, Bloque, CitaVista, Segmento, Vista } from "../../api/contrato";
import { nombreModelo, porcentaje } from "../../estado";
import type { EtapaPaso } from "../../ui";
import type {
  AlertasApi,
  EntradaIndice,
  EstadoCaso,
  EstadoComparacion,
  FilaJev,
  AlertaLegible,
  GrupoBloque,
  ItemRevision,
  JevMetadatos,
  LecturaJev,
  LlamadaBitacora,
  MarcaIndice,
  MetadatosCaso,
  NivelRevision,
  Redaccion,
} from "./tipos";

export const ETIQUETA_ESTADO_CITA: Record<CitaVista["estado"], string> = {
  verificada: "Verificada",
  revisar: "Con alerta",
  rechazada: "No verificada",
};

const ETIQUETA_SENTIDO: Record<string, string> = {
  ampara: "Ampara",
  niega: "Niega el amparo",
  improcedente: "Declara improcedente",
  carencia_actual_de_objeto: "Carencia actual de objeto",
  otro: "Otro o indeterminado",
};

const ETIQUETA_ROL: Record<string, string> = {
  accionante: "Accionante",
  accionada: "Accionada",
  vinculada: "Vinculada",
  otro: "Otro",
};

const ETIQUETA_NODO: Record<string, string> = {
  ingesta: "Archivo",
  apertura: "Apertura",
  apoderados: "Apoderados",
  consideraciones: "Consideraciones",
  caso_concreto: "Caso concreto",
  documentos_caso: "Documentos",
};

const mayuscula = (texto: string) => (texto ? texto.charAt(0).toUpperCase() + texto.slice(1) : texto);
const etiquetaDe = (mapa: Record<string, string>, clave: string) => mapa[clave] ?? clave;
const limpiar = (texto: string) => texto.replace(/\s+/g, " ").trim();

const SECCIONES_REDACTADAS = [
  { nodo: "apertura", secciones: "Secciones II a IV" },
  { nodo: "consideraciones", secciones: "Sección V" },
] as const;

const nombreEfectivo = (id: string) => nombreModelo(id.replace(/-\d{8}$/, ""));

export function redaccionPorNodo(bitacora: LlamadaBitacora[] | null | undefined): Redaccion[] {
  if (!Array.isArray(bitacora)) return [];
  const filas: Redaccion[] = [];
  for (const { nodo, secciones } of SECCIONES_REDACTADAS) {
    const ultima = bitacora.findLast((l) => l.nodo === nodo && l.proveedor !== "jev");
    const efectivo = ultima?.modelo_efectivo || ultima?.modelo_pedido;
    if (!ultima || !efectivo) continue;
    const modelo = nombreEfectivo(efectivo);
    const pedido = ultima.modelo_pedido ? nombreEfectivo(ultima.modelo_pedido) : null;
    filas.push({ nodo, secciones, modelo, pedido: pedido && pedido !== modelo ? pedido : null });
  }
  return filas;
}

export const textoBloque = (bloque: Bloque): string => bloque.segmentos.map((s) => s.texto).join("");

function estadoDe(coincide: boolean | null | undefined): EstadoComparacion {
  if (coincide === true) return "coincide";
  if (coincide === false) return "difiere";
  return "sin_comparar";
}

function motivoConfianza(lecturas: (LecturaJev | undefined)[], umbral: number | undefined): string | null {
  if (umbral === undefined) return null;
  const baja = lecturas.find((l) => l !== undefined && l.confidence < umbral);
  return baja
    ? `La confianza de Jev (${porcentaje(baja.confidence)}) queda por debajo del mínimo para comparar (${porcentaje(umbral)}).`
    : null;
}

const AYUDA_SENTIDO = "Revise la frase del borrador que describe la decisión de primera instancia (I y III) antes de decidir.";
const AYUDA_ROL = "Revise quién impugna en la sección IV.";

export function filasJev(jev: JevMetadatos | null | undefined, md: MetadatosCaso | null | undefined): FilaJev[] {
  const preguntas = jev?.preguntas;
  if (!jev || !preguntas) return [];
  const filas: FilaJev[] = [];
  const { sentido_fallo: fallo, sentido_clausula: clausula, rol_impugnante: rol } = preguntas;

  if (fallo || clausula) {
    const estado = estadoDe(jev.coincide?.sentido);
    let motivo: string | null = estado === "difiere" ? AYUDA_SENTIDO : null;
    if (estado === "sin_comparar") {
      motivo =
        (!fallo && "Jev no pudo leer el sentido del fallo.") ||
        (!clausula && "Jev no pudo leer la frase del borrador sobre la decisión de primera instancia.") ||
        motivoConfianza([fallo, clausula], jev.umbral) ||
        "No hubo lecturas suficientes para comparar.";
    }
    filas.push({
      id: "sentido",
      etiqueta: "Sentido del fallo de primera instancia",
      borrador: {
        principal: md?.decision_a_quo ? mayuscula(limpiar(md.decision_a_quo)) : null,
        secundario: clausula
          ? `Jev entiende esa frase como «${etiquetaDe(ETIQUETA_SENTIDO, clausula.choice)}» (${porcentaje(clausula.confidence)})`
          : null,
      },
      jev: {
        principal: fallo ? etiquetaDe(ETIQUETA_SENTIDO, fallo.choice) : null,
        confianza: fallo?.confidence ?? null,
        nota: null,
      },
      estado,
      motivo,
    });
  }

  if (rol) {
    const estado = estadoDe(jev.coincide?.rol_impugnante);
    let motivo: string | null = estado === "difiere" ? AYUDA_ROL : null;
    if (estado === "sin_comparar") {
      motivo =
        (!md?.impugnante_rol && "El borrador no registra la calidad de quien impugna.") ||
        motivoConfianza([rol], jev.umbral) ||
        "No hubo lecturas suficientes para comparar.";
    }
    filas.push({
      id: "rol",
      etiqueta: "Quién impugna",
      borrador: {
        principal: md?.impugnante_rol ? etiquetaDe(ETIQUETA_ROL, md.impugnante_rol) : null,
        secundario: md?.impugnante ? limpiar(md.impugnante) : null,
      },
      jev: { principal: etiquetaDe(ETIQUETA_ROL, rol.choice), confianza: rol.confidence, nota: "en el escrito de impugnación" },
      estado,
      motivo,
    });
  }
  return filas;
}

function textoAlerta(mensaje: unknown): string | null {
  if (mensaje === null || mensaje === undefined) return null;
  const texto = typeof mensaje === "object" ? JSON.stringify(mensaje) : String(mensaje);
  return texto.trim() === "" ? null : texto;
}

function normalizarAlertas(alertas: AlertasApi | null | undefined): [string, string][] {
  if (!alertas) return [];
  const aTextos = (valor: unknown): string[] =>
    (Array.isArray(valor) ? valor : [valor]).map(textoAlerta).filter((m): m is string => m !== null);
  if (typeof alertas !== "object" || Array.isArray(alertas)) return aTextos(alertas).map((m): [string, string] => ["ingesta", m]);
  return Object.entries(alertas).flatMap(([nodo, mensajes]) => aTextos(mensajes).map((m): [string, string] => [nodo, m]));
}

function etiquetaNodo(nodo: string): string {
  return ETIQUETA_NODO[nodo] ?? mayuscula(nodo.replace(/_/g, " "));
}

const SECCIONES_NODO: Record<string, string> = { apertura: "II a IV", consideraciones: "V" };

const CAMPO_EXTENSION: Record<string, [string, string, string, string]> = {
  antecedentes: ["Los antecedentes", "son", "largos", "cortos"],
  sentencia_impugnada: ["La sentencia impugnada", "es", "larga", "corta"],
  impugnacion: ["La impugnación", "es", "larga", "corta"],
  consideraciones: ["Las consideraciones", "son", "largas", "cortas"],
  "caso concreto": ["El caso concreto", "es", "largo", "corto"],
};

const CAMPO_METADATOS: Record<string, string> = {
  juzgado_a_quo: "juzgado de primera instancia",
  accionante: "accionante",
  accionadas: "accionadas",
  vinculadas: "vinculadas",
  impugnante: "impugnante",
  impugnante_rol: "calidad de quien impugna",
};

const ORDEN_NIVEL: NivelRevision[] = ["mal", "alerta", "info", "ok"];

const NODO_APODERADOS = "apoderados";

export const dividirMotivos = (detalle: string | null): string[] =>
  (detalle ?? "").split(/(?<=\.);\s+/).filter((m) => m.trim() !== "");

function valoresPython(texto: string): string[] {
  const valores = [...texto.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)].map((m) => (m[1] ?? m[2] ?? "").replace(/\\(.)/g, (_, c: string) => ("nrt".includes(c) ? " " : c)));
  return valores.length > 0 ? valores : [texto];
}

export function humanizarAlerta(nodo: string, mensaje: string, bloquea: boolean): AlertaLegible {
  const seccion = SECCIONES_NODO[nodo];
  const origenNodo = seccion ? `${etiquetaNodo(nodo)} · ${seccion}` : etiquetaNodo(nodo);
  let m: RegExpExecArray | null;

  if ((m = /^(\S+) (.+): texto truncado a (\d+) caracteres para el LLM\.$/.exec(mensaje))) {
    const [, docId = "", archivo = "", n = "0"] = m;
    return {
      nivel: "info",
      origen: `Archivo ${docId}`,
      titulo: "El modelo leyó solo una parte de este documento",
      linea: archivo,
      lineaCompleta: false,
      detalle: {
        tipo: "archivo",
        archivo,
        nota: `Se le entregaron los primeros ${Number(n).toLocaleString("es-CO")} caracteres; lo que sigue no se tuvo en cuenta al redactar.`,
      },
    };
  }

  if ((m = /^(\S+) (.+) \((\w+)\): páginas sin texto legible: (.+)\.$/.exec(mensaje))) {
    const [, docId = "", archivo = "", , lista = ""] = m;
    const varias = lista.includes(",");
    return {
      nivel: "info",
      origen: `Archivo ${docId}`,
      titulo: `${varias ? "Páginas" : "Página"} ${lista} sin texto legible`,
      linea: archivo,
      lineaCompleta: false,
      detalle: { tipo: "archivo", archivo, nota: `El modelo no pudo leer ${varias ? "esas páginas" : "esa página"}.` },
    };
  }

  if ((m = /^([\w ]+): tiene (\d+) palabras, por (encima del máximo|debajo del mínimo) esperado \((\d+) a (\d+)\)\.$/.exec(mensaje))) {
    const [, campo = "", n = "", lado = "", minimo = "", maximo = ""] = m;
    const concordancia = CAMPO_EXTENSION[campo];
    const largo = lado.startsWith("encima");
    return {
      nivel: "alerta",
      origen: origenNodo,
      titulo: concordancia
        ? `${concordancia[0]} ${concordancia[1]} más ${largo ? concordancia[2] : concordancia[3]} de lo esperado`
        : `${mayuscula(campo)}: ${n} palabras`,
      linea: `${n} palabras; se esperaban entre ${minimo} y ${maximo}.`,
      lineaCompleta: true,
      detalle: null,
    };
  }

  if (
    (m = /^En metadatos, campo (\w+), la ingesta extrajo (.+?) y el modelo leyó (.+); se conserva el de la ingesta, verifique cuál es correcto\.$/.exec(
      mensaje,
    ))
  ) {
    const [, campo = "", extraido = "", leido = ""] = m;
    return {
      nivel: "alerta",
      origen: origenNodo,
      titulo: `${mayuscula(CAMPO_METADATOS[campo] ?? campo.replace(/_/g, " "))}: dos lecturas distintas`,
      linea: "Se conservó la que se extrajo del expediente.",
      lineaCompleta: false,
      detalle: {
        tipo: "comparar",
        lecturas: [
          { etiqueta: "Extraído del expediente · se conservó", valores: valoresPython(extraido) },
          { etiqueta: "Leído por el modelo", valores: valoresPython(leido) },
        ],
      },
    };
  }

  return { nivel: bloquea ? "mal" : "alerta", origen: origenNodo, titulo: mensaje, linea: null, lineaCompleta: false, detalle: null };
}

export function seccionesDeCitas(vista: Vista): Record<string, string> {
  const titulos = new Map(vista.indice.map((e) => [e.id, casoOracion(e.titulo)]));
  const secciones: Record<string, string> = {};
  for (const pagina of vista.paginas) {
    for (const bloque of pagina.bloques) {
      for (const segmento of bloque.segmentos) {
        if (segmento.cita_id) secciones[segmento.cita_id] = (bloque.seccion && titulos.get(bloque.seccion)) || "";
      }
    }
  }
  return secciones;
}

/**
 * Las marcas del índice: cuántas citas y nombres de abogados por revisar (o rechazados) hay en cada sección y en su
 * último subtítulo, cada uno una sola vez. Los abogados cuentan con el estado que trae /apoderados (`apoderados`);
 * sin él, sus nombres no marcan nada, como en el texto.
 */
export function marcasDelIndice(vista: Vista, apoderados: ReadonlyMap<string, Pick<ApoderadoVista, "estado">> = new Map()): Record<string, MarcaIndice> {
  const estados = new Map(vista.citas.map((c) => [c.id, c.estado]));
  const marcas: Record<string, MarcaIndice> = {};
  let subtitulo: string | null = null;
  const contadas = new Set<string>();
  const marcar = (clave: string | null, mal: boolean, id: string, abogado: boolean) => {
    if (!clave || contadas.has(`${clave}\0${id}`)) return;
    contadas.add(`${clave}\0${id}`);
    const marca = (marcas[clave] ??= { n: 0, mal: false });
    marca.n += 1;
    marca.mal ||= mal;
    if (abogado) marca.apoderados = (marca.apoderados ?? 0) + 1;
  };
  for (const pagina of vista.paginas) {
    for (const bloque of pagina.bloques) {
      if (bloque.tipo === "titulo") subtitulo = null;
      if (bloque.tipo === "encabezado" && bloque.seccion) subtitulo = bloque.id;
      for (const segmento of bloque.segmentos) {
        const marca = marcaDe(segmento, estados, apoderados);
        if (!marca) continue;
        marcar(bloque.seccion, marca.mal, marca.id, marca.abogado);
        marcar(subtitulo, marca.mal, marca.id, marca.abogado);
      }
    }
  }
  return marcas;
}

/** Lo que un segmento aporta al índice: una cita sin verificar o el nombre de un abogado sin verificar; si no, nada. */
function marcaDe(
  segmento: Segmento,
  citas: ReadonlyMap<string, CitaVista["estado"]>,
  apoderados: ReadonlyMap<string, Pick<ApoderadoVista, "estado">>,
): { id: string; mal: boolean; abogado: boolean } | null {
  if (segmento.cita_id) {
    const estado = citas.get(segmento.cita_id);
    return estado && estado !== "verificada" ? { id: `c:${segmento.cita_id}`, mal: estado === "rechazada", abogado: false } : null;
  }
  if (segmento.apoderado_id) {
    const estado = apoderados.get(segmento.apoderado_id)?.estado;
    return estado && estado !== "verificado" ? { id: `a:${segmento.apoderado_id}`, mal: estado === "no_verificado", abogado: true } : null;
  }
  return null;
}

export function construirRevision(
  citas: CitaVista[],
  alertas: AlertasApi | null | undefined,
  jev: FilaJev[],
  secciones: Record<string, string>,
): ItemRevision[] {
  const items: ItemRevision[] = [];
  const idsCitas = new Set(citas.map((c) => c.id));

  for (const cita of citas) {
    const motivos = dividirMotivos(cita.detalle);
    const seccion = secciones[cita.id];
    items.push({
      clave: `cita-${cita.id}`,
      nivel: cita.estado === "rechazada" ? "mal" : cita.estado === "revisar" ? "alerta" : "ok",
      origen: seccion ? `Cita · ${seccion}` : "Cita",
      titulo: mayuscula(cita.fuente) || cita.id,
      linea: cita.estado === "verificada" ? `Verificada · cobertura ${porcentaje(cita.cobertura)}` : (motivos[0] ?? ETIQUETA_ESTADO_CITA[cita.estado]),
      lineaCompleta: false,
      detalle: { tipo: "cita", cita, motivos },
      marca: { tipo: "cita", id: cita.id },
      grupo: "citas",
    });
  }

  for (const fila of jev) {
    items.push({
      clave: `jev-${fila.id}`,
      nivel: fila.estado === "difiere" ? "alerta" : fila.estado === "coincide" ? "ok" : "info",
      origen: fila.estado === "difiere" ? "Jev · no coincide" : fila.estado === "coincide" ? "Jev · coincide" : "Jev · sin comparar",
      titulo: fila.etiqueta,
      linea: `Borrador: ${fila.borrador.principal ?? "Sin dato"} · Jev: ${fila.jev.principal ?? "Sin lectura"}`,
      lineaCompleta: false,
      detalle: { tipo: "jev", fila },
      marca: null,
      grupo: "citas",
    });
  }

  normalizarAlertas(alertas).forEach(([nodo, mensaje], i) => {
    const bloquea = /^BLOQUEA:\s*/.test(mensaje);
    const texto = mensaje.replace(/^(ALERTA|BLOQUEA):\s*/, "");
    const rechazo = /^La cita (\S+) \(.*\) (?:fue rechazada|requiere revisión):/.exec(texto);
    if (rechazo?.[1] && idsCitas.has(rechazo[1])) return;
    if (jev.length > 0 && /^Jev lee /.test(texto)) return;
    const grupo = nodo === NODO_APODERADOS ? "apoderados" : "citas";
    items.push({ clave: `alerta-${nodo}-${i}`, ...humanizarAlerta(nodo, texto, bloquea), marca: null, grupo });
  });

  return ORDEN_NIVEL.flatMap((nivel) => items.filter((item) => item.nivel === nivel));
}

export const claveRevisados = (caso: string, sha: string): string => `judicabot:revisados:${caso}:${sha}`;

export function leerRevisados(clave: string): Set<string> {
  try {
    const crudo = localStorage.getItem(clave);
    if (!crudo) return new Set();
    const valor: unknown = JSON.parse(crudo);
    return Array.isArray(valor) && valor.every((v) => typeof v === "string") ? new Set<string>(valor) : new Set();
  } catch {
    return new Set();
  }
}

export function guardarRevisados(clave: string, revisados: ReadonlySet<string>): void {
  try {
    const prefijo = clave.slice(0, clave.lastIndexOf(":") + 1);
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const otra = localStorage.key(i);
      if (otra && otra !== clave && otra.startsWith(prefijo)) localStorage.removeItem(otra);
    }
    localStorage.setItem(clave, JSON.stringify([...revisados]));
  } catch {
    return;
  }
}

export function limitePasos(estado: EstadoCaso | null): EtapaPaso {
  if (estado?.estado === "esperando_decision") return "decision";
  if (estado?.estado === "terminado") return "fallo";
  return "borrador";
}

export function agruparBloques(bloques: Bloque[]): GrupoBloque[] {
  const grupos: GrupoBloque[] = [];
  for (const bloque of bloques) {
    const ultimo = grupos[grupos.length - 1];
    if (bloque.tipo === "tabla" || bloque.tipo === "lista") {
      if (ultimo && ultimo.tipo === bloque.tipo) ultimo.bloques.push(bloque);
      else grupos.push({ tipo: bloque.tipo, bloques: [bloque] });
    } else {
      grupos.push({ tipo: "bloque", bloque });
    }
  }
  return grupos;
}

export function casoOracion(titulo: string): string {
  if (titulo !== titulo.toUpperCase()) return titulo;
  const m = /^([IVXL]+\.\s*)?(.*)$/.exec(titulo);
  const numeral = m?.[1] ?? "";
  const resto = (m?.[2] ?? "").toLowerCase();
  return `${numeral}${mayuscula(resto)}`;
}

export function construirIndice(vista: Vista): EntradaIndice[] {
  const titulos = new Map(vista.indice.map((e) => [e.id, e.titulo]));
  const entradas: EntradaIndice[] = [];
  for (const pagina of vista.paginas) {
    for (const bloque of pagina.bloques) {
      if (bloque.tipo === "titulo") {
        const titulo = titulos.get(bloque.id);
        entradas.push({
          id: bloque.id,
          titulo: casoOracion(titulo ?? limpiar(textoBloque(bloque))),
          sub: false,
          anexo: !/^[IVXL]+\./.test(titulo ?? ""),
        });
      } else if (bloque.tipo === "encabezado" && bloque.seccion) {
        const titulo = limpiar(textoBloque(bloque));
        if (titulo && titulo.length <= 120) entradas.push({ id: bloque.id, titulo: casoOracion(titulo), sub: true, anexo: false });
      }
    }
  }
  return entradas;
}

export function tituloDelCaso(caso: string, md: MetadatosCaso | null | undefined): string {
  const accionante = md?.accionante?.trim();
  const accionadas = (md?.accionadas ?? []).filter(Boolean);
  if (accionante && accionadas.length > 0) return `${accionante} c. ${accionadas.join(", ")}`;
  return accionante || caso;
}

export function comportamientoScroll(): ScrollBehavior {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

export function irA(elemento: Element | null, block: ScrollLogicalPosition = "start"): void {
  if (elemento && typeof elemento.scrollIntoView === "function") {
    elemento.scrollIntoView({ block, behavior: comportamientoScroll() });
  }
}
