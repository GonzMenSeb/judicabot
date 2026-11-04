import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";

export const tituloVista = signal<string | null>(null);

export function useTitulo(titulo: string | null | undefined): void {
  useEffect(() => {
    if (!titulo) return;
    tituloVista.value = titulo;
    return () => {
      if (tituloVista.value === titulo) tituloVista.value = null;
    };
  }, [titulo]);
}
