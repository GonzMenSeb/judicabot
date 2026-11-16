import { fireEvent, render, screen, within } from "@testing-library/preact";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CitaVista } from "../../api/contrato";
import { porcentaje } from "../../estado";
import { PanelRevision, type PropsPanelRevision } from "./PanelRevision";
import type { FilaJev, ItemRevision } from "./tipos";

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
    cita: "c3",
    nivel: "mal",
    origen: "Cita · Consideraciones",
    titulo: "Sentencia c3",
    linea: "No se encontró en la relatoría",
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C3, motivos: ["No se encontró en la relatoría.", "Revise el número."] },
  },
  {
    clave: "alerta-ingesta-0",
    cita: null,
    nivel: "mal",
    origen: "Ingesta",
    titulo: `Hubo un error al leer ${ARCHIVO_LARGO}`,
    linea: null,
    lineaCompleta: false,
    detalle: null,
  },
  {
    clave: "cita-c2",
    cita: "c2",
    nivel: "alerta",
    origen: "Cita · Apertura",
    titulo: "Sentencia c2",
    linea: "La cobertura es baja.",
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C2, motivos: ["La cobertura es baja.", "Verifique el pasaje."] },
  },
  {
    clave: "jev-sentido",
    cita: null,
    nivel: "alerta",
    origen: "Jev · no coincide",
    titulo: FILA_DIFIERE.etiqueta,
    linea: "Borrador: Niega el amparo · Jev: Concede el amparo",
    lineaCompleta: false,
    detalle: { tipo: "jev", fila: FILA_DIFIERE },
  },
  {
    clave: "alerta-metadatos-0",
    cita: null,
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
    cita: null,
    nivel: "info",
    origen: "Archivo 1a-007",
    titulo: "El modelo leyó solo una parte de este documento",
    linea: ARCHIVO_LARGO,
    lineaCompleta: false,
    detalle: { tipo: "archivo", archivo: ARCHIVO_LARGO, nota: "Se le entregaron los primeros 120.000 caracteres; lo que sigue no se tuvo en cuenta." },
  },
  {
    clave: "jev-rol",
    cita: null,
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
    cita: "c1",
    nivel: "ok",
    origen: "Cita · Consideraciones",
    titulo: "Sentencia c1",
    linea: `Verificada · cobertura ${porcentaje(0.97)}`,
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C1, motivos: [] },
  },
  {
    clave: "cita-c4",
    cita: "c4",
    nivel: "ok",
    origen: "Cita",
    titulo: "Sentencia c4",
    linea: `Verificada · cobertura ${porcentaje(0.61)}`,
    lineaCompleta: false,
    detalle: { tipo: "cita", cita: C4, motivos: [] },
  },
  {
    clave: "jev-ok",
    cita: null,
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
    umbralJev: 0.8,
    avisoEstado: null,
    abiertoMovil: false,
    onCerrarMovil: vi.fn(),
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
    const { container } = render(<PanelRevision {...props({ seleccionada: "c2" })} />);
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
    expect(alVerEnTexto).toHaveBeenCalledWith("c3", expect.any(HTMLElement));
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

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: ancho });
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("desde 1024 px desplaza la fila al cambiar la selección", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    const { rerender } = render(<PanelRevision {...props()} />);
    expect(scroll).not.toHaveBeenCalled();
    rerender(<PanelRevision {...props({ seleccionada: "c2" })} />);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
    expect(scroll.mock.contexts[0]).toBe(document.querySelector(".bor-fila-activa"));
  });

  it("bajo 1024 px no desplaza", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 });
    render(<PanelRevision {...props({ seleccionada: "c2" })} />);
    expect(scroll).not.toHaveBeenCalled();
  });

  it("no lanza cuando el navegador no implementa scrollIntoView", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    expect(() => render(<PanelRevision {...props({ seleccionada: "c2" })} />)).not.toThrow();
  });

  it("no lanza con una selección que no tiene fila", () => {
    expect(() => render(<PanelRevision {...props({ seleccionada: "no-existe" })} />)).not.toThrow();
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
