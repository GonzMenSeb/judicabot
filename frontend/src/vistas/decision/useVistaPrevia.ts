import { useEffect, useRef, useState } from "preact/hooks";
import { api, cancelable, esAbortado } from "../../api";
import type { DecisionVistaRespuesta } from "../../api/contrato";
import type { DecisionCuerpo } from "./tipos";

export const ESPERA_MS = 250;

export interface VistaPrevia {
  datos: DecisionVistaRespuesta | null;
  pendiente: boolean;
  error: string | null;
  reintentar: () => void;
}

export function useVistaPrevia(caso: string, decision: DecisionCuerpo, activo: boolean): VistaPrevia {
  const [datos, setDatos] = useState<DecisionVistaRespuesta | null>(null);
  const [resuelto, setResuelto] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intento, setIntento] = useState(0);
  const siguiente = useRef(cancelable());
  const primera = useRef(true);
  const cuerpo = JSON.stringify(decision);

  useEffect(() => {
    if (!activo) return;
    let vigente = true;
    let enVuelo = false;
    const espera = primera.current ? 0 : ESPERA_MS;
    primera.current = false;
    const temporizador = setTimeout(() => {
      enVuelo = true;
      api
        .post<DecisionVistaRespuesta>(`/api/casos/${encodeURIComponent(caso)}/decision/vista`, JSON.parse(cuerpo), {
          signal: siguiente.current(),
        })
        .then((respuesta) => {
          if (!vigente) return;
          setDatos(respuesta);
          setError(null);
          setResuelto(cuerpo);
        })
        .catch((e: unknown) => {
          if (esAbortado(e) || !vigente) return;
          setError(e instanceof Error ? e.message : "No se pudo actualizar la vista previa.");
          setResuelto(cuerpo);
        });
    }, espera);
    return () => {
      vigente = false;
      clearTimeout(temporizador);
      if (enVuelo) siguiente.current();
    };
  }, [caso, cuerpo, activo, intento]);

  useEffect(() => {
    const cancelar = siguiente.current;
    return () => {
      cancelar();
    };
  }, []);

  return {
    datos,
    pendiente: activo && resuelto !== cuerpo,
    error,
    reintentar: () => {
      setResuelto(null);
      setIntento((n) => n + 1);
    },
  };
}
