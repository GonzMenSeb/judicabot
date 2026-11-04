import { describe, expect, it } from "vitest";
import {
  aClaveApi,
  aClaveInterna,
  aDecision,
  agregarLibre,
  agregarOrden,
  clavesOrdenadas,
  combinar,
  elegirSustitutiva,
  formularioInicial,
  hallazgosLocales,
  moverClave,
  ordinal,
  sanear,
  validar,
} from "./formulario";
import { partirNegritas } from "./Resuelve";
import type { Formulario, PayloadDecision } from "./tipos";

const payload: PayloadDecision = {
  reparos: [{ id: "R1", sintesis: "uno" }, { id: "R2", sintesis: "dos" }],
  derechos_invocados: ["salud", "mínimo vital"],
  fecha_hoy: "2026-11-03",
};

const inicial = (): Formulario => formularioInicial(payload, "Juez Demo", "2026-01-01");
const mensajes = (f: Formulario) => hallazgosLocales(f).map((h) => h.mensaje);

function completo(): Formulario {
  let f: Formulario = { ...inicial(), resultado: "REVOCAR", eje: "  El a quo omitió la orden.  " };
  f = elegirSustitutiva(f, "AMPARAR");
  const o = f.ordenes[0];
  if (!o) throw new Error("falta la orden automática");
  return { ...f, ordenes: [{ ...o, destinatario: " la EPS X ", conducta: " entregue el medicamento " }] };
}

describe("formularioInicial", () => {
  it("precarga reparos, derechos, fecha del servidor y quien decide", () => {
    const f = inicial();
    expect(f.reparos.map((r) => [r.id, r.disposicion])).toEqual([["R1", "ACOGE"], ["R2", "ACOGE"]]);
    expect(f.derechos.map((d) => [d.nombre, d.disposicion])).toEqual([["salud", "AMPARA"], ["mínimo vital", "AMPARA"]]);
    expect(f.fechaFallo).toBe("2026-11-03");
    expect(f.decididoPor).toBe("Juez Demo");
    expect(f.notificar && f.remitir).toBe(true);
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

describe("aDecision (claves del legado)", () => {
  it("arma el cuerpo con las mismas claves que el formulario anterior", () => {
    const d = aDecision(completo());
    expect(Object.keys(d).sort()).toEqual(
      [
        "accion", "resultado", "sustitutiva", "eje", "por_reparo", "derechos", "ordenes", "desvincular", "prevenir", "compulsa",
        "numerales", "decidido_por", "generar_formato", "fecha_fallo", "fecha_oficio", "etiqueta_encabezado", "numerales_libres", "orden_numerales",
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

  it("solo envía derechos al amparar o negar y órdenes al amparar", () => {
    const f = completo();
    expect(aDecision(f).derechos).toHaveLength(2);
    expect(aDecision({ ...f, sustitutiva: "NEGAR" }).ordenes).toEqual([]);
    expect(aDecision({ ...f, sustitutiva: "NEGAR" }).derechos).toHaveLength(2);
    expect(aDecision({ ...f, sustitutiva: "IMPROCEDENTE" }).derechos).toEqual([]);
    const conf = aDecision({ ...f, resultado: "CONFIRMAR" });
    expect(conf.sustitutiva).toBeNull();
    expect(conf.ordenes).toEqual([]);
    expect(conf.derechos).toEqual([]);
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
});
