import { useEffect, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado } from "../../api";
import type { CasoResumen } from "../../api/contrato";
import { useTitulo } from "../../estado";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Migas, Pasos, Vacio } from "../../ui";
import type { EtapaPaso } from "../../ui";
import type { PropsVista } from "../tipos";
import { AccionFinal, BloqueError, baseCaso } from "./Acciones";
import { Seguimiento } from "./Seguimiento";
import { cargar } from "./carga";
import type { EstadoCaso } from "./tipos";
import "./estilos.css";

const LIMITE: Record<CasoResumen["etapa"], EtapaPaso> = {
  0: "documentos",
  1: "proceso",
  2: "decision",
  3: "decision",
  4: "fallo",
};

type Origen =
  | { fase: "cargando" }
  | { fase: "no_existe" }
  | { fase: "error"; mensaje: string }
  | { fase: "job"; jobId: string; cmd: string | null }
  | { fase: "sin_job"; estado: EstadoCaso };

function limiteDe(resumen: CasoResumen | null, estado: EstadoCaso | null): EtapaPaso {
  if (estado?.estado === "terminado") return "fallo";
  if (estado?.estado === "esperando_decision") return "decision";
  return resumen ? LIMITE[resumen.etapa] : "proceso";
}

function VistaProceso({ caso }: { caso: string }) {
  const [origen, setOrigen] = useState<Origen>({ fase: "cargando" });
  const [version, setVersion] = useState(0);
  const [resumen, setResumen] = useState<CasoResumen | null>(null);
  const [estado, setEstado] = useState<EstadoCaso | null>(null);

  const nombre = resumen?.nombre ?? caso;
  useTitulo(`Proceso · ${nombre}`);

  useEffect(() => {
    const control = new AbortController();
    setResumen(null);
    api.get<CasoResumen>(`/api/casos/${encodeURIComponent(caso)}/resumen`, { signal: control.signal }).then(setResumen, () => {});
    return () => control.abort();
  }, [caso]);

  useEffect(() => {
    const control = new AbortController();
    setOrigen({ fase: "cargando" });
    setEstado(null);
    cargar(caso, control.signal).then(
      (carga) => {
        if (carga.jobId) {
          setOrigen({ fase: "job", jobId: carga.jobId, cmd: carga.cmd });
        } else {
          setEstado(carga.estado);
          setOrigen({ fase: "sin_job", estado: carga.estado });
        }
      },
      (error) => {
        if (esAbortado(error)) return;
        if (error instanceof ErrorApi && error.estado === 404) {
          setOrigen({ fase: "no_existe" });
          return;
        }
        setOrigen({ fase: "error", mensaje: error instanceof Error ? error.message : "No se pudo consultar el caso." });
      },
    );
    return () => control.abort();
  }, [caso, version]);

  const reintentar = () => setVersion((v) => v + 1);
  const nuevoJob = (jobId: string) => {
    setEstado(null);
    setOrigen({ fase: "job", jobId, cmd: "continuar" });
  };

  if (origen.fase === "no_existe") {
    return (
      <div data-vista="proceso">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        <CasoNoEncontrado />
      </div>
    );
  }

  return (
    <div data-vista="proceso">
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <header class="tz-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {resumen && (resumen.radicado || resumen.juzgado_a_quo) && (
          <div class="tz-meta">
            {resumen.radicado && <span>Radicado {resumen.radicado}</span>}
            {resumen.juzgado_a_quo && <span>{resumen.juzgado_a_quo}</span>}
          </div>
        )}
      </header>
      <Pasos caso={caso} actual="proceso" limite={limiteDe(resumen, estado)} />

      {origen.fase === "cargando" && <Cargando texto="Consultando el estado del caso…" />}
      {origen.fase === "error" && (
        <Aviso
          tipo="error"
          titulo="No se pudo consultar el caso"
          acciones={<Boton onClick={reintentar}>Reintentar</Boton>}
        >
          {origen.mensaje}
        </Aviso>
      )}
      {origen.fase === "job" && (
        <Seguimiento
          key={`${origen.jobId}:${version}`}
          caso={caso}
          jobId={origen.jobId}
          cmd={origen.cmd}
          alNuevoJob={nuevoJob}
          alReintentar={reintentar}
          alEstado={setEstado}
        />
      )}
      {origen.fase === "sin_job" && <SinEjecucion caso={caso} estado={origen.estado} alNuevoJob={nuevoJob} alReintentar={reintentar} />}
    </div>
  );
}

interface PropsSin {
  caso: string;
  estado: EstadoCaso;
  alNuevoJob: (jobId: string) => void;
  alReintentar: () => void;
}

function SinEjecucion({ caso, estado, alNuevoJob, alReintentar }: PropsSin) {
  if (estado.estado === "esperando_decision" || estado.estado === "terminado") {
    return (
      <>
        <p class="sub tz-aviso">No hay una ejecución en curso.</p>
        <AccionFinal caso={caso} estado={estado.estado} />
      </>
    );
  }
  if (estado.estado === "error") {
    const accion = estado.resumen?.decision?.accion;
    return (
      <BloqueError
        caso={caso}
        mensaje={estado.error ?? "El proceso quedó a medias."}
        cmd={accion === "decidir" ? "decidir" : null}
        alNuevoJob={alNuevoJob}
        alReintentar={alReintentar}
      />
    );
  }
  return (
    <Vacio
      titulo="Todavía no se ha iniciado la redacción"
      accion={
        <Boton variante="primario" href={`${baseCaso(caso)}/documentos`}>
          Ir a documentos
        </Boton>
      }
    >
      Revise los documentos del expediente y use «Iniciar redacción» para ver el proceso en vivo.
    </Vacio>
  );
}

export default function Proceso({ caso }: PropsVista) {
  if (!caso) return <Vacio titulo="Falta indicar el caso" />;
  return <VistaProceso caso={caso} />;
}
