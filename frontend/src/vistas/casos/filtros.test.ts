import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CasoResumen, EstadoCasoApi } from "../../api/contrato";
import { diaIso, fechaCorta } from "../../estado/formato";
import { coincideBusqueda } from "./agrupar";
import {
  ESTADOS,
  ESTADOS_DEFECTO,
  estadoDe,
  facetaPorClave,
  FILA,
  generales,
  infoProceso,
  opciones,
  procesoDe,
  PROCESOS,
  PROPIAS,
  propias,
  type DatoFila,
  type EstadoUi,
  type Faceta,
  type TipoProceso,
} from "./facetas";
import { casosMock } from "./mock";
import {
  activos,
  actividad,
  agruparPor,
  alternar,
  conteoEstados,
  conteoFechas,
  conteoOpciones,
  conteoPestanas,
  contar,
  datosFila,
  deserializar,
  deshacer,
  elegirDia,
  elegirEstado,
  elegirPreset,
  fijar,
  fijarRango,
  inicial,
  limpiar,
  ordenarPor,
  pasa,
  predicados,
  procesoActivo,
  quitarFiltro,
  rangoPreset,
  serializar,
  sugerencia,
  textoFecha,
  validar,
  type Filtros,
} from "./filtros";

const HOY = new Date(2026, 10, 17, 15, 0);
const J9 = "Juzgado 9 Penal Municipal con Función de Control de Garantías";
const J2 = "Juzgado 2 Penal Municipal con Función de Conocimiento";
const J14 = "Juzgado 14 Penal Municipal con Función de Control de Garantías";
const HORIZONTE = "EPS Horizonte Salud S.A.S.";
const ALTAMIRA = "Fondo Pensional Altamira";

/** Marca de tiempo en hora local, como la devolvería el servidor (ISO con zona). */
const en = (mes: number, dia: number, hora = 10, minuto = 0) => new Date(2026, mes - 1, dia, hora, minuto).toISOString();

function caso(id: string, estado: EstadoCasoApi, actualizado: string, extra: Partial<CasoResumen> = {}): CasoResumen {
  return {
    id,
    nombre: `Caso ${id}`,
    radicado: null,
    accionante: null,
    accionadas: [],
    juzgado_a_quo: null,
    estado,
    etapa: 0,
    siguiente_paso: "",
    n_insumos: 0,
    n_alertas: 0,
    job_activo: null,
    actualizado,
    ...extra,
  };
}

const CASOS: CasoResumen[] = [
  caso("quintero", "esperando_decision", en(11, 17, 14, 35), { radicado: "2026-00412", juzgado_a_quo: J9, accionadas: [HORIZONTE], n_alertas: 1 }),
  caso("zuluaga", "esperando_decision", en(11, 13, 17, 20), {
    radicado: "2026-00398",
    juzgado_a_quo: "Juzgado 3 Civil Municipal de Oralidad",
    accionadas: ["Secretaría de Salud de San Rafael", "EPS Ceiba Salud"],
    n_alertas: 3,
  }),
  caso("restrepo", "corriendo", en(11, 17, 14, 57), { radicado: "2026-00390", juzgado_a_quo: "Juzgado 5 Penal", accionadas: [ALTAMIRA] }),
  caso("cardenas", "incompleto", en(11, 12, 9, 10), { radicado: "2026-00374", juzgado_a_quo: J2, accionadas: ["Aseguradora Montaña Azul"], n_alertas: 2 }),
  caso("arango", "revision", en(11, 16, 8, 40), { radicado: "2026-00377", juzgado_a_quo: J14, accionadas: ["eps  ceiba salud"] }),
  caso("gaviria", "error", en(11, 10, 11, 2), { radicado: "2026-00212", juzgado_a_quo: "Juzgado 1 Promiscuo", accionadas: ["Municipio de San Rafael"], n_alertas: 1 }),
  caso("nuevo", "sin_iniciar", en(10, 20)),
  caso("mejia", "terminado", en(11, 4, 16, 20), { radicado: "2026-00301", juzgado_a_quo: J9, accionadas: [ALTAMIRA] }),
  caso("ocampo", "terminado", en(10, 28, 10, 15), { radicado: "2026-00286", juzgado_a_quo: J14, accionadas: [HORIZONTE] }),
];

const TODOS_ESTADOS = ESTADOS.map((e) => e.id);
const ids = (casos: readonly CasoResumen[]) => casos.map((c) => c.id);
const visibles = (f: Filtros, casos = CASOS) => ids(casos.filter((c) => pasa(c, predicados(f, HOY))));
const juzgadoId = (texto: string) => facetaPorClave("juzgado", CASOS)!.opciones.find((o) => o.etiqueta === texto)!.id;

describe("formato de fechas", () => {
  it("diaIso usa el día local", () => {
    expect(diaIso(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
    expect(diaIso(new Date(2026, 10, 17, 0, 0))).toBe("2026-11-17");
  });

  it("fechaCorta da día y mes abreviado", () => {
    expect(fechaCorta("2026-10-19")).toBe("19 oct.");
    expect(fechaCorta("2026-05-03")).toBe("3 may.");
    expect(fechaCorta(en(11, 17, 23, 30))).toBe("17 nov.");
    expect(fechaCorta("")).toBe("");
    expect(fechaCorta("nada")).toBe("");
  });
});

describe("coincideBusqueda", () => {
  it("compara sin tildes ni mayúsculas y con radicado compacto", () => {
    const c = CASOS[1]!;
    expect(coincideBusqueda(c, "SECRETARIA")).toBe(true);
    expect(coincideBusqueda(c, "2026 00398")).toBe(true);
    expect(coincideBusqueda(c, "202600398")).toBe(true);
    expect(coincideBusqueda(c, "   ")).toBe(true);
    expect(coincideBusqueda(c, "altamira")).toBe(false);
  });

  it("busca en nombre, partes, juzgado y radicado de los casos de ejemplo", () => {
    const buscar = (q: string) => ids(casosMock.filter((c) => coincideBusqueda(c, q)));
    expect(buscar("CARDENAS")).toEqual(["cardenas-ospina"]);
    expect(buscar("ceiba")).toEqual(["arango-londono", "duque-salazar"]);
    expect(buscar("00412")).toEqual(["quintero-bedoya"]);
    expect(buscar("juzgado 14")).toEqual(["arango-londono"]);
    expect(buscar("zzz")).toEqual([]);
  });

  it("ignora separadores en el radicado", () => {
    const c = { ...CASOS[0]!, radicado: "05001 40 88 009 2026 00412 00" };
    for (const q of ["2026-00412", "2026 00412", "202600412"]) expect(coincideBusqueda(c, q)).toBe(true);
    expect(coincideBusqueda(c, "2026-00999")).toBe(false);
  });
});

describe("registro de facetas", () => {
  it.each([
    ["esperando_decision", "decidir"],
    ["incompleto", "faltan"],
    ["error", "error"],
    ["sin_iniciar", "preparar"],
    ["revision", "preparar"],
    ["corriendo", "redaccion"],
    ["terminado", "terminado"],
  ] as const)("el estado %s es «%s»", (api, ui) => {
    expect(estadoDe(api)).toBe(ui);
    expect(estadoDe({ estado: api })).toBe(ui);
  });

  it("los estados tienen etiquetas, tonos y el defecto deja fuera los terminados", () => {
    expect(ESTADOS.map((e) => [e.id, e.etiqueta, e.tono])).toEqual([
      ["decidir", "Por decidir", "sello"],
      ["faltan", "Faltan documentos", "alerta"],
      ["error", "Con error", "alerta"],
      ["preparar", "Por preparar", ""],
      ["redaccion", "En redacción", "trabajando"],
      ["terminado", "Terminados", "ok"],
    ]);
    expect(ESTADOS_DEFECTO).toEqual(["decidir", "faltan", "error", "preparar", "redaccion"]);
  });

  it("procesos para las pestañas; hoy todo caso es de segunda", () => {
    expect(PROCESOS.map((p) => p.id)).toEqual(["todos", "primera", "segunda", "desacato", "penal"]);
    expect(infoProceso("segunda").corto).toBe("2ª instancia");
    expect(procesoDe(CASOS[0]!)).toBe("segunda");
    expect(Object.values(PROPIAS).every((p) => p.length === 0)).toBe(true);
    expect(propias("segunda")).toEqual([]);
    expect(FILA.segunda(CASOS[0]!)).toEqual([]);
  });

  it("generales: juzgado según el proceso, entidades agrupando variantes y alertas", () => {
    const segunda = generales("segunda", CASOS);
    expect(segunda.map((f) => [f.clave, f.corto, f.tipo])).toEqual([
      ["juzgado", "Juzgado de 1ª inst.", "buscable"],
      ["entidad", "Entidad accionada", "buscable"],
      ["alertas", "Con alertas", "interruptor"],
    ]);
    expect(generales(null, CASOS)[0]!.corto).toBe("Juzgado");
    expect(generales("desacato", CASOS)[1]!.etiqueta).toBe("Entidad requerida");
    expect(segunda[1]!.opciones.map((o) => o.etiqueta)).toEqual([
      "EPS Ceiba Salud",
      "EPS Horizonte Salud S.A.S.",
      "Fondo Pensional Altamira",
      "Aseguradora Montaña Azul",
      "Municipio de San Rafael",
      "Secretaría de Salud de San Rafael",
    ]);
    expect(segunda[1]!.valor(CASOS[4]!)).toEqual(["eps ceiba salud"]);
    expect(segunda[0]!.opciones[0]!.etiqueta).toBe(J9);
    expect(segunda[2]!.activo).toBe("con");
  });

  it("omite juzgado y entidad sin opciones", () => {
    expect(generales("segunda", [CASOS[6]!]).map((f) => f.clave)).toEqual(["alertas"]);
  });

  it("facetaPorClave reconoce generales y rechaza lo desconocido", () => {
    expect(facetaPorClave("alertas")?.tipo).toBe("interruptor");
    expect(facetaPorClave("juzgado")?.opciones).toEqual([]);
    expect(facetaPorClave("nada")).toBeUndefined();
    expect(facetaPorClave("segunda.aquo")).toBeUndefined();
    expect(facetaPorClave("todos.aquo")).toBeUndefined();
  });
});

describe("inicial y predicados", () => {
  it("valores por defecto en Inicio y en la página del proceso", () => {
    expect(inicial()).toMatchObject({ proceso: "todos", agrupar: "ninguno", orden: "prioridad", fecha: "todo", sel: {} });
    expect(inicial("segunda")).toMatchObject({ proceso: "segunda", agrupar: "estado" });
  });

  it("por defecto oculta los terminados", () => {
    expect(visibles(inicial())).toEqual(["quintero", "zuluaga", "restrepo", "cardenas", "arango", "gaviria", "nuevo"]);
  });

  it("combina búsqueda, faceta y estado", () => {
    expect(visibles({ ...inicial(), q: "ceiba" })).toEqual(["zuluaga", "arango"]);
    expect(visibles(alternar(inicial(), "alertas", "con"))).toEqual(["quintero", "zuluaga", "cardenas", "gaviria"]);
    expect(visibles(alternar(inicial(), "entidad", "eps ceiba salud"))).toEqual(["zuluaga", "arango"]);
    expect(visibles({ ...inicial(), estado: ["terminado"] })).toEqual(["mejia", "ocampo"]);
    expect(visibles({ ...inicial("primera") })).toEqual([]);
  });

  it("pasa y contar aceptan omitir como clave, lista o función", () => {
    const f = { ...alternar(inicial(), "alertas", "con"), q: "ceiba" };
    const preds = predicados(f, HOY);
    expect(contar(CASOS, preds)).toBe(1);
    expect(contar(CASOS, preds, "q")).toBe(4);
    expect(contar(CASOS, preds, ["q", "alertas"])).toBe(7);
    expect(contar(CASOS, preds, (k) => k !== "estado")).toBe(7);
    expect(contar(CASOS, preds, "q", (c) => c.n_alertas > 1)).toBe(2);
  });
});

describe("elegirEstado", () => {
  const sigue = (f: Filtros, ...pasos: EstadoUi[]) => pasos.reduce(elegirEstado, f).estado;

  it("desde el defecto, el primer toque deja solo ese estado", () => {
    expect(sigue(inicial(), "decidir")).toEqual(["decidir"]);
  });

  it("los toques siguientes alternan, en el orden de la franja", () => {
    expect(sigue(inicial(), "faltan", "decidir")).toEqual(["decidir", "faltan"]);
    expect(sigue(inicial(), "faltan", "decidir", "faltan")).toEqual(["decidir"]);
  });

  it("vaciar la selección vuelve al defecto", () => {
    expect(sigue(inicial(), "decidir", "decidir")).toEqual(ESTADOS_DEFECTO);
  });

  it("Terminados se suma encima y se vuelve a ocultar", () => {
    expect(sigue(inicial(), "terminado")).toEqual(TODOS_ESTADOS);
    expect(sigue(inicial(), "terminado", "terminado")).toEqual(ESTADOS_DEFECTO);
    expect(sigue(inicial(), "decidir", "terminado")).toEqual(["decidir", "terminado"]);
  });
});

describe("alternar y fijar", () => {
  it("agrega, quita y borra la clave al quedar vacía", () => {
    const uno = alternar(inicial(), "juzgado", "a");
    expect(uno.sel).toEqual({ juzgado: ["a"] });
    expect(alternar(uno, "juzgado", "b").sel).toEqual({ juzgado: ["a", "b"] });
    expect(alternar(uno, "juzgado", "a").sel).toEqual({});
    expect(fijar(alternar(uno, "alertas", "con"), "juzgado", []).sel).toEqual({ alertas: ["con"] });
  });
});

describe("conteos facetados", () => {
  const f = alternar(elegirEstado(inicial(), "decidir"), "alertas", "con");
  const preds = predicados(f, HOY);

  it("la franja de estados ignora el estado pero no las demás facetas", () => {
    expect(conteoEstados(CASOS, preds)).toEqual({ decidir: 2, faltan: 1, error: 1, preparar: 0, redaccion: 0, terminado: 0 });
  });

  it("las opciones de una pastilla ignoran su propia clave", () => {
    const alertas = generales("segunda", CASOS)[2]!;
    expect(conteoOpciones(CASOS, preds, alertas)).toEqual(new Map([["con", 2]]));
    const juzgado = generales("segunda", CASOS)[0]!;
    expect(conteoOpciones(CASOS, predicados(inicial(), HOY), juzgado).get(juzgadoId(J9))).toBe(1);
  });

  it("cada caso cuenta una vez por opción aunque repita el valor", () => {
    const repetido = caso("x", "revision", en(11, 1), { accionadas: [ALTAMIRA, "fondo pensional ALTAMIRA"] });
    const entidad = generales(null, [repetido])[0]!;
    expect(conteoOpciones([repetido], predicados(inicial(), HOY), entidad)).toEqual(new Map([["fondo pensional altamira", 1]]));
  });

  it("las pestañas ignoran el proceso", () => {
    expect(conteoPestanas(CASOS, predicados({ ...inicial(), proceso: "primera" }, HOY))).toEqual({
      todos: 7,
      primera: 0,
      segunda: 7,
      desacato: 0,
      penal: 0,
    });
  });

  it("procesoActivo: el elegido, o el único presente", () => {
    expect(procesoActivo(inicial(), CASOS)).toBe("segunda");
    expect(procesoActivo(inicial(), [])).toBeNull();
    expect(procesoActivo({ ...inicial(), proceso: "penal" }, CASOS)).toBe("penal");
  });
});

describe("Trabajado", () => {
  it.each([
    ["hoy", "2026-11-17", "2026-11-17"],
    ["ayer", "2026-11-16", "2026-11-16"],
    ["semana", "2026-11-11", "2026-11-17"],
    ["mes", "2026-11-01", "2026-11-17"],
    ["mespasado", "2026-10-01", "2026-10-31"],
    ["todo", "", ""],
  ] as const)("el preset %s va de %s a %s", (id, desde, hasta) => {
    expect(rangoPreset(id, HOY)).toEqual({ desde, hasta });
  });

  it("los presets cruzan el año", () => {
    const enero = new Date(2026, 0, 5, 8);
    expect(rangoPreset("semana", enero)).toEqual({ desde: "2025-12-30", hasta: "2026-01-05" });
    expect(rangoPreset("mespasado", enero)).toEqual({ desde: "2025-12-01", hasta: "2025-12-31" });
  });

  it("cuenta los casos de cada preset ignorando la fecha", () => {
    const f = { ...elegirPreset(inicial(), "hoy"), estado: TODOS_ESTADOS };
    expect(conteoFechas(CASOS, predicados(f, HOY), HOY)).toEqual({ hoy: 2, ayer: 1, semana: 5, mes: 7, mespasado: 2, todo: 9 });
    expect(visibles(f)).toEqual(["quintero", "restrepo"]);
  });

  it("filtra por rango libre, abierto en un extremo y ordenado", () => {
    expect(visibles(fijarRango(inicial(), "2026-11-12", "2026-11-13"))).toEqual(["zuluaga", "cardenas"]);
    expect(visibles(fijarRango(inicial(), "2026-11-16", ""))).toEqual(["quintero", "restrepo", "arango"]);
    expect(visibles(fijarRango(inicial(), "", "2026-11-10"))).toEqual(["gaviria", "nuevo"]);
    expect(fijarRango(inicial(), "2026-11-13", "2026-11-12")).toMatchObject({ desde: "2026-11-12", hasta: "2026-11-13" });
    expect(fijarRango(fijarRango(inicial(), "2026-11-12", ""), "", "").fecha).toBe("todo");
  });

  it("dos toques en el histograma arman el rango", () => {
    const primero = elegirDia(inicial(), "2026-11-13", null);
    expect(primero.pendiente).toBe("2026-11-13");
    expect(primero.filtros).toMatchObject({ fecha: "rango", desde: "2026-11-13", hasta: "2026-11-13" });
    const segundo = elegirDia(primero.filtros, "2026-11-10", primero.pendiente);
    expect(segundo.pendiente).toBeNull();
    expect(segundo.filtros).toMatchObject({ fecha: "rango", desde: "2026-11-10", hasta: "2026-11-13" });
  });

  it("describe la fecha elegida", () => {
    expect(textoFecha(inicial())).toBe("");
    expect(textoFecha(elegirPreset(inicial(), "semana"))).toBe("Últimos 7 días");
    expect(textoFecha(fijarRango(inicial(), "2026-11-12", "2026-11-12"))).toBe("12 nov.");
    expect(textoFecha(fijarRango(inicial(), "2026-10-19", "2026-11-03"))).toBe("19 oct. – 3 nov.");
    expect(textoFecha(fijarRango(inicial(), "2026-11-16", ""))).toBe("Desde 16 nov.");
    expect(textoFecha(fijarRango(inicial(), "", "2026-11-16"))).toBe("Hasta 16 nov.");
  });

  it("actividad cuenta por día local en la ventana", () => {
    const dias = actividad(CASOS, HOY);
    expect(dias).toHaveLength(30);
    expect(dias[0]!.iso).toBe("2026-10-19");
    expect(dias.at(-1)).toEqual({ iso: "2026-11-17", n: 2, diaSemana: 2 });
    expect(dias.find((d) => d.iso === "2026-10-20")!.n).toBe(1);
    expect(dias.reduce((s, d) => s + d.n, 0)).toBe(9);
    expect(actividad(CASOS, HOY, 7).reduce((s, d) => s + d.n, 0)).toBe(5);
  });
});

describe("orden y grupos", () => {
  it.each([
    ["prioridad", ["quintero", "zuluaga", "cardenas", "gaviria", "arango", "nuevo", "restrepo", "mejia", "ocampo"]],
    ["reciente", ["restrepo", "quintero", "arango", "zuluaga", "cardenas", "gaviria", "mejia", "ocampo", "nuevo"]],
    ["antiguo", ["nuevo", "ocampo", "mejia", "gaviria", "cardenas", "zuluaga", "arango", "quintero", "restrepo"]],
    ["radicado", ["gaviria", "ocampo", "mejia", "cardenas", "arango", "restrepo", "zuluaga", "quintero", "nuevo"]],
  ] as const)("ordena por %s", (orden, esperado) => {
    expect(ids(ordenarPor(CASOS, orden))).toEqual(esperado);
  });

  it("no cambia la lista original", () => {
    const copia = [...CASOS];
    ordenarPor(CASOS, "radicado");
    expect(CASOS).toEqual(copia);
  });

  it("agrupa por estado en el orden de la franja, sin grupos vacíos", () => {
    const grupos = agruparPor(ordenarPor(CASOS, "prioridad"), "estado");
    expect(grupos.map((g) => [g.titulo, ids(g.casos)])).toEqual([
      ["Por decidir", ["quintero", "zuluaga"]],
      ["Faltan documentos", ["cardenas"]],
      ["Con error", ["gaviria"]],
      ["Por preparar", ["arango", "nuevo"]],
      ["En redacción", ["restrepo"]],
      ["Terminados", ["mejia", "ocampo"]],
    ]);
  });

  it("el límite reparte los primeros casos y conserva los totales", () => {
    const grupos = agruparPor(ordenarPor(CASOS, "prioridad"), "estado", 3);
    expect(grupos.map((g) => [g.id, ids(g.casos), g.total])).toEqual([
      ["decidir", ["quintero", "zuluaga"], 2],
      ["faltan", ["cardenas"], 1],
    ]);
    expect(agruparPor(CASOS, "ninguno", 2)).toEqual([{ id: "todos", titulo: "", casos: CASOS.slice(0, 2), total: 9 }]);
    expect(agruparPor([], "ninguno")).toEqual([]);
  });
});

describe("limpiar, deshacer y sugerencia", () => {
  const defaults = inicial();
  const sucio: Filtros = {
    ...alternar(elegirEstado(elegirPreset(defaults, "semana"), "decidir"), "alertas", "con"),
    q: "ceiba",
    orden: "reciente",
  };

  it("limpiar deja el defecto y conserva orden, agrupación y proceso", () => {
    const { filtros, deshacer: guardado } = limpiar({ ...sucio, proceso: "segunda" }, defaults);
    expect(filtros).toEqual({ ...defaults, orden: "reciente", proceso: "segunda" });
    expect(guardado.q).toBe("ceiba");
  });

  it("deshacer devuelve lo limpiado sin pisar el orden actual", () => {
    const { filtros, deshacer: guardado } = limpiar(sucio, defaults);
    const restaurado = deshacer({ ...filtros, orden: "antiguo" }, guardado);
    expect(restaurado).toEqual({ ...sucio, orden: "antiguo" });
  });

  it("lista los filtros aplicados con sus nombres", () => {
    const facetas = generales("segunda", CASOS);
    const f = alternar(sucio, "juzgado", juzgadoId(J9));
    expect(activos(f, defaults, facetas)).toEqual([
      { clave: "estado", texto: "Estado" },
      { clave: "fecha", texto: "Trabajado: Últimos 7 días" },
      { clave: "juzgado", texto: `Juzgado de primera instancia: ${J9}` },
      { clave: "alertas", texto: "Alertas: Con alertas" },
      { clave: "q", texto: "Búsqueda «ceiba»" },
    ]);
    expect(activos(defaults, defaults, facetas)).toEqual([]);
    expect(activos({ ...defaults, proceso: "segunda" }, defaults, facetas)).toEqual([]);
  });

  it("quitarFiltro vuelve cada filtro a su defecto", () => {
    expect(quitarFiltro(sucio, "estado", defaults).estado).toEqual(ESTADOS_DEFECTO);
    expect(quitarFiltro(sucio, "fecha", defaults).fecha).toBe("todo");
    expect(quitarFiltro(sucio, "q", defaults).q).toBe("");
    expect(quitarFiltro(sucio, "alertas", defaults).sel).toEqual({});
  });

  it("sugiere el filtro cuya retirada muestra más casos", () => {
    const facetas = generales("segunda", CASOS);
    const f = alternar(elegirEstado(defaults, "decidir"), "juzgado", juzgadoId(J2));
    expect(visibles(f)).toEqual([]);
    expect(sugerencia(CASOS, f, defaults, facetas, HOY)).toEqual({ clave: "juzgado", texto: `Juzgado de primera instancia: ${J2}`, n: 2 });
    expect(sugerencia(CASOS, { ...defaults, q: "zzz" }, defaults, facetas, HOY)).toMatchObject({ clave: "q", n: 7 });
  });

  it("no sugiere nada si ningún filtro devuelve casos", () => {
    expect(sugerencia([], { ...defaults, q: "zzz" }, defaults, [], HOY)).toBeNull();
    expect(sugerencia(CASOS, defaults, defaults, [], HOY)).toBeNull();
  });
});

describe("URL", () => {
  const defaults = inicial();
  const contexto = { defaults, casos: CASOS };

  it("el defecto no escribe nada", () => {
    expect(serializar(defaults, defaults)).toBe("");
    expect(serializar(inicial("segunda"), inicial("segunda"))).toBe("");
    expect(deserializar("", contexto)).toEqual(defaults);
  });

  it("escribe solo lo que cambió, con claves cortas", () => {
    let f = elegirEstado(elegirEstado(defaults, "faltan"), "decidir");
    f = alternar(alternar(f, "alertas", "con"), "juzgado", juzgadoId(J9));
    f = { ...elegirPreset(f, "semana"), q: "ceiba salud", proceso: "segunda", orden: "reciente", agrupar: "estado" };
    expect(serializar(f, defaults)).toBe(
      "q=ceiba%20salud&p=segunda&e=decidir,faltan&f=semana&s.alertas=con" +
        "&s.juzgado=juzgado%209%20penal%20municipal%20con%20funcion%20de%20control%20de%20garantias&o=reciente&g=estado",
    );
  });

  it("ida y vuelta estable", () => {
    let f = alternar(elegirEstado(defaults, "terminado"), "entidad", "eps ceiba salud");
    f = alternar(f, "entidad", "eps horizonte salud s.a.s.");
    f = { ...fijarRango(f, "2026-10-19", "2026-11-03"), q: "a,b & c=d" };
    const q = serializar(f, defaults);
    const leido = deserializar(q, contexto);
    expect(leido).toEqual(f);
    expect(serializar(leido, defaults)).toBe(q);
    expect(serializar(deserializar("d=2026-11-16", contexto), defaults)).toBe("d=2026-11-16");
  });

  it("en Inicio descarta un proceso sin casos, que dejaría la lista vacía y sin pestañas", () => {
    expect(deserializar("p=primera", contexto).proceso).toBe("todos");
    expect(deserializar("p=segunda", contexto).proceso).toBe("segunda");
    expect(deserializar("p=primera", { defaults }).proceso).toBe("primera");
  });

  it("en la página de un proceso, el proceso es fijo", () => {
    const fijo = inicial("segunda");
    expect(deserializar("p=penal&g=ninguno", { defaults: fijo }).proceso).toBe("segunda");
    expect(serializar({ ...fijo, agrupar: "ninguno" }, fijo)).toBe("g=ninguno");
  });

  it("validar descarta claves, valores y fechas desconocidos", () => {
    const leido = deserializar(
      "zz=1&p=civil&e=decidir,nada&f=siglo&s.nada=x&s.alertas=quizas,con,con&s.juzgado=inventado&o=azar&g=juzgado&q=%E0%A4%A",
      contexto,
    );
    expect(leido).toEqual({ ...defaults, estado: ["decidir"], sel: { alertas: ["con"] } });
    expect(deserializar("e=nada", contexto).estado).toEqual(ESTADOS_DEFECTO);
    expect(deserializar("d=2026-02-30&h=abc", contexto).fecha).toBe("todo");
    expect(deserializar("d=2026-02-28&h=2026-13-01", contexto)).toMatchObject({ fecha: "rango", desde: "2026-02-28", hasta: "" });
    expect(deserializar("d=2026-11-13&h=2026-11-01", contexto)).toMatchObject({ desde: "2026-11-01", hasta: "2026-11-13" });
    expect(deserializar("f=hoy&d=2026-11-01", contexto)).toMatchObject({ fecha: "hoy", desde: "", hasta: "" });
    expect(deserializar("?q=a+b", contexto).q).toBe("a b");
  });

  it("sin casos, acepta cualquier valor en las facetas dinámicas", () => {
    expect(deserializar("s.juzgado=inventado", { defaults }).sel).toEqual({ juzgado: ["inventado"] });
    expect(deserializar("s.juzgado=inventado", contexto).sel).toEqual({});
  });

  it("validar también limpia un Filtros armado a mano", () => {
    const roto = { ...defaults, proceso: "civil", estado: [], fecha: "rango", desde: "", hasta: "", orden: "x" } as unknown as Filtros;
    expect(validar(roto, contexto)).toEqual(defaults);
  });
});

describe("facetas propias (como las llenará PR2)", () => {
  const original = { propias: PROPIAS.segunda, fila: FILA.segunda };
  const aquo: Faceta = {
    clave: "aquo",
    etiqueta: "Decisión de primera instancia",
    corto: "Decisión 1ª inst.",
    tipo: "varias",
    opciones: opciones("Amparó", "Negó el amparo"),
    valor: (c) => (c.n_alertas > 0 ? "Amparó" : "Negó el amparo"),
  };
  const mutable = PROPIAS as Record<TipoProceso, readonly Faceta[]>;
  const filas = FILA as Record<TipoProceso, (c: CasoResumen) => readonly (DatoFila | null)[]>;

  beforeEach(() => {
    mutable.segunda = [aquo];
    filas.segunda = (c) => [{ texto: `1ª inst.: ${aquo.valor(c) as string}`, clave: "aquo", valor: aquo.valor(c) as string }, null];
  });
  afterEach(() => {
    mutable.segunda = original.propias;
    filas.segunda = original.fila;
  });

  it("prefija la clave con el proceso y filtra con ella", () => {
    expect(propias("segunda").map((f) => f.clave)).toEqual(["segunda.aquo"]);
    expect(facetaPorClave("segunda.aquo")?.corto).toBe("Decisión 1ª inst.");
    const f = alternar(inicial(), "segunda.aquo", "Amparó");
    expect(visibles(f)).toEqual(["quintero", "zuluaga", "cardenas", "gaviria"]);
    expect(conteoPestanas(CASOS, predicados(f, HOY)).segunda).toBe(7);
  });

  it("valida sus valores en la URL", () => {
    const leido = deserializar("s.segunda.aquo=Ampar%C3%B3,Otro", { defaults: inicial() });
    expect(leido.sel).toEqual({ "segunda.aquo": ["Amparó"] });
    expect(serializar(leido, inicial())).toBe("s.segunda.aquo=Ampar%C3%B3");
  });

  it("datosFila resalta el dato cuyo filtro está elegido", () => {
    const f = alternar(inicial(), "segunda.aquo", "Amparó");
    expect(datosFila(CASOS[0]!, f)).toEqual([{ texto: "1ª inst.: Amparó", clave: "aquo", valor: "Amparó", eco: true }]);
    expect(datosFila(CASOS[2]!, f)[0]!.eco).toBe(false);
  });
});
