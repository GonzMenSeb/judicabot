import { describe, expect, it } from "vitest";
import {
  archivosSoltados,
  construirArbol,
  contarArchivos,
  esCarpetaPrimera,
  esCarpetaSegunda,
  formatoTamano,
  nombreGenerico,
  raizComun,
  recorrerEntrada,
  resumirSeleccion,
  sinOcultos,
} from "./carpeta";
import type { ArchivoSeleccionado, Entrada } from "./carpeta";
import { archivoDe } from "./utilesPrueba";

const archivoFalso = (ruta: string): Entrada => ({
  isFile: true,
  isDirectory: false,
  fullPath: `/${ruta}`,
  file: (ok) => ok(archivoDe(ruta)),
});

function directorioFalso(ruta: string, hijas: Entrada[], tamanoLote = 2): Entrada {
  return {
    isFile: false,
    isDirectory: true,
    fullPath: `/${ruta}`,
    createReader() {
      let pendientes = [...hijas];
      return {
        readEntries(ok) {
          const lote = pendientes.slice(0, tamanoLote);
          pendientes = pendientes.slice(tamanoLote);
          ok(lote);
        },
      };
    },
  };
}

describe("recorrerEntrada", () => {
  it("recorre carpetas anidadas leyendo todos los lotes de readEntries", async () => {
    const raiz = directorioFalso("caso", [
      archivoFalso("caso/a.pdf"),
      directorioFalso("caso/C01", [archivoFalso("caso/C01/001.pdf"), archivoFalso("caso/C01/002.pdf"), archivoFalso("caso/C01/003.pdf")]),
      archivoFalso("caso/b.pdf"),
    ]);
    const salida: ArchivoSeleccionado[] = [];
    await recorrerEntrada(raiz, salida);
    expect(salida.map((x) => x.ruta).sort()).toEqual(["caso/C01/001.pdf", "caso/C01/002.pdf", "caso/C01/003.pdf", "caso/a.pdf", "caso/b.pdf"]);
  });

  it("usa el nombre del archivo si la ruta completa viene vacía", async () => {
    const salida: ArchivoSeleccionado[] = [];
    await recorrerEntrada({ isFile: true, isDirectory: false, fullPath: "/", file: (ok) => ok(archivoDe("solo.pdf")) }, salida);
    expect(salida[0]?.ruta).toBe("solo.pdf");
  });

  it("propaga el error de lectura", async () => {
    const roto: Entrada = {
      isFile: false,
      isDirectory: true,
      fullPath: "/x",
      createReader: () => ({ readEntries: (_ok, mal) => mal(new Error("sin permiso")) }),
    };
    await expect(recorrerEntrada(roto, [])).rejects.toThrow("sin permiso");
  });
});

describe("archivosSoltados", () => {
  it("lee las entradas de forma síncrona antes de esperar", async () => {
    let llamadas = 0;
    const entrada = directorioFalso("caso", [archivoFalso("caso/a.pdf")]);
    const promesa = archivosSoltados({
      items: [
        {
          kind: "file",
          webkitGetAsEntry: () => {
            llamadas += 1;
            return entrada;
          },
        },
      ],
      files: [],
    });
    expect(llamadas).toBe(1);
    expect((await promesa).map((x) => x.ruta)).toEqual(["caso/a.pdf"]);
  });

  it("ignora los items que no son archivos", async () => {
    const salida = await archivosSoltados({
      items: [{ kind: "string" }, { kind: "file", webkitGetAsEntry: () => archivoFalso("a.pdf") }],
    });
    expect(salida.map((x) => x.ruta)).toEqual(["a.pdf"]);
  });

  it("cae a files cuando no hay webkitGetAsEntry", async () => {
    const suelto = archivoDe("c/b.pdf");
    const salida = await archivosSoltados({ items: [{ kind: "file" }], files: [suelto] });
    expect(salida).toEqual([{ archivo: suelto, ruta: "c/b.pdf" }]);
  });

  it("cae a files cuando alguna entrada es nula", async () => {
    const suelto = archivoDe("z.pdf");
    const salida = await archivosSoltados({ items: [{ kind: "file", webkitGetAsEntry: () => null }], files: [suelto] });
    expect(salida.map((x) => x.ruta)).toEqual(["z.pdf"]);
  });
});

describe("selección", () => {
  const sel = (...rutas: string[]): ArchivoSeleccionado[] => rutas.map((ruta) => ({ archivo: archivoDe(ruta, "abcd"), ruta }));

  it("descarta rutas con segmentos ocultos", () => {
    expect(sinOcultos(sel("c/a.pdf", "c/.DS_Store", ".git/x", "c/.tmp/y.pdf")).map((x) => x.ruta)).toEqual(["c/a.pdf"]);
  });

  it("detecta la raíz común solo si todos están dentro de la misma carpeta", () => {
    expect(raizComun(["c/a.pdf", "c/d/b.pdf"])).toBe("c");
    expect(raizComun(["c/a.pdf", "otra/b.pdf"])).toBeNull();
    expect(raizComun(["a.pdf", "c/b.pdf"])).toBeNull();
    expect(raizComun([])).toBeNull();
  });

  it("resume total, bytes y raíz", () => {
    expect(resumirSeleccion(sel("c/a.pdf", "c/b.pdf"))).toEqual({ total: 2, bytes: 8, raiz: "c" });
  });

  it("formatea tamaños", () => {
    expect(formatoTamano(500)).toBe("500 B");
    expect(formatoTamano(2048)).toBe("2 KB");
    expect(formatoTamano(5.5 * 1048576)).toBe("5,5 MB");
  });
});

describe("construirArbol", () => {
  it("usa la carpeta común como raíz y ordena de forma natural", () => {
    const arbol = construirArbol(["T/01Primera/C01/010.pdf", "T/01Primera/C01/002.pdf", "T/02Segunda/x.pdf", "T/nota.txt"]);
    expect(arbol.nombre).toBe("T");
    expect(arbol.archivos).toEqual(["nota.txt"]);
    expect(arbol.carpetas.map((c) => c.nombre)).toEqual(["01Primera", "02Segunda"]);
    expect(arbol.carpetas[0]?.carpetas[0]?.archivos).toEqual(["002.pdf", "010.pdf"]);
    expect(contarArchivos(arbol)).toBe(4);
  });

  it("sin raíz común deja el nombre vacío y los archivos sueltos en la base", () => {
    const arbol = construirArbol(["a.pdf", "b.pdf"]);
    expect(arbol.nombre).toBe("");
    expect(arbol.archivos).toEqual(["a.pdf", "b.pdf"]);
  });
});

describe("clasificación de carpetas", () => {
  it.each(["01PrimeraInstancia", "01 Primera Instancia", "Primera instancia", "01.1aInstancia"])("%s es de primera", (n) => {
    expect(esCarpetaPrimera(n)).toBe(true);
    expect(esCarpetaSegunda(n)).toBe(false);
  });

  it.each(["02SegundaInstancia", "02 Segunda", "2da instancia", "Juzgado del Circuito"])("%s es de segunda", (n) => {
    expect(esCarpetaSegunda(n)).toBe(true);
  });

  it("marca como genéricos los nombres de instancia y de cuaderno", () => {
    expect(nombreGenerico("01PrimeraInstancia")).toBe(true);
    expect(nombreGenerico("C01Principal")).toBe(true);
    expect(nombreGenerico("Tutela 2026-00412")).toBe(false);
  });
});
