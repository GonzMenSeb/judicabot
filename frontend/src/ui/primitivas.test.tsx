import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Chip, Hoja, Migas, Pasos, Topbar, Vacio, VisorPagina } from "./index";

describe("Boton", () => {
  it("aplica la variante y dispara onClick", () => {
    const alClic = vi.fn();
    render(<Boton variante="peligro" grande onClick={alClic}>Borrar</Boton>);
    const boton = screen.getByRole("button", { name: "Borrar" });
    expect(boton.className).toBe("btn peligro grande");
    expect(boton.getAttribute("type")).toBe("button");
    fireEvent.click(boton);
    expect(alClic).toHaveBeenCalledOnce();
  });

  it("usa secundario por defecto", () => {
    render(<Boton>Ok</Boton>);
    expect(screen.getByRole("button").className).toBe("btn secundario");
  });

  it("deshabilita y marca ocupado mientras carga", () => {
    render(<Boton cargando>Guardar</Boton>);
    const boton = screen.getByRole("button", { name: "Guardar" });
    expect((boton as HTMLButtonElement).disabled).toBe(true);
    expect(boton.getAttribute("aria-busy")).toBe("true");
    expect(boton.querySelector(".giro")).toBeTruthy();
  });

  it("se vuelve enlace con href y pierde el destino si está inactivo", () => {
    const { rerender } = render(<Boton href="/api/zip" download="caso.zip">Descargar</Boton>);
    const enlace = screen.getByRole("link", { name: "Descargar" });
    expect(enlace.getAttribute("href")).toBe("/api/zip");
    expect(enlace.getAttribute("download")).toBe("caso.zip");
    rerender(<Boton href="/api/zip" disabled>Descargar</Boton>);
    expect(screen.getByText("Descargar").getAttribute("href")).toBeNull();
    expect(screen.getByText("Descargar").getAttribute("aria-disabled")).toBe("true");
  });
});

describe("Chip", () => {
  it("aplica el tono", () => {
    render(<Chip tono="ok">Listo</Chip>);
    expect(screen.getByText("Listo").className).toBe("chip ok");
  });
  it("neutro no agrega clase de tono", () => {
    render(<Chip>Sin tono</Chip>);
    expect(screen.getByText("Sin tono").className).toBe("chip");
  });
});

describe("Aviso", () => {
  it("el error usa role alert y los demás status", () => {
    render(
      <>
        <Aviso tipo="error" titulo="Falló">Detalle</Aviso>
        <Aviso tipo="ok">Guardado</Aviso>
      </>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Falló");
    expect(screen.getByRole("status").textContent).toContain("Guardado");
  });
  it("muestra acciones", () => {
    render(<Aviso tipo="alerta" acciones={<button>Reintentar</button>}>Algo</Aviso>);
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeTruthy();
    expect(screen.getByRole("status").className).toBe("aviso alerta");
  });
});

describe("Migas", () => {
  it("enlaza todo menos el último, que es la página actual", () => {
    render(<Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Casos", href: "#/segunda" }, { texto: "Caso 1" }]} />);
    expect(screen.getByRole("link", { name: "Inicio" }).getAttribute("href")).toBe("#/");
    expect(screen.getByRole("link", { name: "Casos" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Caso 1" })).toBeNull();
    expect(screen.getByText("Caso 1").getAttribute("aria-current")).toBe("page");
  });
});

describe("Pasos", () => {
  const estados = () => screen.getAllByRole("listitem").map((li) => li.className);

  it("marca hecho, actual y bloqueado según el paso visto", () => {
    render(<Pasos caso="c1" actual="borrador" />);
    expect(estados()).toEqual([
      "paso hecho",
      "paso hecho",
      "paso actual",
      "paso bloqueado decide",
      "paso bloqueado",
    ]);
    expect(screen.getByRole("link", { current: "step" }).textContent).toContain("Borrador");
    expect(screen.getByRole("link", { name: /Documentos/ }).getAttribute("href")).toBe("#/segunda/c1/documentos");
    expect(screen.queryByRole("link", { name: /Decisión/ })).toBeNull();
    expect(screen.getByText(/Decisión/).textContent).toContain("aún no disponible");
  });

  it("usa limite para dejar disponibles los pasos ya alcanzados", () => {
    render(<Pasos caso="c1" actual="documentos" limite="decision" />);
    expect(estados()).toEqual(["paso actual", "paso hecho", "paso hecho", "paso disponible decide", "paso bloqueado"]);
    expect(screen.getByRole("link", { name: /Decisión/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Fallo/ })).toBeNull();
  });

  it("la decisión actual lleva la variante decide y el caso se codifica en el enlace", () => {
    render(<Pasos caso="a b/c" actual="decision" />);
    expect(estados()[3]).toBe("paso actual decide");
    expect(screen.getByRole("link", { name: /Documentos/ }).getAttribute("href")).toBe("#/segunda/a%20b%2Fc/documentos");
  });

  it("permite reemplazar el detalle de un paso", () => {
    render(<Pasos caso="c1" actual="documentos" detalles={{ documentos: "9 documentos revisados" }} />);
    expect(screen.getByText("9 documentos revisados")).toBeTruthy();
  });
});

describe("Topbar", () => {
  it("enlaza Inicio, Formato e IA y marca la sección actual", () => {
    render(<Topbar seccion="formato" clave modelo="Sonnet 5.5" />);
    expect(screen.getByRole("link", { name: "Judicabot, ir al inicio" }).getAttribute("href")).toBe("#/");
    expect(screen.getByRole("link", { name: "Inicio" }).getAttribute("href")).toBe("#/");
    const formato = screen.getByRole("link", { name: "Formato de documentos" });
    expect(formato.getAttribute("href")).toBe("#/formato");
    expect(formato.getAttribute("aria-current")).toBe("page");
    const ia = screen.getByRole("link", { name: /Inteligencia artificial/ });
    expect(ia.getAttribute("href")).toBe("#/ia");
    expect(ia.textContent).toContain("clave lista");
    expect(ia.textContent).toContain("Sonnet 5.5");
    expect(ia.querySelector(".punto")?.className).toBe("punto");
  });

  it("indica cuando falta la clave o se desconoce", () => {
    const { rerender } = render(<Topbar clave={false} />);
    expect(screen.getByRole("link", { name: /Inteligencia artificial/ }).textContent).toContain("falta la clave");
    expect(document.querySelector(".punto")?.className).toBe("punto mal");
    rerender(<Topbar clave={null} />);
    expect(document.querySelector(".punto")?.className).toBe("punto nulo");
  });
});

describe("Hoja, VisorPagina, Cargando y Vacio", () => {
  it("Hoja es un artículo con etiqueta", () => {
    render(<Hoja etiqueta="Borrador">Texto</Hoja>);
    const hoja = screen.getByRole("article", { name: "Borrador" });
    expect(hoja.className).toBe("hoja");
  });

  it("VisorPagina etiqueta la página y muestra el número", () => {
    render(<VisorPagina numero={2} total={5}>Cuerpo</VisorPagina>);
    const pagina = screen.getByRole("region", { name: "Página 2 de 5" });
    expect(pagina.className).toBe("visor-pagina");
    expect(pagina.textContent).toContain("2 / 5");
  });

  it("Cargando anuncia el estado", () => {
    render(<Cargando texto="Leyendo caso…" />);
    expect(screen.getByRole("status").textContent).toContain("Leyendo caso…");
  });

  it("Vacio muestra título, detalle y acción", () => {
    render(<Vacio titulo="Sin casos" accion={<button>Nuevo</button>}>Cree el primero.</Vacio>);
    expect(screen.getByText("Sin casos")).toBeTruthy();
    expect(screen.getByText("Cree el primero.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nuevo" })).toBeTruthy();
  });

  it("CasoNoEncontrado explica y vuelve a la lista de casos", () => {
    const { container } = render(<CasoNoEncontrado class="extra" />);
    expect(screen.getByText("No se encontró el caso")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Volver a los casos" }).getAttribute("href")).toBe("#/segunda");
    expect(container.querySelector(".vacio.extra")).toBeTruthy();
  });
});
