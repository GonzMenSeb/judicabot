import { useEffect, useRef, useState } from "preact/hooks";
import { api, esAbortado, useEventos } from "../../api";
import type { JobEstado } from "./tipos";

const INTERVALO_MS = 1200;

export function Progreso({ jobId, onFin }: { jobId: string; onFin: (job: JobEstado | null) => void }) {
  const [segundos, setSegundos] = useState(0);
  const fin = useRef(onFin);
  fin.current = onFin;
  const url = typeof EventSource === "undefined" ? null : `/api/jobs/${encodeURIComponent(jobId)}/eventos`;
  const { eventos } = useEventos(url);
  const ultimo = eventos[eventos.length - 1];

  useEffect(() => {
    const inicio = Date.now();
    const reloj = setInterval(() => setSegundos(Math.floor((Date.now() - inicio) / 1000)), 1000);
    return () => clearInterval(reloj);
  }, []);

  useEffect(() => {
    const control = new AbortController();
    let temporizador: ReturnType<typeof setTimeout> | undefined;
    const consultar = async () => {
      try {
        const job = await api.get<JobEstado>(`/api/jobs/${encodeURIComponent(jobId)}`, { signal: control.signal });
        if (job.estado === "corriendo") temporizador = setTimeout(consultar, INTERVALO_MS);
        else fin.current(job);
      } catch (error) {
        if (esAbortado(error)) return;
        fin.current(null);
      }
    };
    void consultar();
    return () => {
      control.abort();
      clearTimeout(temporizador);
    };
  }, [jobId]);

  return (
    <section class="docs-progreso" role="status" aria-live="polite">
      <span class="giro" aria-hidden="true" />
      <div>
        <b>Leyendo el expediente…</b>
        <p class="sub">
          Se extrae el texto de cada PDF, se asigna su rol y se genera el auto que asume el conocimiento. Lleva {segundos} s.
        </p>
        {ultimo && <p class="docs-evento">{ultimo.texto}</p>}
      </div>
    </section>
  );
}
