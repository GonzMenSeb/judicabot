import { api } from "../api/cliente";
import type { EstadoDataset } from "../api/contrato";

async function llevarAlServidor(): Promise<void> {
  const estado = await api.get<EstadoDataset>("/api/dataset");
  if (estado.vigente) return;
  const origen = await fetch(estado.url, { credentials: "omit", referrerPolicy: "no-referrer" });
  if (!origen.ok) return;
  const cuerpo = new FormData();
  cuerpo.append("archivo", await origen.blob(), "cc_sentencias.csv");
  await api.put<void>("/api/dataset", cuerpo);
}

let enCurso: Promise<void> | null = null;

export function sincronizarDataset(): Promise<void> {
  enCurso ??= llevarAlServidor().catch(() => undefined);
  return enCurso;
}
