import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useState } from "preact/hooks";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApoderadosRespuesta, CitaVista } from "../../api/contrato";
import { porcentaje } from "../../estado";
import { itemsApoderados } from "./apoderados";
import { APODERADOS_BORRADOR } from "./mock";
import { PanelRevision, type PropsPanelRevision } from "./PanelRevision";
import type { PanelApoderados } from "./TabApoderados";
import type { FilaJev, ItemRevision, Pestana } from "./tipos";

const ARCHIVO_LARGO = "007_007Respuesta_de_la_Superintendencia_de_Industria_y_Comercio_Anexos_Completos_Version_Final.pdf";
const LISTA_LARGA = "['COMPAÑIA_DE_SERVICIOS_PUBLICOS_DOMICILIARIOS_DEL_VALLE_DEL_CAUCA_S.A._E.S.P.', 'OTRA_ENTIDAD_ACCIONADA_SIN_ESPACIOS']";

function cita(id: string, estado: CitaVista["estado"], extra: Partial<CitaVista> = {}): CitaVista {
  return { id, texto: `Fragmento de la cita ${id}`, fuente: `sentencia ${id}`, cobertura: 0.61, estado, detalle: null, ...extra };
}

const C1 = cita("c1", "verificada", { cobertura: 0.97, url: "https://www.corteconstitucional.gov.co/relatoria/2020/T-001-20.htm" });
const C2 = cita("c2", "revisar", { detalle: "La cobertura es baja. Verifique el pasaje.", url: "https://example.org/no-debe-aparecer" });
const C3 = cita("c3", "rechazada", { cobertura: null, detalle: "No se encontró en la relatoría; revise el número." });
const C4 = cita("c4", "verificada", { url: null });

const FILA_DIFIERE: FilaJev = {
  id: "sentido",
  etiqueta: "Sentido del fallo de primera instancia",
  borrador: { principal: "Niega el amparo", secundario: "Jev entiende esa frase como «Niega» (90 %)." },
  jev: { principal: "Concede el amparo", confianza: 0.87, nota: "en el expediente" },
  estado: "difiere",
  motivo: "Revise la frase del borrador que describe la decisión de primera instancia.",
};

const ITEMS: ItemRevision[] = [
  {
    clave: "cita-c3",
    marca: { tipo: "cita", id: "c3" },
    grupo: "citas",
    nivel: "mal",
    origen: "Cita · Consideraciones",
    titulo: "Sentencia c3",
    linea: "No se encontró en la relatoría",
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C3, motivos: ["No se encontró en la relatoría.", "Revise el número."] },
  },
  {
    clave: "alerta-ingesta-0",
    marca: null,
    grupo: "citas",
    nivel: "mal",
    origen: "Ingesta",
    titulo: `Hubo un error al leer ${ARCHIVO_LARGO}`,
    linea: null,
    lineaCompleta: false,
    detalle: null,
  },
  {
    clave: "cita-c2",
    marca: { tipo: "cita", id: "c2" },
    grupo: "citas",
    nivel: "alerta",
    origen: "Cita · Apertura",
    titulo: "Sentencia c2",
    linea: "La cobertura es baja.",
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C2, motivos: ["La cobertura es baja.", "Verifique el pasaje."] },
  },
  {
    clave: "jev-sentido",
    marca: null,
    grupo: "citas",
    nivel: "alerta",
    origen: "Jev · no coincide",
    titulo: FILA_DIFIERE.etiqueta,
    linea: "Borrador: Niega el amparo · Jev: Concede el amparo",
    lineaCompleta: false,
    detalle: { tipo: "jev", fila: FILA_DIFIERE },
  },
  {
    clave: "alerta-metadatos-0",
    marca: null,
    grupo: "citas",
    nivel: "alerta",
    origen: "Metadatos",
    titulo: "Accionadas: dos lecturas distintas",
    linea: "Se conservó la que se extrajo del expediente.",
    lineaCompleta: true,
    detalle: {
      tipo: "comparar",
      lecturas: [
        { etiqueta: "Extraído del expediente · se conservó", valores: ["Empresa A", "Empresa B"] },
        { etiqueta: "Leído por el modelo", valores: [LISTA_LARGA] },
      ],
    },
  },
  {
    clave: "alerta-ingesta-1",
    marca: null,
    grupo: "citas",
    nivel: "info",
    origen: "Archivo 1a-007",
    titulo: "El modelo leyó solo una parte de este documento",
    linea: ARCHIVO_LARGO,
    lineaCompleta: false,
    detalle: { tipo: "archivo", archivo: ARCHIVO_LARGO, nota: "Se le entregaron los primeros 120.000 caracteres; lo que sigue no se tuvo en cuenta." },
  },
  {
    clave: "jev-rol",
    marca: null,
    grupo: "citas",
    nivel: "info",
    origen: "Jev · sin comparar",
    titulo: "Quién impugna",
    linea: "Borrador: Sin dato · Jev: Sin lectura",
    lineaCompleta: false,
    detalle: {
      tipo: "jev",
      fila: {
        id: "rol",
        etiqueta: "Quién impugna",
        borrador: { principal: null, secundario: null },
        jev: { principal: null, confianza: null, nota: null },
        estado: "sin_comparar",
        motivo: "Jev no pudo leer el escrito.",
      },
    },
  },
  {
    clave: "cita-c1",
    marca: { tipo: "cita", id: "c1" },
    grupo: "citas",
    nivel: "ok",
    origen: "Cita · Consideraciones",
    titulo: "Sentencia c1",
    linea: `Verificada · cobertura ${porcentaje(0.97)}`,
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C1, motivos: [] },
  },
  {
    clave: "cita-c4",
    marca: { tipo: "cita", id: "c4" },
    grupo: "citas",
    nivel: "ok",
    origen: "Cita",
    titulo: "Sentencia c4",
    linea: `Verificada · cobertura ${porcentaje(0.61)}`,
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C4, motivos: [] },
  },
  {
    clave: "jev-ok",
    marca: null,
    grupo: "citas",
    nivel: "ok",
    origen: "Jev · coincide",
    titulo: "Otro dato",
    linea: null,
    lineaCompleta: false,
    detalle: null,
  },
];

function props(extra: Partial<PropsPanelRevision> = {}): PropsPanelRevision {
  return {
    items: ITEMS,
    revisados: new Set<string>(),
    alRevisar: vi.fn(),
    abierta: null,
    alAbrir: vi.fn(),
    seleccionada: null,
    alVerEnTexto: vi.fn(),
    alVerEvidencia: vi.fn(),
    alCorregir: vi.fn(),
    alRestaurarPoder: vi.fn(),
    apoderadosEnTexto: new Set<string>(),
    umbralJev: 0.8,
    avisoEstado: null,
    abiertoMovil: false,
    onCerrarMovil: vi.fn(),
    pestana: "citas",
    alPestana: vi.fn(),
    apoderados: conDatos(null),
    ...extra,
  };
}

function patron(texto: string): RegExp {
  return new RegExp(texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s/g, "\\s"));
}

function grupo(nombre: string): HTMLElement {
  return screen.getByRole("region", { name: nombre });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PanelRevision: cabecera y grupos", () => {
  it("es el aside #bor-panel con el título y el resumen en cero", () => {
    const { container } = render(<PanelRevision {...props()} />);
    const aside = container.querySelector("aside#bor-panel");
    expect(aside).toBeTruthy();
    expect(aside?.getAttribute("aria-labelledby")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Antes de decidir" })).toBeTruthy();
    const resumen = container.querySelector(".bor-panel-resumen");
    expect(resumen?.textContent).toBe("Lleva 0 de 7 revisados. Nada de esto bloquea la decisión.");
    expect(resumen?.querySelector("b")?.textContent).toBe("0 de 7");
  });

  it("muestra los grupos por urgencia con lo que queda por revisar", () => {
    render(<PanelRevision {...props()} />);
    expect(within(grupo("Corregir antes de firmar")).getByText("2 de 2")).toBeTruthy();
    expect(within(grupo("Revisar")).getByText("3 de 3")).toBeTruthy();
    expect(within(grupo("Para tener en cuenta")).getByText("2 de 2")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Corregir antes de firmar", "Revisar", "Para tener en cuenta"]);
  });

  it("cuenta los revisados, pinta la barra segmentada y marca ✓ el grupo completo", () => {
    const revisados = new Set(["cita-c3", "alerta-ingesta-0", "jev-rol"]);
    const { container } = render(<PanelRevision {...props({ revisados })} />);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toContain("Lleva 3 de 7 revisados");
    const barra = screen.getByRole("progressbar", { name: "Puntos revisados" });
    expect(barra.getAttribute("aria-valuemin")).toBe("0");
    expect(barra.getAttribute("aria-valuemax")).toBe("7");
    expect(barra.getAttribute("aria-valuenow")).toBe("3");
    expect(barra.querySelectorAll("i")).toHaveLength(7);
    expect(barra.querySelectorAll("i.hecho")).toHaveLength(3);
    expect(within(grupo("Corregir antes de firmar")).getByText("✓")).toBeTruthy();
    expect(within(grupo("Para tener en cuenta")).getByText("1 de 2")).toBeTruthy();
  });

  it("no cuenta los comprobados entre los pendientes", () => {
    render(<PanelRevision {...props({ items: ITEMS.filter((i) => i.nivel === "ok") })} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("heading", { level: 3, name: "Revisar" })).toBeNull();
  });
});

describe("PanelRevision: filas", () => {
  it("el círculo de revisado tiene nombre, aria-pressed y llama a alRevisar con la clave", () => {
    const alRevisar = vi.fn();
    render(<PanelRevision {...props({ alRevisar, revisados: new Set(["cita-c2"]) })} />);
    const pendiente = screen.getByRole("button", { name: "Revisado: Sentencia c3" });
    expect(pendiente.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "Revisado: Sentencia c2" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(pendiente);
    expect(alRevisar).toHaveBeenCalledWith("cita-c3");
  });

  it("muestra origen, título y la línea de una sola línea; lineaCompleta usa la variante que envuelve", () => {
    const { container } = render(<PanelRevision {...props()} />);
    const fila = container.querySelector("li.n-mal");
    expect(fila?.querySelector(".bor-fila-tipo")?.textContent).toBe("Cita · Consideraciones");
    expect(fila?.querySelector(".bor-fila-titulo")?.textContent).toBe("Sentencia c3");
    expect(fila?.querySelector(".bor-fila-sub")?.textContent).toBe("No se encontró en la relatoría");
    expect(fila?.querySelector(".bor-fila-sub.completa")).toBeNull();
    const completa = screen.getByText("Se conservó la que se extrajo del expediente.");
    expect(completa.className).toContain("completa");
  });

  it("no pinta la línea cuando es null y no hace expandible la fila sin detalle", () => {
    const { container } = render(<PanelRevision {...props()} />);
    const sinDetalle = [...container.querySelectorAll("li")].find((li) => li.textContent?.includes("Hubo un error"));
    expect(sinDetalle?.querySelector(".bor-fila-sub")).toBeNull();
    expect(sinDetalle?.querySelector("button[aria-expanded]")).toBeNull();
    expect(sinDetalle?.textContent).toContain(ARCHIVO_LARGO);
  });

  it("la fila con detalle es un botón expandible que llama a alAbrir y se cierra con la misma clave", () => {
    const alAbrir = vi.fn();
    const { rerender } = render(<PanelRevision {...props({ alAbrir })} />);
    const boton = screen.getByRole("button", { name: /Sentencia c3/, expanded: false });
    fireEvent.click(boton);
    expect(alAbrir).toHaveBeenCalledWith("cita-c3");
    rerender(<PanelRevision {...props({ alAbrir, abierta: "cita-c3" })} />);
    expect(screen.getByRole("button", { name: /Sentencia c3/, expanded: true })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Sentencia c3/, expanded: true }));
    expect(alAbrir).toHaveBeenLastCalledWith(null);
  });

  it("solo abre una fila: el detalle de las demás no se pinta", () => {
    render(<PanelRevision {...props({ abierta: "cita-c3" })} />);
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(1);
    expect(screen.queryByText("Fragmento de la cita c2")).toBeNull();
  });

  it("al abrir una fila deja de repetirse la línea resumen", () => {
    render(<PanelRevision {...props({ abierta: "cita-c3" })} />);
    expect(screen.queryByText("No se encontró en la relatoría", { selector: ".bor-fila-sub" })).toBeNull();
  });

  it("la fila de la cita seleccionada lleva bor-fila-activa", () => {
    const { container } = render(<PanelRevision {...props({ seleccionada: { tipo: "cita", id: "c2" } })} />);
    const activas = container.querySelectorAll(".bor-fila-activa");
    expect(activas).toHaveLength(1);
    expect(activas[0]?.textContent).toContain("Sentencia c2");
  });
});

describe("PanelRevision: detalle por tipo", () => {
  it("cita rechazada: fragmento, cobertura sin dato, motivos y Ver en el texto, sin enlace a la relatoría", () => {
    const alVerEnTexto = vi.fn();
    const { container } = render(<PanelRevision {...props({ abierta: "cita-c3", alVerEnTexto })} />);
    expect(screen.getByText("Fragmento de la cita c3").tagName).toBe("Q");
    expect(container.querySelector(".bor-medidor")?.textContent).toContain("—");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(expect.arrayContaining(["No se encontró en la relatoría.", "Revise el número."]));
    expect(screen.queryByRole("link", { name: /relatoría/ })).toBeNull();
    const ver = screen.getByRole("button", { name: /Ver en el texto/ });
    fireEvent.click(ver);
    expect(alVerEnTexto).toHaveBeenCalledWith({ tipo: "cita", id: "c3" }, expect.any(HTMLElement));
  });

  it("cita con alerta y url: no enlaza a la relatoría porque no está verificada", () => {
    render(<PanelRevision {...props({ abierta: "cita-c2" })} />);
    expect(screen.getByText(patron(porcentaje(0.61)))).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("cita verificada con url: enlace a la relatoría en pestaña nueva y cobertura", () => {
    const { container } = render(<PanelRevision {...props({ abierta: "cita-c1" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Comprobado/ }));
    const enlace = screen.getByRole("link", { name: /Abrir en la relatoría/ });
    expect(enlace.getAttribute("href")).toBe(C1.url);
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
    expect(enlace.textContent).toContain("se abre en una pestaña nueva");
    expect(container.querySelector(".bor-medidor")?.textContent).toContain(porcentaje(0.97));
    expect(container.querySelector(".bor-motivos")).toBeNull();
  });

  it("cita verificada sin url: sin enlace", () => {
    render(<PanelRevision {...props({ abierta: "cita-c4" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Comprobado/ }));
    expect(screen.getByRole("button", { name: /Ver en el texto/ })).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("Jev que difiere: las dos lecturas, el motivo y la nota del umbral", () => {
    render(<PanelRevision {...props({ abierta: "jev-sentido" })} />);
    expect(screen.getByText("El borrador dice")).toBeTruthy();
    expect(screen.getByText("Niega el amparo", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText("Jev entiende esa frase como «Niega» (90 %).")).toBeTruthy();
    expect(screen.getByText("Jev lee en el expediente")).toBeTruthy();
    expect(screen.getByText("Concede el amparo", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText(patron(`${porcentaje(0.87)} de confianza`))).toBeTruthy();
    expect(screen.getByText(FILA_DIFIERE.motivo as string).className).toContain("alerta");
    expect(screen.getByText(patron(`Solo compara con al menos ${porcentaje(0.8)} de confianza`))).toBeTruthy();
  });

  it("Jev sin comparar: muestra la explicación sin el tono de alerta", () => {
    render(<PanelRevision {...props({ abierta: "jev-rol" })} />);
    expect(screen.getByText("Jev no pudo leer el escrito.").className).not.toContain("alerta");
  });

  it("Jev sin dato ni umbral: usa Sin dato y Sin lectura y omite la frase del umbral", () => {
    render(<PanelRevision {...props({ abierta: "jev-rol", umbralJev: undefined })} />);
    expect(screen.getByText("Sin dato", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText("Sin lectura", { selector: "strong" })).toBeTruthy();
    expect(screen.queryByText(/Solo compara/)).toBeNull();
    expect(screen.getByText(/Jev leyó por su cuenta/)).toBeTruthy();
  });

  it("archivo: el nombre largo va en un code y la nota debajo", () => {
    const { container } = render(<PanelRevision {...props({ abierta: "alerta-ingesta-1" })} />);
    const code = container.querySelector("code.bor-archivo");
    expect(code?.textContent).toBe(ARCHIVO_LARGO);
    expect(screen.getByText(/Se le entregaron los primeros 120.000 caracteres/)).toBeTruthy();
  });

  it("comparar: listas en viñetas y un valor largo de Python en un solo bloque", () => {
    const { container } = render(<PanelRevision {...props({ abierta: "alerta-metadatos-0" })} />);
    expect(screen.getByText("Extraído del expediente · se conservó")).toBeTruthy();
    expect(screen.getByText("Leído por el modelo")).toBeTruthy();
    const lista = container.querySelector(".bor-comparar ul");
    expect([...(lista?.querySelectorAll("li") ?? [])].map((li) => li.textContent)).toEqual(["Empresa A", "Empresa B"]);
    expect(screen.getByText(LISTA_LARGA, { selector: "strong" })).toBeTruthy();
  });
});

describe("PanelRevision: comprobado", () => {
  it("está plegado por defecto y se despliega con aria-expanded", () => {
    render(<PanelRevision {...props()} />);
    const boton = screen.getByRole("button", { name: /Comprobado/ });
    expect(boton.getAttribute("aria-expanded")).toBe("false");
    expect(boton.textContent).toContain("3");
    expect(screen.queryByText("Sentencia c1")).toBeNull();
    fireEvent.click(boton);
    expect(boton.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Sentencia c1")).toBeTruthy();
    expect(screen.getByText("Otro dato")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Revisado: Sentencia c1" })).toBeNull();
    fireEvent.click(boton);
    expect(screen.queryByText("Sentencia c1")).toBeNull();
  });

  it("no aparece si no hay comprobados", () => {
    render(<PanelRevision {...props({ items: ITEMS.filter((i) => i.nivel !== "ok") })} />);
    expect(screen.queryByRole("button", { name: /Comprobado/ })).toBeNull();
  });
});

describe("PanelRevision: vacío y aviso", () => {
  it("sin pendientes dice que no hay nada pendiente", () => {
    const { container } = render(<PanelRevision {...props({ items: ITEMS.filter((i) => i.nivel === "ok") })} />);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("Nada pendiente en lo que el sistema pudo comprobar.");
    expect(screen.getByText("Todo salió bien")).toBeTruthy();
  });

  it("sin alertas leídas no afirma que Jev coincida", () => {
    render(<PanelRevision {...props({ items: ITEMS.filter((i) => i.nivel === "ok"), alertasLeidas: false })} />);
    expect(screen.queryByText("Todo salió bien")).toBeNull();
    expect(screen.queryByText(/Jev coincide/)).toBeNull();
    expect(screen.getByText("Citas sin objeciones")).toBeTruthy();
  });

  it("sin ningún ítem sigue mostrándose completo", () => {
    render(<PanelRevision {...props({ items: [] })} />);
    expect(screen.getByText("Nada pendiente en lo que el sistema pudo comprobar.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Comprobado/ })).toBeNull();
  });

  it("muestra el aviso del estado bajo la cabecera", () => {
    const aviso = "No se pudieron leer las alertas del caso; se muestran solo las citas.";
    const { container } = render(<PanelRevision {...props({ avisoEstado: aviso })} />);
    expect(screen.getByText(aviso)).toBeTruthy();
    expect(container.querySelector(".bor-panel-cabeza")?.nextElementSibling?.textContent).toBe(aviso);
  });

  it("sin aviso no pinta el bloque", () => {
    const { container } = render(<PanelRevision {...props()} />);
    expect(container.querySelector(".bor-panel-aviso")).toBeNull();
  });
});

describe("PanelRevision: cajón", () => {
  it("lleva la clase abierto solo cuando abiertoMovil", () => {
    const { container, rerender } = render(<PanelRevision {...props()} />);
    expect(container.querySelector("#bor-panel")?.classList.contains("abierto")).toBe(false);
    rerender(<PanelRevision {...props({ abiertoMovil: true })} />);
    expect(container.querySelector("#bor-panel")?.classList.contains("abierto")).toBe(true);
  });

  it("el botón Cerrar la revisión llama a onCerrarMovil", () => {
    const onCerrarMovil = vi.fn();
    render(<PanelRevision {...props({ onCerrarMovil })} />);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar la revisión" }));
    expect(onCerrarMovil).toHaveBeenCalledOnce();
  });
});

describe("PanelRevision: desplazamiento a la fila activa", () => {
  const ancho = window.innerWidth;
  const caja = (top: number, alto: number) => ({ top, bottom: top + alto, height: alto, left: 0, right: 300, width: 300, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  let filaActiva = caja(0, 0);

  // jsdom no maqueta: el cuerpo del panel ocupa de 100 a 600 px y la fila activa, lo que diga cada prueba.
  beforeEach(() => {
    filaActiva = caja(0, 0);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("bor-panel-cuerpo")) return caja(100, 500);
      if (this.classList.contains("bor-fila-activa")) return filaActiva;
      return caja(0, 0);
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: ancho });
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    vi.restoreAllMocks();
  });

  function seleccionar(fila: DOMRect, inicial = 0) {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const ventana = vi.spyOn(window, "scrollBy").mockImplementation(() => undefined);
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    const { rerender, container } = render(<PanelRevision {...props()} />);
    const cuerpo = container.querySelector(".bor-panel-cuerpo") as HTMLElement;
    cuerpo.scrollTop = inicial;
    filaActiva = fila;
    rerender(<PanelRevision {...props({ seleccionada: { tipo: "cita", id: "c2" } })} />);
    // Nunca scrollIntoView ni la ventana: deshacerían el desplazamiento hacia la marca o el del detalle.
    expect(scroll).not.toHaveBeenCalled();
    expect(ventana).not.toHaveBeenCalled();
    return cuerpo.scrollTop;
  }

  it("desde 1024 px baja el cuerpo del panel lo justo para ver una fila que queda debajo", () => {
    expect(seleccionar(caja(640, 60), 40)).toBe(40 + (700 - 600 + 8));
  });

  it("sube el cuerpo del panel si la fila quedó arriba", () => {
    expect(seleccionar(caja(50, 60), 200)).toBe(200 - (100 - 50 + 8));
  });

  it("no mueve nada si la fila ya se ve entera", () => {
    expect(seleccionar(caja(300, 60), 120)).toBe(120);
  });

  it("una fila más alta que el panel (un abogado con su evidencia) se muestra desde su nombre", () => {
    expect(seleccionar(caja(400, 700), 0)).toBe(400 - 100 - 8);
  });

  it("bajo 1024 px no desplaza", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 });
    filaActiva = caja(640, 60);
    const { container } = render(<PanelRevision {...props({ seleccionada: { tipo: "cita", id: "c2" } })} />);
    expect((container.querySelector(".bor-panel-cuerpo") as HTMLElement).scrollTop).toBe(0);
    expect(scroll).not.toHaveBeenCalled();
  });

  it("no lanza con una selección que no tiene fila", () => {
    expect(() => render(<PanelRevision {...props({ seleccionada: { tipo: "cita", id: "no-existe" } })} />)).not.toThrow();
  });
});

function conDatos(datos: ApoderadosRespuesta | null, extra: Partial<PanelApoderados> = {}): PanelApoderados {
  return {
    datos,
    error: null,
    errorRevision: null,
    recargar: vi.fn(),
    subir: vi.fn(async () => {}),
    consultar: vi.fn(async () => {}),
    ajustar: vi.fn(async () => {
      throw new Error("sin ajuste");
    }),
    identificar: vi.fn(async () => {}),
    identificando: false,
    errorIdentificacion: null,
    ...extra,
  };
}

function conApoderados(datos: ApoderadosRespuesta = structuredClone(APODERADOS_BORRADOR), extra: Partial<PropsPanelRevision> = {}): PropsPanelRevision {
  return props({ items: [...ITEMS, ...itemsApoderados(datos)], apoderados: conDatos(datos), ...extra });
}

function ConPestanas(extra: Partial<PropsPanelRevision>) {
  const [pestana, setPestana] = useState<Pestana>("citas");
  return <PanelRevision {...conApoderados(undefined, extra)} pestana={pestana} alPestana={setPestana} />;
}

const pestana = (nombre: RegExp) => screen.getByRole("tab", { name: nombre });

describe("PanelRevision: pestañas", () => {
  it("es un tablist con Citas y Apoderados, sus cuentas y un tabpanel enlazado", () => {
    render(<PanelRevision {...conApoderados()} />);
    const lista = screen.getByRole("tablist", { name: "Qué revisar" });
    expect(within(lista).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Citas 10", "Apoderados 3, con apoderados no verificados"]);
    const citas = pestana(/^Citas/);
    expect(citas.getAttribute("aria-selected")).toBe("true");
    expect(citas.tabIndex).toBe(0);
    expect(pestana(/^Apoderados/).getAttribute("aria-selected")).toBe("false");
    expect(pestana(/^Apoderados/).tabIndex).toBe(-1);
    const panel = screen.getByRole("tabpanel");
    expect(panel.id).toBe(citas.getAttribute("aria-controls"));
    expect(panel.getAttribute("aria-labelledby")).toBe(citas.id);
    expect(document.getElementById(pestana(/^Apoderados/).getAttribute("aria-controls") ?? "")?.hidden).toBe(true);
  });

  it("conserva el título «Antes de decidir» y el aside etiquetado en ambas pestañas", () => {
    const { container } = render(<ConPestanas />);
    fireEvent.click(pestana(/^Apoderados/));
    expect(container.querySelector("aside#bor-panel")?.getAttribute("aria-labelledby")).toBe("bor-panel-titulo");
    expect(screen.getByRole("heading", { level: 2, name: "Antes de decidir" })).toBeTruthy();
  });

  it("las flechas, Inicio y Fin cambian de pestaña y mueven el foco", () => {
    render(<ConPestanas />);
    const citas = pestana(/^Citas/);
    citas.focus();
    fireEvent.keyDown(citas, { key: "ArrowRight" });
    expect(pestana(/^Apoderados/).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(pestana(/^Apoderados/));
    expect(screen.getByRole("heading", { level: 3, name: "No verificados" })).toBeTruthy();
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowRight" });
    expect(document.activeElement).toBe(pestana(/^Citas/));
    expect(pestana(/^Citas/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(pestana(/^Apoderados/));
    fireEvent.keyDown(document.activeElement as Element, { key: "Home" });
    expect(document.activeElement).toBe(pestana(/^Citas/));
    expect(pestana(/^Citas/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(document.activeElement as Element, { key: "End" });
    expect(pestana(/^Apoderados/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(document.activeElement as Element, { key: "Enter" });
    expect(pestana(/^Apoderados/).getAttribute("aria-selected")).toBe("true");
  });

  it("la pestaña de citas solo lista citas y alertas; la de apoderados, los abogados", () => {
    render(<ConPestanas />);
    expect(screen.queryByText("CARLOS EDUARDO PINEDA RUIZ")).toBeNull();
    expect(screen.getByText("Sentencia c3")).toBeTruthy();
    fireEvent.click(pestana(/^Apoderados/));
    expect(screen.queryByText("Sentencia c3")).toBeNull();
    expect(screen.getByText("CARLOS EDUARDO PINEDA RUIZ")).toBeTruthy();
  });
});

describe("PanelRevision: apoderados", () => {
  const enApoderados = (datos?: ApoderadosRespuesta, extra: Partial<PropsPanelRevision> = {}) =>
    render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados", ...extra })} />);

  it("agrupa en No verificados, Por revisar, Verificados y Sin apoderado", () => {
    enApoderados();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["No verificados", "Por revisar", "Verificados", "Sin apoderado"]);
    expect(within(grupo("No verificados")).getByText("CARLOS EDUARDO PINEDA RUIZ")).toBeTruthy();
    expect(within(grupo("No verificados")).getByText("1 de 1")).toBeTruthy();
    expect(within(grupo("Por revisar")).getByText("LUIS FERNANDO OSPINA ARANGO")).toBeTruthy();
    expect(within(grupo("Verificados")).getByText("ANDREA PAOLA GIRALDO MONTOYA")).toBeTruthy();
    const sin = grupo("Sin apoderado");
    expect(within(sin).getByText("SUPERINTENDENCIA NACIONAL DE SALUD")).toBeTruthy();
    expect(within(sin).getByText("Accionada")).toBeTruthy();
    expect(within(sin).getByText("Actúa por su representante legal o por un funcionario. No hay abogado que verificar.")).toBeTruthy();
    expect(within(sin).queryByRole("button")).toBeNull();
  });

  it("la fila cerrada de quien necesita que se suba el certificado lo dice con un chip; abierta, muestra la ayuda", () => {
    const { container, rerender } = enApoderados();
    const fila = container.querySelector<HTMLElement>('li[data-clave="apoderado-ap-81be04c5f2"]');
    const sub = fila?.querySelector(".bor-fila-sub");
    expect(sub?.querySelector(".chip.alerta")?.textContent).toBe("Necesita su ayuda");
    expect(sub?.textContent).toBe("Necesita su ayuda Tarjeta sin consultar · poder (Doc. 1a-002, p. 6)");
    expect(container.querySelectorAll(".bor-fila-sub .chip")).toHaveLength(1);
    rerender(<PanelRevision {...conApoderados(undefined, { pestana: "apoderados", abierta: "apoderado-ap-81be04c5f2" })} />);
    expect(fila?.querySelector(".bor-fila-sub")).toBeNull();
    expect(within(fila as HTMLElement).getByRole("group", { name: /Subir el certificado de vigencia/ })).toBeTruthy();
  });

  it("resume los apoderados por estado y pinta la barra de estados", () => {
    const { container } = enApoderados();
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("3 apoderados · 1 verificado · 1 por revisar · 1 no verificado");
    expect(container.querySelector(".bor-panel-resumen b")?.textContent).toBe("3 apoderados");
    expect(screen.queryByRole("progressbar")).toBeNull();
    const barra = container.querySelector(".bor-progreso[aria-hidden=true]");
    expect([...(barra?.querySelectorAll("i") ?? [])].map((i) => i.className)).toEqual(["s-mal", "s-alerta", "s-ok"]);
  });

  it("el círculo de revisado de un abogado llama a alRevisar con su clave; el verificado no tiene", () => {
    const alRevisar = vi.fn();
    enApoderados(undefined, { alRevisar });
    fireEvent.click(screen.getByRole("button", { name: "Revisado: CARLOS EDUARDO PINEDA RUIZ" }));
    expect(alRevisar).toHaveBeenCalledWith("apoderado-ap-c47d19e6a8");
    expect(screen.queryByRole("button", { name: "Revisado: ANDREA PAOLA GIRALDO MONTOYA" })).toBeNull();
  });

  it("muestra la evidencia del abogado al abrir la fila, con la cédula enmascarada", () => {
    const { container } = enApoderados(undefined, { abierta: "apoderado-ap-c47d19e6a8" });
    const fila = screen.getByRole("button", { name: /CARLOS EDUARDO PINEDA RUIZ/, expanded: true }).closest("li") as HTMLElement;
    expect(within(fila).getByText(/otorgo poder especial al doctor CARLOS EDUARDO PINEDA RUIZ/).tagName).toBe("Q");
    expect(within(fila).getByText("No vigente", { selector: "strong" })).toBeTruthy();
    expect(within(fila).getByText(/^T\.P\. 097\.551 · C\.C\. 16\.•••\.•40 · consultado/)).toBeTruthy();
    expect(within(fila).getByText("Poder hallado", { selector: "strong" })).toBeTruthy();
    expect(within(fila).getByText("La tarjeta profesional 97551 figura como «SUSPENDIDA» en el certificado N.° 4471388.").closest("ul")?.className).toContain("rechazada");
    expect(container.textContent).not.toContain("16000040");
  });

  it("«Poder · p. N» abre el visor en la página del poder y «Ver en el texto» busca su nombre", () => {
    const alVerEvidencia = vi.fn();
    const alVerEnTexto = vi.fn();
    enApoderados(undefined, { abierta: "apoderado-ap-c47d19e6a8", alVerEvidencia, alVerEnTexto, apoderadosEnTexto: new Set(["ap-c47d19e6a8"]) });
    const fila = screen.getByRole("button", { name: /CARLOS EDUARDO PINEDA RUIZ/, expanded: true }).closest("li") as HTMLElement;
    expect(within(fila).queryByRole("link", { name: /Abrir el poder/ })).toBeNull();
    const poder = within(fila).getByRole("button", { name: "Poder · p. 5" });
    fireEvent.click(poder);
    expect(alVerEvidencia).toHaveBeenCalledWith(
      {
        apoderado: "ap-c47d19e6a8",
        evidencia: expect.objectContaining({ doc_id: "1a-011", pagina: 5 }),
        titulo: "Poder especial · Doc. 1a-011",
        subtitulo: "Evidencia de que CARLOS EDUARDO PINEDA RUIZ representa a CLÍNICA SANTA AURORA S.A.S.",
      },
      poder,
    );
    const ver = within(fila).getByRole("button", { name: /Ver en el texto/ });
    expect((ver as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(ver);
    expect(alVerEnTexto).toHaveBeenCalledWith({ tipo: "apoderado", id: "ap-c47d19e6a8" }, ver);
  });

  it("«Ver en el texto» queda deshabilitado si el nombre no está marcado en el borrador", () => {
    enApoderados(undefined, { abierta: "apoderado-ap-c47d19e6a8" });
    const ver = screen.getByRole("button", { name: /Ver en el texto/ }) as HTMLButtonElement;
    expect(ver.disabled).toBe(true);
    expect(ver.title).toBe("Su nombre no está marcado en el texto del borrador.");
  });

  it("con certificado guardado ofrece «Certificado PDF» en una pestaña nueva", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const url = "/api/casos/caso-1/apoderados/ap-c47d19e6a8/certificado";
    datos.apoderados = datos.apoderados.map((a) => (a.id === "ap-c47d19e6a8" ? { ...a, vigencia: { ...a.vigencia, certificado_url: url } } : a));
    enApoderados(datos, { abierta: "apoderado-ap-c47d19e6a8" });
    const enlace = screen.getByRole("link", { name: /Certificado PDF/ });
    expect(enlace.getAttribute("href")).toBe(url);
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("sin poder ofrece abrir su propio escrito en el visor", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const mencion = { ...datos.apoderados[2]!.poder.mencion!, doc_id: "1b-006", pagina: 1 };
    datos.apoderados = datos.apoderados.map((a) =>
      a.id === "ap-81be04c5f2" ? { ...a, poder: { ...a.poder, estado: "sin_poder" as const, evidencia: null, cadena: null, mencion } } : a,
    );
    const alVerEvidencia = vi.fn();
    enApoderados(datos, { abierta: "apoderado-ap-81be04c5f2", alVerEvidencia });
    fireEvent.click(screen.getByRole("button", { name: "Su escrito · p. 1" }));
    expect(alVerEvidencia).toHaveBeenCalledWith(expect.objectContaining({ apoderado: "ap-81be04c5f2", titulo: "Escrito de LUIS FERNANDO OSPINA ARANGO · Doc. 1b-006" }), expect.any(HTMLElement));
  });

  it("si la tarjeta necesita ayuda muestra cómo subir el certificado y lo sube para ese abogado", async () => {
    const subir = vi.fn(async () => {});
    const datos = structuredClone(APODERADOS_BORRADOR);
    enApoderados(datos, { abierta: "apoderado-ap-81be04c5f2", apoderados: conDatos(datos, { subir }) });
    const fila = screen.getByRole("button", { name: /LUIS FERNANDO OSPINA ARANGO/, expanded: true }).closest("li") as HTMLElement;
    expect(within(fila).getByRole("link", { name: "Abrir Certificado de vigencia" })).toBeTruthy();
    const zona = within(fila).getByRole("group", { name: "Subir el certificado de vigencia de LUIS FERNANDO OSPINA ARANGO" });
    const archivo = new File(["%PDF-1.7"], "CV_RNA-TPA.pdf", { type: "application/pdf" });
    const entrada = zona.querySelector("input[type=file]") as HTMLInputElement;
    Object.defineProperty(entrada, "files", { configurable: true, value: [archivo] });
    fireEvent.change(entrada);
    expect(subir).toHaveBeenCalledWith("ap-81be04c5f2", archivo);
  });

  it("con la tarjeta no vigente deja reemplazar el certificado; vigente o sin edición, no", () => {
    const rojo = enApoderados(undefined, { abierta: "apoderado-ap-c47d19e6a8" });
    expect(screen.getByRole("group", { name: "Subir el certificado de vigencia de CARLOS EDUARDO PINEDA RUIZ" })).toBeTruthy();
    rojo.unmount();
    const verde = enApoderados(undefined, { abierta: "apoderado-ap-3f9c2a71d0" });
    expect(screen.queryByRole("link", { name: "Abrir Certificado de vigencia" })).toBeNull();
    verde.unmount();
    enApoderados({ ...structuredClone(APODERADOS_BORRADOR), editable: false }, { abierta: "apoderado-ap-81be04c5f2" });
    expect(screen.queryByRole("link", { name: "Abrir Certificado de vigencia" })).toBeNull();
  });

  it("avisa si la revisión anterior venció porque cambió la evidencia", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const rojo = datos.apoderados.find((a) => a.id === "ap-c47d19e6a8");
    if (rojo) rojo.revision_vencida = true;
    enApoderados(datos, { abierta: "apoderado-ap-c47d19e6a8" });
    expect(screen.getByText(/la evidencia cambió: revíselo de nuevo/)).toBeTruthy();
  });

  it("si el caso ya no espera la decisión deshabilita la revisión y lo explica", () => {
    const datos = { ...structuredClone(APODERADOS_BORRADOR), editable: false };
    enApoderados(datos);
    expect((screen.getByRole("button", { name: "Revisado: CARLOS EDUARDO PINEDA RUIZ" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("La revisión de los apoderados solo se puede cambiar mientras el caso espera la decisión.")).toBeTruthy();
  });

  it("las alertas del nodo de apoderados van en su propio grupo con el círculo de revisado", () => {
    const alerta: ItemRevision = {
      clave: "alerta-apoderados-0",
      marca: null,
      grupo: "apoderados",
      nivel: "alerta",
      origen: "Apoderados",
      titulo: "Según el modelo, la Clínica actúa por medio de abogado, pero no se pudo comprobar.",
      linea: null,
      lineaCompleta: false,
      detalle: null,
    };
    const datos = structuredClone(APODERADOS_BORRADOR);
    render(<PanelRevision {...props({ pestana: "apoderados", items: [...itemsApoderados(datos), alerta], apoderados: conDatos(datos) })} />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "No verificados",
      "Por revisar",
      "Avisos de la identificación",
      "Verificados",
      "Sin apoderado",
    ]);
    expect(within(grupo("Avisos de la identificación")).getByRole("button", { name: /^Revisado: Según el modelo/ })).toBeTruthy();
  });

  it("caso sin identificación: lo dice en el resumen y en la pestaña, sin cuenta", () => {
    const datos: ApoderadosRespuesta = { ...structuredClone(APODERADOS_BORRADOR), identificacion: "no_disponible", apoderados: [], sin_apoderado: [], bloquea_decision: false };
    const { container } = enApoderados(datos);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("Identificación no disponible para este caso.");
    expect(screen.getByText("Identificación no disponible para este caso", { selector: "b" })).toBeTruthy();
    expect(pestana(/^Apoderados/).textContent).toBe("Apoderados");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("identificación fallida: lo dice y sugiere rehacer la apertura", () => {
    const datos: ApoderadosRespuesta = { ...structuredClone(APODERADOS_BORRADOR), identificacion: "fallida", apoderados: [], sin_apoderado: [], bloquea_decision: false };
    const { container } = enApoderados(datos);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("No se pudieron identificar los apoderados.");
    expect(screen.getByText(/Si pide rehacer la apertura/)).toBeTruthy();
  });

  it("mientras carga lo dice y si falla ofrece reintentar", () => {
    const recargar = vi.fn();
    const { rerender } = render(<PanelRevision {...props({ pestana: "apoderados", apoderados: conDatos(null) })} />);
    expect(screen.getAllByText("Cargando los apoderados…").length).toBeGreaterThan(0);
    rerender(<PanelRevision {...props({ pestana: "apoderados", apoderados: conDatos(null, { error: "Error 500", recargar }) })} />);
    expect(screen.getByText("No se pudo leer el estado de los apoderados", { selector: "b" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(recargar).toHaveBeenCalledOnce();
  });

  it("muestra el error de una revisión que no se guardó", () => {
    enApoderados(undefined, { apoderados: conDatos(structuredClone(APODERADOS_BORRADOR), { errorRevision: "El caso no está esperando la decisión." }) });
    expect(screen.getByText("No se pudo guardar la revisión", { selector: "b" }).closest("[role=alert]")?.textContent).toContain(
      "El caso no está esperando la decisión.",
    );
  });
});

describe("PanelRevision: bloqueo de la decisión", () => {
  it("con un apoderado no verificado sin revisar avisa y deja de decir que nada bloquea", () => {
    const alPestana = vi.fn();
    const { container } = render(<PanelRevision {...conApoderados(undefined, { alPestana })} />);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("Lleva 0 de 7 revisados.");
    const aviso = screen.getByRole("alert");
    expect(aviso.textContent).toContain("Un apoderado no pudo verificarse. Resuélvalo antes de aprobar el borrador.");
    expect(container.querySelector(".bor-tab .punto")).toBeTruthy();
    fireEvent.click(within(aviso).getByRole("button", { name: "Ver apoderados" }));
    expect(alPestana).toHaveBeenCalledWith("apoderados");
  });

  it("«Ver apoderados» desaparece al cambiar de pestaña y deja el foco en la pestaña Apoderados", () => {
    const { container } = render(<ConPestanas />);
    const aviso = screen.getByRole("alert");
    const boton = within(aviso).getByRole("button", { name: "Ver apoderados" });
    boton.focus();
    fireEvent.click(boton);
    expect(pestana(/^Apoderados/).getAttribute("aria-selected")).toBe("true");
    expect(within(screen.getByRole("alert")).queryByRole("button", { name: "Ver apoderados" })).toBeNull();
    expect(document.activeElement).toBe(pestana(/^Apoderados/));
    expect(container.querySelector("aside#bor-panel")?.contains(document.activeElement)).toBe(true);
  });

  it("en plural con varios y sin el botón cuando ya está en la pestaña", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    datos.apoderados = datos.apoderados.map((a) => ({ ...a, estado: "no_verificado", bloquea: true }));
    render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados" })} />);
    const aviso = screen.getByRole("alert");
    expect(aviso.textContent).toContain("3 apoderados no pudieron verificarse. Resuélvalos antes de aprobar el borrador.");
    expect(within(aviso).queryByRole("button")).toBeNull();
  });

  it("revisado el no verificado, vuelve a decir que nada bloquea", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    datos.apoderados = datos.apoderados.map((a) => ({ ...a, bloquea: false }));
    const { container } = render(<PanelRevision {...conApoderados(datos)} />);
    expect(container.querySelector(".bor-panel-resumen")?.textContent).toBe("Lleva 0 de 7 revisados. Nada de esto bloquea la decisión.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.querySelector(".bor-tab .punto")).toBeNull();
  });
});

describe("panel.css: nada se desborda en horizontal", () => {
  const css = readFileSync(join(import.meta.dirname, "panel.css"), "utf8");

  it("toda pista fr va dentro de minmax(0, …)", () => {
    const plantillas = [...css.matchAll(/grid-template-columns:\s*([^;}]+)/g)].map((m) => m[1] as string);
    expect(plantillas.length).toBeGreaterThan(0);
    for (const plantilla of plantillas) {
      expect(plantilla.replace(/minmax\(0,\s*[^)]+\)/g, ""), plantilla).not.toMatch(/\bfr\b|\dfr/);
    }
  });

  it("los textos largos se parten y el cuerpo solo desplaza en vertical", () => {
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/\.bor-panel-cuerpo\s*\{[^}]*overflow-y:\s*auto[^}]*overflow-x:\s*hidden/);
  });

  it("limita la altura de escritorio con la barra superior y la inferior", () => {
    expect(css).toContain("max-height: calc(100vh - 3.5rem - var(--bor-dock, 4.75rem) - 2rem)");
  });

  it("no depende de variables que no existen en los tokens", () => {
    const tokens = readFileSync(join(import.meta.dirname, "../../estilos/tokens.css"), "utf8");
    const usadas = new Set([...css.matchAll(/var\(--([\w-]+)/g)].map((m) => m[1] as string));
    for (const nombre of usadas) {
      if (nombre === "bor-dock") continue;
      expect(tokens, nombre).toContain(`--${nombre}:`);
    }
  });
});

describe("PanelRevision: consulta automática de la vigencia", () => {
  const ID_AMBAR = "ap-81be04c5f2";
  const ID_ROJO = "ap-c47d19e6a8";
  const conConsulta = (consulta: Partial<ApoderadosRespuesta["consulta"]>, cambiar?: (d: ApoderadosRespuesta) => void): ApoderadosRespuesta => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    datos.consulta = { ...datos.consulta, ...consulta };
    cambiar?.(datos);
    return datos;
  };
  const fase = (id: string, f: "en_cola" | "consultando") => (d: ApoderadosRespuesta) => {
    const ap = d.apoderados.find((a) => a.id === id);
    if (ap) {
      ap.fase = f;
      ap.vigencia.fase = f;
    }
  };
  const enApoderados = (datos: ApoderadosRespuesta, extra: Partial<PropsPanelRevision> = {}) =>
    render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados", ...extra })} />);
  const aviso = () => screen.getByRole("note", { name: "Consulta automática de la vigencia" });

  it("con la extensión conectada explica que la consulta sale del navegador, como en la mesa Consulta", () => {
    enApoderados(conConsulta({ extension: "conectada", activa: true }, fase(ID_AMBAR, "consultando")));
    expect(within(aviso()).getByText("Consulta desde su navegador", { selector: "b" })).toBeTruthy();
    expect(within(aviso()).getByText("Extensión conectada").className).toBe("chip ok");
    expect(aviso().textContent).toContain("La Rama Judicial solo responde a conexiones desde Colombia, así que cada consulta sale de su navegador, una a la vez.");
    expect(within(aviso()).queryByRole("link")).toBeNull();
  });

  it.each([
    ["desactualizada", "Extensión desactualizada", "Actualizar la extensión"],
    ["no_conectada", "Extensión no conectada", "Instalar la extensión"],
  ] as const)("con la extensión %s lo dice y enlaza a su configuración", (extension, chip, enlace) => {
    enApoderados(conConsulta({ extension }));
    expect(within(aviso()).getByText(chip).className).toBe("chip alerta");
    expect(within(aviso()).getByRole("link", { name: enlace }).getAttribute("href")).toBe("#/configuracion/extension");
    expect(aviso().textContent).toContain("suba el certificado a mano");
  });

  it("consulta directa y simulada tienen su propio aviso", () => {
    const { unmount } = enApoderados(conConsulta({ modo: "directa" }));
    expect(within(aviso()).getByText("Consulta desde el servidor", { selector: "b" })).toBeTruthy();
    expect(within(aviso()).queryByText(/Extensión/)).toBeNull();
    unmount();
    enApoderados(conConsulta({ modo: "fake" }));
    expect(within(aviso()).getByText("Consulta simulada", { selector: "b" })).toBeTruthy();
    expect(within(aviso()).getByText("Modo de prueba").className).toBe("chip info");
    expect(aviso().textContent).toContain("los certificados son inventados");
  });

  it("con la consulta apagada solo deja una nota discreta y no ofrece reintentarla", () => {
    enApoderados(conConsulta({ modo: "apagada", extension: "conectada" }), { abierta: `apoderado-${ID_AMBAR}` });
    expect(screen.queryByRole("note", { name: "Consulta automática de la vigencia" })).toBeNull();
    expect(screen.getByText(/La consulta automática de la vigencia está desactivada en esta instalación/).className).toContain("bor-nota");
    expect(screen.queryByRole("button", { name: "Reintentar consulta automática" })).toBeNull();
    expect(screen.getByRole("group", { name: /Subir el certificado de vigencia/ })).toBeTruthy();
  });

  it("si nada está pendiente no hay aviso", () => {
    const datos = conConsulta({ extension: "no_conectada" }, (d) => {
      d.apoderados = d.apoderados.filter((a) => a.vigencia.fase === "listo");
    });
    enApoderados(datos);
    expect(screen.queryByRole("note", { name: "Consulta automática de la vigencia" })).toBeNull();
    const apagada = conConsulta({ modo: "apagada" }, (d) => {
      d.apoderados = d.apoderados.filter((a) => a.vigencia.fase === "listo");
    });
    cleanup();
    enApoderados(apagada);
    expect(screen.queryByText(/está desactivada/)).toBeNull();
  });

  it("anuncia la pausa de la Rama Judicial con la hora del reintento", () => {
    const hasta = new Date(2026, 10, 17, 15, 42).toISOString();
    enApoderados(conConsulta({ extension: "conectada", pausa_hasta: hasta }));
    expect(within(aviso()).getByText("La Rama Judicial no respondió; se reintenta a las 15:42.")).toBeTruthy();
  });

  it("el progreso de la consulta va en el resumen, en una región de estado", () => {
    const { container } = enApoderados(conConsulta({ extension: "conectada", activa: true }, fase(ID_AMBAR, "consultando")));
    const estado = container.querySelector(".bor-panel-resumen [role=status]");
    expect(estado?.textContent).toBe("2 de 3 listos · consultando la Rama Judicial");
  });

  it("la fila en cola lleva su chip y la que se consulta, el renglón con giro", () => {
    const datos = conConsulta({ extension: "conectada", activa: true }, (d) => {
      fase(ID_AMBAR, "en_cola")(d);
      fase(ID_ROJO, "consultando")(d);
    });
    const { container } = enApoderados(datos);
    const ambar = container.querySelector<HTMLElement>(`li[data-clave="apoderado-${ID_AMBAR}"]`) as HTMLElement;
    expect(ambar.querySelector(".bor-fila-sub .chip")?.textContent).toBe("En cola");
    expect(ambar.querySelector(".bor-fila-curso")).toBeNull();
    const rojo = container.querySelector<HTMLElement>(`li[data-clave="apoderado-${ID_ROJO}"]`) as HTMLElement;
    const curso = rojo.querySelector(".bor-fila-curso");
    expect(curso?.textContent).toBe("Consultando vigencia en la Rama Judicial…");
    expect(curso?.querySelector(".giro[aria-hidden=true]")).toBeTruthy();
    expect(rojo.querySelector(".bor-fila-sub .chip")).toBeNull();
  });

  it("«Reintentar consulta automática» de la fila fuerza la consulta de ese abogado", async () => {
    const consultar = vi.fn(async () => {});
    const datos = conConsulta({ extension: "conectada" });
    enApoderados(datos, { abierta: `apoderado-${ID_AMBAR}`, apoderados: conDatos(datos, { consultar }) });
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta automática" }));
    await waitFor(() => expect(consultar).toHaveBeenCalledWith([ID_AMBAR], true));
  });
});

describe("PanelRevision: el foco cuando el sondeo cambia la lista", () => {
  const ID_LUIS = "ap-81be04c5f2";
  const conLuisVigente = (datos: ApoderadosRespuesta): ApoderadosRespuesta => ({
    ...datos,
    apoderados: datos.apoderados.map((a) =>
      a.id === ID_LUIS ? { ...a, estado: "verificado", fase: "listo", motivos: [], vigencia: { ...a.vigencia, estado: "vigente", fase: "listo" } } : a,
    ),
  });
  const luis = (): HTMLElement => {
    const boton = document.querySelector<HTMLElement>(`li[data-clave="apoderado-${ID_LUIS}"] button.bor-fila-boton`);
    if (!boton) throw new Error("falta la fila");
    return boton;
  };

  it.each([false, true])("si el resultado mueve al abogado de grupo, el foco sigue en su fila (cajón: %s)", (abiertoMovil) => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const { rerender } = render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados", abiertoMovil })} />);
    const antes = luis();
    expect(within(grupo("Por revisar")).getByText("LUIS FERNANDO OSPINA ARANGO")).toBeTruthy();
    antes.focus();
    rerender(<PanelRevision {...conApoderados(conLuisVigente(datos), { pestana: "apoderados", abiertoMovil })} />);
    const ahora = luis();
    expect(ahora).not.toBe(antes);
    expect(within(grupo("Verificados")).getByText("LUIS FERNANDO OSPINA ARANGO")).toBeTruthy();
    expect(document.activeElement).toBe(ahora);
  });

  it("no le quita el foco a quien hizo clic en otra parte", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const { rerender } = render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados" })} />);
    luis().focus();
    fireEvent.pointerDown(document.body);
    luis().blur();
    rerender(<PanelRevision {...conApoderados(conLuisVigente(datos), { pestana: "apoderados" })} />);
    expect(document.activeElement).toBe(document.body);
  });
});

describe("PanelRevision: correcciones a mano y casos anteriores", () => {
  const ID_VERDE = "ap-3f9c2a71d0";
  const enApoderados = (datos: ApoderadosRespuesta = structuredClone(APODERADOS_BORRADOR), extra: Partial<PropsPanelRevision> = {}) =>
    render(<PanelRevision {...conApoderados(datos, { pestana: "apoderados", ...extra })} />);
  const correcciones = (nombre: string) => screen.getByRole("group", { name: `Corregir a mano lo cotejado de ${nombre}` });

  it("la fila abierta ofrece «No es correcto…» sobre el poder hallado y lo pide para ese abogado", () => {
    const alCorregir = vi.fn();
    enApoderados(undefined, { abierta: `apoderado-${ID_VERDE}`, alCorregir });
    const grupo = correcciones("ANDREA PAOLA GIRALDO MONTOYA");
    expect(within(grupo).getAllByRole("button").map((b) => b.textContent)).toEqual(["No es correcto…"]);
    const boton = within(grupo).getByRole("button", { name: "No es correcto…" });
    fireEvent.click(boton);
    expect(alCorregir).toHaveBeenCalledWith({ tipo: "descartar", apoderado: ID_VERDE }, boton);
  });

  it("con el poder descartado y sin cédula ofrece señalarlo, deshacer el descarte y escribir la cédula", () => {
    const alCorregir = vi.fn();
    const alRestaurarPoder = vi.fn();
    const datos = structuredClone(APODERADOS_BORRADOR);
    const verde = datos.apoderados.find((a) => a.id === ID_VERDE);
    if (!verde) throw new Error("falta el apoderado");
    verde.poder = { ...verde.poder, estado: "descartado", evidencia: null };
    verde.cedula = null;
    enApoderados(datos, { abierta: `apoderado-${ID_VERDE}`, alCorregir, alRestaurarPoder });
    const grupo = correcciones("ANDREA PAOLA GIRALDO MONTOYA");
    expect(within(grupo).getAllByRole("button").map((b) => b.textContent)).toEqual(["Señalar el poder a mano…", "Deshacer el descarte", "Escribir la cédula"]);
    fireEvent.click(within(grupo).getByRole("button", { name: "Señalar el poder a mano…" }));
    expect(alCorregir).toHaveBeenLastCalledWith({ tipo: "poder", apoderado: ID_VERDE }, expect.any(HTMLElement));
    fireEvent.click(within(grupo).getByRole("button", { name: "Escribir la cédula" }));
    expect(alCorregir).toHaveBeenLastCalledWith({ tipo: "cedula", apoderado: ID_VERDE }, expect.any(HTMLElement));
    fireEvent.click(within(grupo).getByRole("button", { name: "Deshacer el descarte" }));
    expect(alRestaurarPoder).toHaveBeenCalledWith(ID_VERDE);
  });

  it("si el caso no admite cambios no ofrece correcciones", () => {
    enApoderados({ ...structuredClone(APODERADOS_BORRADOR), editable: false }, { abierta: `apoderado-${ID_VERDE}` });
    expect(screen.queryByRole("group", { name: /Corregir a mano/ })).toBeNull();
  });

  const sinIdentificar = (extra: Partial<ApoderadosRespuesta> = {}): ApoderadosRespuesta => ({
    ...structuredClone(APODERADOS_BORRADOR),
    identificacion: "no_disponible",
    apoderados: [],
    sin_apoderado: [],
    bloquea_decision: false,
    ...extra,
  });

  it("un caso anterior a la identificación ofrece identificar a los apoderados", () => {
    const identificar = vi.fn(async () => {});
    const datos = sinIdentificar();
    enApoderados(datos, { apoderados: conDatos(datos, { identificar }) });
    fireEvent.click(screen.getByRole("button", { name: "Identificar apoderados" }));
    expect(identificar).toHaveBeenCalledOnce();
    expect(screen.queryByRole("note", { name: "Consulta automática de la vigencia" })).toBeNull();
  });

  it("mientras identifica lo anuncia y el botón queda ocupado; un error se muestra como alerta", () => {
    const datos = sinIdentificar({ editable: false });
    const identificar = vi.fn(async () => {});
    const { rerender } = enApoderados(datos, { apoderados: conDatos(datos, { identificando: true, identificar }) });
    const boton = screen.getByRole("button", { name: "Identificar apoderados" }) as HTMLButtonElement;
    // Ocupado con aria-disabled, no con disabled: así no pierde el foco.
    expect(boton.disabled).toBe(false);
    expect(boton.getAttribute("aria-disabled")).toBe("true");
    expect(boton.getAttribute("aria-busy")).toBe("true");
    expect(boton.querySelector(".giro")).toBeTruthy();
    fireEvent.click(boton);
    expect(identificar).not.toHaveBeenCalled();
    expect(screen.getByText("Buscando a los abogados en el expediente; puede tardar unos minutos.").getAttribute("role")).toBe("status");
    const libre = sinIdentificar();
    rerender(
      <PanelRevision
        {...conApoderados(libre, { pestana: "apoderados", apoderados: conDatos(libre, { errorIdentificacion: "Ya hay una ejecución en curso para este caso." }) })}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Ya hay una ejecución en curso para este caso.");
  });

  it("el foco sigue en el botón mientras identifica y al terminar pasa al panel, no a <body>", () => {
    const identificar = vi.fn(async () => {});
    const libre = sinIdentificar();
    const { rerender } = enApoderados(libre, { apoderados: conDatos(libre, { identificar }) });
    const boton = screen.getByRole("button", { name: "Identificar apoderados" });
    boton.focus();
    const ocupado = sinIdentificar({ editable: false });
    rerender(<PanelRevision {...conApoderados(ocupado, { pestana: "apoderados", apoderados: conDatos(ocupado, { identificar, identificando: true }) })} />);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Identificar apoderados" }));
    const lista = structuredClone(APODERADOS_BORRADOR);
    rerender(<PanelRevision {...conApoderados(lista, { pestana: "apoderados" })} />);
    expect(screen.queryByRole("button", { name: "Identificar apoderados" })).toBeNull();
    expect(document.activeElement).toBe(document.getElementById("bor-panel-titulo"));
  });

  it("sin un poder hallado al que volver no ofrece deshacer el descarte", () => {
    const datos = structuredClone(APODERADOS_BORRADOR);
    const verde = datos.apoderados.find((a) => a.id === ID_VERDE);
    if (!verde) throw new Error("falta el apoderado");
    // Era un poder señalado a mano sobre un abogado sin poder propio: al descartarlo, no queda ninguno.
    verde.poder = { ...verde.poder, estado: "descartado", evidencia: null, hay_hallado: false };
    enApoderados(datos, { abierta: `apoderado-${ID_VERDE}` });
    const grupo = correcciones("ANDREA PAOLA GIRALDO MONTOYA");
    expect(within(grupo).getAllByRole("button").map((b) => b.textContent)).toEqual(["Señalar el poder a mano…"]);
  });

  it("si la identificación falló ofrece intentarlo de nuevo; sin edición, no", () => {
    const fallida = sinIdentificar({ identificacion: "fallida" });
    const { unmount } = enApoderados(fallida);
    expect(screen.getByRole("button", { name: "Intentar de nuevo" })).toBeTruthy();
    unmount();
    enApoderados(sinIdentificar({ editable: false }));
    expect(screen.queryByRole("button", { name: "Identificar apoderados" })).toBeNull();
  });
});
