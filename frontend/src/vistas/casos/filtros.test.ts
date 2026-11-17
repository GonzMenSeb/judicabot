import { describe, expect, it } from "vitest";
import type { CasoResumen, DatosSegunda, EstadoCasoApi } from "../../api/contrato";
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
  procesoDe,
  PROCESOS,
  PLAZOS,
  plazoDe,
  PROPIAS,
  propias,
  propiasVisibles,
  textoPlazo,
  tonoPlazo,
  tituloPlazo,
  urgente,
  type EstadoUi,
} from "./facetas";
import { casosMock } from "./mock";
import {
  activos,
  actividad,
  AGRUPACIONES,
  agruparPor,
  alternar,
  conteoEstados,
  conteoFechas,
  conteoOpciones,
  conteoPestanas,
  conteoPlazos,
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
  ORDENES,
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
    proceso: "segunda",
    segunda: null,
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
    creado: null,
    termino: null,
    vence: null,
    dias_restantes: null,
    ...extra,
  };
}

/** Datos de segunda instancia; lo que no se pase queda vacío, como lo manda el servidor sin datos. */
const conSegunda = (d: Partial<DatosSegunda>): DatosSegunda => ({
  decision_a_quo: null,
  impugnante: null,
  resultado: null,
  sustitutiva: null,
  derechos: [],
  pruebas_nuevas: null,
  n_citas_revisar: null,
  jev_discrepa: null,
  ...d,
});

// cardenas y nuevo traen segunda null (estado ilegible); arango, todos los datos vacíos.
const CASOS: CasoResumen[] = [
  caso("quintero", "esperando_decision", en(11, 17, 14, 35), {
    radicado: "2026-00412",
    juzgado_a_quo: J9,
    accionadas: [HORIZONTE],
    n_alertas: 1,
    segunda: conSegunda({ decision_a_quo: "niega", impugnante: "accionante", derechos: ["Salud", "Vida digna"], pruebas_nuevas: false, n_citas_revisar: 2, jev_discrepa: false }),
  }),
  caso("zuluaga", "esperando_decision", en(11, 13, 17, 20), {
    radicado: "2026-00398",
    juzgado_a_quo: "Juzgado 3 Civil Municipal de Oralidad",
    accionadas: ["Secretaría de Salud de San Rafael", "EPS Ceiba Salud"],
    n_alertas: 3,
    segunda: conSegunda({ decision_a_quo: "ampara", impugnante: "accionada", derechos: ["salud"], pruebas_nuevas: true, n_citas_revisar: 0, jev_discrepa: true }),
  }),
  caso("restrepo", "corriendo", en(11, 17, 14, 57), {
    radicado: "2026-00390",
    juzgado_a_quo: "Juzgado 5 Penal",
    accionadas: [ALTAMIRA],
    segunda: conSegunda({ decision_a_quo: "improcedente", impugnante: "accionante", derechos: ["Seguridad social", "Mínimo vital"], pruebas_nuevas: false }),
  }),
  caso("cardenas", "incompleto", en(11, 12, 9, 10), { radicado: "2026-00374", juzgado_a_quo: J2, accionadas: ["Aseguradora Montaña Azul"], n_alertas: 2 }),
  caso("arango", "revision", en(11, 16, 8, 40), { radicado: "2026-00377", juzgado_a_quo: J14, accionadas: ["eps  ceiba salud"], segunda: conSegunda({}) }),
  caso("gaviria", "error", en(11, 10, 11, 2), {
    radicado: "2026-00212",
    juzgado_a_quo: "Juzgado 1 Promiscuo",
    accionadas: ["Municipio de San Rafael"],
    n_alertas: 1,
    segunda: conSegunda({ decision_a_quo: "carencia_actual_de_objeto", impugnante: "varios", derechos: ["Petición"] }),
  }),
  caso("nuevo", "sin_iniciar", en(10, 20)),
  caso("mejia", "terminado", en(11, 4, 16, 20), {
    radicado: "2026-00301",
    juzgado_a_quo: J9,
    accionadas: [ALTAMIRA],
    segunda: conSegunda({ decision_a_quo: "niega", impugnante: "accionante", resultado: "REVOCAR", sustitutiva: "AMPARAR", derechos: ["Seguridad social", "Mínimo vital"], pruebas_nuevas: false }),
  }),
  caso("ocampo", "terminado", en(10, 28, 10, 15), {
    radicado: "2026-00286",
    juzgado_a_quo: J14,
    accionadas: [HORIZONTE],
    segunda: conSegunda({ decision_a_quo: "ampara", impugnante: "accionada", resultado: "CONFIRMAR", derechos: ["Salud"], pruebas_nuevas: true }),
  }),
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

  it("procesos para las pestañas; el proceso sale del caso y solo segunda tiene facetas propias", () => {
    expect(PROCESOS.map((p) => p.id)).toEqual(["todos", "primera", "segunda", "desacato", "penal"]);
    expect(infoProceso("segunda").corto).toBe("2ª instancia");
    expect(procesoDe(CASOS[0]!)).toBe("segunda");
    expect(procesoDe({ ...CASOS[0]!, proceso: "primera" as never })).toBe("primera");
    for (const p of ["primera", "desacato", "penal"] as const) {
      expect(PROCESOS.some((x) => x.id === p)).toBe(true);
      expect(PROPIAS[p](CASOS)).toEqual([]);
      expect(propias(p, CASOS)).toEqual([]);
      expect(FILA[p](CASOS[0]!)).toEqual([]);
    }
    expect(propias(null, CASOS)).toEqual([]);
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
    expect(facetaPorClave("segunda.aquo")?.corto).toBe("Decisión 1ª inst.");
    expect(facetaPorClave("segunda.nada")).toBeUndefined();
    expect(facetaPorClave("primera.aquo")).toBeUndefined();
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

describe("facetas propias de segunda instancia", () => {
  const ABIERTOS: Filtros = inicial();
  const TODOS: Filtros = { ...inicial(), estado: TODOS_ESTADOS };
  const faceta = (clave: string, casos: readonly CasoResumen[] = CASOS) => facetaPorClave(`segunda.${clave}`, casos)!;
  const etiquetas = (clave: string, casos?: readonly CasoResumen[]) => faceta(clave, casos).opciones.map((o) => o.etiqueta);
  const elegir = (f: Filtros, clave: string, ...ids: string[]) => fijar(f, `segunda.${clave}`, ids);
  const textos = (c: CasoResumen, f = ABIERTOS) => datosFila(c, f).map((d) => d.texto);
  const porId = (id: string) => CASOS.find((c) => c.id === id)!;

  it("van en orden, con la clave prefijada (s.segunda.<clave> en la URL)", () => {
    expect(propias("segunda", CASOS).map((f) => [f.clave, f.corto, f.tipo])).toEqual([
      ["segunda.aquo", "Decisión 1ª inst.", "varias"],
      ["segunda.impugna", "Impugnó", "varias"],
      ["segunda.sentido", "Sentido 2ª inst.", "varias"],
      ["segunda.derecho", "Derecho", "buscable"],
      ["segunda.revisar", "Por revisar", "varias"],
      ["segunda.pruebas", "Con pruebas nuevas", "interruptor"],
    ]);
    expect(faceta("pruebas").activo).toBe("con");
  });

  it("Decisión 1ª inst.: «Sin dato» solo si algún caso no la trae", () => {
    expect(etiquetas("aquo")).toEqual(["Amparó", "Negó el amparo", "Declaró improcedente", "Carencia actual de objeto", "Otra", "Sin dato"]);
    expect(etiquetas("aquo", CASOS.slice(0, 2))).toEqual(["Amparó", "Negó el amparo", "Declaró improcedente", "Carencia actual de objeto", "Otra"]);
    expect(visibles(elegir(ABIERTOS, "aquo", "niega"))).toEqual(["quintero"]);
    expect(visibles(elegir(TODOS, "aquo", "niega"))).toEqual(["quintero", "mejia"]);
    expect(visibles(elegir(ABIERTOS, "aquo", "sin_dato"))).toEqual(["cardenas", "arango", "nuevo"]);
    expect(visibles(elegir(ABIERTOS, "aquo", "carencia_actual_de_objeto", "improcedente"))).toEqual(["restrepo", "gaviria"]);
  });

  it("Impugnó", () => {
    expect(etiquetas("impugna")).toEqual(["Accionante", "Accionada", "Vinculada", "Otro", "Varios"]);
    expect(visibles(elegir(ABIERTOS, "impugna", "accionada"))).toEqual(["zuluaga"]);
    expect(visibles(elegir(TODOS, "impugna", "accionada"))).toEqual(["zuluaga", "ocampo"]);
    expect(visibles(elegir(ABIERTOS, "impugna", "varios"))).toEqual(["gaviria"]);
  });

  it("Sentido 2ª inst.: el resultado del fallo; los demás, sin decidir", () => {
    expect(etiquetas("sentido")).toEqual(["Confirma", "Revoca", "Modifica", "Sin decidir"]);
    expect(etiquetas("sentido", [porId("mejia"), porId("ocampo")])).toEqual(["Confirma", "Revoca", "Modifica"]);
    expect(visibles(elegir(TODOS, "sentido", "revoca"))).toEqual(["mejia"]);
    expect(visibles(elegir(TODOS, "sentido", "confirma", "modifica"))).toEqual(["ocampo"]);
    expect(visibles(elegir(ABIERTOS, "sentido", "sin_decidir"))).toHaveLength(7);
  });

  it("Derecho: opciones de los casos (variantes juntas) y basta con uno de los elegidos", () => {
    expect(faceta("derecho").opciones).toEqual([
      { id: "salud", etiqueta: "Salud" },
      { id: "minimo vital", etiqueta: "Mínimo vital" },
      { id: "seguridad social", etiqueta: "Seguridad social" },
      { id: "peticion", etiqueta: "Petición" },
      { id: "vida digna", etiqueta: "Vida digna" },
    ]);
    expect(visibles(elegir(ABIERTOS, "derecho", "salud", "peticion"))).toEqual(["quintero", "zuluaga", "gaviria"]);
    expect(propiasVisibles("segunda", [porId("cardenas")]).map((f) => f.clave)).not.toContain("segunda.derecho");
    expect(propiasVisibles("segunda", CASOS).map((f) => f.clave)).toContain("segunda.derecho");
  });

  it("Por revisar: citas por revisar y discrepancias de Jev", () => {
    expect(etiquetas("revisar")).toEqual(["Citas por revisar", "Jev discrepa"]);
    expect(visibles(elegir(ABIERTOS, "revisar", "citas"))).toEqual(["quintero"]);
    expect(visibles(elegir(ABIERTOS, "revisar", "jev"))).toEqual(["zuluaga"]);
    expect(visibles(elegir(ABIERTOS, "revisar", "citas", "jev"))).toEqual(["quintero", "zuluaga"]);
  });

  it("Con pruebas nuevas: solo pruebas_nuevas === true", () => {
    expect(visibles(elegir(ABIERTOS, "pruebas", "con"))).toEqual(["zuluaga"]);
    expect(visibles(elegir(TODOS, "pruebas", "con"))).toEqual(["zuluaga", "ocampo"]);
    expect(conteoOpciones(CASOS, predicados(ABIERTOS, HOY), faceta("pruebas")).get("con")).toBe(1);
  });

  it("segunda null o ausente nunca rompe un predicado, un conteo ni la fila", () => {
    const antiguo = { ...porId("cardenas"), id: "antiguo", segunda: undefined as unknown as null };
    const casos = [...CASOS, antiguo];
    const todas = propias("segunda", casos);
    let f = TODOS;
    for (const fac of todas) f = fijar(f, fac.clave, fac.opciones.map((o) => o.id));
    expect(() => casos.map((c) => todas.map((fac) => fac.valor(c)))).not.toThrow();
    expect(visibles(f, [porId("cardenas"), antiguo])).toEqual([]);
    for (const fac of todas) expect(() => conteoOpciones(casos, predicados(f, HOY), fac)).not.toThrow();
    expect(visibles(elegir(TODOS, "aquo", "sin_dato"), [antiguo])).toEqual(["antiguo"]);
    expect(FILA.segunda(antiguo)).toEqual([]);
    expect(datosFila(porId("nuevo"), f)).toEqual([]);
  });

  it("cada conteo ignora su propia clave; las pestañas, todas las propias", () => {
    const f = elegir(elegir(ABIERTOS, "pruebas", "con"), "aquo", "niega");
    const preds = predicados(f, HOY);
    expect(visibles(f)).toEqual([]);
    expect([...conteoOpciones(CASOS, preds, faceta("aquo"))]).toEqual([["ampara", 1]]);
    expect([...conteoOpciones(CASOS, preds, faceta("pruebas"))]).toEqual([["sin", 1]]);
    expect(conteoPestanas(CASOS, preds)).toMatchObject({ todos: 7, segunda: 7 });
    const soloPruebas = predicados(elegir(ABIERTOS, "pruebas", "con"), HOY);
    expect(conteoEstados(CASOS, soloPruebas)).toMatchObject({ decidir: 1, terminado: 1, faltan: 0 });
    expect([...conteoOpciones(CASOS, predicados(ABIERTOS, HOY), faceta("aquo"))].sort()).toEqual([
      ["ampara", 1],
      ["carencia_actual_de_objeto", 1],
      ["improcedente", 1],
      ["niega", 1],
      ["sin_dato", 3],
    ]);
  });

  it("los filtros aplicados se nombran con la etiqueta de la faceta y de sus opciones", () => {
    const f = elegir(elegir(ABIERTOS, "aquo", "niega", "sin_dato"), "pruebas", "con");
    expect(activos(f, ABIERTOS, propias("segunda", CASOS))).toEqual([
      { clave: "segunda.aquo", texto: "Decisión de primera instancia: Negó el amparo, Sin dato" },
      { clave: "segunda.pruebas", texto: "Pruebas nuevas en segunda instancia: Con pruebas nuevas" },
    ]);
  });

  it("ida y vuelta por la URL, descartando valores y claves desconocidos", () => {
    const sel = {
      "segunda.aquo": ["niega", "sin_dato"],
      "segunda.derecho": ["minimo vital"],
      "segunda.impugna": ["accionada"],
      "segunda.pruebas": ["con"],
      "segunda.revisar": ["citas", "jev"],
      "segunda.sentido": ["revoca"],
    };
    const texto = serializar({ ...ABIERTOS, sel }, ABIERTOS);
    expect(texto).toBe(
      "s.segunda.aquo=niega,sin_dato&s.segunda.derecho=minimo%20vital&s.segunda.impugna=accionada" +
        "&s.segunda.pruebas=con&s.segunda.revisar=citas,jev&s.segunda.sentido=revoca",
    );
    expect(deserializar(texto, { defaults: ABIERTOS, casos: CASOS }).sel).toEqual(sel);
    expect(deserializar(texto, { defaults: ABIERTOS }).sel).toEqual(sel);

    const sucio = "s.segunda.aquo=niega,xx&s.segunda.zz=1&s.primera.aquo=niega&s.segunda.derecho=nada&s.segunda.pruebas=si,sin&s.alertas=sin";
    expect(deserializar(sucio, { defaults: ABIERTOS, casos: CASOS }).sel).toEqual({ "segunda.aquo": ["niega"] });
    expect(deserializar(sucio, { defaults: ABIERTOS }).sel).toEqual({ "segunda.aquo": ["niega"], "segunda.derecho": ["nada"] });
    expect(deserializar("s.segunda.aquo=sin_dato,niega", { defaults: ABIERTOS, casos: [porId("quintero")] }).sel).toEqual({ "segunda.aquo": ["niega"] });
  });

  it("los filtros propios solo valen con su carril a la vista, por la URL igual que al cambiar de pestaña", () => {
    const mezclados = [...CASOS, { ...porId("quintero"), id: "primera-1", proceso: "primera" as never, segunda: null }];
    const url = "s.segunda.aquo=niega&s.alertas=con";
    // Inicio con varios procesos y la pestaña «Todos»: no hay carril propio que muestre el filtro.
    expect(deserializar(url, { defaults: ABIERTOS, casos: mezclados }).sel).toEqual({ alertas: ["con"] });
    expect(deserializar(`${url}&p=segunda`, { defaults: ABIERTOS, casos: mezclados }).sel).toEqual({ alertas: ["con"], "segunda.aquo": ["niega"] });
    expect(deserializar(url, { defaults: inicial("segunda"), casos: mezclados }).sel).toEqual({ alertas: ["con"], "segunda.aquo": ["niega"] });
    // Inicio con un solo proceso: su carril se ve, y sin casos no se sabe cuál es, así que se conserva.
    expect(deserializar(url, { defaults: ABIERTOS, casos: CASOS }).sel).toEqual({ alertas: ["con"], "segunda.aquo": ["niega"] });
    expect(deserializar(url, { defaults: ABIERTOS }).sel).toEqual({ alertas: ["con"], "segunda.aquo": ["niega"] });
    expect(deserializar(`${url}&p=penal`, { defaults: ABIERTOS }).sel).toEqual({ alertas: ["con"] });
  });

  it("la fila muestra sus datos cortos y resalta los que reflejan un filtro elegido", () => {
    expect(datosFila(porId("quintero"), ABIERTOS)).toEqual([
      { texto: "1ª inst.: Negó el amparo", clave: "aquo", valor: "niega", eco: false },
      { texto: "Impugna: accionante", clave: "impugna", valor: "accionante", eco: false },
      { texto: "2 citas por revisar", tono: "alerta", clave: "revisar", valor: "citas", eco: false },
    ]);
    expect(textos(porId("zuluaga"))).toEqual(["1ª inst.: Amparó", "Impugna: accionada", "Pruebas nuevas en 2ª", "Jev discrepa"]);
    expect(textos(porId("mejia"))).toEqual(["1ª inst.: Negó el amparo", "Impugna: accionante", "Fallo: revoca y ampara"]);
    expect(datosFila(porId("mejia"), ABIERTOS)[2]).toMatchObject({ tono: "ok", clave: "sentido", valor: "revoca" });
    expect(textos(porId("ocampo"))).toEqual(["1ª inst.: Amparó", "Impugna: accionada", "Fallo: confirma", "Pruebas nuevas en 2ª"]);
    expect(textos(porId("gaviria"))).toEqual(["1ª inst.: Carencia actual de objeto", "Impugna: varios"]);
    expect(textos(porId("arango"))).toEqual([]);
    expect(textos(porId("cardenas"))).toEqual([]);

    const con = (d: Partial<DatosSegunda>) => ({ ...porId("arango"), segunda: conSegunda(d) });
    expect(textos(con({ n_citas_revisar: 1 }))).toEqual(["1 cita por revisar"]);
    expect(textos(con({ resultado: "CONFIRMAR", sustitutiva: "AMPARAR" }))).toEqual(["Fallo: confirma"]);
    expect(textos(con({ resultado: "MODIFICAR", sustitutiva: "CARENCIA_HECHO_SUPERADO" }))).toEqual(["Fallo: modifica y declara hecho superado"]);
    expect(textos(con({ resultado: "REVOCAR", sustitutiva: "NEGAR", pruebas_nuevas: false }))).toEqual(["Fallo: revoca y niega"]);

    const f = elegir(elegir(ABIERTOS, "revisar", "jev"), "pruebas", "con");
    expect(datosFila(porId("zuluaga"), f).filter((d) => d.eco).map((d) => d.texto)).toEqual(["Pruebas nuevas en 2ª", "Jev discrepa"]);
    expect(datosFila(porId("quintero"), f).some((d) => d.eco)).toBe(false);
  });
});

describe("plazos", () => {
  const termino = (inicio: string, dias = 20, unidad: "habiles" | "calendario" = "habiles") => ({ inicio, dias, unidad });
  const plazo = (vence: string | null, dias_restantes: number | null, t = termino("2026-10-15")) => ({ termino: t, vence, dias_restantes });
  // Hoy es el martes 17 de noviembre de 2026 (el lunes 16 fue festivo). mejia trae un plazo viejo aunque terminó.
  const PLAZOS_DE: Record<string, Partial<CasoResumen>> = {
    quintero: plazo("2026-11-20", 3, termino("2026-10-21")),
    zuluaga: plazo("2026-11-13", -1),
    cardenas: plazo("2026-11-17", 0),
    arango: plazo("2026-11-18", 1),
    gaviria: plazo("2026-11-27", 8),
    restrepo: plazo("2026-12-01", 14, termino("2026-11-03", 28, "calendario")),
    mejia: plazo("2026-11-10", -5),
  };
  const PLZ = CASOS.map((c) => ({ ...c, ...PLAZOS_DE[c.id] }));
  const de = (id: string) => PLZ.find((c) => c.id === id)!;
  const defaults = inicial();
  const visiblesPlz = (f: Filtros) => ids(PLZ.filter((c) => pasa(c, predicados(f, HOY))));

  it("cubetas en orden de urgencia; sin término o terminado, «sin»", () => {
    expect(PLAZOS.map((p) => [p.id, p.etiqueta])).toEqual([
      ["vencido", "Vencidos"],
      ["pronto", "Vencen hoy o en 1 día"],
      ["semana", "Vencen en 2 a 5 días"],
      ["despues", "Vencen en 6 días o más"],
      ["sin", "Sin término calculado"],
    ]);
    expect(Object.fromEntries(PLZ.map((c) => [c.id, plazoDe(c)]))).toEqual({
      quintero: "semana",
      zuluaga: "vencido",
      restrepo: "despues",
      cardenas: "pronto",
      arango: "pronto",
      gaviria: "despues",
      nuevo: "sin",
      mejia: "sin",
      ocampo: "sin",
    });
    const con = (r: number) => plazoDe({ ...de("quintero"), dias_restantes: r });
    expect([-30, -1, 0, 1, 2, 5, 6, 40].map(con)).toEqual(["vencido", "vencido", "pronto", "pronto", "semana", "semana", "despues", "despues"]);
    expect(PLZ.filter(urgente).map((c) => c.id)).toEqual(["zuluaga", "cardenas"]);
    // El chip toma el tono de su baldosa: rojo vencido u hoy, ámbar de 1 a 5 días, neutro después o sin término.
    expect([-3, 0, 1, 5, 6].map((r) => tonoPlazo({ ...de("quintero"), dias_restantes: r }))).toEqual(["mal", "mal", "alerta", "alerta", "neutro"]);
    expect(tonoPlazo(de("nuevo"))).toBe("neutro");
    expect(tonoPlazo(de("mejia"))).toBe("neutro");
    expect(facetaPorClave("plazo")?.opciones.map((o) => o.id)).toEqual(["vencido", "pronto", "semana", "despues", "sin"]);
  });

  it("el texto del chip cuenta en la unidad del término; «mañana» solo si vence al día siguiente", () => {
    expect(textoPlazo(de("zuluaga"), HOY)).toBe("Venció hace 1 día hábil");
    expect(textoPlazo({ ...de("zuluaga"), dias_restantes: -2 }, HOY)).toBe("Venció hace 2 días hábiles");
    expect(textoPlazo(de("cardenas"), HOY)).toBe("Vence hoy");
    expect(textoPlazo(de("arango"), HOY)).toBe("Vence mañana");
    expect(textoPlazo(de("quintero"), HOY)).toBe("Faltan 3 días hábiles");
    expect(textoPlazo(de("restrepo"), HOY)).toBe("Faltan 14 días calendario");
    expect(textoPlazo({ ...de("restrepo"), dias_restantes: -2 }, HOY)).toBe("Venció hace 2 días calendario");
    expect(textoPlazo({ ...de("restrepo"), dias_restantes: 1, vence: "2026-11-18" }, HOY)).toBe("Vence mañana");
    // Un viernes, el siguiente día hábil es el lunes: no es «mañana».
    expect(textoPlazo({ ...de("arango"), vence: "2026-11-23" }, new Date(2026, 10, 20, 9))).toBe("Falta 1 día hábil");
    expect(textoPlazo(de("nuevo"), HOY)).toBeNull();
    expect(textoPlazo(de("mejia"), HOY)).toBeNull();
  });

  it("el título dice desde cuándo corre, cuándo vence y la regla", () => {
    expect(tituloPlazo(de("quintero"))).toBe("Recibido el 21 de octubre de 2026; vence el 20 de noviembre de 2026 (20 días hábiles)");
    expect(tituloPlazo(de("restrepo"))).toBe("Recibido el 3 de noviembre de 2026; vence el 1 de diciembre de 2026 (28 días calendario)");
    expect(tituloPlazo({ ...de("quintero"), termino: termino("2026-11-16", 1) })).toContain("(1 día hábil)");
    expect(tituloPlazo(de("nuevo"))).toBe("");
  });

  it("el filtro deja los casos de las cubetas elegidas y se nombra en los filtros aplicados", () => {
    const f = fijar(defaults, "plazo", ["vencido", "pronto"]);
    expect(visiblesPlz(f)).toEqual(["zuluaga", "cardenas", "arango"]);
    expect(activos(f, defaults, [])).toEqual([{ clave: "plazo", texto: "Plazo: Vencidos, Vencen hoy o en 1 día" }]);
    expect(quitarFiltro(f, "plazo", defaults).sel).toEqual({});
    expect(limpiar(f, defaults).filtros.sel).toEqual({});
    expect(visiblesPlz(fijar(defaults, "plazo", ["sin"]))).toEqual(["nuevo"]);
  });

  it("las baldosas cuentan ignorando solo el plazo", () => {
    const f = fijar(defaults, "plazo", ["vencido"]);
    expect(conteoPlazos(PLZ, predicados(f, HOY))).toEqual({ vencido: 1, pronto: 2, semana: 1, despues: 2, sin: 1 });
    const conAlertas = alternar(f, "alertas", "con");
    expect(conteoPlazos(PLZ, predicados(conAlertas, HOY))).toEqual({ vencido: 1, pronto: 1, semana: 1, despues: 1, sin: 0 });
    // El estado sí cuenta: con los terminados a la vista, «sin» los suma.
    expect(conteoPlazos(PLZ, predicados(elegirEstado(f, "terminado"), HOY)).sin).toBe(3);
  });

  it("«Lo que me toca primero» pone primero lo vencido y lo que vence hoy, y luego el orden de siempre", () => {
    expect(ids(ordenarPor(PLZ, "prioridad"))).toEqual(["zuluaga", "cardenas", "quintero", "gaviria", "arango", "nuevo", "restrepo", "mejia", "ocampo"]);
  });

  it("«Vence primero» va por fecha de vencimiento; sin término al final y los terminados detrás", () => {
    expect(ORDENES.map((o) => o.id)).toEqual(["prioridad", "vence", "reciente", "antiguo", "radicado"]);
    expect(ids(ordenarPor(PLZ, "vence"))).toEqual(["zuluaga", "cardenas", "arango", "quintero", "gaviria", "restrepo", "nuevo", "mejia", "ocampo"]);
  });

  it("agrupa por plazo en orden de urgencia, sin grupos vacíos", () => {
    expect(AGRUPACIONES.map((a) => a.id)).toEqual(["ninguno", "estado", "plazo"]);
    const grupos = agruparPor(ordenarPor(PLZ, "vence"), "plazo");
    expect(grupos.map((g) => [g.id, g.titulo, ids(g.casos), g.total])).toEqual([
      ["vencido", "Vencidos", ["zuluaga"], 1],
      ["pronto", "Vencen hoy o en 1 día", ["cardenas", "arango"], 2],
      ["semana", "Vencen en 2 a 5 días", ["quintero"], 1],
      ["despues", "Vencen en 6 días o más", ["gaviria", "restrepo"], 2],
      ["sin", "Sin término calculado", ["nuevo", "mejia", "ocampo"], 3],
    ]);
    expect(agruparPor(ordenarPor(CASOS, "vence"), "plazo").map((g) => g.id)).toEqual(["sin"]);
  });

  it("ida y vuelta por la URL con la clave pl, en orden de urgencia y descartando lo desconocido", () => {
    const contexto = { defaults, casos: PLZ };
    let f = fijar(defaults, "plazo", ["pronto", "vencido"]);
    f = { ...alternar(elegirPreset(f, "semana"), "alertas", "con"), orden: "vence", agrupar: "plazo" };
    const q = serializar(f, defaults);
    expect(q).toBe("f=semana&pl=vencido,pronto&s.alertas=con&o=vence&g=plazo");
    const leido = deserializar(q, contexto);
    expect(leido.sel).toEqual({ plazo: ["vencido", "pronto"], alertas: ["con"] });
    expect([leido.orden, leido.agrupar]).toEqual(["vence", "plazo"]);
    expect(serializar(leido, defaults)).toBe(q);
    expect(deserializar("pl=vencido,zzz,vencido", contexto).sel).toEqual({ plazo: ["vencido"] });
    expect(deserializar("pl=zzz", contexto).sel).toEqual({});
    expect(deserializar("pl=", contexto).sel).toEqual({});
    expect(deserializar("o=vence&g=plazo", { defaults: inicial("segunda") })).toMatchObject({ orden: "vence", agrupar: "plazo" });
  });
});
