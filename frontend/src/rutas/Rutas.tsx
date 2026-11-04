import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { Cargando } from "../ui/Estados";
import { cargadas, fallida, precargar, ruta } from "./router";
import type { Ruta } from "./router";

export const mostrada = signal<Ruta | null>(null);

const claveDe = ({ vista, params }: Ruta) => `${vista}:${params.caso ?? ""}`;

export function Rutas() {
  const actual = ruta.value;
  const { vista } = actual;
  const Vista = cargadas.value[vista];
  const previa = useRef<Ruta | null>(null);
  const visible = Vista ? actual : null;

  useEffect(() => {
    void precargar(vista);
  }, [vista]);

  useEffect(() => {
    if (visible) mostrada.value = visible;
  }, [visible]);

  if (fallida.value === vista) {
    return (
      <p role="alert">
        No se pudo cargar la vista. <button onClick={() => location.reload()}>Recargar</button>
      </p>
    );
  }
  if (Vista) {
    previa.current = actual;
    return <Vista key={claveDe(actual)} {...actual.params} />;
  }
  const anterior = previa.current;
  const VistaAnterior = anterior ? cargadas.value[anterior.vista] : undefined;
  if (anterior && VistaAnterior) return <VistaAnterior key={claveDe(anterior)} {...anterior.params} />;
  return <Cargando />;
}
