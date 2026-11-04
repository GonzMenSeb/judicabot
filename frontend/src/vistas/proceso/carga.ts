import { api, esAbortado } from "../../api";
import { casoActual, jobActual } from "../../estado";
import type { Carga, EstadoCaso, InfoJob } from "./tipos";

export async function cargar(caso: string, signal: AbortSignal): Promise<Carga> {
  const estado = await api.get<EstadoCaso>(`/api/casos/${encodeURIComponent(caso)}/estado`, { signal });
  const candidato = estado.job_activo ?? jobActual.peek();
  if (!candidato) return { estado, jobId: null, cmd: null };

  let job: InfoJob | null = null;
  try {
    job = await api.get<InfoJob>(`/api/jobs/${encodeURIComponent(candidato)}`, { signal });
  } catch (error) {
    if (esAbortado(error)) throw error;
  }
  if (job && job.caso !== caso) job = null;

  if (estado.job_activo) return { estado, jobId: estado.job_activo, cmd: job?.cmd ?? null };
  if (job) return { estado, jobId: job.id, cmd: job.cmd };
  if (casoActual.peek() === caso) return { estado, jobId: candidato, cmd: null };
  return { estado, jobId: null, cmd: null };
}
