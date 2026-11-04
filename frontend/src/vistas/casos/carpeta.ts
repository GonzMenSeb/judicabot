export interface ArchivoSeleccionado {
  archivo: File;
  ruta: string;
}

interface EntradaArchivo {
  isFile: true;
  isDirectory: false;
  fullPath: string;
  file(ok: (archivo: File) => void, mal: (error: unknown) => void): void;
}

interface LectorDirectorio {
  readEntries(ok: (lote: Entrada[]) => void, mal: (error: unknown) => void): void;
}

interface EntradaDirectorio {
  isFile: false;
  isDirectory: true;
  fullPath: string;
  createReader(): LectorDirectorio;
}

export type Entrada = EntradaArchivo | EntradaDirectorio;

export interface ItemSoltado {
  kind: string;
  webkitGetAsEntry?: () => unknown;
}

export interface FuenteSoltada {
  items?: ArrayLike<ItemSoltado> | null;
  files?: ArrayLike<File> | null;
}

const leerLote = (lector: LectorDirectorio) => new Promise<Entrada[]>((ok, mal) => lector.readEntries(ok, mal));
const archivoDe = (entrada: EntradaArchivo) => new Promise<File>((ok, mal) => entrada.file(ok, mal));

export async function recorrerEntrada(entrada: Entrada, salida: ArchivoSeleccionado[]): Promise<void> {
  if (entrada.isFile) {
    const archivo = await archivoDe(entrada);
    salida.push({ archivo, ruta: entrada.fullPath.replace(/^\/+/, "") || archivo.name });
    return;
  }
  if (!entrada.isDirectory) return;
  const lector = entrada.createReader();
  for (;;) {
    const lote = await leerLote(lector);
    if (lote.length === 0) break;
    for (const hija of lote) await recorrerEntrada(hija, salida);
  }
}

export async function archivosSoltados(fuente: FuenteSoltada): Promise<ArchivoSeleccionado[]> {
  const entradas = Array.from(fuente.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => (item.webkitGetAsEntry ? (item.webkitGetAsEntry() as Entrada | null) : null));
  const sueltos = Array.from(fuente.files ?? []);
  const salida: ArchivoSeleccionado[] = [];
  const validas = entradas.filter((e): e is Entrada => e !== null);
  if (validas.length > 0 && validas.length === entradas.length) {
    for (const entrada of validas) await recorrerEntrada(entrada, salida);
  } else {
    for (const archivo of sueltos) salida.push({ archivo, ruta: archivo.webkitRelativePath || archivo.name });
  }
  return salida;
}

export function archivosElegidos(archivos: ArrayLike<File> | null | undefined): ArchivoSeleccionado[] {
  return Array.from(archivos ?? [], (archivo) => ({ archivo, ruta: archivo.webkitRelativePath || archivo.name }));
}

const esOculta = (ruta: string) => ruta.split("/").some((parte) => parte.startsWith("."));

export const sinOcultos = (lista: ArchivoSeleccionado[]) => lista.filter((x) => !esOculta(x.ruta));

export function raizComun(rutas: string[]): string | null {
  if (rutas.length === 0) return null;
  const partes = rutas.map((r) => r.split("/"));
  if (partes.some((p) => p.length < 2)) return null;
  const primera = partes[0]?.[0] ?? "";
  return partes.every((p) => p[0] === primera) ? primera : null;
}

export interface ResumenSeleccion {
  total: number;
  bytes: number;
  raiz: string | null;
}

export function resumirSeleccion(lista: ArchivoSeleccionado[]): ResumenSeleccion {
  return {
    total: lista.length,
    bytes: lista.reduce((suma, x) => suma + x.archivo.size, 0),
    raiz: raizComun(lista.map((x) => x.ruta)),
  };
}

export function formatoTamano(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(1).replace(".", ",")} MB`;
}

export interface NodoCarpeta {
  nombre: string;
  ruta: string;
  carpetas: NodoCarpeta[];
  archivos: string[];
}

const comparar = (a: string, b: string) => a.localeCompare(b, "es", { numeric: true, sensitivity: "base" });

export function construirArbol(rutas: string[]): NodoCarpeta {
  const raiz = raizComun(rutas);
  const base: NodoCarpeta = { nombre: raiz ?? "", ruta: raiz ?? "", carpetas: [], archivos: [] };
  for (const ruta of rutas) {
    const partes = ruta.split("/");
    if (raiz !== null) partes.shift();
    const nombreArchivo = partes.pop() ?? ruta;
    let nodo = base;
    for (const parte of partes) {
      let hija = nodo.carpetas.find((c) => c.nombre === parte);
      if (!hija) {
        hija = { nombre: parte, ruta: nodo.ruta ? `${nodo.ruta}/${parte}` : parte, carpetas: [], archivos: [] };
        nodo.carpetas.push(hija);
      }
      nodo = hija;
    }
    nodo.archivos.push(nombreArchivo);
  }
  const ordenar = (nodo: NodoCarpeta) => {
    nodo.carpetas.sort((a, b) => comparar(a.nombre, b.nombre));
    nodo.archivos.sort(comparar);
    nodo.carpetas.forEach(ordenar);
  };
  ordenar(base);
  return base;
}

export const contarArchivos = (nodo: NodoCarpeta): number =>
  nodo.archivos.length + nodo.carpetas.reduce((suma, c) => suma + contarArchivos(c), 0);

const plano = (texto: string) =>
  texto
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();

export function esCarpetaPrimera(nombre: string): boolean {
  const c = plano(nombre);
  return /^01(?!\d)\W*(?:primera|1a|instancia)/.test(c) || c.includes("primera");
}

export function esCarpetaSegunda(nombre: string): boolean {
  const c = plano(nombre);
  return /^02(?!\d)/.test(c) || c.includes("segunda") || /^\s*2\s*(?:a|da|nda)?[\s._-]*instancia/.test(c) || /\bcircuito\b/.test(c);
}

export const nombreGenerico = (nombre: string) => esCarpetaPrimera(nombre) || esCarpetaSegunda(nombre) || /^C\d+/i.test(nombre);
