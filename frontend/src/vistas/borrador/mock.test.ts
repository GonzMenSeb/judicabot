import { describe, expect, it } from "vitest";
import { ErrorApi } from "../../api/cliente";
import type { EdicionCuerpo } from "../../api/contrato";
import { unidadesDe } from "./datos";
import { CASO_MOCK_BORRADOR, crearEdicionesMock, mocks, VISTA_BORRADOR } from "./mock";

const HECHOS = "apertura.antecedentes_hechos";
const peticion = (pieza: string, cuerpo?: EdicionCuerpo) => ({ metodo: "PUT" as const, ruta: `/api/casos/${CASO_MOCK_BORRADOR}/ediciones/${pieza}`, cuerpo });

describe("mock de ediciones", () => {
  it("las fuentes de la vista coinciden con las piezas y sus párrafos", () => {
    const mock = crearEdicionesMock();
    const { piezas } = mock.respuesta();
    const unidades = new Set(unidadesDe(mock.vista()).values());
    expect(unidades.size).toBe(15);
    for (const u of unidades) expect(piezas[u.pieza]?.parrafos[u.parrafo], u.clave).toBeTruthy();
    expect(Object.keys(piezas)).toContain("consideraciones.bloques.0.titulo");
    expect(piezas["consideraciones.bloques.0.texto"]?.parrafos[0]).toContain("⟦cita c1 · T-760 de 2008⟧");
  });

  it("sin ediciones la vista del mock es idéntica a VISTA_BORRADOR", () => {
    expect(crearEdicionesMock().vista()).toEqual(VISTA_BORRADOR);
  });

  it("editar cambia el texto de la vista, marca el párrafo y restaurar lo devuelve", () => {
    const mock = crearEdicionesMock();
    const original = mock.respuesta().piezas[HECHOS]?.parrafos[1] ?? "";
    const respuesta = mock.editar(peticion(HECHOS, { parrafo: 1, original, texto: "Texto nuevo.\n\nSegundo párrafo nuevo." }));
    expect(respuesta.piezas[HECHOS]?.parrafos).toHaveLength(4);
    expect(respuesta.piezas[HECHOS]?.editados).toEqual([1, 2]);
    const bloques = mock.vista().paginas.flatMap((p) => p.bloques);
    const nuevos = bloques.filter((b) => b.fuente?.pieza === HECHOS);
    expect(nuevos.map((b) => b.fuente?.parrafo)).toEqual([0, 1, 2, 3]);
    expect(nuevos.map((b) => b.segmentos.map((s) => s.texto).join("")).slice(1, 3)).toEqual(["Texto nuevo.", "Segundo párrafo nuevo."]);
    mock.restaurar(peticion(HECHOS));
    expect(mock.respuesta().piezas[HECHOS]?.editados).toEqual([]);
    expect(mock.vista()).toEqual(VISTA_BORRADOR);
  });

  it("rechaza lo mismo que el servidor: original desfasado, pieza desconocida, ficha cambiada, vacío y título con salto", () => {
    const mock = crearEdicionesMock();
    const falla = (f: () => unknown) => {
      try {
        f();
      } catch (e) {
        return e instanceof ErrorApi ? e.estado : -1;
      }
      return 0;
    };
    expect(falla(() => mock.editar(peticion(HECHOS, { parrafo: 0, original: "otro", texto: "x" })))).toBe(409);
    expect(falla(() => mock.editar(peticion("no.existe", { parrafo: 0, original: "", texto: "x" })))).toBe(404);
    const cita = mock.respuesta().piezas["consideraciones.bloques.0.texto"]?.parrafos[0] ?? "";
    expect(falla(() => mock.editar(peticion("consideraciones.bloques.0.texto", { parrafo: 0, original: cita, texto: cita.replace(/⟦[^⟧]*⟧/, "") })))).toBe(422);
    const unico = mock.respuesta().piezas["apertura.contestaciones.0.texto"]?.parrafos[0] ?? "";
    expect(falla(() => mock.editar(peticion("apertura.contestaciones.0.texto", { parrafo: 0, original: unico, texto: "  " })))).toBe(422);
    const titulo = mock.respuesta().piezas["consideraciones.bloques.0.titulo"]?.parrafos[0] ?? "";
    expect(falla(() => mock.editar(peticion("consideraciones.bloques.0.titulo", { parrafo: 0, original: titulo, texto: "a\nb" })))).toBe(422);
  });

  it("las rutas del mock cubren GET, PUT, DELETE y el POST de resolver", () => {
    const base = `/api/casos/${CASO_MOCK_BORRADOR}/ediciones`;
    const cubre = (metodo: string, ruta: string) => mocks.some((m) => m.metodo === metodo && (typeof m.ruta === "string" ? new RegExp(`^${m.ruta.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:\\?.*)?$`) : m.ruta).test(ruta));
    expect(cubre("GET", base)).toBe(true);
    expect(cubre("PUT", `${base}/${HECHOS}`)).toBe(true);
    expect(cubre("DELETE", `${base}/${HECHOS}`)).toBe(true);
    expect(cubre("POST", `${base}/${HECHOS}/resolver`)).toBe(true);
    expect(cubre("POST", `${base}/${HECHOS}`)).toBe(false);
  });
});
