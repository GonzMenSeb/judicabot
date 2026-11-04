import { describe, expect, it } from "vitest";
import {
  aClaveApi,
  aClaveInterna,
  aDecision,
  advertenciasLocales,
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
  MSG,
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

  it("sanear completa la causal en borradores anteriores y descarta valores desconocidos", () => {
    const anterior: Partial<Formulario> = inicial();
    delete anterior.causal;
    expect(sanear(anterior, payload)?.causal).toBe("");
    expect(sanear({ ...inicial(), causal: "OTRA" }, payload)?.causal).toBe("");
    expect(sanear({ ...inicial(), causal: "COSA_JUZGADA" }, payload)?.causal).toBe("COSA_JUZGADA");
  });
});
