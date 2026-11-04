import type { Bloque, CitaVista, Vista } from "../../api/contrato";
import { porcentaje } from "../../estado";
import type { EtapaPaso } from "../../ui";
import type {
  AlertasApi,
  EntradaIndice,
  EstadoCaso,
  EstadoComparacion,
  FilaJev,
  GrupoBloque,
  ItemRevision,
  JevMetadatos,
  LecturaJev,
  MetadatosCaso,
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
  consideraciones: "Consideraciones",
  caso_concreto: "Caso concreto",
  documentos_caso: "Documentos",
};

const mayuscula = (texto: string) => (texto ? texto.charAt(0).toUpperCase() + texto.slice(1) : texto);
const etiquetaDe = (mapa: Record<string, string>, clave: string) => mapa[clave] ?? clave;
const limpiar = (texto: string) => texto.replace(/\s+/g, " ").trim();

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

export function filasJev(jev: JevMetadatos | null | undefined, md: MetadatosCaso | null | undefined): FilaJev[] {
  const preguntas = jev?.preguntas;
  if (!jev || !preguntas) return [];
  const filas: FilaJev[] = [];
  const { sentido_fallo: fallo, sentido_clausula: clausula, rol_impugnante: rol } = preguntas;

  if (fallo || clausula) {
    const estado = estadoDe(jev.coincide?.sentido);
    let motivo: string | null = null;
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
    let motivo: string | null = null;
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

function normalizarAlertas(alertas: AlertasApi | null | undefined): [string, string][] {
  if (!alertas) return [];
  if (Array.isArray(alertas)) return alertas.map((m) => ["ingesta", m]);
  return Object.entries(alertas).flatMap(([nodo, mensajes]) =>
    Array.isArray(mensajes) ? mensajes.map((m): [string, string] => [nodo, m]) : [],
  );
}

function etiquetaNodo(nodo: string): string {
  return ETIQUETA_NODO[nodo] ?? mayuscula(nodo.replace(/_/g, " "));
}

export function construirRevision(citas: CitaVista[], alertas: AlertasApi | null | undefined): ItemRevision[] {
  const items: ItemRevision[] = [];
  for (const cita of citas) {
    if (cita.estado === "verificada") continue;
    items.push({
      clave: `cita-${cita.id}`,
      tono: cita.estado === "rechazada" ? "mal" : "alerta",
      etiqueta: cita.estado === "rechazada" ? "Cita no verificada" : "Cita con alerta",
      texto: cita.fuente || cita.texto || cita.id,
      detalle: cita.detalle,
      cita: cita.id,
    });
  }
  normalizarAlertas(alertas).forEach(([nodo, mensaje], i) => {
    const bloquea = /^BLOQUEA:\s*/.test(mensaje);
    items.push({
      clave: `alerta-${nodo}-${i}`,
      tono: bloquea ? "mal" : "alerta",
      etiqueta: etiquetaNodo(nodo),
      texto: mensaje.replace(/^(ALERTA|BLOQUEA):\s*/, ""),
      detalle: null,
      cita: null,
    });
  });
  return [...items.filter((x) => x.tono === "mal"), ...items.filter((x) => x.tono === "alerta")];
}

export function conteoCitas(citas: CitaVista[]): Record<CitaVista["estado"], number> {
  const conteo = { verificada: 0, revisar: 0, rechazada: 0 };
  for (const c of citas) conteo[c.estado] += 1;
  return conteo;
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
        entradas.push({ id: bloque.id, titulo: casoOracion(titulos.get(bloque.id) ?? limpiar(textoBloque(bloque))), sub: false });
      } else if (bloque.tipo === "encabezado" && bloque.seccion) {
        const titulo = limpiar(textoBloque(bloque));
        if (titulo && titulo.length <= 120) entradas.push({ id: bloque.id, titulo: casoOracion(titulo), sub: true });
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
