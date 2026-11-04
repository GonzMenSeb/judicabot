import type { MockRuta } from "../../api/mock";
import type { DecisionVistaRespuesta, NumeralVista } from "../../api/contrato";
import type { DecisionCuerpo, PayloadDecision } from "./tipos";

const CASO = "quintero-bedoya";

const payload: PayloadDecision = {
  reparos: [
    { id: "R1", sintesis: "El a quo no valoró la orden médica vigente que prescribe el tratamiento." },
    { id: "R2", sintesis: "Se desconoció el carácter fundamental del derecho a la salud de una persona con enfermedad crónica." },
  ],
  decision_a_quo: "Declaró improcedente la acción de tutela",
  impugnante: "Marta Inés Quintero Bedoya",
  impugnante_rol: "accionante",
  impugnantes: [],
  derechos_invocados: ["salud", "mínimo vital"],
  pruebas_nuevas_2a: [],
  fecha_hoy: "2026-11-03",
  errores: [],
};

const falta = (nombre: string) => `⟦FALTA: ${nombre}⟧`;
const ARTICULO = /^(el|la|los|las)\s+/i;
const conArticulo = (d: string) => (ARTICULO.test(d) ? d : d === "salud" ? "la salud" : `el ${d}`);
const sinArticulo = (d: string) => d.replace(ARTICULO, "");
const UNIDADES: Record<string, string> = { horas_habiles: "horas hábiles", dias_habiles: "días hábiles", horas: "horas", dias: "días" };

function numeralesDe(d: DecisionCuerpo): NumeralVista[] {
  const por = new Map<string, NumeralVista>();
  const resultado = d.resultado ?? falta("resultado");
  por.set("resultado", {
    clave: "resultado",
    texto: `${resultado} la sentencia proferida el veintiocho (28) de septiembre de dos mil veintiséis (2026) por el Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín, que declaró improcedente la acción de tutela, de conformidad con lo expuesto en la parte motiva de este proveído.`,
    negritas: [resultado],
  });
  if (d.resultado !== "CONFIRMAR") {
    const amparados = d.derechos.filter((x) => x.disposicion === "AMPARA").map((x) => conArticulo(x.derecho));
    const lista = amparados.length ? amparados.join(" y ") : falta("derechos");
    const textos: Record<string, [string, string]> = {
      AMPARAR: ["AMPARAR", `AMPARAR los derechos fundamentales a ${lista} de MARTA INÉS QUINTERO BEDOYA.`],
      NEGAR: ["NEGAR", "NEGAR el amparo solicitado por MARTA INÉS QUINTERO BEDOYA, por las razones expuestas en la parte motiva."],
      IMPROCEDENTE: ["DECLARAR IMPROCEDENTE", "DECLARAR IMPROCEDENTE la acción de tutela promovida por MARTA INÉS QUINTERO BEDOYA, por las razones expuestas en la parte motiva."],
    };
    const [negrita, texto] = (d.sustitutiva && textos[d.sustitutiva]) || [
      d.sustitutiva ? "DECLARAR LA CARENCIA ACTUAL DE OBJETO" : "",
      d.sustitutiva
        ? "DECLARAR LA CARENCIA ACTUAL DE OBJETO en la acción de tutela promovida por MARTA INÉS QUINTERO BEDOYA, por las razones expuestas en la parte motiva."
        : falta("decisión sustitutiva"),
    ];
    por.set("sustitutiva", { clave: "sustitutiva", texto, negritas: negrita ? [negrita] : [] });
  }
  d.ordenes.forEach((o, i) => {
    const dest = o.destinatario || falta("destinatario");
    const conducta = (o.conducta || falta("conducta")).replace(/[ .:;,]+$/, "");
    const via = o.via_representante ? " a través de su representante legal y/o quien haga sus veces," : "";
    const termino = o.mismo_termino ? "dentro del mismo término" : `dentro de ${o.plazo.n} ${UNIDADES[o.plazo.unidad] ?? o.plazo.unidad} a la notificación de esta providencia`;
    por.set(`orden:${i}`, { clave: `orden:${i}`, texto: `${o.verbo} a ${dest}${via} que, ${termino}, ${conducta}.`, negritas: [o.verbo, sinArticulo(dest)] });
  });
  if (d.prevenir.length) por.set("prevenir", { clave: "prevenir", texto: `PREVENIR a ${d.prevenir.join(" y a ")} para que, en lo sucesivo, no vuelva a incurrir en las acciones u omisiones que dieron lugar a la presente acción de tutela.`, negritas: ["PREVENIR"] });
  if (d.desvincular.length) por.set("desvincular", { clave: "desvincular", texto: `DESVINCULAR de la presente acción de tutela a ${d.desvincular.join(" y a ")}, por las razones expuestas en la parte motiva de esta providencia.`, negritas: ["DESVINCULAR"] });
  if (d.compulsa) {
    const organo = d.compulsa.organo ?? "Comisión Seccional de Disciplina Judicial de Antioquia";
    por.set("compulsa", { clave: "compulsa", texto: `COMPULSAR COPIAS ante la ${organo} para que, de estimarlo pertinente, adelante las actuaciones a que haya lugar respecto de ${d.compulsa.respecto_de || falta("respecto de quién")}.`, negritas: ["COMPULSAR COPIAS"] });
  }
  d.numerales_libres.forEach((t, i) => por.set(`libre:${i}`, { clave: `libre:${i}`, texto: t || falta("texto libre"), negritas: [] }));
  if (d.numerales.notificar) por.set("notificar", { clave: "notificar", texto: "NOTIFICAR esta providencia a las partes por el medio más expedito, de conformidad con lo dispuesto en el artículo 30 del Decreto 2591 de 1991.", negritas: ["NOTIFICAR"] });
  if (d.numerales.remitir_corte) por.set("remitir", { clave: "remitir", texto: "REMITIR el expediente a la Honorable Corte Constitucional para su eventual revisión.", negritas: ["REMITIR"] });
  const claves = [...new Set([...d.orden_numerales, ...por.keys()])].filter((k) => por.has(k));
  return claves.map((k) => por.get(k) as NumeralVista);
}

function vistaDe(cuerpo: unknown): DecisionVistaRespuesta {
  const d = cuerpo as DecisionCuerpo;
  const faltantes: DecisionVistaRespuesta["faltantes"] = [];
  if (!d.resultado) faltantes.push({ campo: "resultado", mensaje: "Falta el resultado (CONFIRMAR, REVOCAR o MODIFICAR)." });
  if (!d.sustitutiva && d.resultado !== "CONFIRMAR") faltantes.push({ campo: "sustitutiva", mensaje: "Falta la decisión sustitutiva (AMPARAR, NEGAR, ...)." });
  if (!d.eje) faltantes.push({ campo: "eje", mensaje: "Falta el eje: 2 a 5 líneas con el porqué de la decisión." });
  if (d.sustitutiva === "AMPARAR" && !d.ordenes.length) faltantes.push({ campo: "ordenes", mensaje: "Si se ampara, hay que indicar al menos una orden." });
  d.ordenes.forEach((o, i) => {
    if (!o.destinatario) faltantes.push({ campo: `ordenes.${i}.destinatario`, mensaje: "Cada orden necesita destinatario y conducta." });
    if (!o.conducta) faltantes.push({ campo: `ordenes.${i}.conducta`, mensaje: "Cada orden necesita destinatario y conducta." });
  });
  return { numerales: numeralesDe(d), faltantes, errores: [...new Set(faltantes.map((f) => f.mensaje))] };
}

export const mocks: MockRuta[] = [
  {
    metodo: "GET",
    ruta: `/api/casos/${CASO}/estado`,
    respuesta: { ok: true, estado: "esperando_decision", payload, salidas: [], resumen: {}, error: null, job_activo: null },
  },
  {
    metodo: "GET",
    ruta: `/api/casos/${CASO}/config`,
    respuesta: { despacho: { juez: "Santiago Alejandro Cadavid Duque", cierre_fallo: "NOTIFÍQUESE Y CÚMPLASE" }, llm: { proveedor: "fake" } },
  },
  { metodo: "POST", ruta: /^\/api\/casos\/[^/]+\/decision\/vista$/, respuesta: ({ cuerpo }) => vistaDe(cuerpo) },
  { metodo: "POST", ruta: `/api/casos/${CASO}/run`, respuesta: { job_id: "job-decision-demo" } },
];
