import type { ComponentType } from "preact";
import { useEffect } from "preact/hooks";
import { claveActiva, estadoServidor, nombreModelo } from "../estado";
import { Cargando } from "../ui/Estados";
import { Panel } from "../ui/Panel";
import { claseClave, estadoClave, ID_CONFIGURACION } from "../ui/Topbar";
import { configuracion, hashConfiguracion, hashDe, navegarDirecto, precargarSeccion, ruta, SECCIONES_CONFIGURACION, seccionesCargadas, seccionFallida } from "./router";
import type { SeccionConfiguracion } from "./router";

function EstadoIa() {
  const servidor = estadoServidor.value;
  const clave = servidor ? claveActiva(servidor) : null;
  return (
    <>
      <span class={claseClave(clave)} aria-hidden="true" />
      {servidor && nombreModelo(servidor.modelo)}
      <span class="solo-lectura">, {estadoClave(clave)}</span>
    </>
  );
}

const DETALLES: Partial<Record<SeccionConfiguracion, ComponentType>> = { ia: EstadoIa };

const cerrar = () => navegarDirecto(hashDe(ruta.value));

export function Configuracion() {
  const seccion = configuracion.value;
  const Cuerpo = seccion ? seccionesCargadas.value[seccion] : undefined;

  useEffect(() => {
    if (seccion) void precargarSeccion(seccion);
  }, [seccion]);

  const items = SECCIONES_CONFIGURACION.map((s) => {
    const Detalle = DETALLES[s.id];
    return { href: hashConfiguracion(s.id), texto: s.titulo, actual: s.id === seccion, detalle: Detalle && <Detalle /> };
  });

  return (
    <Panel
      abierto={seccion !== null}
      titulo="Configuración"
      items={items}
      encabezado={SECCIONES_CONFIGURACION.find((s) => s.id === seccion)?.titulo ?? ""}
      onCerrar={cerrar}
      retorno={`#${ID_CONFIGURACION}`}
    >
      {seccion && seccionFallida.value === seccion ? (
        <p role="alert">
          No se pudo cargar la sección. <button onClick={() => location.reload()}>Recargar</button>
        </p>
      ) : Cuerpo ? (
        <Cuerpo key={seccion} />
      ) : (
        <Cargando />
      )}
    </Panel>
  );
}
