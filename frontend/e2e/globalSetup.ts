import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

export default function globalSetup(): void {
  const raiz = process.env.E2E_RAIZ;
  if (!raiz) throw new Error("E2E_RAIZ no está definida");
  const insumos = join(raiz, "insumos");
  execFileSync("uv", ["run", "python", "scripts/caso_sintetico.py", "generar", insumos], {
    cwd: resolve(import.meta.dirname, "../../backend"),
    stdio: "pipe",
    timeout: 300_000,
  });
  const principal = join(insumos, "01PrimeraInstancia", "C01Principal");
  if (!existsSync(principal) || readdirSync(principal).filter((n) => n.endsWith(".pdf")).length !== 9) {
    throw new Error(`El caso sintético no generó los 9 PDF en ${principal}`);
  }
}
