import { cleanup, fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dock, type PropsDock } from "./Dock";
import { Indice, type PropsIndice } from "./Indice";
import type { EntradaIndice, Redaccion } from "./tipos";

afterEach(cleanup);

const ENTRADAS: EntradaIndice[] = [
  { id: "b-t1", titulo: "I. Asunto", sub: false, anexo: false },
  { id: "b-t2", titulo: "V. Consideraciones", sub: false, anexo: false },
  { id: "b-t2a", titulo: "Marco jurídico", sub: true, anexo: false },
  { id: "b-t3", titulo: "Informe de citas", sub: false, anexo: true },
  { id: "b-t4", titulo: "Anexo dos", sub: false, anexo: true },
];

const REDACCION: Redaccion[] = [
  { nodo: "apertura", secciones: "Secciones II a IV", modelo: "Sonnet 5.5", pedido: "Opus 5.5" },
  { nodo: "consideraciones", secciones: "Sección V", modelo: "Opus 5.5", pedido: null },
];

function indice(extra: Partial<PropsIndice> = {}) {
  const props: PropsIndice = {
    entradas: ENTRADAS,
    marcas: {},
    activa: null,
    alSeccion: () => {},
    redaccion: [],
    abierto: false,
    ...extra,
  };
  return render(<Indice {...props} />);
}

function dock(extra: Partial<PropsDock> = {}) {
  const props: PropsDock = {
    pendientes: 3,
    revisados: 0,
    total: 3,
    enCurso: false,
    hrefDecision: "#/decision",
    puedeCorregir: true,
    motivoNoCorregir: null,
    alCorregir: () => {},
    ...extra,
  };
  return render(<Dock {...props} />);
}

describe("Indice", () => {
  it("es la navegación «Contenido del borrador» con el rótulo «Contenido»", () => {
    indice();
    const nav = screen.getByRole("navigation", { name: "Contenido del borrador" });
    expect(nav.id).toBe("bor-indice");
    expect(nav.classList.contains("bor-indice")).toBe(true);
    expect(within(nav).getByText("Contenido")).toBeTruthy();
    expect(within(nav).getAllByRole("button")).toHaveLength(ENTRADAS.length);
  });

  it("solo lleva la clase abierto cuando abierto es true", () => {
    const { rerender } = indice();
    expect(screen.getByRole("navigation").classList.contains("abierto")).toBe(false);
    rerender(<Indice entradas={ENTRADAS} marcas={{}} activa={null} alSeccion={() => {}} redaccion={[]} abierto />);
    expect(screen.getByRole("navigation").classList.contains("abierto")).toBe(true);
  });

  it("marca la sección activa con aria-current y llama alSeccion con el id", () => {
    const alSeccion = vi.fn();
    indice({ activa: "b-t2", alSeccion });
    expect(screen.getByRole("button", { name: "V. Consideraciones" }).getAttribute("aria-current")).toBe("location");
    expect(screen.getByRole("button", { name: "I. Asunto" }).hasAttribute("aria-current")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Marco jurídico" }));
    expect(alSeccion).toHaveBeenCalledWith("b-t2a");
  });

  it("muestra el marcador con su texto para lectores, en singular y plural, y distingue mal de alerta", () => {
    indice({ marcas: { "b-t1": { n: 1, mal: false }, "b-t2": { n: 3, mal: true } } });
    const uno = screen.getByRole("button", { name: /I\. Asunto/ });
    expect(uno.textContent).toContain("1");
    expect(within(uno).getByText(/1 cita por revisar/).classList.contains("solo-lectura")).toBe(true);
    expect(uno.querySelector(".bor-marcador")?.classList.contains("alerta")).toBe(true);
    const tres = screen.getByRole("button", { name: /V\. Consideraciones/ });
    expect(within(tres).getByText(/3 citas por revisar/)).toBeTruthy();
    expect(tres.querySelector(".bor-marcador")?.classList.contains("mal")).toBe(true);
    expect(screen.getByRole("button", { name: "Anexo dos" }).querySelector(".bor-marcador")).toBeNull();
  });

  it("distingue para lectores las citas de los nombres de abogados por revisar", () => {
    indice({ marcas: { "b-t1": { n: 2, mal: false, apoderados: 1 }, "b-t2": { n: 2, mal: true, apoderados: 2 } } });
    expect(within(screen.getByRole("button", { name: /I\. Asunto/ })).getByText("1 cita y 1 abogado por revisar")).toBeTruthy();
    expect(within(screen.getByRole("button", { name: /V\. Consideraciones/ })).getByText("2 abogados por revisar")).toBeTruthy();
  });

  it("pone un separador solo antes del primer anexo", () => {
    indice();
    const nav = screen.getByRole("navigation");
    const cortes = nav.querySelectorAll(".bor-corte");
    expect(cortes).toHaveLength(1);
    expect(cortes[0]?.nextElementSibling?.textContent).toBe("Informe de citas");
  });

  it("no pone separador si no hay anexos", () => {
    indice({ entradas: ENTRADAS.slice(0, 3) });
    expect(screen.getByRole("navigation").querySelector(".bor-corte")).toBeNull();
  });

  it("marca subtítulos y anexos con clases propias", () => {
    indice();
    expect(screen.getByRole("button", { name: "Marco jurídico" }).closest("li")?.classList.contains("sub")).toBe(true);
    expect(screen.getByRole("button", { name: "Informe de citas" }).closest("li")?.classList.contains("anexo")).toBe(true);
  });

  it("no pinta «Quién redactó» sin redacción", () => {
    indice();
    expect(screen.queryByRole("heading", { name: "Quién redactó" })).toBeNull();
  });

  it("lista quién redactó cada sección y avisa cuando el modelo pedido difiere", () => {
    indice({ redaccion: REDACCION });
    const seccion = screen.getByRole("heading", { level: 2, name: "Quién redactó" }).closest("section") as HTMLElement;
    expect(within(seccion).getByText("Secciones II a IV")).toBeTruthy();
    expect(within(seccion).getByText("Sección V")).toBeTruthy();
    expect(within(seccion).getByText("Sonnet 5.5")).toBeTruthy();
    expect(within(seccion).getByText("Se pidió Opus 5.5; respondió Sonnet 5.5.")).toBeTruthy();
    expect(within(seccion).getAllByText(/Se pidió/)).toHaveLength(1);
  });
});

describe("Dock", () => {
  it("pone los dos botones y el enlace a la decisión", () => {
    dock();
    expect(screen.getByRole("button", { name: "Pedir correcciones" })).toBeTruthy();
    const decidir = screen.getByRole("link", { name: /Pasar a la decisión/ });
    expect(decidir.getAttribute("href")).toBe("#/decision");
    expect(decidir.classList.contains("sello")).toBe(true);
    expect(decidir.classList.contains("grande")).toBe(true);
  });

  it("con un apoderado que bloquea deshabilita «Pasar a la decisión» y da la razón", () => {
    const razon = "CARLOS EDUARDO PINEDA RUIZ no pudo verificarse. Márquelo como revisado en la pestaña Apoderados para pasar a la decisión.";
    dock({ bloqueo: razon, motivoNoCorregir: "No se pudo comprobar el estado del caso." });
    expect(screen.getByText("Revise los apoderados no verificados")).toBeTruthy();
    expect(screen.getByText(razon).id).toBe("bor-dock-linea");
    expect(screen.queryByText(/No bloquean la decisión/)).toBeNull();
    const decidir = screen.getByText("Pasar a la decisión").closest("a") as HTMLElement;
    expect(decidir.getAttribute("aria-disabled")).toBe("true");
    expect(decidir.hasAttribute("href")).toBe(false);
    expect(decidir.getAttribute("aria-describedby")).toBe("bor-dock-linea");
  });

  it("una redacción en curso tiene prioridad sobre el bloqueo", () => {
    dock({ bloqueo: "Alguien no pudo verificarse.", enCurso: true });
    expect(screen.getByText("Hay una redacción en curso")).toBeTruthy();
    expect(screen.getByText("Pasar a la decisión").closest("a")?.getAttribute("aria-disabled")).toBe("true");
  });

  it("dice cuántos puntos quedan sin revisar", () => {
    dock({ pendientes: 3, revisados: 0, total: 3 });
    expect(screen.getByText("Quedan 3 puntos por revisar")).toBeTruthy();
    expect(screen.getByText("Lleva 0 de 3. No bloquean la decisión.")).toBeTruthy();
  });

  it("usa el singular cuando queda un punto", () => {
    dock({ pendientes: 1, revisados: 2, total: 3 });
    expect(screen.getByText("Queda 1 punto por revisar")).toBeTruthy();
    expect(screen.getByText("Lleva 2 de 3. No bloquean la decisión.")).toBeTruthy();
  });

  it("felicita cuando todo está revisado", () => {
    dock({ pendientes: 0, revisados: 3, total: 3 });
    expect(screen.getByText("Revisó los 3 puntos")).toBeTruthy();
    expect(screen.getByText("Puede pasar a la decisión.")).toBeTruthy();
  });

  it("usa «el único punto» cuando solo había uno", () => {
    dock({ pendientes: 0, revisados: 1, total: 1 });
    expect(screen.getByText("Revisó el único punto")).toBeTruthy();
  });

  it("dice que está listo cuando no hay nada que revisar", () => {
    dock({ pendientes: 0, revisados: 0, total: 0 });
    expect(screen.getByText("El borrador está listo para su decisión")).toBeTruthy();
    expect(screen.getByText("Todas las comprobaciones salieron bien.")).toBeTruthy();
  });

  it("sin alertas leídas no dice que está listo", () => {
    dock({ pendientes: 0, revisados: 0, total: 0, alertas: "cargando" });
    expect(screen.getByText("Comprobando el borrador")).toBeTruthy();
    expect(screen.queryByText("El borrador está listo para su decisión")).toBeNull();
    cleanup();
    dock({ pendientes: 0, revisados: 0, total: 0, alertas: "fallo" });
    expect(screen.getByText("No se pudieron leer las alertas")).toBeTruthy();
    expect(screen.queryByText("Todas las comprobaciones salieron bien.")).toBeNull();
  });

  it("con una redacción en curso avisa y deshabilita la decisión", () => {
    dock({ enCurso: true });
    expect(screen.getByText("Hay una redacción en curso")).toBeTruthy();
    expect(screen.getByText("Podrá decidir cuando termine.")).toBeTruthy();
    const decidir = screen.getByText(/Pasar a la decisión/).closest("a") as HTMLElement;
    expect(decidir.getAttribute("aria-disabled")).toBe("true");
    expect(decidir.hasAttribute("href")).toBe(false);
  });

  it("deshabilita «Pedir correcciones» y muestra el motivo en lugar de la segunda línea", () => {
    dock({ puedeCorregir: false, motivoNoCorregir: "Solo se puede mientras espera su decisión." });
    expect((screen.getByRole("button", { name: "Pedir correcciones" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Solo se puede mientras espera su decisión.")).toBeTruthy();
    expect(screen.queryByText(/No bloquean la decisión/)).toBeNull();
  });

  it("en curso, el aviso de redacción gana al motivo de no corregir", () => {
    dock({ enCurso: true, puedeCorregir: false, motivoNoCorregir: "Otro motivo." });
    expect(screen.getByText("Podrá decidir cuando termine.")).toBeTruthy();
    expect(screen.queryByText("Otro motivo.")).toBeNull();
  });

  it("llama alCorregir al pulsar «Pedir correcciones»", () => {
    const alCorregir = vi.fn();
    dock({ alCorregir });
    fireEvent.click(screen.getByRole("button", { name: "Pedir correcciones" }));
    expect(alCorregir).toHaveBeenCalledTimes(1);
  });
});
