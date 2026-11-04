import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function puertoLibre(): Promise<number> {
  const servidor = createServer();
  await new Promise<void>((ok) => servidor.listen(0, "127.0.0.1", ok));
  const direccion = servidor.address();
  await new Promise((ok) => servidor.close(ok));
  if (!direccion || typeof direccion === "string") throw new Error("No se obtuvo un puerto libre");
  return direccion.port;
}

process.env.E2E_RAIZ ??= mkdtempSync(join(tmpdir(), "judicabot-e2e-"));
process.env.E2E_PUERTO_ABIERTO ??= String(await puertoLibre());
process.env.E2E_PUERTO_COMPUERTA ??= String(await puertoLibre());
process.env.E2E_CLAVE ??= "e2e-clave-de-acceso";

const raiz = process.env.E2E_RAIZ;
const urlAbierto = `http://127.0.0.1:${process.env.E2E_PUERTO_ABIERTO}`;
const urlCompuerta = `http://127.0.0.1:${process.env.E2E_PUERTO_COMPUERTA}`;

function servidor(nombre: string, puerto: string, url: string, extra: Record<string, string> = {}) {
  const casos = join(raiz, nombre, "casos");
  return {
    command: `rm -rf "${join(raiz, nombre)}" && mkdir -p "${casos}" && exec uv run --project ../backend tutela2-ui`,
    url: `${url}/healthz`,
    reuseExistingServer: false,
    timeout: 90_000,
    stdout: "ignore" as const,
    stderr: (process.env.E2E_LOG ? "pipe" : "ignore") as "pipe" | "ignore",
    env: {
      ...(process.env as Record<string, string>),
      PORT: puerto,
      HOST: "127.0.0.1",
      CASOS_DIR: casos,
      TUTELA2_PROVEEDOR: "fake",
      ANTHROPIC_API_KEY: "",
      JEV_API_KEY: "",
      JUDICABOT_PASSWORD: "",
      ...extra,
    },
  };
}

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/globalSetup.ts",
  globalTeardown: "./e2e/globalTeardown.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["junit", { outputFile: "e2e-results.xml" }]] : "list",
  use: { trace: "retain-on-failure", viewport: { width: 1440, height: 900 }, locale: "es-CO" },
  projects: [
    {
      name: "abierto",
      testDir: "e2e/abierto",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, baseURL: urlAbierto },
    },
    {
      name: "compuerta",
      testDir: "e2e/compuerta",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, baseURL: urlCompuerta },
    },
  ],
  webServer: [
    servidor("abierto", process.env.E2E_PUERTO_ABIERTO, urlAbierto),
    servidor("compuerta", process.env.E2E_PUERTO_COMPUERTA, urlCompuerta, {
      JUDICABOT_PASSWORD: process.env.E2E_CLAVE,
      ANTHROPIC_API_KEY: "e2e-clave-sin-uso",
    }),
  ],
});
