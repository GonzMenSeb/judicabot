import type { EstadoCasoApi } from "../../api/contrato";

export interface EstadoCaso {
  estado: EstadoCasoApi;
  error: string | null;
  job_activo: string | null;
  resumen?: { decision?: { accion?: string } | null } | null;
}

export interface InfoJob {
  id: string;
  caso: string;
  cmd: string;
  estado: "corriendo" | "terminado" | "error";
  error: string | null;
}

export interface Carga {
  estado: EstadoCaso;
  jobId: string | null;
  cmd: string | null;
}
