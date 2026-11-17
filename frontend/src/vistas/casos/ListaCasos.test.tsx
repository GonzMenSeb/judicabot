import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CasoResumen, EstadoServidor } from "../../api/contrato";
import { estadoServidor } from "../../estado";
import { consulta, ruta } from "../../rutas";
import { ListaCasos } from "./ListaCasos";
import { casosMock } from "./mock";

const CASOS: CasoResumen[] = casosMock;

/** Marca de tiempo local de noviembre de 2026. */
const en = (dia: number, hora = 10) => new Date(2026, 10, dia, hora).toISOString();
const FECHADOS: CasoResumen[] = CASOS.map((c) => ({
  ...c,
  actualizado: { "quintero-bedoya": en(17, 14), "cardenas-ospina": en(16, 9), "arango-londono": en(13, 11), "restrepo-gil": en(17, 12), "mejia-rios": en(4), "duque-salazar": en(1), "demo-sin-leer": en(10) }[c.id]!,
}));

const nombres = () =>
  screen
    .queryAllByRole("article")
    .map((a) => a.querySelector("h3, h4")!.textContent);
const cuenta = () => screen.getByRole("status").textContent;
const boton = (name: string | RegExp) => screen.getByRole("button", { name });
const panel = (name: string) => screen.getByRole("dialog", { name });

beforeEach(() => {
  ruta.value = { vista: "inicio", params: {} };
  history.replaceState(null, "", "/");
  consulta.value = "";
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  estadoServidor.value = null;
});

describe("ListaCasos", () => {
  it("muestra la franja de estados con los terminados ocultos y el carril de filtros generales", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    expect(screen.getByRole("region", { name: "Casos" })).toBeTruthy();
    const franja = screen.getByRole("group", { name: "Estado" });
    const segmentos = within(franja).getAllByRole("button");
    expect(segmentos.map((b) => [b.getAttribute("aria-label"), b.getAttribute("aria-pressed"), b.querySelector("b")!.textContent])).toEqual([
      ["Por decidir", "true", "1"],
      ["Faltan documentos", "true", "1"],
      ["Con error", "true", "0"],
      ["Por preparar", "true", "2"],
      ["En redacción", "true", "1"],
      ["Terminados", "false", "2"],
    ]);
    expect(boton("Terminados").textContent).toContain("Terminados · ocultos");
    expect(boton("Terminados").style.flexGrow).toBe("2");
    expect(cuenta()).toBe("5 casos abiertos");

    const generales = screen.getByRole("group", { name: "Filtros generales" });
    for (const nombre of ["Trabajado", "Juzgado de 1ª inst.", "Entidad accionada"]) {
      expect(within(generales).getByRole("button", { name: nombre }).getAttribute("aria-expanded")).toBe("false");
    }
    expect(within(generales).getByRole("button", { name: "Con alertas" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByRole("group", { name: "Proceso" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("el carril «Propios de 2ª instancia» trae los filtros de segunda, también en Inicio con un solo proceso", () => {
    for (const proceso of ["segunda", undefined] as const) {
      const { unmount } = render(<ListaCasos casos={CASOS} proceso={proceso} />);
      const propio = screen.getByRole("group", { name: "Filtros propios de 2ª instancia" });
      expect(propio.querySelector(".carril-cab")!.textContent).toBe("Propios de 2ª instancia");
      expect(propio.querySelector(".carril-ico svg")).toBeTruthy();
      for (const nombre of ["Decisión 1ª inst.", "Impugnó", "Sentido 2ª inst.", "Derecho", "Por revisar"]) {
        expect(within(propio).getByRole("button", { name: nombre }).getAttribute("aria-expanded")).toBe("false");
      }
      expect(within(propio).getByRole("button", { name: "Con pruebas nuevas" }).getAttribute("aria-pressed")).toBe("false");
      expect(screen.queryByRole("group", { name: "Proceso" })).toBeNull();
      unmount();
    }
  });

  it("las fichas muestran los datos de segunda y la Decisión 1ª inst. cuenta, filtra y resalta", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const quintero = () => screen.getByRole("link", { name: "Decidir: Quintero Bedoya c. EPS Horizonte Salud" }).closest("article")!;
    const datos = (a: Element, sel = ".dato") => [...a.querySelectorAll(sel)].map((d) => d.textContent);
    expect(datos(quintero())).toEqual(["1ª inst.: Negó el amparo", "Impugna: accionante", "Pruebas nuevas en 2ª", "2 citas por revisar", "Jev discrepa"]);
    expect(datos(quintero(), ".eco")).toEqual([]);

    const propio = screen.getByRole("group", { name: "Filtros propios de 2ª instancia" });
    expect(propio.querySelector(".cuantos")).toBeNull();
    fireEvent.click(within(propio).getByRole("button", { name: "Decisión 1ª inst." }));
    const dialogo = panel("Decisión de primera instancia");
    const conteos = () => within(dialogo).getAllByRole("checkbox").map((o) => [o.closest("label")!.textContent, o.getAttribute("title")]);
    const esperados = [
      ["Amparó0", "0 casos"],
      ["Negó el amparo1", "1 caso"],
      ["Declaró improcedente0", "0 casos"],
      ["Carencia actual de objeto1", "1 caso"],
      ["Otra0", "0 casos"],
      ["Sin dato3", "3 casos"],
    ];
    expect(conteos()).toEqual(esperados);

    fireEvent.click(within(dialogo).getByRole("checkbox", { name: "Negó el amparo" }));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud"]);
    expect(location.hash).toBe("#/?s.segunda.aquo=niega");
    expect(conteos()).toEqual(esperados);
    expect(datos(quintero(), ".dato.eco")).toEqual(["1ª inst.: Negó el amparo"]);
    const cuantos = propio.querySelector(".cuantos")!;
    expect([cuantos.textContent, cuantos.getAttribute("aria-hidden")]).toEqual(["1", "true"]);
    expect(propio.querySelector(".carril-cab .solo-lectura")!.textContent).toBe("1 filtro propio aplicado");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Listo · 1 caso" }));
    expect(boton("Decisión 1ª inst.: Negó el amparo")).toBeTruthy();

    fireEvent.click(boton("Compacta"));
    expect(quintero().className).toContain("fila-c");
    expect(datos(quintero())).toEqual(["1ª inst.: Negó el amparo"]);
    expect(datos(quintero(), ".dato.eco")).toEqual(["1ª inst.: Negó el amparo"]);
    fireEvent.click(boton("Con pruebas nuevas"));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud"]);
    expect(datos(quintero())).toEqual(["1ª inst.: Negó el amparo"]);
  });

  it("en Inicio con varios procesos, la pestaña «Todos» no muestra carril ni datos propios", () => {
    const primera = { ...CASOS[0]!, id: "primera-1", nombre: "Caso de primera", proceso: "primera" as never, segunda: null };
    render(<ListaCasos casos={[...CASOS, primera]} />);
    expect(boton(/^Todos/).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("group", { name: "Filtros propios de 2ª instancia" })).toBeNull();
    expect(document.querySelector(".dato")).toBeNull();
    fireEvent.click(boton(/^2ª instancia/));
    expect(screen.getByRole("group", { name: "Filtros propios de 2ª instancia" })).toBeTruthy();
    expect(document.querySelector(".dato")).toBeTruthy();
  });

  it("el interruptor Con pruebas nuevas filtra de un toque y resalta el dato", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const pruebas = boton("Con pruebas nuevas");
    expect(pruebas.getAttribute("title")).toBe("1 caso");
    fireEvent.click(pruebas);
    expect(pruebas.getAttribute("aria-pressed")).toBe("true");
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud"]);
    expect(location.hash).toBe("#/?s.segunda.pruebas=con");
    expect([...document.querySelectorAll(".dato.eco")].map((d) => d.textContent)).toEqual(["Pruebas nuevas en 2ª"]);

    fireEvent.click(boton("Terminados"));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud", "Duque Salazar c. EPS Ceiba Salud"]);
    fireEvent.click(pruebas);
    expect(nombres()).toHaveLength(7);
    expect(document.querySelector(".dato.eco")).toBeNull();
  });

  it("un toque en la franja deja solo ese estado; «Ver todos los abiertos» vuelve al defecto", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    fireEvent.click(boton("Por decidir"));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud"]);
    expect(boton("Faltan documentos").getAttribute("aria-pressed")).toBe("false");
    expect(cuenta()).toBe("1 de 7 casos");
    expect(location.hash).toBe("#/?e=decidir");

    fireEvent.click(boton("Ver todos los abiertos"));
    expect(nombres()).toHaveLength(5);
    expect(location.hash).toBe("#/");
  });

  it("la pastilla abre sus opciones con conteos, filtra, cierra con «Listo» y se quita con su ✕", () => {
    const largo = history.length;
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const pastilla = boton("Entidad accionada");
    fireEvent.click(pastilla);
    const dialogo = panel("Entidad accionada");
    expect(pastilla.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(within(dialogo).getByRole("searchbox", { name: "Buscar en Entidad accionada" }));
    const opciones = within(dialogo).getAllByRole("checkbox");
    expect(opciones.map((o) => [o.closest("label")!.textContent, o.getAttribute("title")])).toEqual([
      ["EPS Ceiba Salud1", "1 caso"],
      ["Fondo Pensional Altamira1", "1 caso"],
      ["Aseguradora Montaña Azul1", "1 caso"],
      ["EPS Horizonte Salud S.A.S.1", "1 caso"],
    ]);
    expect(within(dialogo).getByRole("button", { name: "Listo · 5 casos" })).toBeTruthy();

    fireEvent.input(within(dialogo).getByRole("searchbox"), { target: { value: "horiz" } });
    expect(within(dialogo).getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.input(within(dialogo).getByRole("searchbox"), { target: { value: "xyz" } });
    expect(within(dialogo).getByText("Ninguna opción coincide.")).toBeTruthy();
    fireEvent.input(within(dialogo).getByRole("searchbox"), { target: { value: "" } });

    fireEvent.click(within(dialogo).getByRole("checkbox", { name: "EPS Ceiba Salud" }));
    expect(nombres()).toEqual(["Arango Londoño c. EPS Ceiba Salud"]);
    expect(location.hash).toBe("#/?s.entidad=eps%20ceiba%20salud");
    expect(history.length).toBe(largo);
    fireEvent.click(within(dialogo).getByRole("button", { name: "Listo · 1 caso" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    const conValor = boton("Entidad accionada: EPS Ceiba Salud");
    expect(document.activeElement).toBe(conValor);

    fireEvent.click(boton("Quitar el filtro Entidad accionada"));
    expect(nombres()).toHaveLength(5);
    expect(document.activeElement).toBe(boton("Entidad accionada"));
    expect(screen.queryByRole("button", { name: /^Quitar el filtro/ })).toBeNull();
  });

  it("el interruptor Con alertas filtra de un toque y muestra cuántos casos tienen alertas", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const alertas = boton("Con alertas");
    expect(alertas.getAttribute("title")).toBe("2 casos");
    fireEvent.click(alertas);
    expect(alertas.getAttribute("aria-pressed")).toBe("true");
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud", "Cárdenas Ospina c. Aseguradora Montaña Azul"]);
    fireEvent.click(alertas);
    expect(nombres()).toHaveLength(5);
  });

  it("Trabajado: un preset y luego dos días del histograma", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 17, 15, 0));
    render(<ListaCasos casos={FECHADOS} />);
    fireEvent.click(boton("Trabajado"));
    const dialogo = panel("Trabajado (última actividad en el caso)");
    const presets = Object.fromEntries(
      ["Hoy", "Ayer", "Últimos 7 días", "Este mes", "Mes pasado", "Cualquier fecha"].map((p) => [p, within(dialogo).getByRole("button", { name: p }).getAttribute("title")]),
    );
    expect(presets).toEqual({ Hoy: "2 casos", Ayer: "1 caso", "Últimos 7 días": "4 casos", "Este mes": "5 casos", "Mes pasado": "0 casos", "Cualquier fecha": "5 casos" });

    fireEvent.click(within(dialogo).getByRole("button", { name: "Hoy" }));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud", "Restrepo Gil c. Fondo Pensional Altamira"]);
    expect(within(dialogo).getByRole("button", { name: "Hoy" }).getAttribute("aria-pressed")).toBe("true");
    expect(boton("Trabajado: Hoy")).toBeTruthy();

    const barras = within(dialogo).getAllByRole("button", { name: /de (octubre|noviembre)(, fin de semana)?: \d+ casos?$/ });
    expect(barras).toHaveLength(30);
    const dia13 = within(dialogo).getByRole("button", { name: /13 de noviembre: 1 caso$/ });
    expect(dia13.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(dia13);
    expect(dia13.getAttribute("aria-pressed")).toBe("true");
    expect(nombres()).toEqual(["Arango Londoño c. EPS Ceiba Salud"]);
    expect(boton("Trabajado: 13 nov.")).toBeTruthy();
    expect(within(dialogo).getByText("Ahora toque el último día del rango.")).toBeTruthy();
    fireEvent.click(within(dialogo).getByRole("button", { name: /16 de noviembre/ }));
    expect(nombres()).toEqual(["Cárdenas Ospina c. Aseguradora Montaña Azul", "Arango Londoño c. EPS Ceiba Salud"]);
    expect(boton("Trabajado: 13 nov. – 16 nov.")).toBeTruthy();
    expect(location.hash).toBe("#/?d=2026-11-13&h=2026-11-16");
    expect((within(dialogo).getByLabelText("Desde") as HTMLInputElement).value).toBe("2026-11-13");
    expect(within(dialogo).getAllByRole("button", { pressed: true, name: /de noviembre/ })).toHaveLength(4);
  });

  it("el histograma raya los fines de semana y los festivos que publica el servidor", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 17, 15, 0));
    estadoServidor.value = { festivos: ["2026-11-02", "2026-11-16", "2026-12-08"] } as EstadoServidor;
    render(<ListaCasos casos={FECHADOS} />);
    fireEvent.click(boton("Trabajado"));
    const dialogo = panel("Trabajado (última actividad en el caso)");
    const barra = (nombre: RegExp) => within(dialogo).getByRole("button", { name: nombre });
    const rayada = (nombre: RegExp) => barra(nombre).classList.contains("inhabil");
    expect(barra(/16 de noviembre/).getAttribute("aria-label")).toBe("lunes, 16 de noviembre, festivo: 1 caso");
    expect(barra(/14 de noviembre/).getAttribute("aria-label")).toBe("sábado, 14 de noviembre, fin de semana: 0 casos");
    expect(barra(/13 de noviembre/).getAttribute("aria-label")).toBe("viernes, 13 de noviembre: 1 caso");
    expect([rayada(/16 de noviembre/), rayada(/ 2 de noviembre/), rayada(/15 de noviembre/), rayada(/13 de noviembre/), rayada(/17 de noviembre/)]).toEqual([true, true, true, false, false]);
    expect(within(dialogo).getAllByRole("button", { name: /, festivo:/ })).toHaveLength(2);
    expect(within(dialogo).getByText("Toque un día, o dos para un rango. Rayado: fin de semana o festivo.")).toBeTruthy();
  });

  it("las baldosas de Plazos cuentan sin su propio filtro, filtran de un toque y quedan en la URL", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const plazos = screen.getByRole("group", { name: "Plazos" });
    const baldosas = () => within(plazos).getAllByRole("button").map((b) => [b.getAttribute("aria-label"), b.getAttribute("aria-pressed")]);
    expect(baldosas()).toEqual([
      ["Vencidos: 1 caso", "false"],
      ["Vencen hoy o en 1 día: 1 caso", "false"],
      ["Vencen en 2 a 5 días: 1 caso", "false"],
    ]);

    fireEvent.click(boton(/^Vencidos/));
    expect(boton(/^Vencidos/).getAttribute("aria-pressed")).toBe("true");
    expect(nombres()).toEqual(["Cárdenas Ospina c. Aseguradora Montaña Azul"]);
    expect(location.hash).toBe("#/?pl=vencido");
    fireEvent.click(boton(/^Vencen hoy o en 1 día/));
    expect(nombres()).toEqual(["Cárdenas Ospina c. Aseguradora Montaña Azul", "Arango Londoño c. EPS Ceiba Salud"]);
    expect(location.hash).toBe("#/?pl=vencido,pronto");
    expect(cuenta()).toBe("2 de 7 casos");
    expect(baldosas()).toEqual([
      ["Vencidos: 1 caso", "true"],
      ["Vencen hoy o en 1 día: 1 caso", "true"],
      ["Vencen en 2 a 5 días: 1 caso", "false"],
    ]);

    // Las demás facetas sí cuentan: con alertas, nada vence hoy.
    fireEvent.click(boton("Con alertas"));
    expect(boton(/^Vencen hoy o en 1 día/).getAttribute("aria-label")).toBe("Vencen hoy o en 1 día: 0 casos");
    expect(boton(/^Vencen hoy o en 1 día/).className).not.toContain("cero");
    fireEvent.click(boton(/^Vencen hoy o en 1 día/));
    expect(boton(/^Vencen hoy o en 1 día/).className).toBe("plazo alerta cero");
    expect(location.hash).toBe("#/?pl=vencido&s.alertas=con");

    fireEvent.click(boton("Limpiar filtros"));
    expect(baldosas().every(([, pulsada]) => pulsada === "false")).toBe(true);
    expect(location.hash).toBe("#/");
  });

  it("sin ningún caso con término no muestra las baldosas de Plazos", () => {
    render(<ListaCasos casos={CASOS.map((c) => ({ ...c, termino: null, vence: null, dias_restantes: null }))} proceso="segunda" />);
    expect(screen.getByRole("group", { name: "Estado" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Plazos" })).toBeNull();
    const chips = [...document.querySelectorAll("article .chip")].map((c) => c.textContent);
    expect(chips.filter((t) => /^(Vence|Venció|Falta)/.test(t ?? ""))).toEqual([]);
  });

  it("cada ficha muestra su plazo en el tono de su baldosa, con la regla en el título", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 17, 15, 0));
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const chip = (texto: string) => screen.getByText(texto);
    expect(chip("Venció hace 2 días hábiles").className).toBe("chip mal");
    expect(chip("Venció hace 2 días hábiles").getAttribute("title")).toBe(
      "Recibido el 14 de octubre de 2026; vence el 12 de noviembre de 2026 (20 días hábiles)",
    );
    expect(chip("Vence hoy").className).toBe("chip mal");
    expect(chip("Faltan 3 días hábiles").className).toBe("chip alerta");
    expect(chip("Faltan 14 días calendario").className).toBe("chip");
    expect(chip("Faltan 14 días calendario").getAttribute("title")).toBe("Recibido el 3 de noviembre de 2026; vence el 1 de diciembre de 2026 (28 días calendario)");
    const zapata = screen.getByRole("link", { name: /Zapata Henao/ }).closest("article")!;
    expect(zapata.querySelector(".chip")).toBeNull();

    fireEvent.click(boton("Compacta"));
    const cardenas = screen.getByRole("link", { name: /Cárdenas Ospina/ }).closest("article")!;
    expect([...cardenas.querySelectorAll(".c-marcas .chip")].map((c) => c.textContent)).toEqual(["Venció hace 2 días hábiles", "2 alertas"]);
    fireEvent.click(boton("Terminados"));
    const mejia = screen.getByRole("link", { name: /Mejía Ríos/ }).closest("article")!;
    expect(mejia.querySelector(".chip")).toBeNull();
  });

  it("«Quitar» en el pie de Trabajado descarta el primer toque del rango", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 17, 15, 0));
    render(<ListaCasos casos={FECHADOS} />);
    fireEvent.click(boton("Trabajado"));
    const dialogo = panel("Trabajado (última actividad en el caso)");
    fireEvent.click(within(dialogo).getByRole("button", { name: /13 de noviembre/ }));
    expect(within(dialogo).getByText("Ahora toque el último día del rango.")).toBeTruthy();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Quitar" }));
    expect(within(dialogo).queryByText("Ahora toque el último día del rango.")).toBeNull();
    fireEvent.click(within(dialogo).getByRole("button", { name: /16 de noviembre/ }));
    expect(boton("Trabajado: 16 nov.")).toBeTruthy();
    expect(location.hash).toBe("#/?d=2026-11-16&h=2026-11-16");
  });

  it("sin resultados sugiere el filtro que más casos devuelve", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    fireEvent.input(screen.getByRole("searchbox", { name: "Buscar casos" }), { target: { value: "zzz" } });
    expect(screen.getByText("Ningún caso coincide con «zzz».")).toBeTruthy();
    fireEvent.click(boton("Quitar Búsqueda «zzz» · 5 casos"));
    expect(nombres()).toHaveLength(5);
    expect((screen.getByRole("searchbox", { name: "Buscar casos" }) as HTMLInputElement).value).toBe("");

    fireEvent.click(boton("Con alertas"));
    fireEvent.click(boton("Entidad accionada"));
    fireEvent.click(within(panel("Entidad accionada")).getByRole("checkbox", { name: "EPS Ceiba Salud" }));
    expect(screen.getByText(/^Ningún caso coincide con estos filtros/)).toBeTruthy();
    fireEvent.click(boton("Quitar Entidad accionada: EPS Ceiba Salud · 2 casos"));
    expect(nombres()).toEqual(["Quintero Bedoya c. EPS Horizonte Salud", "Cárdenas Ospina c. Aseguradora Montaña Azul"]);
  });

  it("si todo está terminado ofrece verlos", () => {
    render(<ListaCasos casos={CASOS.filter((c) => c.estado === "terminado")} proceso="segunda" />);
    expect(screen.getByText("No hay casos abiertos")).toBeTruthy();
    fireEvent.click(boton("Ver los terminados (2)"));
    expect(nombres()).toEqual(["Mejía Ríos c. Fondo Pensional Altamira", "Duque Salazar c. EPS Ceiba Salud"]);
    expect(boton("Terminados").getAttribute("aria-pressed")).toBe("true");
  });

  it("Limpiar quita los filtros y Deshacer los devuelve", () => {
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    fireEvent.click(boton("Con alertas"));
    fireEvent.click(boton("Terminados"));
    expect(cuenta()).toBe("2 de 7 casos");
    fireEvent.click(boton("Limpiar filtros"));
    expect(cuenta()).toBe("5 casos abiertos");
    expect(screen.getByText(/Filtros limpiados/)).toBeTruthy();
    expect(document.activeElement).toBe(boton("Deshacer"));
    expect(location.hash).toBe("#/");

    fireEvent.click(boton("Deshacer"));
    expect(cuenta()).toBe("2 de 7 casos");
    expect(boton("Con alertas").getAttribute("aria-pressed")).toBe("true");
    expect(boton("Terminados").getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: "Deshacer" })).toBeNull();
    expect(document.activeElement).toBe(boton("Limpiar filtros"));
  });

  it("Ordenar y Agrupar cambian la lista y quedan en la URL", () => {
    render(<ListaCasos casos={CASOS} />);
    expect(screen.getByRole("region", { name: "Mi trabajo" })).toBeTruthy();
    expect(screen.queryAllByRole("heading", { level: 4 })).toHaveLength(0);
    // Lo vencido y lo que vence hoy primero; luego por estado.
    expect(nombres()).toEqual([
      "Cárdenas Ospina c. Aseguradora Montaña Azul",
      "Arango Londoño c. EPS Ceiba Salud",
      "Quintero Bedoya c. EPS Horizonte Salud",
      "Zapata Henao c. EPS Sendero",
      "Restrepo Gil c. Fondo Pensional Altamira",
    ]);

    fireEvent.change(screen.getByRole("combobox", { name: "Ordenar" }), { target: { value: "radicado" } });
    expect(nombres()).toEqual([
      "Arango Londoño c. EPS Ceiba Salud",
      "Restrepo Gil c. Fondo Pensional Altamira",
      "Cárdenas Ospina c. Aseguradora Montaña Azul",
      "Quintero Bedoya c. EPS Horizonte Salud",
      "Zapata Henao c. EPS Sendero",
    ]);

    fireEvent.change(screen.getByRole("combobox", { name: "Agrupar" }), { target: { value: "estado" } });
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Por decidir 1", "Faltan documentos 1", "Por preparar 2", "En redacción 1"]);
    expect(screen.getAllByRole("heading", { level: 4 })).toHaveLength(5);
    expect(location.hash).toBe("#/?o=radicado&g=estado");

    fireEvent.change(screen.getByRole("combobox", { name: "Ordenar" }), { target: { value: "vence" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Agrupar" }), { target: { value: "plazo" } });
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Vencidos 1",
      "Vencen hoy o en 1 día 1",
      "Vencen en 2 a 5 días 1",
      "Vencen en 6 días o más 1",
      "Sin término calculado 1",
    ]);
    expect(nombres()).toEqual([
      "Cárdenas Ospina c. Aseguradora Montaña Azul",
      "Arango Londoño c. EPS Ceiba Salud",
      "Quintero Bedoya c. EPS Horizonte Salud",
      "Restrepo Gil c. Fondo Pensional Altamira",
      "Zapata Henao c. EPS Sendero",
    ]);
    expect(location.hash).toBe("#/?o=vence&g=plazo");
  });

  it("la vista compacta conserva los nombres de los enlaces y se recuerda", () => {
    const { unmount } = render(<ListaCasos casos={CASOS} proceso="segunda" />);
    const decidir = "Decidir: Quintero Bedoya c. EPS Horizonte Salud";
    expect(screen.getByRole("link", { name: decidir }).closest("article")!.className).toContain("ficha");
    fireEvent.click(boton("Compacta"));
    expect(boton("Compacta").getAttribute("aria-pressed")).toBe("true");
    const enlace = screen.getByRole("link", { name: decidir });
    expect(enlace.closest("article")!.className).toContain("fila-c");
    expect(enlace.getAttribute("href")).toBe("#/segunda/quintero-bedoya/borrador");
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("aria-label"))).toEqual([
      decidir,
      "Completar: Cárdenas Ospina c. Aseguradora Montaña Azul",
      "Revisar documentos: Arango Londoño c. EPS Ceiba Salud",
      "Procesar documentos: Zapata Henao c. EPS Sendero",
      "Ver avance: Restrepo Gil c. Fondo Pensional Altamira",
    ]);
    expect(localStorage.getItem("judicabot:densidad")).toBe("compacta");
    unmount();
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    expect(boton("Compacta").getAttribute("aria-pressed")).toBe("true");
  });

  it("muestra de a diez casos con «Mostrar más»", () => {
    const muchos = Array.from({ length: 12 }, (_, i) => ({ ...CASOS[0]!, id: `c${i}`, nombre: `Caso ${i}` }));
    render(<ListaCasos casos={muchos} />);
    expect(nombres()).toHaveLength(10);
    fireEvent.click(boton("Mostrar 2 más"));
    expect(nombres()).toHaveLength(12);
    expect(screen.queryByRole("button", { name: /^Mostrar/ })).toBeNull();
    // El botón desaparece: el foco pasa al primer caso nuevo en vez de caer en <body>.
    expect(document.activeElement?.getAttribute("href")).toContain("/c10/");
  });

  it("no escribe en la URL de otra página mientras esta sigue montada", () => {
    history.replaceState(null, "", "#/?e=decidir");
    consulta.value = "e=decidir";
    render(<ListaCasos casos={CASOS} />);
    act(() => {
      ruta.value = { vista: "documentos", params: { caso: "c1" } };
    });
    fireEvent.input(screen.getByRole("searchbox", { name: "Buscar casos" }), { target: { value: "ceiba" } });
    expect(screen.getByRole("searchbox", { name: "Buscar casos" })).toHaveProperty("value", "ceiba");
    expect(location.hash).toBe("#/?e=decidir");
    expect(consulta.value).toBe("e=decidir");
  });

  it("lee los filtros del hash al montar y sigue los cambios de Atrás", async () => {
    const cambio = new Promise((r) => addEventListener("hashchange", r, { once: true }));
    location.hash = "#/segunda?e=terminado&o=radicado&zz=1";
    await cambio;
    render(<ListaCasos casos={CASOS} proceso="segunda" />);
    expect(nombres()).toEqual(["Duque Salazar c. EPS Ceiba Salud", "Mejía Ríos c. Fondo Pensional Altamira"]);
    expect((screen.getByRole("combobox", { name: "Ordenar" }) as HTMLSelectElement).value).toBe("radicado");

    act(() => {
      consulta.value = "q=ceiba";
    });
    expect(nombres()).toEqual(["Arango Londoño c. EPS Ceiba Salud"]);
    expect((screen.getByRole("searchbox", { name: "Buscar casos" }) as HTMLInputElement).value).toBe("ceiba");
  });

  it("sin casos muestra el estado vacío y, mientras carga, el aviso", () => {
    const { rerender } = render(<ListaCasos casos={[]} proceso="segunda" aviso={<p>Cargando casos…</p>} vacio={<p>Aún no hay casos</p>} />);
    expect(screen.getByText("Cargando casos…")).toBeTruthy();
    expect(screen.queryByRole("searchbox")).toBeNull();
    rerender(<ListaCasos casos={[]} proceso="segunda" vacio={<p>Aún no hay casos</p>} />);
    expect(screen.getByText("Aún no hay casos")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Casos" })).toBeTruthy();
  });
});

describe("ficha.css: la vista compacta no oculta chips", () => {
  it("las marcas pasan a otra línea en vez de recortarse, así el plazo y las alertas siempre se ven", () => {
    const css = readFileSync(join(import.meta.dirname, "ficha.css"), "utf8");
    const marcas = /\.c-marcas\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(marcas).toMatch(/flex-wrap:\s*wrap/);
    expect(marcas).not.toMatch(/overflow/);
  });
});
