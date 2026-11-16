import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { cargarEstadoServidor, estadoServidor, tituloVista } from "../estado";
import { Toasts } from "../ui/Toasts";
import { Topbar } from "../ui/Topbar";
import type { SeccionTopbar } from "../ui/Topbar";
import { Configuracion } from "./Configuracion";
import { mostrada } from "./Rutas";
import { configuracion, ruta, SECCIONES_CONFIGURACION } from "./router";
import type { NombreVista, RutaHash } from "./router";

const MARCA = "Judicabot";

const TITULOS: Record<NombreVista, string> = {
  inicio: "",
  casos: "Casos de segunda instancia",
  documentos: "Documentos",
  proceso: "Proceso",
  borrador: "Borrador",
  decision: "Decisión",
  fallo: "Fallo",
};

export function tituloDeRuta({ vista, params, configuracion: seccion }: RutaHash): string {
  const titulo = SECCIONES_CONFIGURACION.find((s) => s.id === seccion)?.titulo;
  const partes = titulo ? [titulo, "Configuración"] : [TITULOS[vista], params.caso];
  return [...partes, MARCA].filter(Boolean).join(" · ");
}

export function seccionDe({ configuracion: seccion }: RutaHash): SeccionTopbar {
  return seccion ? "configuracion" : "inicio";
}

export function Shell({ children }: { children?: ComponentChildren }) {
  const principal = useRef<HTMLElement>(null);
  const primera = useRef(true);
  const destino = ruta.value;
  const visible = mostrada.value;
  const seccion = configuracion.value;
  const servidor = estadoServidor.value;
  const propio = tituloVista.value;
  const actual: RutaHash = seccion ? { ...destino, configuracion: seccion } : (visible ?? destino);

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
    document.title = propio && !seccion ? `${propio} · ${MARCA}` : tituloDeRuta(actual);
  }, [visible, destino, seccion, propio]);

  return (
    <>
      <Topbar seccion={seccionDe(actual)} clave={servidor ? servidor.api_key : null} />
      <main id="contenido" class="lienzo" ref={principal} tabIndex={-1} aria-busy={visible !== destino ? "true" : undefined}>
        {children}
      </main>
      <Configuracion />
      {seccion === null && <Toasts />}
    </>
  );
}
