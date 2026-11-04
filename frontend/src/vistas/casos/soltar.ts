import { useEffect, useRef, useState } from "preact/hooks";

const ESPERA_SIN_MOVIMIENTO_MS = 1500;

const traeArchivos = (dt: DataTransfer | null): dt is DataTransfer => dt !== null && Array.from(dt.types ?? []).includes("Files");

export function useSoltarGlobal(alSoltar: (dt: DataTransfer) => void, habilitado: boolean): boolean {
  const [arrastrando, setArrastrando] = useState(false);
  const alSoltarRef = useRef(alSoltar);
  const habilitadoRef = useRef(habilitado);
  alSoltarRef.current = alSoltar;
  habilitadoRef.current = habilitado;

  useEffect(() => {
    let profundidad = 0;
    let vigilante: ReturnType<typeof setTimeout> | undefined;

    const ocultar = () => {
      profundidad = 0;
      clearTimeout(vigilante);
      setArrastrando(false);
    };
    const mostrar = () => {
      clearTimeout(vigilante);
      vigilante = setTimeout(ocultar, ESPERA_SIN_MOVIMIENTO_MS);
      if (habilitadoRef.current) setArrastrando(true);
    };

    const alEntrar = (ev: DragEvent) => {
      if (!traeArchivos(ev.dataTransfer)) return;
      ev.preventDefault();
      profundidad += 1;
      mostrar();
    };
    const alPasar = (ev: DragEvent) => {
      if (!traeArchivos(ev.dataTransfer)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = habilitadoRef.current ? "copy" : "none";
      if (profundidad === 0) profundidad = 1;
      mostrar();
    };
    const alSalir = (ev: DragEvent) => {
      if (!traeArchivos(ev.dataTransfer)) return;
      profundidad = Math.max(0, profundidad - 1);
      if (profundidad === 0) ocultar();
    };
    const alCaer = (ev: DragEvent) => {
      if (!traeArchivos(ev.dataTransfer)) return;
      ev.preventDefault();
      const dt = ev.dataTransfer;
      ocultar();
      if (habilitadoRef.current) alSoltarRef.current(dt);
    };

    document.addEventListener("dragenter", alEntrar);
    document.addEventListener("dragover", alPasar);
    document.addEventListener("dragleave", alSalir);
    document.addEventListener("drop", alCaer);
    return () => {
      clearTimeout(vigilante);
      document.removeEventListener("dragenter", alEntrar);
      document.removeEventListener("dragover", alPasar);
      document.removeEventListener("dragleave", alSalir);
      document.removeEventListener("drop", alCaer);
    };
  }, []);

  return arrastrando;
}
