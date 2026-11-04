import { describe, expect, it } from "vitest";
import { agregarMocks, resolverMock } from "./mock";
import type { MockRuta } from "./mock";

const peticion = (metodo: "GET" | "POST", ruta: string, cuerpo: unknown = undefined) => ({ metodo, ruta, cuerpo });

describe("mocks", () => {
  it("incluye el estado del servidor por defecto", async () => {
    const respuesta = (await resolverMock(peticion("GET", "/api/estado-servidor"))) as { modelos: string[] };
    expect(respuesta.modelos).toContain("claude-sonnet-5-5");
  });

  it("empareja rutas de texto exactas con o sin consulta y respeta el método", async () => {
    agregarMocks([{ metodo: "GET", ruta: "/api/prueba-a", respuesta: { a: 1 } }]);
    expect(await resolverMock(peticion("GET", "/api/prueba-a"))).toEqual({ a: 1 });
    expect(await resolverMock(peticion("GET", "/api/prueba-a?x=1"))).toEqual({ a: 1 });
    expect(resolverMock(peticion("POST", "/api/prueba-a"))).toBeNull();
    expect(resolverMock(peticion("GET", "/api/prueba-a/otra"))).toBeNull();
  });

  it("empareja expresiones regulares y pasa la petición al manejador", async () => {
    const mock: MockRuta = {
      metodo: "POST",
      ruta: /^\/api\/prueba-regex\/([^/]+)\/run$/,
      respuesta: (p) => ({ ruta: p.ruta, cuerpo: p.cuerpo }),
    };
    agregarMocks([mock]);
    expect(await resolverMock(peticion("POST", "/api/prueba-regex/c1/run", { cmd: "nuevo" }))).toEqual({
      ruta: "/api/prueba-regex/c1/run",
      cuerpo: { cmd: "nuevo" },
    });
  });

  it("resuelve el resumen de cada caso de demostración y deja pasar los desconocidos", async () => {
    const lista = (await resolverMock(peticion("GET", "/api/casos"))) as { id: string }[];
    const ids = [...lista.map((c) => c.id), "demo-sin-leer", "quintero-eps-horizonte", "sin-fallo"];
    for (const id of ids) {
      const resumen = (await resolverMock(peticion("GET", `/api/casos/${id}/resumen`))) as { id: string; nombre: string; etapa: number };
      expect(resumen.id).toBe(id);
      expect(resumen.nombre).toBeTruthy();
      expect(resumen.etapa).toBeGreaterThanOrEqual(0);
    }
    expect(resolverMock(peticion("GET", "/api/casos/no-existe/resumen"))).toBeNull();
  });

  it("entrega copias de las respuestas estáticas", async () => {
    agregarMocks([{ metodo: "GET", ruta: "/api/prueba-c", respuesta: { lista: [1] } }]);
    const primera = (await resolverMock(peticion("GET", "/api/prueba-c"))) as { lista: number[] };
    primera.lista.push(2);
    expect(await resolverMock(peticion("GET", "/api/prueba-c"))).toEqual({ lista: [1] });
  });
});
