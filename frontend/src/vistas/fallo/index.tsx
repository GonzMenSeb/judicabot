import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { api, cancelable, ErrorApi, esAbortado, esCasoNoEncontrado } from "../../api";
import type { CasoResumen, Vista } from "../../api/contrato";
import { useTitulo } from "../../estado";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Migas, Pasos } from "../../ui";
import type { EtapaPaso } from "../../ui";
import type { PropsVista } from "../tipos";
import { Descargas } from "./Descargas";
import { Visor } from "./Visor";
import {
  agruparSalidas,
  calcularAvisos,
  citasDeEstado,
  citasDeVista,
  destinoSinFallo,
  rutaFallo,
} from "./datos";
import type { EstadoCaso, InfoCaso, SalidasRespuesta } from "./tipos";
import "./estilos.css";

type Carga =
  | { fase: "cargando" }
  | { fase: "no_existe" }
  | { fase: "error"; mensaje: string }
  | { fase: "listo"; vista: Vista | null; archivos: string[]; estado: EstadoCaso | null; info: InfoCaso | null };

type Resultado<T> = { ok: true; valor: T } | { ok: false; error: unknown };

const capturar = <T,>(promesa: Promise<T>): Promise<Resultado<T>> =>
  promesa.then(
    (valor) => ({ ok: true as const, valor }),
    (error: unknown) => ({ ok: false as const, error }),
  );

const esEstado = (error: unknown, estado: number) => error instanceof ErrorApi && error.estado === estado;

const mensajeDe = (error: unknown) => (error instanceof Error && error.message ? error.message : "Error desconocido.");

function infoDe(resumen: CasoResumen | null, caso: string, estado: EstadoCaso | null): InfoCaso | null {
  if (resumen) return resumen;
  const md = estado?.resumen?.metadatos;
  if (!md) return null;
  return { nombre: caso, radicado: md.cui_2a ?? md.cui_1a ?? null, juzgado_a_quo: md.juzgado_a_quo ?? null };
}

function useFallo(caso: string) {
  const [carga, setCarga] = useState<Carga>({ fase: "cargando" });
  const senal = useRef(cancelable());

  const cargar = useCallback(async () => {
    const signal = senal.current();
    const base = `/api/casos/${encodeURIComponent(caso)}`;
    setCarga({ fase: "cargando" });
    const [vista, salidas, estado, resumen] = await Promise.all([
      capturar(api.get<Vista>(`${base}/vista/fallo`, { signal })),
      capturar(api.get<SalidasRespuesta>(`${base}/salidas`, { signal })),
      capturar(api.get<EstadoCaso>(`${base}/estado`, { signal })),
      capturar(api.get<CasoResumen>(`${base}/resumen`, { signal })),
    ]);
    if (signal.aborted) return;
    const abortado = [vista, salidas, estado].find((r) => !r.ok && esAbortado(r.error));
    if (abortado) return;

    if ((!salidas.ok && esEstado(salidas.error, 404)) || (!vista.ok && esCasoNoEncontrado(vista.error))) {
      setCarga({ fase: "no_existe" });
      return;
    }
    if (!vista.ok && !esEstado(vista.error, 404)) {
      setCarga({ fase: "error", mensaje: mensajeDe(vista.error) });
      return;
    }
    const estadoCaso = estado.ok ? estado.valor : null;
    const archivos = salidas.ok ? salidas.valor.archivos : (estadoCaso?.salidas ?? []);
    setCarga({
      fase: "listo",
      vista: vista.ok ? vista.valor : null,
      archivos,
      estado: estadoCaso,
      info: infoDe(resumen.ok ? resumen.valor : null, caso, estadoCaso),
    });
  }, [caso]);

  useEffect(() => {
    void cargar();
    const cancelarPendiente = senal.current;
    return () => {
      cancelarPendiente();
    };
  }, [cargar]);

  return { carga, recargar: cargar };
}

const PASO_DE: Record<string, EtapaPaso> = { documentos: "documentos", proceso: "proceso", decision: "decision" };

function Cabeza({ caso, info, actual }: { caso: string; info: InfoCaso | null; actual: EtapaPaso }) {
  const nombre = info?.nombre ?? caso;
  return (
    <>
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <header class="fallo-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {info && (info.radicado || info.juzgado_a_quo) && (
          <div class="fallo-meta">
            {info.radicado && <span>Radicado {info.radicado}</span>}
            {info.juzgado_a_quo && <span>{info.juzgado_a_quo}</span>}
          </div>
        )}
      </header>
      <Pasos caso={caso} actual={actual} limite={actual === "fallo" ? "fallo" : undefined} />
    </>
  );
}

function FalloCaso({ caso }: { caso: string }) {
  const { carga, recargar } = useFallo(caso);
  const info = carga.fase === "listo" ? carga.info : null;
  useTitulo(`Fallo · ${info?.nombre ?? caso}`);

  if (carga.fase === "cargando") return <Cargando texto="Cargando el fallo…" />;

  if (carga.fase === "no_existe" || carga.fase === "error") {
    return (
      <div data-vista="fallo" class="fallo">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        {carga.fase === "no_existe" ? (
          <CasoNoEncontrado />
        ) : (
          <Aviso tipo="error" titulo="No se pudo cargar el fallo" acciones={<Boton onClick={() => void recargar()}>Reintentar</Boton>}>
            {carga.mensaje}
          </Aviso>
        )}
      </div>
    );
  }

  const { vista, archivos, estado } = carga;
  const principal = rutaFallo(archivos);

  if (!vista && !principal) {
    const { texto, destino } = destinoSinFallo(caso, estado);
    return (
      <div data-vista="fallo" class="fallo">
        <Cabeza caso={caso} info={carga.info} actual={PASO_DE[destino.enlace] ?? "fallo"} />
        <Aviso
          tipo="info"
          titulo="Aún no hay fallo para este caso"
          acciones={<Boton variante="primario" href={destino.href}>{destino.texto}</Boton>}
        >
          {texto}
        </Aviso>
      </div>
    );
  }

  const citas = vista ? citasDeVista(vista) : estado?.resumen?.citas ? citasDeEstado(estado.resumen.citas) : null;
  const avisos = calcularAvisos({ citas, alertas: estado?.resumen?.alertas, archivos });
  const grupos = agruparSalidas(archivos, principal);

  return (
    <div data-vista="fallo" class="fallo">
      <Cabeza caso={caso} info={carga.info} actual="fallo" />
      <div class="dos res">
        <div>
          {vista ? (
            <Visor vista={vista} />
          ) : (
            <Aviso tipo="alerta" titulo="El fallo no tiene vista previa">
              El fallo existe y se puede descargar, pero se generó antes de que hubiera vista previa. Vuelva a generarlo para verlo aquí.
            </Aviso>
          )}
        </div>
        <Descargas caso={caso} principal={principal} grupos={grupos} avisos={avisos} estado={estado} />
      </div>
    </div>
  );
}

export default function Fallo({ caso }: PropsVista) {
  if (!caso) {
    return (
      <div data-vista="fallo" class="fallo">
        <Aviso tipo="error" titulo="Falta el caso" acciones={<Boton href="#/segunda">Volver a los casos</Boton>}>
          La dirección no indica de qué caso es el fallo.
        </Aviso>
      </div>
    );
  }
  return <FalloCaso caso={caso} />;
}
