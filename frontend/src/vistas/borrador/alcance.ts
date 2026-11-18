import type { CorreccionCuerpo } from "./tipos";

type Accion = CorreccionCuerpo["decision"]["accion"];

export type IdAviso = "plantilla-fija" | "encabezado" | "resuelve" | "asunto" | "alcance-apertura" | "alcance-consideraciones";

export interface AvisoAlcance {
  id: IdAviso;
  texto: string;
}

const TEXTOS: Record<IdAviso, string> = {
  "plantilla-fija":
    "Competencia, legitimación, el marco general de la acción de tutela (artículo 86 y Decreto 2591 de 1991) y el párrafo de transición son texto fijo de la plantilla: una corrección no los cambia. Si necesita otro texto, edítelo en el .docx del fallo antes de firmar.",
  encabezado:
    "Los datos del encabezado (radicado, partes, procedencia) salen del expediente y una corrección no los cambia: se corrigen en Documentos antes de iniciar la redacción. El nombre del despacho y el pie salen del formato con el que se creó el caso; cambiarlos en Configuración → Formato de documentos solo afecta a los casos nuevos.",
  resuelve: "El RESUELVE, la fecha y la firma no forman parte del borrador: salen de su decisión. Se fijan en el paso Decisión.",
  asunto: "El Asunto (sección I) se rehace con «Rehacer la apertura»: «Rehacer las consideraciones» solo cambia la sección V.",
  "alcance-apertura":
    "«Rehacer las consideraciones» solo cambia la sección V, y su instrucción parece hablar de los antecedentes, la sentencia impugnada o la impugnación (secciones II a IV). Si es eso lo que quiere cambiar, elija «Rehacer la apertura».",
  "alcance-consideraciones":
    "«Rehacer la apertura» cambia las secciones I a IV y después rehace las consideraciones desde cero, sin su instrucción. Su instrucción parece hablar de la sección V (consideraciones o citas). Si es eso lo que quiere cambiar, elija «Rehacer las consideraciones».",
};

/** Sin tildes ni mayúsculas, para que «COMPETENCIA» y «competencia» valgan igual. */
const normalizar = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

interface Regla {
  id: IdAviso;
  patron: RegExp;
  aplica: (accion: Accion | null) => boolean;
}

// Las tres primeras reglas hablan de texto que ninguna corrección cambia y valen con cualquier opción (o sin elegir);
// las demás exigen una opción elegida porque comparan lo que pide la instrucción con lo que esa opción rehace.
const REGLAS: Regla[] = [
  {
    id: "plantilla-fija",
    patron: /\b(competen\w*|legitimaci\w*|articulo 86|art\.? 86|decreto 2591|transicion|presupuestos generales|marco general)\b/,
    aplica: () => true,
  },
  {
    id: "encabezado",
    patron: /\b(encabezado|radicado|tabla de datos|datos del encabezado|procedencia|nombre del (accionante|accionado|accionada|despacho|juzgado))\b/,
    aplica: () => true,
  },
  {
    // Exige artículo («el/del/al resuelve») para no saltar con «se resuelve el caso».
    id: "resuelve",
    patron: /\b(?:(?:el|del|al)\s+resuelve|parte resolutiva|numeral(?:es)?|fecha del fallo|la firma|notifiquese)\b/,
    aplica: () => true,
  },
  { id: "asunto", patron: /\basunto\b/, aplica: (a) => a === "rehacer_consideraciones" },
  {
    id: "alcance-apertura",
    patron: /\b(antecedentes?|los hechos|contestaci\w+|sentencia impugnada|escrito de impugnacion|la impugnacion)\b/,
    aplica: (a) => a === "rehacer_consideraciones",
  },
  {
    id: "alcance-consideraciones",
    patron: /\b(procedibilidad|inmediatez|subsidiariedad|perjuicio irremediable|jurisprudencia\w*|consideraciones|cita\w*|(?:sentencia )?(?:t|su|c)-\s?\d+)\b/,
    aplica: (a) => a === "rehacer_apertura",
  },
];

/**
 * Avisos orientativos (nunca bloquean el envío) sobre lo que una instrucción de corrección no puede cambiar o no alcanza
 * con la opción elegida. Cada regla aporta como máximo un aviso, en el orden de `REGLAS`.
 */
export function avisosDeAlcance(instruccion: string, accion: Accion | null): AvisoAlcance[] {
  const texto = normalizar(instruccion);
  if (texto.trim() === "") return [];
  return REGLAS.filter((r) => r.aplica(accion) && r.patron.test(texto)).map((r) => ({ id: r.id, texto: TEXTOS[r.id] }));
}
