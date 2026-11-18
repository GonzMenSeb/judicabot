import { describe, expect, it } from "vitest";
import {
  aClaveApi,
  aClaveInterna,
  aDecision,
  advertenciasLocales,
  agregarDerecho,
  agregarLibre,
  agregarOrden,
  clavesOrdenadas,
  clavesVigentes,
  combinar,
  elegirSustitutiva,
  esPlaceholderDecididoPor,
  fechaLarga,
  formularioInicial,
  hallazgosLocales,
  leerHallazgos,
  MSG,
  moverClave,
  ordinal,
  plazoEnviado,
  sanear,
  validar,
} from "./formulario";
import { partirNegritas } from "./Resuelve";
import type { Formulario, OrdenForm, PayloadDecision } from "./tipos";

const payload: PayloadDecision = {
  reparos: [{ id: "R1", sintesis: "uno" }, { id: "R2", sintesis: "dos" }],
  derechos_invocados: ["salud", "mínimo vital"],
  fecha_hoy: "2026-11-03",
};

const inicial = (): Formulario => formularioInicial(payload, "Juez Demo");
const mensajes = (f: Formulario) => hallazgosLocales(f).map((h) => h.mensaje);

function completo(): Formulario {
  let f: Formulario = { ...inicial(), resultado: "REVOCAR", eje: "  El a quo omitió la orden.  " };
  f = elegirSustitutiva(f, "AMPARAR");
  const o = f.ordenes[0];
  if (!o) throw new Error("falta la orden automática");
  return { ...f, ordenes: [{ ...o, destinatario: " la EPS X ", conducta: " entregue el medicamento " }] };
}

describe("formularioInicial", () => {
  it("precarga reparos, derechos y quien decide, pero no la fecha", () => {
    const f = inicial();
    expect(f.reparos.map((r) => [r.id, r.disposicion])).toEqual([["R1", "ACOGE"], ["R2", "ACOGE"]]);
    expect(f.derechos.map((d) => [d.nombre, d.disposicion])).toEqual([["salud", "AMPARA"], ["mínimo vital", "AMPARA"]]);
    expect(f.fechaFallo).toBe("");
    expect(f.causal).toBe("");
    expect(f.decididoPor).toBe("Juez Demo");
    expect(f.notificar && f.remitir).toBe(true);
  });

  it.each(["John Doe", " john_doe ", "JOHN-DOE", "prueba", "PRUEBA", "Caso Sintético", "caso_sintetico", "caso-sintetico"])(
    "no prefija quien decide con el valor de prueba %j",
    (juez) => {
      expect(formularioInicial(payload, juez).decididoPor).toBe("");
    },
  );

  it("sin payload ni juez deja quien decide vacío", () => {
    expect(formularioInicial(null, "").decididoPor).toBe("");
  });
});

describe("placeholders de «decidido por» (paridad con el backend)", () => {
  it("compara en minúsculas, sin tildes, con _ y - como espacio e igualdad exacta", () => {
    expect(["John Doe", "john-doe", "JOHN_DOE", "  john   doe ", "Prueba", "Caso Sintético", "caso_sintetico"].map(esPlaceholderDecididoPor)).toEqual(
      Array(7).fill(true),
    );
    expect(["John Doe Jr.", "Pruebas", "caso sintetico 2", "Juez Demo", "", "johndoe"].map(esPlaceholderDecididoPor)).toEqual(Array(6).fill(false));
  });

  it("usa los textos exactos del servidor", () => {
    expect(MSG.decididoPorVacio).toBe("Decidido por está vacío: en la declaración de uso de IA constará «no consta».");
    expect(MSG.decididoPorPlaceholder).toBe("Decidido por parece un valor de prueba: confirme que sea el nombre de quien decide.");
  });

  it("advertenciasLocales avisa si está vacío o es un valor de prueba y no bloquea", () => {
    const base = { ...inicial(), resultado: "CONFIRMAR" as const, eje: "x" };
    expect(advertenciasLocales(base)).toEqual([]);
    expect(advertenciasLocales({ ...base, decididoPor: "   " })).toEqual([{ campo: "decidido_por", mensaje: MSG.decididoPorVacio }]);
    expect(advertenciasLocales({ ...base, decididoPor: "John Doe" })).toEqual([{ campo: "decidido_por", mensaje: MSG.decididoPorPlaceholder }]);
    expect(hallazgosLocales({ ...base, decididoPor: "" })).toEqual([]);
  });
});

describe("fecha del fallo", () => {
  it("aDecision envía fecha_fallo solo si el usuario la editó", () => {
    expect(aDecision(completo()).fecha_fallo).toBeNull();
    expect(aDecision({ ...completo(), fechaFallo: "2026-12-01" }).fecha_fallo).toBe("2026-12-01");
  });

  it("fechaLarga escribe la fecha en español y deja pasar lo que no es ISO", () => {
    expect(fechaLarga("2026-11-04")).toMatch(/^4 de noviembre de 2026$/);
    expect(fechaLarga("mañana")).toBe("mañana");
  });
});

describe("validar (reglas del formulario legado)", () => {
  it("pide resultado, sustitutiva y eje en un formulario vacío", () => {
    expect(mensajes(inicial())).toEqual([
      "Falta el resultado (CONFIRMAR, REVOCAR o MODIFICAR).",
      "Falta la decisión sustitutiva (AMPARAR, NEGAR, ...).",
      "Falta el eje: 2 a 5 líneas con el porqué de la decisión.",
    ]);
  });

  it("al confirmar no pide sustitutiva", () => {
    const f = { ...inicial(), resultado: "CONFIRMAR" as const, eje: "x" };
    expect(hallazgosLocales(f)).toEqual([]);
  });

  it("al amparar exige una orden y cada orden destinatario, conducta y plazo", () => {
    let f: Formulario = { ...inicial(), resultado: "MODIFICAR", eje: "x", sustitutiva: "AMPARAR" };
    expect(mensajes(f)).toEqual(["Si se ampara, hay que indicar al menos una orden."]);
    f = elegirSustitutiva({ ...f, sustitutiva: "" }, "AMPARAR");
    expect(hallazgosLocales(f).map((h) => h.campo)).toEqual(["ordenes.0.destinatario", "ordenes.0.conducta"]);
    const o = f.ordenes[0];
    if (!o) throw new Error("sin orden");
    const sinPlazo = { ...f, ordenes: [{ ...o, destinatario: "la EPS", conducta: "haga", n: "0" }] };
    expect(mensajes(sinPlazo)).toEqual(["El plazo de cada orden debe ser mayor que cero."]);
  });

  it("detecta numerales libres vacíos y compulsa sin persona", () => {
    const base = { ...inicial(), resultado: "CONFIRMAR" as const, eje: "x" };
    const f = { ...agregarLibre(base), compulsa: true };
    expect(hallazgosLocales(f).map((h) => h.campo)).toEqual(["numerales_libres.0", "compulsa.respecto_de"]);
  });

  it("una carencia sin tipo pide el tipo y no la sustitutiva genérica", () => {
    const f = { ...inicial(), resultado: "REVOCAR" as const, eje: "x", sustitutiva: "CARENCIA" as const };
    expect(mensajes(f)).toEqual(["Falta indicar el tipo de carencia actual de objeto."]);
  });

  it("combinar da prioridad a los hallazgos locales y no duplica", () => {
    const locales = [{ campo: "eje", mensaje: "A" }];
    const servidor = [{ campo: "eje", mensaje: "B" }, { campo: "fecha_fallo", mensaje: "C" }, { campo: "fecha_fallo", mensaje: "C" }];
    expect(combinar(locales, servidor)).toEqual([{ campo: "eje", mensaje: "A" }, { campo: "fecha_fallo", mensaje: "C" }]);
  });
});

/** El formulario completo con las órdenes dadas (la primera parte de la automática y las demás de `ordenNueva`). */
function conOrdenes(...cambios: Partial<OrdenForm>[]): Formulario {
  const f = completo();
  const base = f.ordenes[0];
  if (!base) throw new Error("falta la orden automática");
  return {
    ...f,
    ordenes: cambios.map((c, i) => ({ ...base, id: base.id + i, destinatario: "la EPS X", conducta: "cumpla", ...c })),
  };
}

const plazos = (f: Formulario) =>
  validar(aDecision(f))
    .filter((h) => /\.plazo\.n$/.test(h.campo))
    .map((h) => [h.campo, h.mensaje]);

describe("plazo de las órdenes", () => {
  it("validar exige un plazo entero y en rango solo cuando la orden lo usa", () => {
    expect(plazos(conOrdenes({ n: "1.5" }))).toEqual([["ordenes.0.plazo.n", MSG.plazoEntero]]);
    expect(plazos(conOrdenes({ n: "0" }))).toEqual([["ordenes.0.plazo.n", MSG.plazo]]);
    expect(plazos(conOrdenes({ n: "-5" }))).toEqual([["ordenes.0.plazo.n", MSG.plazo]]);
    expect(plazos(conOrdenes({ n: "" }))).toEqual([["ordenes.0.plazo.n", MSG.plazo]]);
    expect(plazos(conOrdenes({ n: "1000000" }))).toEqual([
      ["ordenes.0.plazo.n", "El plazo de la orden 1 no puede superar 999.999."],
    ]);
    expect(plazos(conOrdenes({ n: "48" }, { n: "10000000" }))).toEqual([
      ["ordenes.1.plazo.n", "El plazo de la orden 2 no puede superar 999.999."],
    ]);
    expect(plazos(conOrdenes({ n: "999999" }))).toEqual([]);
    expect(plazos(conOrdenes({ verbo: "ADVERTIR", n: "0" }))).toEqual([]);
    expect(plazos(conOrdenes({ verbo: "PREVENIR", n: "0" }))).toEqual([]);
    expect(plazos(conOrdenes({ n: "48" }, { mismo: true, n: "0" }))).toEqual([]);
  });

  it("aDecision manda el plazo entero cuando la orden no lo usa", () => {
    const plazo = (f: Formulario, i = 0) => aDecision(f).ordenes[i]?.plazo.n;
    expect(plazo(conOrdenes({ verbo: "ADVERTIR", n: "1.5" }))).toBe(1);
    expect(plazo(conOrdenes({ verbo: "PREVENIR", n: "1.5" }))).toBe(1);
    // Una ORDENAR con decimales viaja tal cual para que `validar` y el servidor la marquen.
    expect(plazo(conOrdenes({ n: "1.5" }))).toBe(1.5);
    expect(plazoEnviado(conOrdenes({ n: "1.5" }).ordenes[0] as OrdenForm, false)).toBe(1.5);
    const dos = conOrdenes({ n: "48" }, { mismo: true, n: "1.5" });
    expect(plazo(dos, 0)).toBe(48);
    expect(plazo(dos, 1)).toBe(1);
    expect(plazo(conOrdenes({ n: "" }))).toBe(0);
  });
});

describe("leerHallazgos", () => {
  it("devuelve los {campo, mensaje} bien formados de detalle.errores", () => {
    expect(leerHallazgos({ errores: [{ campo: "fecha_fallo", mensaje: "x" }, 3, { campo: "eje" }] })).toEqual([
      { campo: "fecha_fallo", mensaje: "x" },
    ]);
  });

  it.each([["texto"], [null], [{ errores: [] }], [{ errores: [3] }], [{ mensaje: "x" }], [undefined]])(
    "devuelve null con %j",
    (detalle) => {
      expect(leerHallazgos(detalle)).toBeNull();
    },
  );
});

describe("aDecision (claves del legado)", () => {
  it("arma el cuerpo con las mismas claves que el formulario anterior", () => {
    const d = aDecision(completo());
    expect(Object.keys(d).sort()).toEqual(
      [
        "accion", "resultado", "sustitutiva", "eje", "por_reparo", "derechos", "ordenes", "desvincular", "prevenir", "compulsa",
        "numerales", "decidido_por", "generar_formato", "fecha_fallo", "fecha_oficio", "etiqueta_encabezado", "numerales_libres", "orden_numerales", "causal",
      ].sort(),
    );
    expect(d.eje).toBe("El a quo omitió la orden.");
    expect(d.ordenes[0]).toEqual({
      mismo_termino: false,
      verbo: "ORDENAR",
      destinatario: "la EPS X",
      via_representante: true,
      conducta: "entregue el medicamento",
      plazo: { n: 48, unidad: "horas_habiles" },
      condicion: "",
    });
    expect(d.numerales).toEqual({ notificar: true, remitir_corte: true });
    expect(d.fecha_oficio).toBeNull();
    expect(d.orden_numerales).toEqual([]);
    expect(d.compulsa).toBeNull();
    expect(validar(d)).toEqual([]);
  });

  it("solo envía derechos al amparar o negar", () => {
    const f = completo();
    expect(aDecision(f).derechos).toHaveLength(2);
    expect(aDecision({ ...f, sustitutiva: "NEGAR" }).derechos).toHaveLength(2);
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE" }).derechos).toEqual([]);
    const conf = aDecision({ ...f, resultado: "CONFIRMAR" });
    expect(conf.sustitutiva).toBeNull();
    expect(conf.ordenes).toEqual([]);
    expect(conf.derechos).toEqual([]);
  });

  it("envía las órdenes con cualquier sustitutiva y ninguna al confirmar", () => {
    const f = completo();
    for (const s of ["AMPARAR", "NEGAR", "IMPROCEDENTE", "CARENCIA_HECHO_SUPERADO"] as const) {
      expect(aDecision({ ...f, sustitutiva: s }).ordenes).toHaveLength(1);
    }
    expect(aDecision({ ...f, resultado: "CONFIRMAR" }).ordenes).toEqual([]);
    expect(aDecision({ ...f, sustitutiva: "" }).ordenes).toEqual([]);
  });

  it("una orden ADVERTIR sin amparar viaja con su verbo y no exige que se ampare", () => {
    let f: Formulario = { ...inicial(), resultado: "REVOCAR", eje: "x" };
    f = elegirSustitutiva(f, "NEGAR");
    expect(f.ordenes).toEqual([]);
    f = agregarOrden(f);
    const o = f.ordenes[0];
    if (!o) throw new Error("sin orden");
    f = { ...f, ordenes: [{ ...o, verbo: "ADVERTIR", destinatario: "la EPS X", conducta: "no vuelva a omitir la entrega" }] };
    const d = aDecision(f);
    expect(d.ordenes[0]).toMatchObject({ verbo: "ADVERTIR", destinatario: "la EPS X" });
    expect(validar(d)).toEqual([]);
    expect(clavesVigentes(f)).toContain(`orden#${o.id}`);
    expect(aDecision({ ...f, reordenado: true }).orden_numerales).toContain("orden:0");
  });

  it("al dejar de amparar descarta las órdenes en blanco pero conserva las escritas", () => {
    const vacia = elegirSustitutiva({ ...inicial(), resultado: "REVOCAR", eje: "x" }, "AMPARAR");
    expect(vacia.ordenes).toHaveLength(1);
    const negada = elegirSustitutiva(vacia, "NEGAR");
    expect(negada.ordenes).toEqual([]);
    expect(hallazgosLocales(negada)).toEqual([]);

    const escrita = elegirSustitutiva(completo(), "IMPROCEDENTE");
    expect(escrita.ordenes).toHaveLength(1);
    expect(escrita.ordenes[0]?.destinatario).toBe(" la EPS X ");
  });

  it("incluye el campo causal solo con IMPROCEDENTE", () => {
    const f = { ...completo(), causal: "COSA_JUZGADA" as const };
    expect(aDecision(f).causal).toBeNull();
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE" }).causal).toBe("COSA_JUZGADA");
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE", causal: "SUBSIDIARIEDAD" }).causal).toBe("SUBSIDIARIEDAD");
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE", causal: "" }).causal).toBeNull();
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE", resultado: "CONFIRMAR" }).causal).toBeNull();
  });

  it("limpia la causal al cambiar a otra sustitutiva y la conserva al repetir IMPROCEDENTE", () => {
    const base = { ...inicial(), resultado: "REVOCAR" as const, causal: "SUBSIDIARIEDAD" as const };
    expect(elegirSustitutiva({ ...base, sustitutiva: "IMPROCEDENTE" }, "IMPROCEDENTE").causal).toBe("SUBSIDIARIEDAD");
    expect(elegirSustitutiva({ ...base, sustitutiva: "IMPROCEDENTE" }, "NEGAR").causal).toBe("");
    expect(elegirSustitutiva({ ...base, sustitutiva: "IMPROCEDENTE" }, "CARENCIA_DANO_CONSUMADO").causal).toBe("");
    expect(elegirSustitutiva(base, "AMPARAR").causal).toBe("");
  });

  it("normaliza como el backend: sin ▎, espacios y saltos colapsados y recortados", () => {
    let f: Formulario = completo();
    const o = f.ordenes[0];
    if (!o) throw new Error("sin orden");
    f = {
      ...f,
      eje: "  Primera línea\n\n  segunda\t\u258E línea  ",
      reparos: [{ id: "R1", disposicion: "ACOGE", nota: "\u258E nota\n con salto " }, { id: "R2", disposicion: "ACOGE", nota: "" }],
      libres: [{ id: 90, texto: "\u258E\u258EOTRO  numeral\r\n libre" }],
      ordenes: [{ ...o, conducta: " autorice\n  y entregue\u258E el medicamento " }],
    };
    const d = aDecision(f);
    expect(d.eje).toBe("Primera línea segunda línea");
    expect(d.por_reparo.map((r) => r.nota)).toEqual(["nota con salto", ""]);
    expect(d.numerales_libres).toEqual(["OTRO numeral libre"]);
    expect(d.ordenes[0]?.conducta).toBe("autorice y entregue el medicamento");
  });

  it("un texto que solo tiene ▎ o saltos cuenta como vacío al validar", () => {
    const f = { ...agregarLibre({ ...completo(), eje: "\u258E \n " }), libres: [{ id: 99, texto: " \u258E\n" }] };
    expect(validar(aDecision(f)).map((h) => h.campo)).toEqual(["eje", "numerales_libres.0"]);
  });

  it("incluye el órgano de la compulsa solo si se escribió", () => {
    const base = { ...completo(), compulsa: true, respectoDe: " el señor Pérez " };
    expect(aDecision(base).compulsa).toEqual({ respecto_de: "el señor Pérez", hechos_ref: "" });
    expect(aDecision({ ...base, organo: "Otro órgano" }).compulsa?.organo).toBe("Otro órgano");
  });
});

describe("orden de los numerales", () => {
  it("mueve por teclado y conserva el orden al quitar una orden intermedia", () => {
    let f = agregarOrden(completo());
    f = agregarOrden(f);
    expect(clavesOrdenadas(f)).toHaveLength(7);
    const ids = f.ordenes.map((o) => `orden#${o.id}`);
    f = moverClave(f, "remitir", -1);
    f = moverClave(f, ids[2] ?? "", "resultado");
    expect(f.reordenado).toBe(true);
    expect(clavesOrdenadas(f)[0]).toBe(ids[2]);
    expect(aDecision(f).orden_numerales[0]).toBe("orden:2");
    const sinPrimera = { ...f, ordenes: f.ordenes.slice(1) };
    expect(aDecision(sinPrimera).orden_numerales[0]).toBe("orden:1");
    expect(aDecision(sinPrimera).orden_numerales).not.toContain("orden:2");
  });

  it("convierte claves entre el servidor y el formulario", () => {
    const f = agregarOrden(completo());
    const o1 = f.ordenes[1];
    expect(aClaveInterna(f, "orden:1")).toBe(`orden#${o1?.id}`);
    expect(aClaveApi(f, `orden#${o1?.id}`)).toBe("orden:1");
    expect(aClaveInterna(f, "orden:9")).toBeNull();
    expect(aClaveInterna(f, "notificar")).toBe("notificar");
  });

  it("no mueve fuera de los límites", () => {
    const f = completo();
    expect(moverClave(f, "resultado", -1)).toBe(f);
    expect(moverClave(f, "remitir", 1)).toBe(f);
  });
});

describe("utilidades", () => {
  it("ordinales del RESUELVE", () => {
    expect([1, 2, 10, 11, 20, 39, 40].map(ordinal)).toEqual(["PRIMERO", "SEGUNDO", "DÉCIMO", "DÉCIMO PRIMERO", "VIGÉSIMO", "TRIGÉSIMO NOVENO", "NUMERAL 40"]);
  });

  it("negritas: primera aparición y fusión de solapes", () => {
    expect(partirNegritas("REVOCAR la sentencia, REVOCAR", ["REVOCAR"])).toEqual([
      { texto: "REVOCAR", negrita: true },
      { texto: " la sentencia, REVOCAR", negrita: false },
    ]);
    expect(partirNegritas("AMPARAR a MARTA", ["AMPARAR", "AMPARAR a", "x", ""]).map((t) => t.negrita)).toEqual([true, false]);
  });

  it("sanear descarta borradores corruptos y completa reparos nuevos", () => {
    expect(sanear({ eje: 3 }, payload)).toBeNull();
    expect(sanear(null, payload)).toBeNull();
    const guardado = { ...inicial(), reparos: [{ id: "R1", disposicion: "DESESTIMA" as const, nota: "n" }] };
    const f = sanear(guardado, payload);
    expect(f?.reparos).toEqual([{ id: "R1", disposicion: "DESESTIMA", nota: "n" }, { id: "R2", disposicion: "ACOGE", nota: "" }]);
  });

  it("formularioInicial registra los derechos con los que se armó", () => {
    expect(inicial().derechosBase).toEqual(["salud", "mínimo vital"]);
    expect(formularioInicial(null, "Juez Demo").derechosBase).toEqual([]);
  });

  it("sanear reconcilia los derechos con una extracción nueva", () => {
    const guardado = inicial();
    guardado.derechos = guardado.derechos.map((d) => (d.nombre === "salud" ? { ...d, disposicion: "NIEGA" as const } : d));
    const lista = ["salud", "vida", "dignidad humana"];
    const f = sanear(guardado, { ...payload, derechos_invocados: lista });
    expect(f?.derechos.map((d) => d.nombre)).toEqual(lista);
    expect(f?.derechos.map((d) => d.disposicion)).toEqual(["NIEGA", "AMPARA", "AMPARA"]);
    expect(f?.derechos.every((d) => !d.propio)).toBe(true);
    expect(f?.derechosBase).toEqual(lista);
    expect(new Set(f?.derechos.map((d) => d.id)).size).toBe(3);
    expect(f?.siguienteId).toBe(guardado.siguienteId + 2);
  });

  it("sanear conserva los derechos que agregó el juez", () => {
    const guardado = agregarDerecho(inicial(), "debido proceso");
    const f = sanear(guardado, { ...payload, derechos_invocados: ["salud", "vida"] });
    expect(f?.derechos.map((d) => d.nombre)).toEqual(["salud", "vida", "debido proceso"]);
    expect(f?.derechos.find((d) => d.nombre === "debido proceso")?.propio).toBe(true);
    expect(f?.derechosBase).toEqual(["salud", "vida"]);
  });

  it("sanear no duplica un derecho propio que la extracción nueva también trae", () => {
    const base = agregarDerecho(inicial(), "vida");
    const propio = base.derechos.find((d) => d.nombre === "vida");
    const guardado = { ...base, derechos: base.derechos.map((d) => (d.nombre === "vida" ? { ...d, disposicion: "NIEGA" as const } : d)) };
    const f = sanear(guardado, { ...payload, derechos_invocados: ["salud", "Vida "] });
    expect(f?.derechos.map((d) => d.nombre)).toEqual(["salud", "vida"]);
    const vida = f?.derechos.find((d) => d.nombre === "vida");
    expect(vida?.propio).toBe(false);
    expect(vida?.id).toBe(propio?.id);
    expect(vida?.disposicion).toBe("NIEGA");
  });

  it("sanear sigue alineado tras dos reaperturas seguidas", () => {
    const g1 = sanear(inicial(), { ...payload, derechos_invocados: ["salud", "vida", "mínimo vital"] });
    expect(g1?.derechos.map((d) => d.nombre)).toEqual(["salud", "vida", "mínimo vital"]);
    expect(g1?.derechosBase).toEqual(["salud", "vida", "mínimo vital"]);
    if (!g1) throw new Error("sanear devolvió null");
    const g2 = sanear(g1, { ...payload, derechos_invocados: ["salud", "vida"] });
    expect(g2?.derechos.map((d) => d.nombre)).toEqual(["salud", "vida"]);
    expect(g2?.derechosBase).toEqual(["salud", "vida"]);
  });

  it("sanear conserva la disposición de «salud» tras dos reaperturas seguidas", () => {
    const guardado = inicial();
    guardado.derechos = guardado.derechos.map((d) => (d.nombre === "salud" ? { ...d, disposicion: "NIEGA" as const } : d));
    const g1 = sanear(guardado, { ...payload, derechos_invocados: ["salud", "vida", "mínimo vital"] });
    if (!g1) throw new Error("sanear devolvió null");
    const g2 = sanear(g1, { ...payload, derechos_invocados: ["salud", "vida"] });
    expect(g2?.derechos.map((d) => [d.nombre, d.disposicion])).toEqual([
      ["salud", "NIEGA"],
      ["vida", "AMPARA"],
    ]);
  });

  it("sanear conserva el orden de la extracción nueva", () => {
    const guardado = inicial();
    guardado.derechos = guardado.derechos.map((d) => (d.nombre === "salud" ? { ...d, disposicion: "NIEGA" as const } : d));
    const f = sanear(guardado, { ...payload, derechos_invocados: ["vida", "salud"] });
    expect(f?.derechos.map((d) => [d.nombre, d.disposicion])).toEqual([
      ["vida", "AMPARA"],
      ["salud", "NIEGA"],
    ]);
    expect(f?.derechosBase).toEqual(["vida", "salud"]);
  });

  it("sanear tolera una extracción con un derecho repetido", () => {
    const nuevo = { ...payload, derechos_invocados: ["salud", "salud", "mínimo vital"] };
    const f = sanear(inicial(), nuevo);
    expect(f?.derechos.map((d) => d.nombre)).toEqual(["salud", "salud", "mínimo vital"]);
    expect(f?.derechos.every((d) => !d.propio)).toBe(true);
    expect(new Set(f?.derechos.map((d) => d.id)).size).toBe(3);
    expect(f?.derechosBase).toHaveLength(3);
    expect(sanear(f, nuevo)).toEqual(f);
  });

  it("sanear no toca los nombres corregidos si la extracción no cambió", () => {
    const guardado = inicial();
    guardado.derechos = guardado.derechos.map((d, i) => (i === 0 ? { ...d, nombre: "la salud integral" } : d));
    const f = sanear(guardado, payload);
    expect(f?.derechos[0]?.nombre).toBe("la salud integral");
    expect(f).toEqual(guardado);
  });

  it("sanear conserva el derecho renombrado cuyo original sigue vigente", () => {
    const guardado = inicial();
    guardado.derechos = guardado.derechos.map((d) => (d.nombre === "salud" ? { ...d, nombre: "la salud integral", disposicion: "NIEGA" as const } : d));
    const f = sanear(guardado, { ...payload, derechos_invocados: ["salud", "vida"] });
    expect(f?.derechos.map((d) => [d.nombre, d.disposicion])).toEqual([
      ["la salud integral", "NIEGA"],
      ["vida", "AMPARA"],
    ]);
  });

  it("sanear no reconcilia sin derechosBase o sin payload", () => {
    const nuevo = { ...payload, derechos_invocados: ["salud", "vida"] };
    const viejo: Partial<Formulario> = inicial();
    delete viejo.derechosBase;
    expect(sanear(viejo, nuevo)?.derechos).toEqual(inicial().derechos);
    expect(sanear(inicial(), null)?.derechos).toEqual(inicial().derechos);
    const raro = { ...inicial(), derechosBase: ["salud", 3] as unknown as string[] };
    expect(sanear(raro, nuevo)?.derechos).toEqual(inicial().derechos);
    const noLista = { ...inicial(), derechosBase: "salud" as unknown as string[] };
    expect(sanear(noLista, nuevo)?.derechos).toEqual(inicial().derechos);
  });

  it("sanear no reconcilia si los derechos extraídos no se alinean con la base", () => {
    const guardado = { ...inicial(), derechosBase: ["salud"] };
    expect(sanear(guardado, { ...payload, derechos_invocados: ["vida"] })?.derechos).toEqual(inicial().derechos);
  });

  it("sanear es idempotente", () => {
    const nuevo = { ...payload, derechos_invocados: ["vida", "salud", "dignidad humana"] };
    const guardado = agregarDerecho(inicial(), "debido proceso");
    const una = sanear(guardado, nuevo);
    expect(sanear(una, nuevo)).toEqual(una);
  });

  it("sanear completa la causal en borradores anteriores y descarta valores desconocidos", () => {
    const anterior: Partial<Formulario> = inicial();
    delete anterior.causal;
    expect(sanear(anterior, payload)?.causal).toBe("");
    expect(sanear({ ...inicial(), causal: "OTRA" }, payload)?.causal).toBe("");
    expect(sanear({ ...inicial(), causal: "COSA_JUZGADA" }, payload)?.causal).toBe("COSA_JUZGADA");
  });
});
