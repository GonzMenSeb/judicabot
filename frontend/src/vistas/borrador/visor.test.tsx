import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApoderadoVista, CadenaVista, EvidenciaVista, PaginaExpediente } from "../../api/contrato";
import VisorEvidencia, { type PropsVisorEvidencia } from "./VisorEvidencia";

const CASO = "caso-7";
const CITA = "confiero poder especial, amplio y suficiente a la doctora MARCELA ORTIZ PEÑA";
const CITA_CERTIFICADO = "PEDRO ALVARADO LEMA figura como representante legal de la sociedad";
const TITULO = "Poder especial · Doc. 1a-014";
const SUBTITULO = "Evidencia de que Marcela Ortiz Peña representa a Salud Vital EPS S.A.";

const TEXTO_PODER = [
  "PODER ESPECIAL",
  "Señores TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL",
  "PEDRO ALVARADO LEMA, representante legal de SALUD VITAL EPS S.A., por medio del presente escrito manifiesto que",
  "confiero poder especial, amplio y suficiente a la",
  "doctora MARCELA ORTIZ PEÑA, para que conteste la acción de tutela.",
  "Atentamente,",
].join("\n");

const TEXTO_CERTIFICADO = `CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL\n${CITA_CERTIFICADO}\nFin del certificado.`;

const evidenciaPoder = (extra: Partial<EvidenciaVista> = {}): EvidenciaVista => ({
  doc_id: "1a-014",
  documento: "014_Poder.pdf",
  rol: "anexo",
  pagina: 3,
  total_paginas: 4,
  cita: CITA,
  ocr: false,
  inicio: null,
  fin: null,
  ...extra,
});

const evidenciaCertificado = (): EvidenciaVista => ({
  doc_id: "1a-009",
  documento: "009_Certificado.pdf",
  rol: "anexo",
  pagina: 2,
  total_paginas: 2,
  cita: CITA_CERTIFICADO,
  ocr: false,
  inicio: null,
  fin: null,
});

function apoderado(extra: Partial<ApoderadoVista> = {}, cadena: CadenaVista | null = null): ApoderadoVista {
  return {
    id: "ap-0123456789",
    nombre: "MARCELA ORTIZ PEÑA",
    parte: "SALUD VITAL EPS S.A.",
    rol_parte: "accionada",
    tipo_persona: "juridica",
    estado: "verificado",
    fase: "listo",
    motivos: [],
    cedula: null,
    tarjeta: null,
    vigencia: {
      estado: "vigente",
      fase: "listo",
      cedula: null,
      tarjeta_registro: null,
      consultado_en: null,
      origen: "manual",
      certificado_url: null,
      numero_certificado: null,
      codigo_verificacion: null,
      detalle: "",
      grave: false,
    },
    poder: { estado: "hallado", tipo: "poder", evidencia: evidenciaPoder(), otorgante: "PEDRO ALVARADO LEMA", parte: "SALUD VITAL EPS S.A.", cadena, mencion: null, documentos_revisados: 3, hay_hallado: true },
    cotejos: [
      { ok: true, texto: "El nombre coincide con quien actúa en el expediente" },
      { ok: false, texto: "La T.P. no coincide con el certificado de vigencia" },
      { ok: null, texto: "No se pudo comprobar el alcance del poder" },
    ],
    revisado: false,
    revision_vencida: false,
    bloquea: false,
    huella: "huella-1",
    ...extra,
  };
}

const CADENA: CadenaVista = { estado: "confirmada", otorgante: "PEDRO ALVARADO LEMA", cargo: "representante legal", evidencia: evidenciaCertificado() };

function pagina(docId: string, n: number, extra: Partial<PaginaExpediente> = {}): PaginaExpediente {
  const certificado = docId === "1a-009";
  return {
    doc_id: docId,
    documento: certificado ? "009_Certificado.pdf" : "014_Poder.pdf",
    rol: "anexo",
    pagina: n,
    total: certificado ? 2 : 4,
    texto: certificado ? TEXTO_CERTIFICADO : n === 3 ? TEXTO_PODER : `Texto de la página ${n} del poder.`,
    ocr: false,
    es_pdf: true,
    ...extra,
  };
}

const json = (datos: unknown, estado = 200) => new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });

type Servidor = (docId: string, n: number) => Response | Promise<Response>;

function red(servidor: Servidor = (docId, n) => json(pagina(docId, n))) {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      const m = /\/expediente\/([^/]+)\/paginas\/(\d+)$/.exec(url);
      if (!m) return json({ detail: "No encontrado" }, 404);
      return servidor(m[1]!, Number(m[2]));
    }),
  );
  return urls;
}

function montar(props: Partial<PropsVisorEvidencia> = {}) {
  const alRevisar = vi.fn();
  const alCerrar = vi.fn();
  const resultado = render(
    <VisorEvidencia
      casoId={CASO}
      apoderado={apoderado()}
      evidencia={evidenciaPoder()}
      titulo={TITULO}
      subtitulo={SUBTITULO}
      editable
      revisado={false}
      alRevisar={alRevisar}
      alCerrar={alCerrar}
      {...props}
    />,
  );
  return { ...resultado, alRevisar, alCerrar };
}

const marca = () => document.querySelector("mark");
const esperarTexto = () => screen.findByRole("region", { name: /^Página \d+ de \d+$/ });

let desplazar: ReturnType<typeof vi.fn>;

beforeEach(() => {
  desplazar = vi.fn();
  Element.prototype.scrollIntoView = desplazar as unknown as Element["scrollIntoView"];
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

describe("VisorEvidencia: página y pasaje", () => {
  it("pide la página de la evidencia, muestra su texto y resalta el pasaje", async () => {
    const urls = red();
    montar();
    await esperarTexto();
    expect(urls).toEqual([`/api/casos/${CASO}/expediente/1a-014/paginas/3`]);
    expect(marca()?.textContent).toBe("confiero poder especial, amplio y suficiente a la\ndoctora MARCELA ORTIZ PEÑA");
    expect(document.querySelector(".visor-ev-texto")?.textContent).toBe(TEXTO_PODER);
    expect(screen.getByRole("heading", { level: 2, name: TITULO })).toBeTruthy();
    expect(screen.getByText(SUBTITULO)).toBeTruthy();
    expect(screen.getByText("Página 3 de 4")).toBeTruthy();
  });

  it("lleva el pasaje a la vista", async () => {
    red();
    montar();
    await esperarTexto();
    await waitFor(() => expect(desplazar).toHaveBeenCalledTimes(1));
    expect(desplazar.mock.contexts[0]).toBe(marca());
    expect(desplazar.mock.calls[0]?.[0]).toMatchObject({ block: "center" });
  });

  it("no anima el desplazamiento si la persona pidió menos movimiento", async () => {
    vi.stubGlobal("matchMedia", (consulta: string) => ({ matches: consulta.includes("reduce"), media: consulta }));
    red();
    montar();
    await esperarTexto();
    await waitFor(() => expect(desplazar).toHaveBeenCalled());
    expect(desplazar.mock.calls[0]?.[0]).toMatchObject({ behavior: "auto" });
  });

  it("usa los offsets de la evidencia cuando son verosímiles", async () => {
    const inicio = TEXTO_PODER.indexOf("doctora MARCELA");
    const fin = inicio + "doctora MARCELA ORTIZ PEÑA".length;
    red();
    montar({ evidencia: evidenciaPoder({ cita: "doctora MARCELA ORTIZ PEÑA", inicio, fin }) });
    await esperarTexto();
    expect(marca()?.textContent).toBe("doctora MARCELA ORTIZ PEÑA");
  });

  it("dice que no encontró el pasaje y no marca nada", async () => {
    red();
    montar({ evidencia: evidenciaPoder({ cita: "la parte accionada niega todo lo dicho por la accionante" }) });
    await esperarTexto();
    expect(marca()).toBeNull();
    expect(screen.getByText(/No se encontró el pasaje en la página 3/)).toBeTruthy();
    expect(desplazar).not.toHaveBeenCalled();
    expect(document.querySelector(".visor-ev-texto")?.textContent).toBe(TEXTO_PODER);
  });

  it("avisa cuando la página se leyó por OCR", async () => {
    red((docId, n) => json(pagina(docId, n, { ocr: true })));
    montar();
    await esperarTexto();
    expect(screen.getByText(/reconocimiento de texto \(OCR\)/)).toBeTruthy();
  });

  it("avisa cuando la página no tiene texto", async () => {
    red((docId, n) => json(pagina(docId, n, { texto: "  \n " })));
    montar();
    expect(await screen.findByText(/no tiene texto legible/)).toBeTruthy();
    expect(screen.queryByText(/No se encontró el pasaje/)).toBeNull();
    expect(marca()).toBeNull();
  });

  it("muestra el texto como texto, sin interpretarlo como HTML", async () => {
    const peligroso = "confiero poder <img src=x onerror=alert(1)> a la doctora";
    red((docId, n) => json(pagina(docId, n, { texto: `Obra la parte: ${peligroso}.` })));
    montar({ evidencia: evidenciaPoder({ cita: peligroso }) });
    await esperarTexto();
    expect(document.querySelector(".visor-ev-texto img")).toBeNull();
    expect(document.querySelector(".visor-ev-texto")?.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("muestra la carga mientras llega la página", async () => {
    let liberar: (r: Response) => void = () => {};
    red(() => new Promise<Response>((ok) => (liberar = ok)));
    montar();
    expect(screen.getByText("Cargando la página…")).toBeTruthy();
    await act(async () => {
      liberar(json(pagina("1a-014", 3)));
    });
    await esperarTexto();
    expect(screen.queryByText("Cargando la página…")).toBeNull();
  });
});

describe("VisorEvidencia: navegación entre páginas", () => {
  it("pide la página siguiente y la anterior del mismo documento", async () => {
    const urls = red();
    montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    expect(await screen.findByText("Texto de la página 4 del poder.")).toBeTruthy();
    expect(urls[1]).toBe(`/api/casos/${CASO}/expediente/1a-014/paginas/4`);
    expect(screen.getByText("Página 4 de 4")).toBeTruthy();
    expect(marca()).toBeNull();
    expect(screen.queryByText(/No se encontró el pasaje/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
    await screen.findByText(/PODER ESPECIAL/);
    expect(screen.getByText("Página 3 de 4")).toBeTruthy();
    expect(marca()).not.toBeNull();
    expect(urls).toHaveLength(2);
  });

  it("ofrece volver a la página citada cuando se está en otra", async () => {
    red();
    montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
    await screen.findByText("Texto de la página 2 del poder.");
    expect(screen.getByText(/Está viendo la página 2/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ir a la página citada" }));
    await screen.findByText(/PODER ESPECIAL/);
    expect(screen.getByText("Página 3 de 4")).toBeTruthy();
    expect(marca()).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Ir a la página citada" })).toBeNull();
  });

  it("no pasa de la última página del documento", async () => {
    const urls = red();
    montar({ evidencia: evidenciaPoder({ pagina: 4 }) });
    await screen.findByText("Texto de la página 4 del poder.");
    const siguiente = screen.getByRole("button", { name: "Página siguiente" });
    expect(siguiente.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(siguiente);
    expect(urls).toHaveLength(1);
    expect(screen.getByText("Página 4 de 4")).toBeTruthy();
  });

  it("no ofrece una página anterior a la primera", async () => {
    const urls = red();
    montar({ evidencia: evidenciaPoder({ pagina: 1, cita: "" }) });
    await screen.findByText("Texto de la página 1 del poder.");
    const anterior = screen.getByRole("button", { name: "Página anterior" });
    expect(anterior.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(anterior);
    expect(urls).toHaveLength(1);
    expect(screen.queryByText(/No se encontró el pasaje/)).toBeNull();
  });

  it("ignora la respuesta de una página que ya no se mira", async () => {
    const pendientes = new Map<number, (r: Response) => void>();
    red((docId, n) => (n === 3 ? json(pagina(docId, n)) : new Promise<Response>((ok) => pendientes.set(n, ok))));
    montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
    await screen.findByText(/PODER ESPECIAL/);
    await act(async () => {
      pendientes.get(4)?.(json(pagina("1a-014", 4)));
    });
    expect(screen.queryByText("Texto de la página 4 del poder.")).toBeNull();
    expect(screen.getByText("Página 3 de 4")).toBeTruthy();
  });
});

describe("VisorEvidencia: PDF original", () => {
  it("enlaza al PDF en la página que se mira solo cuando el documento es un PDF", async () => {
    red();
    montar();
    await esperarTexto();
    const enlace = screen.getByRole("link", { name: /Abrir PDF original/ });
    expect(enlace.getAttribute("href")).toBe(`/api/casos/${CASO}/expediente/1a-014/archivo#page=3`);
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");

    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    await screen.findByText("Texto de la página 4 del poder.");
    expect(screen.getByRole("link", { name: /Abrir PDF original/ }).getAttribute("href")).toBe(`/api/casos/${CASO}/expediente/1a-014/archivo#page=4`);
  });

  it("no lo ofrece si el documento no es un PDF", async () => {
    red((docId, n) => json(pagina(docId, n, { es_pdf: false })));
    montar();
    await esperarTexto();
    expect(screen.queryByRole("link", { name: /Abrir PDF original/ })).toBeNull();
    expect(marca()).not.toBeNull();
  });

  it("no lo ofrece mientras no se sabe qué tipo de archivo es", () => {
    red(() => new Promise<Response>(() => {}));
    montar();
    expect(screen.queryByRole("link", { name: /Abrir PDF original/ })).toBeNull();
  });

  it("codifica el caso y el documento en las rutas", async () => {
    const urls = red();
    montar({ casoId: "caso 7/ñ" });
    await esperarTexto();
    expect(urls[0]).toBe("/api/casos/caso%207%2F%C3%B1/expediente/1a-014/paginas/3");
    expect(screen.getByRole("link", { name: /Abrir PDF original/ }).getAttribute("href")).toBe("/api/casos/caso%207%2F%C3%B1/expediente/1a-014/archivo#page=3");
  });
});

describe("VisorEvidencia: lo que se cotejó y la cita", () => {
  it("lista los cotejos con una marca y una lectura para cada resultado", async () => {
    red();
    montar();
    await esperarTexto();
    const lista = screen.getByRole("list");
    const filas = within(lista).getAllByRole("listitem");
    expect(filas.map((f) => f.textContent)).toEqual([
      "Coincide: El nombre coincide con quien actúa en el expediente",
      "No coincide: La T.P. no coincide con el certificado de vigencia",
      "No se pudo cotejar: No se pudo comprobar el alcance del poder",
    ]);
    expect(filas.map((f) => f.querySelector(".visor-ev-marca")?.className)).toEqual(["visor-ev-marca ok", "visor-ev-marca mal", "visor-ev-marca nulo"]);
    expect(filas.every((f) => f.querySelector(".visor-ev-marca")?.getAttribute("aria-hidden") === "true")).toBe(true);
  });

  it("dice cuando no hay cotejos", async () => {
    red();
    montar({ apoderado: apoderado({ cotejos: [] }) });
    await esperarTexto();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText(/No hay comprobaciones automáticas/)).toBeTruthy();
  });

  it("muestra la cita textual con su documento y su página", async () => {
    red();
    montar();
    await esperarTexto();
    const caja = screen.getByRole("region", { name: "Cita textual" });
    expect(within(caja).getByText(CITA).tagName).toBe("Q");
    expect(within(caja).getByText(`${TITULO} · página 3`)).toBeTruthy();
  });

  it("no ofrece la cita ni copiarla si la evidencia no trae cita", async () => {
    red();
    montar({ evidencia: evidenciaPoder({ cita: "" }) });
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "Copiar cita" })).toBeNull();
    expect(document.querySelector(".visor-ev-cita q")).toBeNull();
  });
});

describe("VisorEvidencia: copiar la cita", () => {
  it("copia la cita y lo confirma en una región de estado", async () => {
    const escribir = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: escribir } });
    red();
    montar();
    await esperarTexto();
    const estado = within(screen.getByRole("region", { name: "Cita textual" })).getByRole("status");
    expect(estado.textContent).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Copiar cita" }));
    await waitFor(() => expect(estado.textContent).toBe("Cita copiada."));
    expect(escribir).toHaveBeenCalledWith(CITA);
  });

  it("borra la confirmación pasados unos segundos", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    red();
    montar();
    await esperarTexto();
    vi.useFakeTimers();
    const estado = within(screen.getByRole("region", { name: "Cita textual" })).getByRole("status");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copiar cita" }));
    });
    expect(estado.textContent).toBe("Cita copiada.");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(estado.textContent).toBe("");
  });

  it("explica que no se pudo copiar cuando el navegador lo rechaza", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new DOMException("no", "NotAllowedError")) } });
    red();
    montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Copiar cita" }));
    const estado = within(screen.getByRole("region", { name: "Cita textual" })).getByRole("status");
    await waitFor(() => expect(estado.textContent).toMatch(/No se pudo copiar/));
    expect(estado.className).toContain("mal");
  });

  it("explica que no se pudo copiar cuando el navegador no tiene portapapeles", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    red();
    montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Copiar cita" }));
    const estado = within(screen.getByRole("region", { name: "Cita textual" })).getByRole("status");
    await waitFor(() => expect(estado.textContent).toMatch(/No se pudo copiar/));
  });
});

describe("VisorEvidencia: certificado de existencia", () => {
  it("no lo ofrece si el poder no trae cadena", async () => {
    red();
    montar();
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "Ver certificado de existencia" })).toBeNull();
  });

  it("cambia a la evidencia del certificado y permite volver", async () => {
    const urls = red();
    montar({ apoderado: apoderado({}, CADENA) });
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Ver certificado de existencia" }));

    expect(await screen.findByText(/CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL/)).toBeTruthy();
    expect(urls[1]).toBe(`/api/casos/${CASO}/expediente/1a-009/paginas/2`);
    expect(screen.getByRole("heading", { level: 2, name: "Certificado de existencia · Doc. 1a-009" })).toBeTruthy();
    expect(screen.getByText("Evidencia de que PEDRO ALVARADO LEMA es representante legal de SALUD VITAL EPS S.A.")).toBeTruthy();
    expect(screen.getByText("Página 2 de 2")).toBeTruthy();
    expect(marca()?.textContent).toBe(CITA_CERTIFICADO);
    expect(within(screen.getByRole("region", { name: "Cita textual" })).getByText(CITA_CERTIFICADO)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ver certificado de existencia" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Volver a la evidencia inicial" }));
    await screen.findByText(/PODER ESPECIAL/);
    expect(screen.getByRole("heading", { level: 2, name: TITULO })).toBeTruthy();
    expect(screen.getByText("Página 3 de 4")).toBeTruthy();
    expect(urls).toHaveLength(2);
  });

  it("no lo ofrece cuando el visor ya se abrió sobre el certificado", async () => {
    red();
    montar({ apoderado: apoderado({}, CADENA), evidencia: evidenciaCertificado(), titulo: "Certificado de existencia · Doc. 1a-009" });
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "Ver certificado de existencia" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Volver a la evidencia inicial" })).toBeNull();
  });

  it("mantiene el foco en el botón al cambiar de evidencia", async () => {
    red();
    montar({ apoderado: apoderado({}, CADENA) });
    await esperarTexto();
    const boton = screen.getByRole("button", { name: "Ver certificado de existencia" });
    boton.focus();
    fireEvent.click(boton);
    await screen.findByText(/CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL/);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Volver a la evidencia inicial" }));
  });
});

describe("VisorEvidencia: revisión", () => {
  it("marca como revisado", async () => {
    red();
    const { alRevisar } = montar();
    await esperarTexto();
    const boton = screen.getByRole("button", { name: "Marcar revisado" });
    expect(boton.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(boton);
    expect(alRevisar).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("quita la revisión cuando ya estaba revisado", async () => {
    red();
    const { alRevisar } = montar({ revisado: true });
    await esperarTexto();
    const boton = screen.getByRole("button", { name: "Marcar revisado" });
    expect(boton.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(boton);
    expect(alRevisar).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("no deja cambiarla cuando el caso ya no espera la decisión", async () => {
    red();
    montar({ editable: false });
    await esperarTexto();
    const boton = screen.getByRole("button", { name: "Marcar revisado" }) as HTMLButtonElement;
    expect(boton.disabled).toBe(true);
    expect(boton.getAttribute("aria-describedby")).toBe(screen.getByText("Solo se puede cambiar mientras el caso espera la decisión.").id);
  });
});

describe("VisorEvidencia: «No es correcto…»", () => {
  it("sobre el poder lo ofrece junto a «Marcar revisado» y lo pide", async () => {
    red();
    const alNoEsCorrecto = vi.fn();
    montar({ alNoEsCorrecto });
    await esperarTexto();
    const boton = screen.getByRole("button", { name: "No es correcto…" });
    expect(boton.closest(".visor-ev-pie")).not.toBeNull();
    fireEvent.click(boton);
    expect(alNoEsCorrecto).toHaveBeenCalledOnce();
  });

  it("no lo ofrece sobre el certificado de existencia, sin edición ni sin quien lo atienda", async () => {
    red();
    const alNoEsCorrecto = vi.fn();
    const { unmount } = montar({ alNoEsCorrecto, apoderado: apoderado({}, CADENA) });
    await esperarTexto();
    expect(screen.getByRole("button", { name: "No es correcto…" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ver certificado de existencia" }));
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "No es correcto…" })).toBeNull();
    unmount();
    const sinEdicion = montar({ alNoEsCorrecto, editable: false });
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "No es correcto…" })).toBeNull();
    sinEdicion.unmount();
    montar();
    await esperarTexto();
    expect(screen.queryByRole("button", { name: "No es correcto…" })).toBeNull();
  });
});

describe("VisorEvidencia: errores y cierre", () => {
  it("muestra el detalle del servidor y deja reintentar", async () => {
    let intentos = 0;
    const urls = red((docId, n) => {
      intentos += 1;
      return intentos === 1 ? json({ detail: "El documento 1a-014 no tiene página 3." }, 404) : json(pagina(docId, n));
    });
    montar();
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("El documento 1a-014 no tiene página 3.");
    expect(screen.queryByRole("link", { name: /Abrir PDF original/ })).toBeNull();
    expect(marca()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await esperarTexto();
    expect(urls).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(marca()).not.toBeNull();
  });

  it("usa un mensaje propio cuando el servidor no da detalle", async () => {
    red(() => new Response("boom", { status: 500 }));
    montar();
    expect((await screen.findByRole("alert")).textContent).toContain("Error 500");
  });

  it("explica que no hay conexión", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    montar();
    expect((await screen.findByRole("alert")).textContent).toContain("No se pudo conectar con el servidor");
  });

  it("sigue funcionando la navegación después de un error", async () => {
    red((docId, n) => (n === 3 ? json({ detail: "Página ilegible." }, 500) : json(pagina(docId, n))));
    montar();
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    expect(await screen.findByText("Texto de la página 4 del poder.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Escape cierra el visor", async () => {
    red();
    const { alCerrar } = montar();
    await esperarTexto();
    fireEvent.keyDown(screen.getByRole("button", { name: "Marcar revisado" }), { key: "Escape" });
    expect(alCerrar).toHaveBeenCalledOnce();
  });

  it("el botón de cierre cierra el visor", async () => {
    red();
    const { alCerrar } = montar();
    await esperarTexto();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar visor" }));
    expect(alCerrar).toHaveBeenCalledOnce();
  });

  it("es un diálogo modal con el título de la evidencia", async () => {
    red();
    montar();
    await esperarTexto();
    const dialogo = document.querySelector("dialog") as HTMLDialogElement;
    expect(dialogo.hasAttribute("open")).toBe(true);
    expect(dialogo.classList.contains("visor-ev")).toBe(true);
    expect(dialogo.getAttribute("aria-labelledby")).toBe(screen.getByRole("heading", { level: 2, name: TITULO }).id);
  });

  it("deja de pedir la página al cerrarse", async () => {
    let senal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        senal = init?.signal ?? undefined;
        return new Promise<Response>(() => {});
      }),
    );
    const { unmount } = montar();
    expect(senal?.aborted).toBe(false);
    unmount();
    expect(senal?.aborted).toBe(true);
  });
});

describe("estilos del visor", () => {
  const estilos = readFileSync(join(import.meta.dirname, "visor.css"), "utf8");

  it("solo el visor importa su hoja, para que viaje en el chunk perezoso", () => {
    const fuentes = ["VisorEvidencia.tsx", "index.tsx", "Documento.tsx", "PanelRevision.tsx"].map((n) => readFileSync(join(import.meta.dirname, n), "utf8"));
    expect(fuentes.map((f) => f.includes("visor.css"))).toEqual([true, false, false, false]);
  });

  it("no anima el resaltado cuando se pidió menos movimiento", () => {
    const [, animado] = /@media \(prefers-reduced-motion: no-preference\)\s*\{([\s\S]*?)\}\s*\}/.exec(estilos) ?? [];
    expect(animado).toContain("animation");
    expect(estilos.replace(animado ?? "", "")).not.toMatch(/animation\s*:/);
  });
});
