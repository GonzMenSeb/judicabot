import { fireEvent, render, screen, within } from "@testing-library/preact";
import type { Ref } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { describe, expect, it, vi } from "vitest";
import type { Bloque, CitaVista, Segmento, Vista } from "../../api/contrato";
import { Documento } from "./Documento";
import { PopoverCita } from "./PopoverCita";

const bloque = (id: string, tipo: Bloque["tipo"], origen: Bloque["origen"], ...segmentos: Segmento[]): Bloque => ({
  id,
  tipo,
  origen,
  seccion: null,
  segmentos,
});

const CITAS: CitaVista[] = [
  { id: "c1", texto: "fragmento uno", fuente: "sentencia T-123 de 2020", cobertura: 0.97, estado: "verificada", detalle: null, url: "https://relatoria.example/t-123-20.htm" },
  { id: "c2", texto: "fragmento dos", fuente: "sentencia T-456 de 2021", cobertura: 0.4, estado: "revisar", detalle: "Primero. Segundo.", url: "https://relatoria.example/t-456-21.htm" },
  { id: "c3", texto: "fragmento tres", fuente: "", cobertura: null, estado: "rechazada", detalle: null },
];

const VISTA: Vista = {
  tipo: "borrador",
  sha256: "abc",
  citas: CITAS,
  indice: [],
  paginas: [
    {
      bloques: [
        bloque("t1", "titulo", "plantilla", { texto: "I. ANTECEDENTES" }),
        bloque("p1", "parrafo", "modelo", { texto: "Según " }, { texto: "la sentencia T-123", cita_id: "c1" }, { texto: " se resolvió." }),
        bloque("p2", "parrafo", "plantilla", { texto: "Texto de plantilla." }),
        bloque("l1", "lista", "modelo", { texto: "uno" }),
        bloque("l2", "lista", "modelo", { texto: "dos" }),
      ],
    },
    {
      bloques: [
        bloque("s1", "encabezado", "modelo", { texto: "Subtítulo" }),
        bloque("p3", "parrafo", "modelo", { texto: "Otra cita ", }, { texto: "T-456", cita_id: "c2" }),
        bloque("pie1", "pie", "plantilla", { texto: "Pie de página" }),
      ],
    },
  ],
};
VISTA.paginas[1]!.bloques[0]!.seccion = "s1";

const mapa = new Map(CITAS.map((c) => [c.id, c]));

function documento(extra: Partial<Parameters<typeof Documento>[0]> = {}) {
  const alCita = vi.fn();
  const salida = render(<Documento vista={VISTA} citas={mapa} seleccionada={null} plantilla={false} alCita={alCita} {...extra} />);
  return { alCita, ...salida };
}

describe("Documento", () => {
  it("la cita es un role=button que se parte con la línea, con aria-pressed y estado para lectores", () => {
    const { container } = documento({ seleccionada: "c1" });
    const cita = container.querySelector<HTMLElement>('[data-cita="c1"]')!;
    expect(cita.tagName).toBe("SPAN");
    expect(cita.getAttribute("role")).toBe("button");
    expect(cita.tabIndex).toBe(0);
    expect(cita.getAttribute("aria-pressed")).toBe("true");
    expect(cita.getAttribute("aria-haspopup")).toBe("dialog");
    expect(cita.getAttribute("aria-controls")).toBe("bor-detalle");
    expect(cita.classList.contains("verificada")).toBe(true);
    expect(cita.classList.contains("sel")).toBe(true);
    expect(cita.textContent).toContain("(Verificada)");
    const otra = container.querySelector<HTMLElement>('[data-cita="c2"]')!;
    expect(otra.getAttribute("aria-pressed")).toBe("false");
    expect(otra.getAttribute("aria-controls")).toBeNull();
  });

  it("clic, Enter y Espacio llaman alCita con el id y el elemento; Espacio no desplaza la página", () => {
    const { alCita, container } = documento();
    const cita = container.querySelector<HTMLElement>('[data-cita="c1"]')!;
    fireEvent.click(cita);
    expect(alCita).toHaveBeenLastCalledWith("c1", cita);
    expect(fireEvent.keyDown(cita, { key: "Enter" })).toBe(false);
    expect(alCita).toHaveBeenCalledTimes(2);
    expect(fireEvent.keyDown(cita, { key: " " })).toBe(false);
    expect(alCita).toHaveBeenCalledTimes(3);
    expect(fireEvent.keyDown(cita, { key: "a" })).toBe(true);
    expect(alCita).toHaveBeenCalledTimes(3);
  });

  it("plantilla pone bor-con-plantilla en la hoja", () => {
    const { rerender } = documento({ plantilla: true });
    const hoja = screen.getByRole("article", { name: "Borrador del fallo, secciones I a V" });
    expect(hoja.classList.contains("bor-hoja")).toBe(true);
    expect(hoja.classList.contains("bor-con-plantilla")).toBe(true);
    rerender(<Documento vista={VISTA} citas={mapa} seleccionada={null} plantilla={false} alCita={() => {}} />);
    expect(hoja.classList.contains("bor-con-plantilla")).toBe(false);
  });

  it("cada página lleva su etiqueta, los bloques de plantilla bor-tpl y el sello", () => {
    const { container } = documento();
    const paginas = [...container.querySelectorAll<HTMLElement>(".bor-pagina")];
    expect(paginas.map((p) => p.dataset.pagina)).toEqual(["Página 1 de 2", "Página 2 de 2"]);
    expect(container.querySelector("#b-t1")!.classList.contains("bor-tpl")).toBe(true);
    expect(container.querySelectorAll(".bor-tpl").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Borrador, aún no es el fallo")).toBeTruthy();
  });

  it("conserva ids de encabezados, listas y el pie solo en la última página", () => {
    const { container } = documento();
    expect(container.querySelector("h3#b-t1")).toBeTruthy();
    expect(container.querySelector("h4#b-s1")).toBeTruthy();
    expect(container.querySelectorAll("ul.bor-lista li").length).toBe(2);
    const paginas = container.querySelectorAll(".bor-pagina");
    expect(paginas[0]!.querySelector(".bor-pie")).toBeNull();
    expect(paginas[1]!.querySelector(".bor-pie")!.textContent).toBe("Pie de página");
  });

  it("una tabla con más de tres columnas es una región con foco", () => {
    const fila = (id: string) => bloque(id, "tabla", "modelo", { texto: "a" }, { texto: "b" }, { texto: "c" }, { texto: "d" });
    const vista: Vista = { ...VISTA, paginas: [{ bloques: [fila("f1"), fila("f2")] }] };
    const { container } = render(<Documento vista={vista} citas={mapa} seleccionada={null} plantilla={false} alCita={() => {}} />);
    const caja = container.querySelector<HTMLElement>(".bor-tabla-caja")!;
    expect(caja.getAttribute("role")).toBe("region");
    expect(caja.tabIndex).toBe(0);
  });
});

function Montado({ cita, motivos = [], onCerrar = () => {}, enfocar = false }: { cita: CitaVista; motivos?: string[]; onCerrar?: () => void; enfocar?: boolean }) {
  const titulo = useRef<HTMLHeadingElement>(null);
  const [{ ancla, contenedor }] = useState(() => {
    const ancla = document.createElement("span");
    const contenedor = document.createElement("div");
    document.body.append(contenedor);
    contenedor.append(ancla);
    return { ancla, contenedor };
  });
  useEffect(() => {
    if (enfocar) titulo.current?.focus();
  }, [enfocar]);
  return <PopoverCita cita={cita} motivos={motivos} ancla={ancla} contenedor={contenedor} titulo={titulo as Ref<HTMLHeadingElement>} onCerrar={onCerrar} />;
}

describe("PopoverCita", () => {
  it("es una región con el nombre de la fuente en mayúscula inicial y id bor-detalle", () => {
    render(<Montado cita={{ ...CITAS[0]!, fuente: "sentencia T-123 de 2020" }} />);
    const region = screen.getByRole("region", { name: "Sentencia T-123 de 2020" });
    expect(region.id).toBe("bor-detalle");
    expect(within(region).getByRole("heading", { level: 3 }).getAttribute("tabindex")).toBe("-1");
    expect(within(region).getByText("Verificada")).toBeTruthy();
    expect(within(region).getByText("fragmento uno")).toBeTruthy();
    expect(within(region).getByText("97 %")).toBeTruthy();
  });

  it("enfoca el título cuando el padre lo pide", () => {
    render(<Montado cita={CITAS[0]!} enfocar />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 3 }));
  });

  it("Escape y el botón Cerrar llaman onCerrar; Escape no se propaga", () => {
    const onCerrar = vi.fn();
    const fuera = vi.fn();
    document.addEventListener("keydown", fuera);
    render(<Montado cita={CITAS[0]!} onCerrar={onCerrar} />);
    fireEvent.keyDown(screen.getByRole("region"), { key: "Escape" });
    expect(onCerrar).toHaveBeenCalledTimes(1);
    expect(fuera).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onCerrar).toHaveBeenCalledTimes(2);
    document.removeEventListener("keydown", fuera);
  });

  it("los motivos son elementos de lista", () => {
    render(<Montado cita={CITAS[1]!} motivos={["Primero.", "Segundo."]} />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Primero.", "Segundo."]);
  });

  it("el enlace a la relatoría aparece solo si está verificada y hay url", () => {
    const { unmount } = render(<Montado cita={CITAS[0]!} />);
    const enlace = screen.getByRole("link", { name: /Abrir en la relatoría/ });
    expect(enlace.getAttribute("href")).toBe("https://relatoria.example/t-123-20.htm");
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
    expect(enlace.textContent).toContain("se abre en una pestaña nueva");
    unmount();

    render(<Montado cita={CITAS[1]!} />);
    expect(screen.queryByRole("link", { name: /relatoría/ })).toBeNull();
  });

  it("verificada sin url no muestra enlace", () => {
    render(<Montado cita={{ ...CITAS[0]!, url: null }} />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("cobertura null muestra — y fuente vacía cae al id", () => {
    render(<Montado cita={CITAS[2]!} />);
    expect(screen.getByRole("region", { name: "c3" })).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });
});
