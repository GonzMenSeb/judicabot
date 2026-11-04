import { describe, expect, it } from "vitest";
import type { Bloque } from "../../api/contrato";
import { agruparBloques, casoOracion, construirRevision, filasJev, limitePasos, redaccionPorNodo, tituloDelCaso } from "./datos";
import { VISTA_BORRADOR } from "./mock";
import type { EstadoCaso, LlamadaBitacora } from "./tipos";

const md = { impugnante_rol: "accionante", impugnante: "Marta", decision_a_quo: "negó el amparo" };

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

describe("construirRevision", () => {
  it("acepta alertas como dict o como lista, quita prefijos y pone BLOQUEA primero", () => {
    const items = construirRevision([], { apertura: ["ALERTA: a", "BLOQUEA: b"], consideraciones: [] });
    expect(items.map((i) => [i.texto, i.tono, i.etiqueta])).toEqual([
      ["b", "mal", "Apertura"],
      ["a", "alerta", "Apertura"],
    ]);
    const lista = construirRevision([], ["ALERTA: x"]);
    expect(lista[0]?.etiqueta).toBe("Archivo");
  });

  it("incluye solo citas por revisar o rechazadas, con rechazadas primero", () => {
    const items = construirRevision(VISTA_BORRADOR.citas, null);
    expect(items.map((i) => i.cita)).toEqual(["c3", "c2"]);
    expect(items[0]?.tono).toBe("mal");
  });

  it("tolera alertas ausentes", () => {
    expect(construirRevision([], undefined)).toEqual([]);
    expect(construirRevision([], {})).toEqual([]);
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
