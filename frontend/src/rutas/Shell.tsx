import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { cargarEstadoServidor, estadoServidor, nombreModelo, tituloVista } from "../estado";
import { Toasts } from "../ui/Toasts";
import { Topbar } from "../ui/Topbar";
import type { SeccionTopbar } from "../ui/Topbar";
import { mostrada } from "./Rutas";
import { ruta } from "./router";
import type { NombreVista, Ruta } from "./router";

const MARCA = "Judicabot";

const TITULOS: Record<NombreVista, string> = {
  inicio: "",
  casos: "Casos de segunda instancia",
  formato: "Formato de documentos",
  ia: "Inteligencia artificial",
  documentos: "Documentos",
  proceso: "Proceso",
  borrador: "Borrador",
  decision: "Decisión",
  fallo: "Fallo",
};

export function tituloDeRuta({ vista, params }: Ruta): string {
  const partes = [TITULOS[vista], params.caso, MARCA].filter(Boolean);
  return partes.join(" · ");
}

export function seccionDe(vista: NombreVista): SeccionTopbar {
  return vista === "formato" || vista === "ia" ? vista : "inicio";
}

export function Shell({ children }: { children?: ComponentChildren }) {
  const principal = useRef<HTMLElement>(null);
  const primera = useRef(true);
  const destino = ruta.value;
  const visible = mostrada.value;
  const servidor = estadoServidor.value;
  const propio = tituloVista.value;

  useEffect(() => {
    void cargarEstadoServidor();
  }, []);

  useEffect(() => {
    if (!visible) return;
    if (primera.current) {
      primera.current = false;
      return;
    }
    window.scrollTo(0, 0);
    principal.current?.focus({ preventScroll: true });
  }, [visible]);

  useEffect(() => {
    document.title = propio ? `${propio} · ${MARCA}` : tituloDeRuta(visible ?? destino);
  }, [visible, destino, propio]);

  return (
    <>
      <Topbar
        seccion={seccionDe((visible ?? destino).vista)}
        clave={servidor ? servidor.api_key : null}
        modelo={servidor ? nombreModelo(servidor.modelo) : null}
      />
      <main id="contenido" class="lienzo" ref={principal} tabIndex={-1} aria-busy={visible !== destino ? "true" : undefined}>
        {children}
      </main>
      <Toasts />
    </>
  );
}
