import { rmSync } from "node:fs";

export default function globalTeardown(): void {
  const raiz = process.env.E2E_RAIZ;
  if (raiz && !process.env.E2E_CONSERVAR) rmSync(raiz, { recursive: true, force: true });
}
