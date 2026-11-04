import { useEffect, useRef, useState } from "preact/hooks";
import { navegar } from "../../rutas";

export interface GuardiaSalida {
  destino: string | null;
  salir: () => void;
  quedarse: () => void;
}

interface EventoNavegar extends Event {
  destination: { url: string; sameDocument: boolean };
}

const esPrimario = (e: MouseEvent) => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

export function useGuardiaSalida(sucio: boolean): GuardiaSalida {
  const [destino, setDestino] = useState<string | null>(null);
  const libre = useRef(false);

  useEffect(() => {
    if (!sucio) return;

    const alDescargar = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const alHacerClic = (e: MouseEvent) => {
      if (e.defaultPrevented || !esPrimario(e) || !(e.target instanceof Element)) return;
      const enlace = e.target.closest("a[href]");
      const href = enlace?.getAttribute("href");
      if (!href?.startsWith("#/") || href === location.hash || enlace?.getAttribute("target") === "_blank") return;
      e.preventDefault();
      setDestino(href);
    };
    const alNavegar = (e: Event) => {
      const { destination } = e as EventoNavegar;
      if (libre.current || !e.cancelable || !destination.sameDocument) return;
      const hash = new URL(destination.url).hash;
      if (hash === location.hash) return;
      e.preventDefault();
      setDestino(hash);
    };
    const navegacion = (window as unknown as { navigation?: EventTarget }).navigation;

    addEventListener("beforeunload", alDescargar);
    document.addEventListener("click", alHacerClic, true);
    navegacion?.addEventListener("navigate", alNavegar);
    return () => {
      removeEventListener("beforeunload", alDescargar);
      document.removeEventListener("click", alHacerClic, true);
      navegacion?.removeEventListener("navigate", alNavegar);
    };
  }, [sucio]);

  return {
    destino,
    quedarse: () => setDestino(null),
    salir: () => {
      if (destino === null) return;
      const adonde = destino;
      setDestino(null);
      libre.current = true;
      try {
        navegar(adonde);
      } finally {
        libre.current = false;
      }
    },
  };
}
