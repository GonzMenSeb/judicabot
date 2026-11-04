import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const MIN_TEXTO = 4.5;
const MIN_GRAFICO = 3;
const BLANCO = "#ffffff";

function colores(css: string): Record<string, string> {
  const salida: Record<string, string> = {};
  for (const m of css.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\b/gi)) salida[m[1]!] = m[2]!.toLowerCase();
  return salida;
}

const TOKENS = colores(readFileSync(join(SRC, "estilos/tokens.css"), "utf8"));

function canal(c: number): number {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminancia(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * canal(n >> 16) + 0.7152 * canal((n >> 8) & 255) + 0.0722 * canal(n & 255);
}

function contraste(a: string, b: string): number {
  const [claro, oscuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x) as [number, number];
  return (claro + 0.05) / (oscuro + 0.05);
}

function color(nombre: string): string {
  if (nombre === "blanco") return BLANCO;
  const valor = TOKENS[nombre];
  if (!valor) throw new Error(`Falta el token --${nombre} en tokens.css`);
  return valor;
}

function resolver(valor: string): string | null {
  const v = valor.trim().toLowerCase();
  const token = /^var\(--([\w-]+)\)$/.exec(v)?.[1];
  if (token) return TOKENS[token] ?? null;
  if (/^#[0-9a-f]{6}$/.test(v)) return v;
  if (/^#[0-9a-f]{3}$/.test(v)) return `#${[...v.slice(1)].map((c) => c + c).join("")}`;
  return null;
}

function hojas(carpeta: string): string[] {
  return readdirSync(carpeta).flatMap((nombre) => {
    const ruta = join(carpeta, nombre);
    if (statSync(ruta).isDirectory()) return hojas(ruta);
    return nombre.endsWith(".css") ? [ruta] : [];
  });
}

const SUPERFICIES = ["fondo", "fondo-2", "papel", "acento-fondo"];

describe("contraste de los tokens de color", () => {
  it("define los tokens que usan las pruebas", () => {
    for (const nombre of [...SUPERFICIES, "tinta", "suave", "tenue", "tenue-deco", "acento", "acento-2", "sello", "sello-2", "ok", "alerta", "mal"]) {
      expect(TOKENS[nombre], nombre).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it.each(SUPERFICIES.flatMap((s) => ["tinta", "suave", "tenue"].map((t) => [t, s] as const)))("texto --%s sobre --%s llega a 4,5:1", (texto, superficie) => {
    expect(contraste(color(texto), color(superficie))).toBeGreaterThanOrEqual(MIN_TEXTO);
  });

  it.each([
    ["acento", "fondo"],
    ["acento", "fondo-2"],
    ["acento", "papel"],
    ["acento", "acento-fondo"],
    ["acento-2", "acento-fondo"],
    ["sello", "papel"],
    ["sello", "sello-fondo"],
    ["ok", "ok-fondo"],
    ["alerta", "alerta-fondo"],
    ["mal", "mal-fondo"],
    ["ok", "fondo"],
    ["alerta", "fondo"],
    ["mal", "fondo"],
  ])("texto --%s sobre --%s llega a 4,5:1", (texto, superficie) => {
    expect(contraste(color(texto), color(superficie))).toBeGreaterThanOrEqual(MIN_TEXTO);
  });

  it.each(["acento", "acento-2", "sello", "sello-2", "mal", "ok", "alerta", "tinta"])("texto blanco sobre --%s llega a 4,5:1", (fondo) => {
    expect(contraste(BLANCO, color(fondo))).toBeGreaterThanOrEqual(MIN_TEXTO);
  });

  it.each(SUPERFICIES)("el gris decorativo --tenue-deco sobre --%s llega a 3:1", (superficie) => {
    expect(contraste(color("tenue-deco"), color(superficie))).toBeGreaterThanOrEqual(MIN_GRAFICO);
  });

  it("--tenue no baja del umbral de texto aunque se parezca a --suave", () => {
    expect(contraste(color("tenue"), color("fondo-2"))).toBeGreaterThanOrEqual(MIN_TEXTO);
    expect(color("tenue")).not.toBe(color("tenue-deco"));
  });
});

describe("contraste de los pares color/fondo de las hojas de estilo", () => {
  const pares: { origen: string; selector: string; texto: string; fondo: string }[] = [];
  for (const ruta of hojas(SRC)) {
    const css = readFileSync(ruta, "utf8");
    for (const regla of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const cuerpo = regla[2]!;
      const fondo = /(?:^|;)\s*background(?:-color)?:\s*([^;]+)/.exec(cuerpo)?.[1];
      const texto = /(?:^|;)\s*color:\s*([^;]+)/.exec(cuerpo)?.[1];
      const f = fondo ? resolver(fondo) : null;
      const t = texto ? resolver(texto) : null;
      if (f && t) pares.push({ origen: ruta.slice(SRC.length + 1), selector: regla[1]!.trim(), texto: t, fondo: f });
    }
  }

  it("encuentra los chips, avisos, botones y etiquetas definidos con colores resolubles", () => {
    expect(pares.length).toBeGreaterThanOrEqual(30);
    const selectores = pares.map((p) => p.selector);
    for (const esperado of [".chip.ok", ".chip.alerta", ".chip.mal", ".chip.info", ".chip.sello", ".aviso.ok", ".aviso.alerta", ".aviso.error", ".chip"]) {
      expect(selectores, esperado).toContain(esperado);
    }
  });

  it("ningún par color/fondo declarado en la misma regla queda bajo 4,5:1", () => {
    const bajos = pares
      .map((p) => ({ ...p, razon: contraste(p.texto, p.fondo) }))
      .filter((p) => p.razon < MIN_TEXTO)
      .map((p) => `${p.origen} ${p.selector}: ${p.razon.toFixed(2)}`);
    expect(bajos).toEqual([]);
  });
});
