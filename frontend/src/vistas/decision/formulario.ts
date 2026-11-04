import type {
  DecisionCuerpo,
  DisposicionDerecho,
  DisposicionReparo,
  Formulario,
  Hallazgo,
  OrdenForm,
  PayloadDecision,
  Resultado,
  SustitutivaApi,
  SustitutivaForm,
  Unidad,
  Verbo,
} from "./tipos";

export const RESULTADOS: readonly (readonly [Resultado, string])[] = [
  ["CONFIRMAR", "Confirmar"],
  ["REVOCAR", "Revocar"],
  ["MODIFICAR", "Modificar"],
];

export const SUSTITUTIVAS: readonly (readonly [SustitutivaForm, string, string])[] = [
  ["AMPARAR", "Amparar", "Se conceden los derechos y se imparten órdenes."],
  ["NEGAR", "Negar el amparo", "Se niegan las pretensiones."],
  ["IMPROCEDENTE", "Declarar improcedente", "No se estudia de fondo."],
  ["CARENCIA", "Carencia actual de objeto", "Hecho superado, daño consumado o situación sobreviniente."],
];

export const CARENCIAS: readonly (readonly [SustitutivaApi, string])[] = [
  ["CARENCIA_HECHO_SUPERADO", "Hecho superado"],
  ["CARENCIA_DANO_CONSUMADO", "Daño consumado"],
  ["CARENCIA_SOBREVINIENTE", "Situación sobreviniente"],
];

export const DISPOSICIONES_REPARO: readonly (readonly [DisposicionReparo, string])[] = [
  ["ACOGE", "Acoge"],
  ["DESESTIMA", "Desestima"],
  ["ACOGE_PARCIAL", "Acoge parcialmente"],
  ["REFORMULA", "Reformula"],
  ["ABSORBIDO", "Absorbido por otro reparo"],
];

export const DISPOSICIONES_DERECHO: readonly (readonly [DisposicionDerecho, string])[] = [
  ["AMPARA", "Ampara"],
  ["NIEGA", "Niega"],
  ["SIN_PRONUNCIAMIENTO", "Sin pronunciamiento"],
];

export const VERBOS: readonly Verbo[] = ["ORDENAR", "PREVENIR", "ADVERTIR"];

export const UNIDADES: readonly (readonly [Unidad, string])[] = [
  ["horas_habiles", "horas hábiles"],
  ["dias_habiles", "días hábiles"],
  ["horas", "horas"],
  ["dias", "días"],
];

export const MSG = {
  resultado: "Falta el resultado (CONFIRMAR, REVOCAR o MODIFICAR).",
  sustitutiva: "Falta la decisión sustitutiva (AMPARAR, NEGAR, ...).",
  carencia: "Falta indicar el tipo de carencia actual de objeto.",
  eje: "Falta el eje: 2 a 5 líneas con el porqué de la decisión.",
  sinOrdenes: "Si se ampara, hay que indicar al menos una orden.",
  ordenIncompleta: "Cada orden necesita destinatario y conducta.",
  plazo: "El plazo de cada orden debe ser mayor que cero.",
  libreVacio: "Hay un numeral libre vacío.",
  compulsa: "La compulsa de copias necesita indicar respecto de quién.",
} as const;

const ORDINALES = ["PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO", "SEXTO", "SÉPTIMO", "OCTAVO", "NOVENO"];
const DECENAS = ["", "DÉCIMO", "VIGÉSIMO", "TRIGÉSIMO"];

export function ordinal(i: number): string {
  if (i < 10) return ORDINALES[i - 1] ?? `NUMERAL ${i}`;
  if (i >= 40) return `NUMERAL ${i}`;
  const decena = DECENAS[Math.floor(i / 10)] ?? "";
  return i % 10 === 0 ? decena : `${decena} ${ORDINALES[(i % 10) - 1]}`;
}

export const lineas = (texto: string): string[] =>
  texto
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

export function hoyISO(ahora: Date = new Date()): string {
  const mes = String(ahora.getMonth() + 1).padStart(2, "0");
  const dia = String(ahora.getDate()).padStart(2, "0");
  return `${ahora.getFullYear()}-${mes}-${dia}`;
}

export function ordenNueva(id: number): OrdenForm {
  return {
    id,
    verbo: "ORDENAR",
    destinatario: "",
    conducta: "",
    n: "48",
    unidad: "horas_habiles",
    via: true,
    condicion: "",
    mismo: false,
  };
}

export function formularioInicial(payload: PayloadDecision | null, juez: string, hoy: string): Formulario {
  const derechos = (payload?.derechos_invocados ?? []).map((nombre, i) => ({
    id: i + 1,
    nombre,
    disposicion: "AMPARA" as const,
    propio: false,
  }));
  return {
    resultado: "",
    sustitutiva: "",
    eje: "",
    decididoPor: juez,
    reparos: (payload?.reparos ?? []).map((r) => ({ id: r.id, disposicion: "ACOGE", nota: "" })),
    derechos,
    ordenes: [],
    desvincular: "",
    prevenir: "",
    compulsa: false,
    organo: "",
    respectoDe: "",
    hechosRef: "",
    notificar: true,
    remitir: true,
    generarFormato: true,
    fechaFallo: payload?.fecha_hoy ?? hoy,
    fechaOficio: "",
    etiqueta: "",
    libres: [],
    orden: [],
    reordenado: false,
    siguienteId: derechos.length + 1,
  };
}

export function sustitutivaEfectiva(f: Formulario): SustitutivaForm {
  return f.resultado === "CONFIRMAR" ? "" : f.sustitutiva;
}

const esApi = (s: SustitutivaForm): s is SustitutivaApi => s !== "" && s !== "CARENCIA";

export function elegirSustitutiva(f: Formulario, s: SustitutivaForm): Formulario {
  const siguiente = { ...f, sustitutiva: s };
  if (s === "AMPARAR" && f.ordenes.length === 0) {
    return { ...siguiente, ordenes: [ordenNueva(f.siguienteId)], siguienteId: f.siguienteId + 1 };
  }
  return siguiente;
}

export function agregarOrden(f: Formulario): Formulario {
  return { ...f, ordenes: [...f.ordenes, ordenNueva(f.siguienteId)], siguienteId: f.siguienteId + 1 };
}

export function agregarLibre(f: Formulario): Formulario {
  return { ...f, libres: [...f.libres, { id: f.siguienteId, texto: "" }], siguienteId: f.siguienteId + 1 };
}

export function agregarDerecho(f: Formulario, nombre: string): Formulario {
  const limpio = nombre.trim();
  if (!limpio) return f;
  const derechos = [...f.derechos, { id: f.siguienteId, nombre: limpio, disposicion: "AMPARA" as const, propio: true }];
  return { ...f, derechos, siguienteId: f.siguienteId + 1 };
}

export function clavesVigentes(f: Formulario): string[] {
  const k = ["resultado"];
  if (f.resultado && f.resultado !== "CONFIRMAR") k.push("sustitutiva");
  if (sustitutivaEfectiva(f) === "AMPARAR") f.ordenes.forEach((o) => k.push(`orden#${o.id}`));
  if (lineas(f.prevenir).length) k.push("prevenir");
  if (lineas(f.desvincular).length) k.push("desvincular");
  if (f.compulsa) k.push("compulsa");
  f.libres.forEach((l) => k.push(`libre#${l.id}`));
  if (f.notificar) k.push("notificar");
  if (f.remitir) k.push("remitir");
  return k;
}

export function clavesOrdenadas(f: Formulario): string[] {
  const vigentes = clavesVigentes(f);
  if (!f.reordenado) return vigentes;
  return [...f.orden.filter((k) => vigentes.includes(k)), ...vigentes.filter((k) => !f.orden.includes(k))];
}

function indiceDe(lista: { id: number }[], id: string): number {
  return lista.findIndex((x) => x.id === Number(id));
}

export function aClaveApi(f: Formulario, interna: string): string {
  const [tipo = "", id = ""] = interna.split("#");
  if (tipo === "orden") return `orden:${indiceDe(f.ordenes, id)}`;
  if (tipo === "libre") return `libre:${indiceDe(f.libres, id)}`;
  return interna;
}

export function aClaveInterna(f: Formulario, api: string): string | null {
  const [tipo = "", i = ""] = api.split(":");
  const lista = tipo === "orden" ? f.ordenes : tipo === "libre" ? f.libres : null;
  if (!lista) return api;
  const item = lista[Number(i)];
  return item ? `${tipo}#${item.id}` : null;
}

export function moverClave(f: Formulario, interna: string, destino: string | number): Formulario {
  const claves = clavesOrdenadas(f);
  const desde = claves.indexOf(interna);
  const hasta = typeof destino === "number" ? desde + destino : claves.indexOf(destino);
  if (desde < 0 || hasta < 0 || hasta >= claves.length || hasta === desde) return f;
  const nuevas = [...claves];
  nuevas.splice(desde, 1);
  nuevas.splice(hasta, 0, interna);
  return { ...f, orden: nuevas, reordenado: true };
}

export function aDecision(f: Formulario): DecisionCuerpo {
  const sustitutiva = sustitutivaEfectiva(f);
  const amparar = sustitutiva === "AMPARAR";
  const aplicanDerechos = amparar || sustitutiva === "NEGAR";
  const respecto = f.respectoDe.trim();
  const organo = f.organo.trim();
  return {
    accion: "decidir",
    resultado: f.resultado || null,
    sustitutiva: esApi(sustitutiva) ? sustitutiva : null,
    eje: f.eje.trim(),
    por_reparo: f.reparos.map((r) => ({ reparo_id: r.id, disposicion: r.disposicion, nota: r.nota.trim() })),
    derechos: aplicanDerechos ? f.derechos.map((d) => ({ derecho: d.nombre, disposicion: d.disposicion })) : [],
    ordenes: amparar
      ? f.ordenes.map((o) => ({
          mismo_termino: o.mismo,
          verbo: o.verbo,
          destinatario: o.destinatario.trim(),
          via_representante: o.via,
          conducta: o.conducta.trim(),
          plazo: { n: Number(o.n) || 0, unidad: o.unidad },
          condicion: o.condicion.trim(),
        }))
      : [],
    desvincular: lineas(f.desvincular),
    prevenir: lineas(f.prevenir),
    compulsa: f.compulsa
      ? { respecto_de: respecto, hechos_ref: f.hechosRef.trim(), ...(organo ? { organo } : {}) }
      : null,
    numerales: { notificar: f.notificar, remitir_corte: f.remitir },
    decidido_por: f.decididoPor.trim(),
    generar_formato: f.generarFormato,
    fecha_fallo: f.fechaFallo || null,
    fecha_oficio: f.fechaOficio || null,
    etiqueta_encabezado: f.etiqueta.trim(),
    numerales_libres: f.libres.map((l) => l.texto.trim()),
    orden_numerales: f.reordenado ? clavesOrdenadas(f).map((k) => aClaveApi(f, k)) : [],
  };
}

export function validar(d: DecisionCuerpo): Hallazgo[] {
  const e: Hallazgo[] = [];
  if (!d.resultado) e.push({ campo: "resultado", mensaje: MSG.resultado });
  if (!d.sustitutiva && d.resultado !== "CONFIRMAR") e.push({ campo: "sustitutiva", mensaje: MSG.sustitutiva });
  if (!d.eje) e.push({ campo: "eje", mensaje: MSG.eje });
  if (d.sustitutiva === "AMPARAR" && !d.ordenes.length) e.push({ campo: "ordenes", mensaje: MSG.sinOrdenes });
  d.ordenes.forEach((o, i) => {
    if (!o.destinatario) e.push({ campo: `ordenes.${i}.destinatario`, mensaje: MSG.ordenIncompleta });
    if (!o.conducta) e.push({ campo: `ordenes.${i}.conducta`, mensaje: MSG.ordenIncompleta });
    if (!(o.plazo.n > 0)) e.push({ campo: `ordenes.${i}.plazo.n`, mensaje: MSG.plazo });
  });
  d.numerales_libres.forEach((t, i) => {
    if (!t) e.push({ campo: `numerales_libres.${i}`, mensaje: MSG.libreVacio });
  });
  if (d.compulsa && !d.compulsa.respecto_de) e.push({ campo: "compulsa.respecto_de", mensaje: MSG.compulsa });
  return e;
}

export function hallazgosLocales(f: Formulario): Hallazgo[] {
  const hallazgos = validar(aDecision(f));
  if (f.sustitutiva === "CARENCIA" && f.resultado && f.resultado !== "CONFIRMAR") {
    return hallazgos.map((h) => (h.campo === "sustitutiva" ? { ...h, mensaje: MSG.carencia } : h));
  }
  return hallazgos;
}

export function combinar(locales: Hallazgo[], servidor: Hallazgo[]): Hallazgo[] {
  const campos = new Set(locales.map((h) => h.campo));
  const vistos = new Set<string>();
  return [...locales, ...servidor.filter((h) => !campos.has(h.campo))].filter((h) => {
    const clave = `${h.campo}|${h.mensaje}`;
    if (vistos.has(clave)) return false;
    vistos.add(clave);
    return true;
  });
}

export function resumenCorto(h: Hallazgo): string {
  const { campo, mensaje } = h;
  if (campo === "resultado") return "el resultado";
  if (campo === "sustitutiva") return mensaje === MSG.carencia ? "el tipo de carencia" : "la decisión sustitutiva";
  if (campo === "eje") return "el porqué";
  if (campo === "ordenes") return "al menos una orden";
  if (/^ordenes\.\d+\.(destinatario|conducta)$/.test(campo)) return "destinatario y conducta en cada orden";
  if (/^ordenes\.\d+\.plazo/.test(campo)) return "el plazo de cada orden";
  if (campo === "compulsa.respecto_de") return "respecto de quién se compulsa";
  if (campo.startsWith("numerales_libres.")) return "el texto de un numeral libre";
  return mensaje.replace(/\.$/, "");
}

export function idDeCampo(f: Formulario, campo: string): string | null {
  const orden = /^ordenes\.(\d+)\.(destinatario|conducta|plazo)/.exec(campo);
  if (orden) {
    const o = f.ordenes[Number(orden[1])];
    return o ? `dec-orden-${o.id}-${orden[2]}` : null;
  }
  const libre = /^numerales_libres\.(\d+)$/.exec(campo);
  if (libre) {
    const l = f.libres[Number(libre[1])];
    return l ? `dec-libre-${l.id}` : null;
  }
  const simples: Record<string, string> = {
    resultado: "dec-resultado",
    sustitutiva: "dec-sustitutiva",
    eje: "dec-eje",
    decidido_por: "dec-por",
    fecha_fallo: "dec-fecha-fallo",
    fecha_oficio: "dec-fecha-oficio",
    etiqueta_encabezado: "dec-etiqueta",
    ordenes: "dec-agregar-orden",
    "compulsa.respecto_de": "dec-compulsa-respecto",
    compulsa: "dec-compulsa-respecto",
    "compulsa.organo": "dec-compulsa-organo",
    "compulsa.hechos_ref": "dec-compulsa-hechos",
  };
  return simples[campo] ?? null;
}

export function sanear(crudo: unknown, payload: PayloadDecision | null): Formulario | null {
  if (typeof crudo !== "object" || crudo === null) return null;
  const f = crudo as Formulario;
  const listas = [f.reparos, f.derechos, f.ordenes, f.libres, f.orden];
  if (!listas.every(Array.isArray) || typeof f.eje !== "string" || typeof f.siguienteId !== "number") return null;
  const reparos = (payload?.reparos ?? []).map(
    (r) => f.reparos.find((x) => x.id === r.id) ?? { id: r.id, disposicion: "ACOGE" as const, nota: "" },
  );
  return { ...f, reparos };
}
