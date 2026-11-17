import { describe, expect, it } from "vitest";
import { localizar, resaltar, type PasajeCitado } from "./resaltar";

const PAGINA = [
  "PODER ESPECIAL",
  "Señores",
  "TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL",
  "",
  "PEDRO ALVARADO LEMA, mayor de edad, identificado con la cédula de ciudadanía No. 71.000.318, obrando en",
  "calidad de representante legal de SALUD VITAL EPS S.A.S., confiero poder especial, amplio y suficiente a la",
  "doctora MARCELA ORTIZ PEÑA, identificada con la cédula de ciudadanía No. 43.000.021, para que conteste la",
  "acción de tutela de la referencia.",
  "Atentamente,",
].join("\n");

const CITA = "confiero poder especial, amplio y suficiente a la doctora MARCELA ORTIZ PEÑA";
const sin = (cita: string): PasajeCitado => ({ cita, inicio: null, fin: null });
const marcado = (segmentos: ReturnType<typeof resaltar>) => segmentos.filter((s) => s.marcado).map((s) => s.texto);
const unido = (segmentos: ReturnType<typeof resaltar>) => segmentos.map((s) => s.texto).join("");

describe("resaltar: con offsets del servidor", () => {
  it("marca el tramo [inicio, fin) cuando coincide con la cita", () => {
    const inicio = PAGINA.indexOf("confiero");
    const fin = PAGINA.indexOf("ORTIZ PEÑA") + "ORTIZ PEÑA".length;
    const segmentos = resaltar(PAGINA, { cita: CITA.replace(" a la doctora", " a la\ndoctora"), inicio, fin });
    expect(marcado(segmentos)).toEqual([PAGINA.slice(inicio, fin)]);
    expect(unido(segmentos)).toBe(PAGINA);
    expect(segmentos.map((s) => s.marcado)).toEqual([false, true, false]);
  });

  it("deja fuera los espacios y saltos de los bordes del tramo", () => {
    const inicio = PAGINA.indexOf("Atentamente,") - 1;
    expect(marcado(resaltar(PAGINA, { cita: "Atentamente", inicio, fin: PAGINA.length }))).toEqual(["Atentamente,"]);
  });

  it("acepta los offsets cuando la cita viene vacía", () => {
    expect(marcado(resaltar("uno dos tres", { cita: "", inicio: 4, fin: 7 }))).toEqual(["dos"]);
  });

  it("ignora los offsets desplazados y busca la cita", () => {
    const corrido = resaltar(PAGINA, { cita: CITA, inicio: 3, fin: 40 });
    expect(marcado(corrido)).toHaveLength(1);
    expect(marcado(corrido)[0]).toContain("confiero");
    expect(marcado(corrido)[0]).toContain("ORTIZ PEÑA");
  });

  it.each([
    ["negativo", -4, 20],
    ["fuera de la página", 10, PAGINA.length + 50],
    ["invertido", 40, 10],
    ["vacío", 12, 12],
    ["fraccionario", 1.5, 9],
  ])("descarta un rango %s", (_nombre, inicio, fin) => {
    const segmentos = resaltar(PAGINA, { cita: CITA, inicio, fin });
    expect(marcado(segmentos)[0]).toContain("confiero");
  });

  it("sin cita y con offsets fuera de rango no marca nada", () => {
    expect(marcado(resaltar(PAGINA, { cita: "", inicio: 5, fin: PAGINA.length + 1 }))).toEqual([]);
  });

  it("acepta el tramo cuando solo coinciden el comienzo y el final de la cita", () => {
    const inicio = PAGINA.indexOf("confiero");
    const fin = PAGINA.indexOf("ORTIZ PEÑA") + "ORTIZ PEÑA".length;
    const cita = "confiero poder especial, amplio y suficiente a la doctora, textualmente MARCELA ORTIZ PEÑA";
    expect(marcado(resaltar(PAGINA, { cita, inicio, fin }))).toEqual([PAGINA.slice(inicio, fin)]);
  });
});

describe("resaltar: buscando la cita", () => {
  it("encuentra la cita aunque cambien los renglones y marca el original", () => {
    const segmentos = resaltar(PAGINA, sin(CITA));
    expect(marcado(segmentos)).toEqual(["confiero poder especial, amplio y suficiente a la\ndoctora MARCELA ORTIZ PEÑA"]);
    expect(unido(segmentos)).toBe(PAGINA);
  });

  it("ignora mayúsculas y tildes", () => {
    expect(marcado(resaltar(PAGINA, sin("SEÑORES TRIBUNAL superior del distrito")))).toEqual(["Señores\nTRIBUNAL SUPERIOR DEL DISTRITO"]);
    expect(marcado(resaltar(PAGINA, sin("cedula de CIUDADANIA no. 43.000.021")))).toEqual(["cédula de ciudadanía No. 43.000.021"]);
    expect(marcado(resaltar(PAGINA, sin("senores")))).toEqual(["Señores"]);
  });

  it("ignora los espacios repetidos y los saltos de renglón de la cita", () => {
    expect(marcado(resaltar(PAGINA, sin("  acción   de\n\ttutela  de la referencia  ")))).toEqual(["acción de tutela de la referencia"]);
  });

  it("ignora los puntos suspensivos de los extremos", () => {
    expect(marcado(resaltar(PAGINA, sin("…poder especial, amplio y suficiente…")))).toEqual(["poder especial, amplio y suficiente"]);
    expect(marcado(resaltar(PAGINA, sin("[...] poder especial, amplio ...")))).toEqual(["poder especial, amplio"]);
  });

  it("encuentra una palabra partida con guion al final del renglón", () => {
    const texto = "El apoderado debe acreditar la representa-\nción que invoca ante el despacho.";
    expect(marcado(resaltar(texto, sin("acreditar la representación que invoca")))).toEqual(["acreditar la representa-\nción que invoca"]);
  });

  it("encuentra la cita cuando ella conserva el guion colapsado", () => {
    const texto = "El apoderado debe acreditar la representa-\nción que invoca ante el despacho.";
    expect(marcado(resaltar(texto, sin("acreditar la representa- ción que invoca")))).toEqual(["acreditar la representa-\nción que invoca"]);
  });

  it("encuentra el guion blando y el guion largo de fin de renglón", () => {
    expect(marcado(resaltar("poder repre­sentante legal", sin("poder representante")))).toEqual(["poder repre­sentante"]);
    expect(marcado(resaltar("poder repre‐ \nsentante legal", sin("poder representante legal")))).toEqual(["poder repre‐ \nsentante legal"]);
  });

  it("no une un guion de medio de renglón", () => {
    const texto = "el decreto-ley aplicable";
    expect(marcado(resaltar(texto, sin("decreto-ley aplicable")))).toEqual(["decreto-ley aplicable"]);
    expect(marcado(resaltar(texto, sin("decretoley")))).toEqual([]);
  });

  it("entiende el texto con tildes descompuestas", () => {
    const texto = "la cédula de ciudadanía";
    expect(marcado(resaltar(texto, sin("cédula de ciudadanía")))).toEqual(["cédula de ciudadanía"]);
    expect(marcado(resaltar("la cédula de ciudadanía", sin("cédula de ciudadanía")))).toEqual(["cédula de ciudadanía"]);
  });

  it("marca desde el comienzo hasta el final cuando la cita tiene puntos suspensivos en medio", () => {
    const cita = "confiero poder especial, amplio y suficiente … MARCELA ORTIZ PEÑA, identificada con la cédula";
    const [tramo] = marcado(resaltar(PAGINA, sin(cita)));
    expect(tramo).toMatch(/^confiero poder especial/);
    expect(tramo).toMatch(/identificada con la cédula$/);
  });

  it("no marca nada si el pasaje no está", () => {
    const segmentos = resaltar(PAGINA, sin("la parte accionada niega todo lo dicho por la accionante"));
    expect(segmentos).toEqual([{ texto: PAGINA, marcado: false }]);
  });

  it("no marca una cita sin palabras", () => {
    expect(marcado(resaltar(PAGINA, sin("… —")))).toEqual([]);
    expect(localizar(PAGINA, sin(""))).toBeNull();
  });

  it("marca la primera aparición", () => {
    const texto = "pagos al contado. pagos al contado.";
    expect(localizar(texto, sin("pagos al contado"))).toEqual([0, 16]);
  });

  it("deja el texto de una página vacía sin segmentos", () => {
    expect(resaltar("", sin("algo"))).toEqual([]);
  });

  it("entrega el texto tal cual, sin interpretarlo como HTML", () => {
    const texto = "Obra <b>MARCELA</b> & <script>alert(1)</script> como apoderada";
    const segmentos = resaltar(texto, sin("<b>MARCELA</b> & <script>alert(1)</script>"));
    expect(marcado(segmentos)).toEqual(["b>MARCELA</b> & <script>alert(1)</script"]);
    expect(unido(segmentos)).toBe(texto);
  });
});
