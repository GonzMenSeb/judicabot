import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const KB = 1024;
const PRESUPUESTO = {
  "JS inicial": 60 * KB,
  "chunk de ruta": 25 * KB,
  "CSS inicial": 15 * KB,
  "CSS total": 25 * KB,
  fuentes: 60 * KB,
};

const dist = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "backend", "tutela2", "static", "dist");

function archivos(dir) {
  return readdirSync(dir).flatMap((nombre) => {
    const ruta = join(dir, nombre);
    return statSync(ruta).isDirectory() ? archivos(ruta) : [ruta];
  });
}

const gzip = (ruta) => gzipSync(readFileSync(ruta), { level: 9 }).length;
const kb = (bytes) => `${(bytes / KB).toFixed(2)} KB`;

let todos;
let html;
try {
  todos = archivos(dist);
  html = readFileSync(join(dist, "index.html"), "utf8");
} catch {
  console.error(`No hay build en ${dist}. Ejecute pnpm build primero.`);
  process.exit(1);
}

const iniciales = new Set(
  [...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)="([^"]+\.js)"[^>]*>/g)].map((m) => join(dist, m[1].replace(/^\//, ""))),
);
const js = todos.filter((f) => f.endsWith(".js"));
const css = todos.filter((f) => f.endsWith(".css"));
const fuentes = todos.filter((f) => /\.(woff2?|ttf|otf)$/.test(f));

const medidas = [];
const suma = (lista) => lista.reduce((total, f) => total + gzip(f), 0);

medidas.push({ nombre: "JS inicial", bytes: suma(js.filter((f) => iniciales.has(f))), limite: PRESUPUESTO["JS inicial"] });
for (const f of js.filter((f) => !iniciales.has(f))) {
  medidas.push({ nombre: `chunk de ruta ${relative(dist, f)}`, bytes: gzip(f), limite: PRESUPUESTO["chunk de ruta"] });
}
const cssIniciales = new Set(
  [...html.matchAll(/<link\b[^>]*\bhref="([^"]+\.css)"[^>]*>/g)].map((m) => join(dist, m[1].replace(/^\//, ""))),
);
medidas.push({ nombre: "CSS inicial", bytes: suma(css.filter((f) => cssIniciales.has(f))), limite: PRESUPUESTO["CSS inicial"] });
medidas.push({ nombre: "CSS total", bytes: suma(css), limite: PRESUPUESTO["CSS total"] });
medidas.push({ nombre: "fuentes", bytes: suma(fuentes), limite: PRESUPUESTO.fuentes });

let falla = false;
for (const { nombre, bytes, limite } of medidas) {
  const excede = bytes > limite;
  falla ||= excede;
  console.log(`${excede ? "FALLA" : "ok   "}  ${nombre.padEnd(48)} ${kb(bytes).padStart(10)} / ${kb(limite)}`);
}
if (iniciales.size === 0) {
  console.error("No se encontró el JS inicial en index.html.");
  process.exit(1);
}
process.exit(falla ? 1 : 0);
