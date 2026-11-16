import { afterEach, describe, expect, it, vi } from "vitest";
import type { Bloque, CitaVista } from "../../api/contrato";
import { porcentaje } from "../../estado";
import {
  agruparBloques,
  casoOracion,
  claveRevisados,
  construirIndice,
  construirRevision,
  dividirMotivos,
  filasJev,
  guardarRevisados,
  humanizarAlerta,
  leerRevisados,
  limitePasos,
  marcasDelIndice,
  redaccionPorNodo,
  seccionesDeCitas,
  tituloDelCaso,
} from "./datos";
import { ESTADO_BORRADOR, VISTA_BORRADOR } from "./mock";
import type { EstadoCaso, LlamadaBitacora } from "./tipos";

const md = { impugnante_rol: "accionante", impugnante: "Marta", decision_a_quo: "negó el amparo" };

describe("valores de la ingesta", () => {
  it("conserva comillas escapadas y vuelve espacio los saltos", () => {
    const a = humanizarAlerta(
      "apertura",
      "En metadatos, campo accionadas, la ingesta extrajo ['O\\'Brien', 'a\\nb'] y el modelo leyó ['X']; se conserva el de la ingesta, verifique cuál es correcto.",
      false,
    );
    if (a.detalle?.tipo !== "comparar") throw new Error("falta el detalle");
    expect(a.detalle.lecturas[0]?.valores).toEqual(["O'Brien", "a b"]);
  });
});

describe("filasJev", () => {
  it("distingue coincide, difiere y sin comparar", () => {
    const filas = filasJev(
      {
        umbral: 0.8,
        preguntas: {
          sentido_fallo: { choice: "niega", confidence: 0.97 },
          sentido_clausula: { choice: "niega", confidence: 0.62 },
          rol_impugnante: { choice: "accionada", confidence: 0.9 },
        },
        coincide: { sentido: null, rol_impugnante: false },
      },
      md,
    );
    expect(filas.map((f) => f.estado)).toEqual(["sin_comparar", "difiere"]);
    expect(filas[0]?.motivo).toMatch(/62\s*%.*80\s*%/);
    expect(filas[0]?.borrador.principal).toBe("Negó el amparo");
    expect(filas[1]?.jev.principal).toBe("Accionada");
  });

  it("las filas que difieren llevan la ayuda y las no comparadas su explicación", () => {
    const filas = filasJev(
      {
        umbral: 0.8,
        preguntas: {
          sentido_fallo: { choice: "niega", confidence: 0.97 },
          sentido_clausula: { choice: "ampara", confidence: 0.9 },
          rol_impugnante: { choice: "accionada", confidence: 0.9 },
        },
        coincide: { sentido: false, rol_impugnante: false },
      },
      md,
    );
    expect(filas[0]?.motivo).toBe("Revise la frase del borrador que describe la decisión de primera instancia (I y III) antes de decidir.");
    expect(filas[1]?.motivo).toBe("Revise quién impugna en la sección IV.");
    const coinciden = filasJev(
      { umbral: 0.8, preguntas: { rol_impugnante: { choice: "accionante", confidence: 0.9 } }, coincide: { rol_impugnante: true } },
      md,
    );
    expect(coinciden[0]?.motivo).toBeNull();
  });

  it("nunca marca difiere cuando coincide es null y explica la lectura ausente", () => {
    const filas = filasJev(
      { umbral: 0.8, preguntas: { sentido_fallo: { choice: "ampara", confidence: 0.9 } }, coincide: { sentido: null, rol_impugnante: null } },
      md,
    );
    expect(filas).toHaveLength(1);
    expect(filas[0]?.estado).toBe("sin_comparar");
    expect(filas[0]?.motivo).toMatch(/Jev no pudo leer la frase del borrador/);
  });

  it("devuelve vacío sin lecturas y conserva claves desconocidas", () => {
    expect(filasJev(null, md)).toEqual([]);
    expect(filasJev({ preguntas: {} }, md)).toEqual([]);
    const filas = filasJev({ preguntas: { rol_impugnante: { choice: "tercero", confidence: 1 } }, coincide: { rol_impugnante: true } }, md);
    expect(filas[0]?.jev.principal).toBe("tercero");
    expect(filas[0]?.estado).toBe("coincide");
  });
});

describe("dividirMotivos", () => {
  it("parte tras el punto y descarta vacíos", () => {
    expect(dividirMotivos("Primero. Segundo; tercero. Cuarto.")).toEqual(["Primero. Segundo; tercero. Cuarto."]);
    expect(dividirMotivos("A.; B.;   C.")).toEqual(["A.", "B.", "C."]);
    expect(dividirMotivos("A.; ")).toEqual(["A."]);
    expect(dividirMotivos(null)).toEqual([]);
    expect(dividirMotivos("")).toEqual([]);
  });
});

describe("humanizarAlerta", () => {
  it("texto truncado: nota con el número en es-CO y origen de archivo", () => {
    const a = humanizarAlerta(
      "ingesta",
      "1a-007 007_007Respuesta_Anexos.pdf: texto truncado a 120000 caracteres para el LLM.",
      false,
    );
    expect(a).toMatchObject({
      nivel: "info",
      origen: "Archivo 1a-007",
      titulo: "El modelo leyó solo una parte de este documento",
      linea: "007_007Respuesta_Anexos.pdf",
      detalle: {
        tipo: "archivo",
        archivo: "007_007Respuesta_Anexos.pdf",
        nota: `Se le entregaron los primeros ${(120000).toLocaleString("es-CO")} caracteres; lo que sigue no se tuvo en cuenta al redactar.`,
      },
    });
    expect(a.detalle).toMatchObject({ nota: expect.stringContaining("120.000") });
  });

  it("páginas sin texto legible, en singular y plural", () => {
    const varias = humanizarAlerta("ingesta", "1a-002 002_Escrito.pdf (escrito_tutela): páginas sin texto legible: 3, 4.", false);
    expect(varias).toMatchObject({
      nivel: "info",
      origen: "Archivo 1a-002",
      titulo: "Páginas 3, 4 sin texto legible",
      detalle: { tipo: "archivo", archivo: "002_Escrito.pdf", nota: "El modelo no pudo leer esas páginas." },
    });
    const una = humanizarAlerta("ingesta", "1a-002 002_Escrito.pdf (escrito_tutela): páginas sin texto legible: 7.", false);
    expect(una.titulo).toBe("Página 7 sin texto legible");
    expect(una.detalle).toMatchObject({ nota: "El modelo no pudo leer esa página." });
  });

  it("extensión de antecedentes, con línea completa y origen de la apertura", () => {
    const a = humanizarAlerta("apertura", "antecedentes: tiene 1202 palabras, por encima del máximo esperado (510 a 1140).", false);
    expect(a).toEqual({
      nivel: "alerta",
      origen: "Apertura · II a IV",
      titulo: "Los antecedentes son más largos de lo esperado",
      linea: "1202 palabras; se esperaban entre 510 y 1140.",
      lineaCompleta: true,
      detalle: null,
    });
  });

  it("concordancia de cada campo de extensión, por encima y por debajo", () => {
    const t = (nodo: string, campo: string, lado: "encima del máximo" | "debajo del mínimo") =>
      humanizarAlerta(nodo, `${campo}: tiene 9 palabras, por ${lado} esperado (1 a 2).`, false).titulo;
    expect(t("apertura", "antecedentes", "debajo del mínimo")).toBe("Los antecedentes son más cortos de lo esperado");
    expect(t("apertura", "sentencia_impugnada", "encima del máximo")).toBe("La sentencia impugnada es más larga de lo esperado");
    expect(t("apertura", "sentencia_impugnada", "debajo del mínimo")).toBe("La sentencia impugnada es más corta de lo esperado");
    expect(t("apertura", "impugnacion", "encima del máximo")).toBe("La impugnación es más larga de lo esperado");
    expect(t("consideraciones", "consideraciones", "encima del máximo")).toBe("Las consideraciones son más largas de lo esperado");
    expect(t("consideraciones", "consideraciones", "debajo del mínimo")).toBe("Las consideraciones son más cortas de lo esperado");
    expect(t("caso_concreto", "caso concreto", "encima del máximo")).toBe("El caso concreto es más largo de lo esperado");
    expect(t("caso_concreto", "caso concreto", "debajo del mínimo")).toBe("El caso concreto es más corto de lo esperado");
  });

  it("campo de extensión desconocido", () => {
    const a = humanizarAlerta("apertura", "contestaciones: tiene 30 palabras, por debajo del mínimo esperado (50 a 80).", false);
    expect(a.titulo).toBe("Contestaciones: 30 palabras");
    expect(a.linea).toBe("30 palabras; se esperaban entre 50 y 80.");
  });

  it("origen de las consideraciones", () => {
    const a = humanizarAlerta("consideraciones", "consideraciones: tiene 9 palabras, por debajo del mínimo esperado (1 a 2).", false);
    expect(a.origen).toBe("Consideraciones · V");
  });

  it("metadatos con dos lecturas en listas de Python", () => {
    const a = humanizarAlerta(
      "apertura",
      "En metadatos, campo accionadas, la ingesta extrajo ['EPS HORIZONTE SALUD S.A.S.', 'SUPERINTENDENCIA NACIONAL DE SALUD'] y el modelo leyó ['EPS Horizonte Salud S.A.S.', 'Superintendencia Nacional de Salud – Supersalud']; se conserva el de la ingesta, verifique cuál es correcto.",
      false,
    );
    expect(a).toEqual({
      nivel: "alerta",
      origen: "Apertura · II a IV",
      titulo: "Accionadas: dos lecturas distintas",
      linea: "Se conservó la que se extrajo del expediente.",
      lineaCompleta: false,
      detalle: {
        tipo: "comparar",
        lecturas: [
          { etiqueta: "Extraído del expediente · se conservó", valores: ["EPS HORIZONTE SALUD S.A.S.", "SUPERINTENDENCIA NACIONAL DE SALUD"] },
          { etiqueta: "Leído por el modelo", valores: ["EPS Horizonte Salud S.A.S.", "Superintendencia Nacional de Salud – Supersalud"] },
        ],
      },
    });
  });

  it("metadatos con valores simples, con comillas dobles y con campos con nombre propio", () => {
    const a = humanizarAlerta(
      "apertura",
      `En metadatos, campo juzgado_a_quo, la ingesta extrajo 'Juzgado 9' y el modelo leyó "Juzgado d'Or"; se conserva el de la ingesta, verifique cuál es correcto.`,
      false,
    );
    expect(a.titulo).toBe("Juzgado de primera instancia: dos lecturas distintas");
    expect(a.detalle).toMatchObject({
      lecturas: [
        { valores: ["Juzgado 9"] },
        { valores: ["Juzgado d'Or"] },
      ],
    });
    const rol = humanizarAlerta(
      "apertura",
      "En metadatos, campo impugnante_rol, la ingesta extrajo accionante y el modelo leyó accionada; se conserva el de la ingesta, verifique cuál es correcto.",
      false,
    );
    expect(rol.titulo).toBe("Calidad de quien impugna: dos lecturas distintas");
    expect(rol.detalle).toMatchObject({ lecturas: [{ valores: ["accionante"] }, { valores: ["accionada"] }] });
    const otro = humanizarAlerta(
      "apertura",
      "En metadatos, campo cui_2a, la ingesta extrajo 'a' y el modelo leyó 'b'; se conserva el de la ingesta, verifique cuál es correcto.",
      false,
    );
    expect(otro.titulo).toBe("Cui 2a: dos lecturas distintas");
  });

  it("formato desconocido: BLOQUEA es mal y el resto es alerta, con el mensaje completo", () => {
    const largo = "Jev lee el sentido del fallo como 'niega' (97 %); verifique decision_a_quo.";
    expect(humanizarAlerta("apertura", largo, false)).toEqual({
      nivel: "alerta",
      origen: "Apertura · II a IV",
      titulo: largo,
      linea: null,
      lineaCompleta: false,
      detalle: null,
    });
    const bloquea = humanizarAlerta("consideraciones", "La cita c3 (sentencia T-999 de 2019) fue rechazada: no aparece.", true);
    expect(bloquea).toMatchObject({ nivel: "mal", origen: "Consideraciones · V", titulo: expect.stringContaining("fue rechazada"), linea: null, detalle: null });
  });

  it("nodos sin secciones usan solo su etiqueta", () => {
    expect(humanizarAlerta("documentos_caso", "algo raro", false).origen).toBe("Documentos");
    expect(humanizarAlerta("ingesta", "algo raro", false).origen).toBe("Archivo");
    expect(humanizarAlerta("otro_nodo", "algo raro", false).origen).toBe("Otro nodo");
  });
});

describe("seccionesDeCitas y marcasDelIndice", () => {
  it("asocia cada cita con el título en oración de su sección", () => {
    expect(seccionesDeCitas(VISTA_BORRADOR)).toEqual({
      c1: "V. Consideraciones",
      c2: "V. Consideraciones",
      c3: "V. Consideraciones",
    });
  });

  it("cita sin sección da cadena vacía", () => {
    const vista = structuredClone(VISTA_BORRADOR);
    for (const p of vista.paginas) for (const b of p.bloques) if (b.segmentos.some((s) => s.cita_id === "c1")) b.seccion = null;
    expect(seccionesDeCitas(vista).c1).toBe("");
  });

  it("marca la sección y el último subtítulo, con mal si hay una rechazada", () => {
    expect(marcasDelIndice(VISTA_BORRADOR)).toEqual({
      consideraciones: { n: 2, mal: true },
      "consideraciones-5": { n: 1, mal: false },
      "consideraciones-9": { n: 1, mal: true },
    });
  });

  it("cuenta cada cita una sola vez aunque aparezca en varios segmentos de la sección", () => {
    const vista = structuredClone(VISTA_BORRADOR);
    for (const p of vista.paginas)
      for (const b of p.bloques) {
        const i = b.segmentos.findIndex((s) => s.cita_id === "c2");
        if (i >= 0) b.segmentos.splice(i, 0, { ...b.segmentos[i]! });
      }
    expect(marcasDelIndice(vista)).toEqual(marcasDelIndice(VISTA_BORRADOR));
  });

  it("sin citas por revisar no hay marcas", () => {
    const vista = { ...VISTA_BORRADOR, citas: VISTA_BORRADOR.citas.map((c): CitaVista => ({ ...c, estado: "verificada" })) };
    expect(marcasDelIndice(vista)).toEqual({});
  });
});

describe("construirIndice", () => {
  it("marca como anexo los títulos sin numeral romano", () => {
    const entradas = construirIndice(VISTA_BORRADOR);
    expect(entradas.find((e) => e.id === "consideraciones")).toMatchObject({ titulo: "V. Consideraciones", sub: false, anexo: false });
    expect(entradas.find((e) => e.id === "informe-de-citas")).toMatchObject({ titulo: "Informe de citas", sub: false, anexo: true });
    expect(entradas.find((e) => e.id === "alertas-por-nodo")?.anexo).toBe(true);
    expect(entradas.find((e) => e.id === "consideraciones-5")).toMatchObject({ sub: true, anexo: false });
  });
});

describe("construirRevision", () => {
  const secciones = seccionesDeCitas(VISTA_BORRADOR);
  const jev = filasJev(ESTADO_BORRADOR.resumen?.jev_metadatos, ESTADO_BORRADOR.resumen?.metadatos);
  const items = construirRevision(VISTA_BORRADOR.citas, ESTADO_BORRADOR.resumen?.alertas, jev, secciones);

  it("ordena por nivel y, dentro de cada uno, citas, Jev y alertas", () => {
    expect(items.map((i) => [i.nivel, i.clave])).toEqual([
      ["mal", "cita-c3"],
      ["alerta", "cita-c2"],
      ["alerta", "jev-sentido"],
      ["alerta", "alerta-apertura-3"],
      ["alerta", "alerta-apertura-4"],
      ["info", "alerta-ingesta-0"],
      ["info", "alerta-ingesta-1"],
      ["ok", "cita-c1"],
      ["ok", "jev-rol"],
    ]);
  });

  it("pliega la alerta de la cita rechazada y la de Jev que ya muestra su fila", () => {
    const textos = items.map((i) => i.titulo);
    expect(textos.some((t) => t.startsWith("La cita c3"))).toBe(false);
    expect(textos.some((t) => t.startsWith("Jev lee"))).toBe(false);
  });

  it("describe las citas con origen, línea y detalle", () => {
    const c1 = items.find((i) => i.clave === "cita-c1");
    expect(c1).toMatchObject({
      nivel: "ok",
      origen: "Cita · V. Consideraciones",
      titulo: "Sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa",
      linea: `Verificada · cobertura ${porcentaje(0.98)}`,
      cita: "c1",
      detalle: { tipo: "cita", motivos: [] },
    });
    const c2 = items.find((i) => i.clave === "cita-c2");
    expect(c2?.linea).toBe("La cobertura del fragmento citado es 71 %. Compare con la relatoría antes de firmar.");
    expect(items.find((i) => i.clave === "cita-c3")?.linea).toBe("No aparece en el dataset de la Corte Constitucional.");
  });

  it("cita sin motivos usa la etiqueta del estado y sin fuente usa el id", () => {
    const citas: CitaVista[] = [{ id: "z9", texto: "t", fuente: "", cobertura: null, estado: "revisar", detalle: null }];
    const [item] = construirRevision(citas, null, [], {});
    expect(item).toMatchObject({ clave: "cita-z9", origen: "Cita", titulo: "z9", linea: "Con alerta", nivel: "alerta" });
  });

  it("describe las filas de Jev", () => {
    const sentido = items.find((i) => i.clave === "jev-sentido");
    expect(sentido).toMatchObject({
      nivel: "alerta",
      origen: "Jev · no coincide",
      titulo: "Sentido del fallo de primera instancia",
      linea: "Borrador: Declaró improcedente la acción de tutela · Jev: Niega el amparo",
      detalle: { tipo: "jev" },
      cita: null,
    });
    expect(items.find((i) => i.clave === "jev-rol")?.origen).toBe("Jev · coincide");
  });

  it("Jev sin comparar es info y los datos faltantes se rotulan", () => {
    const fila = {
      id: "x",
      etiqueta: "X",
      borrador: { principal: null, secundario: null },
      jev: { principal: null, confianza: null, nota: null },
      estado: "sin_comparar" as const,
      motivo: null,
    };
    const [item] = construirRevision([], null, [fila], {});
    expect(item).toMatchObject({ nivel: "info", origen: "Jev · sin comparar", linea: "Borrador: Sin dato · Jev: Sin lectura" });
  });

  it("sin filas de Jev conserva la alerta de Jev como fila de revisión", () => {
    const sinJev = construirRevision([], ESTADO_BORRADOR.resumen?.alertas, [], {});
    expect(sinJev.some((i) => i.titulo.startsWith("Jev lee"))).toBe(true);
  });

  it("alerta de una cita que no existe se conserva", () => {
    const r = construirRevision([], { consideraciones: ["BLOQUEA: La cita c9 (sentencia X) fue rechazada: no aparece."] }, [], {});
    expect(r).toHaveLength(1);
    expect(r[0]).toMatchObject({ nivel: "mal", clave: "alerta-consideraciones-0" });
  });

  it("acepta alertas como lista y quita los prefijos", () => {
    const lista = construirRevision([], ["ALERTA: x", "BLOQUEA: y"], [], {});
    expect(lista.map((i) => [i.titulo, i.nivel, i.origen])).toEqual([
      ["y", "mal", "Archivo"],
      ["x", "alerta", "Archivo"],
    ]);
  });

  it("tolera alertas ausentes", () => {
    expect(construirRevision([], undefined, [], {})).toEqual([]);
    expect(construirRevision([], {}, [], {})).toEqual([]);
    expect(construirRevision([], null, [], {})).toEqual([]);
  });
});

describe("construirRevision, alertas", () => {
  const citas = VISTA_BORRADOR.citas;
  const claves = (a: unknown) => construirRevision(citas, a as never, [], {}).filter((i) => i.clave.startsWith("alerta-"));

  it("pliega solo los avisos de cita rechazada o por revisar", () => {
    expect(claves({ consideraciones: ["BLOQUEA: La cita c3 (sentencia T-999 de 2019) fue rechazada: no aparece.", "ALERTA: La cita c2 (SU-508) requiere revisión: baja."] })).toEqual([]);
  });

  it("conserva el aviso de cita sin marcador", () => {
    expect(claves({ consideraciones: ["BLOQUEA: La cita c1 (T-760 de 2008) no se usa en ningún marcador del texto."] })).toHaveLength(1);
  });

  it("acepta un texto suelto por nodo y no falla con elementos nulos", () => {
    expect(claves({ apertura: "ALERTA: algo pasó" })).toHaveLength(1);
    expect(claves({ apertura: ["ALERTA: algo pasó", null, 3] })).toHaveLength(2);
    expect(claves(["ALERTA: uno", null])).toHaveLength(1);
  });
});

describe("alertas de formato desconocido", () => {
  const titulos = (alertas: unknown) =>
    construirRevision([], alertas as never, [], {}).map((i) => i.titulo);

  it("no produce [object Object], títulos vacíos ni una fila por carácter", () => {
    expect(titulos([{ a: 1 }])).toEqual(['{"a":1}']);
    expect(titulos({ apertura: [{ x: 1 }] })).toEqual(['{"x":1}']);
    expect(titulos(["", "ALERTA: x"])).toEqual(["x"]);
    expect(titulos("hola")).toEqual(["hola"]);
    expect(titulos({ apertura: "una sola" })).toEqual(["una sola"]);
  });
});

describe("revisados", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("arma la clave con el caso y el sha", () => {
    expect(claveRevisados("c1", "abc")).toBe("judicabot:revisados:c1:abc");
  });

  it("ida y vuelta", () => {
    const clave = claveRevisados("c1", "abc");
    expect(leerRevisados(clave).size).toBe(0);
    guardarRevisados(clave, new Set(["cita-c1", "jev-rol"]));
    expect([...leerRevisados(clave)].sort()).toEqual(["cita-c1", "jev-rol"]);
  });

  it("JSON corrupto, valor que no es arreglo de cadenas o getItem que lanza dan vacío", () => {
    const clave = claveRevisados("c1", "abc");
    localStorage.setItem(clave, "{no es json");
    expect(leerRevisados(clave).size).toBe(0);
    localStorage.setItem(clave, '{"a":1}');
    expect(leerRevisados(clave).size).toBe(0);
    localStorage.setItem(clave, '["a", 2]');
    expect(leerRevisados(clave).size).toBe(0);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    expect(leerRevisados(clave).size).toBe(0);
  });

  it("guardar borra los revisados de otros borradores del mismo caso y respeta los demás", () => {
    localStorage.setItem(claveRevisados("c1", "viejo"), '["a"]');
    localStorage.setItem(claveRevisados("c2", "viejo"), '["a"]');
    localStorage.setItem("otra", "x");
    guardarRevisados(claveRevisados("c1", "nuevo"), new Set(["b"]));
    expect(localStorage.getItem(claveRevisados("c1", "viejo"))).toBeNull();
    expect(localStorage.getItem(claveRevisados("c2", "viejo"))).not.toBeNull();
    expect(localStorage.getItem("otra")).toBe("x");
    expect([...leerRevisados(claveRevisados("c1", "nuevo"))]).toEqual(["b"]);
  });

  it("guardar no lanza si el almacenamiento falla", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("lleno");
    });
    expect(() => guardarRevisados("k", new Set(["a"]))).not.toThrow();
  });
});

describe("utilidades", () => {
  it("agrupa filas de tabla y viñetas consecutivas", () => {
    const b = (id: string, tipo: Bloque["tipo"]): Bloque => ({ id, tipo, origen: "plantilla", seccion: null, segmentos: [] });
    const grupos = agruparBloques([b("1", "parrafo"), b("2", "tabla"), b("3", "tabla"), b("4", "parrafo"), b("5", "lista"), b("6", "lista")]);
    expect(grupos.map((g) => g.tipo)).toEqual(["bloque", "tabla", "bloque", "lista"]);
    expect(grupos[1] && "bloques" in grupos[1] && grupos[1].bloques.length).toBe(2);
  });

  it("pasa a oración los títulos en mayúsculas", () => {
    expect(casoOracion("II. ANTECEDENTES DEL CASO")).toBe("II. Antecedentes del caso");
    expect(casoOracion("La salud y la continuidad")).toBe("La salud y la continuidad");
  });

  it("deriva el límite de pasos y el título del caso", () => {
    const e = (estado: EstadoCaso["estado"]): EstadoCaso => ({ estado });
    expect(limitePasos(e("esperando_decision"))).toBe("decision");
    expect(limitePasos(e("terminado"))).toBe("fallo");
    expect(limitePasos(e("corriendo"))).toBe("borrador");
    expect(limitePasos(null)).toBe("borrador");
    expect(tituloDelCaso("c1", { accionante: "A", accionadas: ["B", "C"] })).toBe("A c. B, C");
    expect(tituloDelCaso("c1", null)).toBe("c1");
  });
});

describe("redaccionPorNodo", () => {
  const llamada = (nodo: string, pedido: string, efectivo: string | null, extra: Partial<LlamadaBitacora> = {}): LlamadaBitacora => ({
    nodo,
    intento: 1,
    proveedor: "anthropic",
    modelo_pedido: pedido,
    modelo_efectivo: efectivo,
    ...extra,
  });

  it("toma el modelo de la última llamada de cada nodo, en el orden de las secciones", () => {
    const filas = redaccionPorNodo([
      llamada("consideraciones", "claude-sonnet-5-5", "claude-sonnet-5-5"),
      llamada("apertura", "claude-haiku-5-5", "claude-haiku-5-5"),
      llamada("apertura", "claude-sonnet-5-5", "claude-sonnet-5-5", { intento: 2 }),
    ]);
    expect(filas).toEqual([
      { nodo: "apertura", secciones: "Secciones II a IV", modelo: "Sonnet 5.5", pedido: null },
      { nodo: "consideraciones", secciones: "Sección V", modelo: "Sonnet 5.5", pedido: null },
    ]);
  });

  it("ignora las lecturas de Jev y los nodos que no escriben el borrador", () => {
    const filas = redaccionPorNodo([
      llamada("roles", "jev-1", "jev-1", { proveedor: "jev" }),
      llamada("apertura", "jev-1", "jev-1", { proveedor: "jev" }),
      llamada("caso_concreto", "claude-sonnet-5-5", "claude-sonnet-5-5"),
    ]);
    expect(filas).toEqual([]);
  });

  it("indica lo pedido solo cuando el modelo efectivo es otro y quita el sufijo de fecha", () => {
    const filas = redaccionPorNodo([
      llamada("apertura", "claude-haiku-5-5", "claude-sonnet-5-5"),
      llamada("consideraciones", "claude-sonnet-5-5", "claude-sonnet-5-5-20261001"),
    ]);
    expect(filas[0]).toMatchObject({ modelo: "Sonnet 5.5", pedido: "Haiku 5.5" });
    expect(filas[1]).toMatchObject({ modelo: "Sonnet 5.5", pedido: null });
  });

  it("usa el modelo pedido si no hay efectivo y tolera la bitácora ausente", () => {
    expect(redaccionPorNodo([llamada("apertura", "claude-opus-5-5", null)])[0]).toMatchObject({ modelo: "Opus 5.5", pedido: null });
    expect(redaccionPorNodo(undefined)).toEqual([]);
    expect(redaccionPorNodo(null)).toEqual([]);
    expect(redaccionPorNodo([])).toEqual([]);
  });
});
