import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { CAMPOS_MOCK, DOCUMENTOS_MOCK, VALORES_MOCK } from "./mock";
import { PreviaDocumento, ProveedorPrevia } from "./previas";
import type { Plantilla } from "./modelo";

function claves(documento: string, plantilla: Plantilla, foco: string | null = null): Set<string> {
  const { container } = render(
    <ProveedorPrevia value={{ valores: VALORES_MOCK, plantilla, foco, campos: CAMPOS_MOCK }}>
      <PreviaDocumento id={documento} />
    </ProveedorPrevia>,
  );
  return new Set(Array.from(container.querySelectorAll<HTMLElement>("[data-c]")).map((el) => el.dataset.c as string));
}

const esperadas = (documento: string, plantilla: Plantilla) =>
  CAMPOS_MOCK.filter((c) => c.documentos.includes(documento))
    .map((c) => c.clave)
    .filter((k) => !(k === "pie" && plantilla === "B") && !(k === "pie_fallo" && plantilla === "A"));

describe("vistas previas frente al catálogo", () => {
  for (const plantilla of ["A", "B"] as const) {
    for (const { id } of DOCUMENTOS_MOCK) {
      it(`muestra exactamente los campos que el catálogo declara para ${id} con la plantilla ${plantilla}`, () => {
        expect([...claves(id, plantilla)].sort()).toEqual(esperadas(id, plantilla).sort());
      });
    }
  }

  it("resalta todas las apariciones del campo enfocado", () => {
    const { container } = render(
      <ProveedorPrevia value={{ valores: VALORES_MOCK, plantilla: "B", foco: "juez", campos: CAMPOS_MOCK }}>
        <PreviaDocumento id="correos" />
      </ProveedorPrevia>,
    );
    expect(container.querySelectorAll('[data-c="juez"].foco').length).toBeGreaterThan(0);
    expect(container.querySelectorAll('[data-c]:not([data-c="juez"]).foco')).toHaveLength(0);
  });

  it("usa una vista genérica para documentos que el catálogo agregue", () => {
    const campos = CAMPOS_MOCK.map((c) => (c.clave === "ciudad" ? { ...c, documentos: [...c.documentos, "nuevo"] } : c));
    const { container } = render(
      <ProveedorPrevia value={{ valores: VALORES_MOCK, plantilla: "B", foco: null, campos }}>
        <PreviaDocumento id="nuevo" />
      </ProveedorPrevia>,
    );
    expect(container.querySelector('[data-c="ciudad"]')?.textContent).toBe("Medellín");
  });

  it("marca los campos vacíos con su etiqueta y escribe los renglones de las listas", () => {
    const valores = { ...VALORES_MOCK, juez: "", firma_correo: ["Línea uno", "Línea dos"] };
    const { container } = render(
      <ProveedorPrevia value={{ valores, plantilla: "B", foco: null, campos: CAMPOS_MOCK }}>
        <PreviaDocumento id="formato" />
        <PreviaDocumento id="correos" />
      </ProveedorPrevia>,
    );
    expect(container.querySelector('[data-c="juez"]')?.textContent).toBe("[Nombre del juez]");
    expect(container.querySelector('[data-c="firma_correo"]')?.innerHTML).toBe("Línea uno<br>Línea dos");
  });
});
