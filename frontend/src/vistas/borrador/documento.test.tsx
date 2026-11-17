import { fireEvent, render, screen, within } from "@testing-library/preact";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Ref } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { describe, expect, it, vi } from "vitest";
import type { ApoderadoVista, Bloque, CitaVista, Segmento, Vista } from "../../api/contrato";
import { APODERADOS_BORRADOR } from "./mock";
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

const SIN_APODERADOS = new Map<string, ApoderadoVista>();

function documento(extra: Partial<Parameters<typeof Documento>[0]> = {}) {
  const alCita = vi.fn();
  const alApoderado = vi.fn();
  const salida = render(
    <Documento vista={VISTA} citas={mapa} apoderados={SIN_APODERADOS} seleccionada={null} plantilla={false} alCita={alCita} alApoderado={alApoderado} {...extra} />,
  );
  return { alCita, alApoderado, ...salida };
}

describe("Documento", () => {
  it("la cita es un role=button que se parte con la línea, con aria-pressed y estado para lectores", () => {
    const { container } = documento({ seleccionada: { tipo: "cita", id: "c1" } });
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
    rerender(<Documento vista={VISTA} citas={mapa} apoderados={SIN_APODERADOS} seleccionada={null} plantilla={false} alCita={() => {}} alApoderado={() => {}} />);
    expect(hoja.classList.contains("bor-con-plantilla")).toBe(false);
  });

  it("cada página lleva su etiqueta, los bloques de plantilla bor-tpl y el sello", () => {
    const { container } = documento();
    const paginas = [...container.querySelectorAll<HTMLElement>(".bor-pagina")];
    expect(paginas.map((p) => p.dataset.pagina)).toEqual(["Página 1 de 2", "Página 2 de 2"]);
    expect(container.querySelector("#b-t1")!.classList.contains("bor-tpl")).toBe(true);
    expect(container.querySelectorAll(".bor-tpl").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Borrador · aún no es el fallo")).toBeTruthy();
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
    const { container } = render(<Documento vista={vista} citas={mapa} apoderados={SIN_APODERADOS} seleccionada={null} plantilla={false} alCita={() => {}} alApoderado={() => {}} />);
    const caja = container.querySelector<HTMLElement>(".bor-tabla-caja")!;
    expect(caja.getAttribute("role")).toBe("region");
    expect(caja.tabIndex).toBe(0);
  });
});

describe("Documento: nombres de abogados", () => {
  const ABOGADOS = new Map(APODERADOS_BORRADOR.apoderados.map((a) => [a.id, a]));
  const [ROJO, AMBAR, VERDE] = APODERADOS_BORRADOR.apoderados as [ApoderadoVista, ApoderadoVista, ApoderadoVista];
  const conNombres: Vista = {
    ...VISTA,
    paginas: [
      {
        bloques: [
          bloque(
            "a1",
            "parrafo",
            "modelo",
            { texto: "Mediante su apoderada, la doctora " },
            { texto: "Andrea Paola Giraldo Montoya", apoderado_id: VERDE.id },
            { texto: ", contestó; el doctor " },
            { texto: "Luis Fernando Ospina Arango", apoderado_id: AMBAR.id, negrita: true },
            { texto: " y el doctor " },
            { texto: "Carlos Eduardo Pineda Ruiz", apoderado_id: ROJO.id },
            { texto: " también; y " },
            { texto: "Alguien Desconocido", apoderado_id: "ap-0000000000" },
            { texto: "." },
          ),
        ],
      },
    ],
  };
  const montar = (extra: Partial<Parameters<typeof Documento>[0]> = {}) => documento({ vista: conNombres, apoderados: ABOGADOS, ...extra });
  const marca = (container: Element, id: string) => container.querySelector<HTMLElement>(`[data-apoderado="${id}"]`)!;

  it("el nombre es un role=button con el color de su estado, aria-pressed y el estado para lectores", () => {
    const { container } = montar({ seleccionada: { tipo: "apoderado", id: VERDE.id } });
    const verde = marca(container, VERDE.id);
    expect(verde.tagName).toBe("SPAN");
    expect(verde.getAttribute("role")).toBe("button");
    expect(verde.tabIndex).toBe(0);
    expect(verde.className).toBe("bor-apo verificada sel");
    expect(verde.getAttribute("aria-pressed")).toBe("true");
    expect(verde.getAttribute("aria-haspopup")).toBe("dialog");
    expect(verde.getAttribute("aria-controls")).toBe("bor-detalle");
    expect(verde.textContent).toBe("Andrea Paola Giraldo Montoya (abogado verificado)");
    const ambar = marca(container, AMBAR.id);
    expect(ambar.className).toBe("bor-apo revisar");
    expect(ambar.getAttribute("aria-pressed")).toBe("false");
    expect(ambar.getAttribute("aria-controls")).toBeNull();
    expect(ambar.querySelector("strong")?.textContent).toBe("Luis Fernando Ospina Arango");
    expect(ambar.textContent).toContain("(abogado por revisar)");
    const rojo = marca(container, ROJO.id);
    expect(rojo.className).toBe("bor-apo rechazada");
    expect(rojo.textContent).toContain("(abogado no verificado)");
    expect(screen.getAllByRole("button").map((b) => b.dataset["apoderado"])).toEqual([VERDE.id, AMBAR.id, ROJO.id]);
  });

  it("la última palabra del nombre va aparte para que el glifo del estado no baje solo al renglón siguiente", () => {
    const { container } = montar();
    expect(marca(container, ROJO.id).querySelector(".bor-apo-cola")?.textContent).toBe("Ruiz");
    // Con formato, la palabra sigue dentro de la negrita.
    expect(marca(container, AMBAR.id).querySelector("strong .bor-apo-cola")?.textContent).toBe("Arango");
    expect(container.querySelectorAll(".bor-apo-cola")).toHaveLength(3);
    const css = readFileSync(join(import.meta.dirname, "apoderados.css"), "utf8");
    expect(css).toMatch(/\.bor-apo-cola \{ white-space: nowrap; \}/);
    expect(css).not.toMatch(/\.bor-apo(\.\w+)?::after/);
  });

  it("seleccionar una cita no marca a ningún abogado aunque compartan id", () => {
    const { container } = montar({ seleccionada: { tipo: "cita", id: VERDE.id } });
    expect(marca(container, VERDE.id).getAttribute("aria-pressed")).toBe("false");
  });

  it("clic, Enter y Espacio llaman alApoderado con el id y el elemento", () => {
    const { container, alApoderado, alCita } = montar();
    const rojo = marca(container, ROJO.id);
    fireEvent.click(rojo);
    expect(alApoderado).toHaveBeenLastCalledWith(ROJO.id, rojo);
    expect(fireEvent.keyDown(rojo, { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(rojo, { key: " " })).toBe(false);
    expect(alApoderado).toHaveBeenCalledTimes(3);
    expect(fireEvent.keyDown(rojo, { key: "Tab" })).toBe(true);
    expect(alApoderado).toHaveBeenCalledTimes(3);
    expect(alCita).not.toHaveBeenCalled();
  });

  it("un id que no está en /apoderados, o /apoderados sin cargar, deja el nombre como texto", () => {
    const { container, unmount } = montar();
    expect(container.querySelector('[data-apoderado="ap-0000000000"]')).toBeNull();
    expect(container.textContent).toContain("también; y Alguien Desconocido.");
    unmount();
    const sinDatos = montar({ apoderados: SIN_APODERADOS });
    expect(sinDatos.container.querySelector("[data-apoderado]")).toBeNull();
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(sinDatos.container.textContent).toContain("la doctora Andrea Paola Giraldo Montoya, contestó");
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
    const region = screen.getByRole("dialog", { name: "Sentencia T-123 de 2020" });
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
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
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
    expect(screen.getByRole("dialog", { name: "c3" })).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });
});
