import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado, esCasoNoEncontrado } from "../../api";
import type { Vista } from "../../api/contrato";
import { casoActual, jobActual, useTitulo } from "../../estado";
import { navegar } from "../../rutas";
import { Aviso, Boton, Cargando, CasoNoEncontrado, Migas, Pasos, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import "./estilos.css";
import {
  construirIndice,
  construirRevision,
  filasJev,
  irA,
  limitePasos,
  tituloDelCaso,
} from "./datos";
import { DialogoCorrecciones } from "./DialogoCorrecciones";
import { Documento } from "./Documento";
import { DetalleCita, Riel } from "./Riel";
import { TarjetaJev } from "./TarjetaJev";
import type { EstadoCaso } from "./tipos";
import { useEspia } from "./useEspia";

type Fase = "cargando" | "listo" | "no_existe" | "error";

const enlaceEtapa = (caso: string, etapa: string) => `#/segunda/${encodeURIComponent(caso)}/${etapa}`;

function motivoNoCorregir(estado: EstadoCaso | null, cargado: boolean): string | null {
  if (!cargado) return "No se pudo comprobar el estado del caso.";
  if (!estado) return null;
  if (estado.job_activo || estado.estado === "corriendo") return "Hay una redacción en curso para este caso.";
  if (estado.estado !== "esperando_decision") return "Solo se pueden pedir correcciones mientras el caso espera su decisión.";
  return null;
}

export default function Borrador({ caso }: PropsVista) {
  const [fase, setFase] = useState<Fase>("cargando");
  const [vista, setVista] = useState<Vista | null>(null);
  const [errorVista, setErrorVista] = useState<string | null>(null);
  const [estado, setEstado] = useState<EstadoCaso | null>(null);
  const [estadoFallo, setEstadoFallo] = useState(false);
  const [sinCaso, setSinCaso] = useState(false);
  const [intento, setIntento] = useState(0);
  const [seleccionada, setSeleccionada] = useState<string | null>(null);
  const [origen, setOrigen] = useState(false);
  const [corrigiendo, setCorrigiendo] = useState(false);
  const tituloDetalle = useRef<HTMLHeadingElement>(null);
  const disparador = useRef<HTMLElement | null>(null);
  const hoja = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    const base = `/api/casos/${encodeURIComponent(caso)}`;
    setFase("cargando");
    setEstadoFallo(false);
    setSinCaso(false);
    setSeleccionada(null);
    api.get<Vista>(`${base}/vista/borrador`, { signal: control.signal }).then(
      (datos) => {
        setVista(datos);
        setFase("listo");
      },
      (e: unknown) => {
        if (esAbortado(e)) return;
        if (esCasoNoEncontrado(e)) setSinCaso(true);
        if (e instanceof ErrorApi && e.estado === 404) {
          setFase("no_existe");
          return;
        }
        setErrorVista(e instanceof ErrorApi ? e.message : "No se pudo conectar con el servidor.");
        setFase("error");
      },
    );
    api.get<EstadoCaso>(`${base}/estado`, { signal: control.signal }).then(
      (datos) => setEstado(datos),
      (e: unknown) => {
        if (esAbortado(e)) return;
        if (e instanceof ErrorApi && e.estado === 404) setSinCaso(true);
        else setEstadoFallo(true);
      },
    );
    return () => control.abort();
  }, [caso, intento]);

  const resumen = estado?.resumen ?? null;
  const metadatos = resumen?.metadatos ?? null;
  const nombre = caso ? tituloDelCaso(caso, metadatos) : "";
  useTitulo(caso ? `Borrador · ${nombre}` : null);

  const citas = vista?.citas;
  const citasPorId = useMemo(() => new Map((citas ?? []).map((c) => [c.id, c])), [citas]);
  const indice = useMemo(() => (vista ? construirIndice(vista) : []), [vista]);
  const idsIndice = useMemo(() => indice.map((e) => e.id), [indice]);
  const activa = useEspia(idsIndice);
  const items = useMemo(() => construirRevision(citas ?? [], resumen?.alertas), [citas, resumen]);
  const filas = useMemo(() => filasJev(resumen?.jev_metadatos, metadatos), [resumen, metadatos]);

  const cita = seleccionada ? (citasPorId.get(seleccionada) ?? null) : null;

  const elegirCita = useCallback((id: string, desde: HTMLElement) => {
    disparador.current = desde;
    setSeleccionada((actual) => (actual === id && desde.hasAttribute("data-cita") ? null : id));
  }, []);

  const verEnTexto = useCallback((id: string, desde: HTMLElement) => {
    disparador.current = desde;
    setSeleccionada(id);
    const marcas = hoja.current?.querySelectorAll<HTMLElement>("[data-cita]") ?? [];
    irA(Array.from(marcas).find((m) => m.dataset["cita"] === id) ?? null, "center");
  }, []);

  const cerrarDetalle = useCallback(() => {
    setSeleccionada(null);
    const previo = disparador.current;
    const destino = previo?.isConnected ? previo : null;
    destino?.focus();
  }, []);

  useEffect(() => {
    if (seleccionada) tituloDetalle.current?.focus({ preventScroll: true });
  }, [seleccionada]);

  const alSeccion = useCallback((id: string) => {
    irA(document.getElementById(`b-${id}`));
  }, []);

  if (!caso) return <Vacio titulo="Falta el caso">Abra el borrador desde la lista de casos.</Vacio>;

  const sinEstado = estado === null;
  const motivo = motivoNoCorregir(estado, !estadoFallo);
  const corrigible = !sinEstado && motivo === null;
  const enCurso = Boolean(estado?.job_activo) || estado?.estado === "corriendo";
  const radicado = metadatos?.cui_2a || metadatos?.cui_1a;

  const cabecera = (
    <>
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <div class="bor-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {(radicado || metadatos?.juzgado_a_quo) && (
          <div class="bor-meta">
            {radicado && <span>Radicado {radicado}</span>}
            {metadatos?.juzgado_a_quo && <span>{metadatos.juzgado_a_quo}</span>}
          </div>
        )}
      </div>
      <Pasos caso={caso} actual="borrador" limite={limitePasos(estado)} detalles={{ borrador: "Revise antes de decidir" }} />
    </>
  );

  if (fase === "cargando") {
    return (
      <div data-vista="borrador" class="borrador">
        {cabecera}
        <Cargando texto="Cargando el borrador…" />
      </div>
    );
  }

  if (sinCaso && (fase === "no_existe" || fase === "error")) {
    return (
      <div data-vista="borrador" class="borrador">
        <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: caso }]} />
        <CasoNoEncontrado />
      </div>
    );
  }

  if (fase === "no_existe" || fase === "error" || !vista) {
    const sinBorrador = fase === "no_existe";
    return (
      <div data-vista="borrador" class="borrador">
        {cabecera}
        {sinBorrador ? (
          <Vacio
            titulo="El borrador aún no está listo"
            accion={
              <>
                <Boton variante="primario" href={enlaceEtapa(caso, "proceso")}>
                  Ver el proceso
                </Boton>
                <Boton href={enlaceEtapa(caso, "documentos")}>Volver a documentos</Boton>
              </>
            }
          >
            Se genera cuando termina la redacción de las secciones I a V.
          </Vacio>
        ) : (
          <Aviso
            tipo="error"
            titulo="No se pudo cargar el borrador"
            acciones={<Boton onClick={() => setIntento(intento + 1)}>Reintentar</Boton>}
          >
            {errorVista}
          </Aviso>
        )}
      </div>
    );
  }

  return (
    <div data-vista="borrador" class="borrador">
      {cabecera}
      {enCurso && (
        <Aviso
          tipo="info"
          class="bor-aviso"
          acciones={
            <Boton href={enlaceEtapa(caso, "proceso")} variante="primario">
              Ver el proceso
            </Boton>
          }
        >
          Hay una redacción en curso para este caso. El borrador puede cambiar cuando termine.
        </Aviso>
      )}
      <TarjetaJev filas={filas} umbral={resumen?.jev_metadatos?.umbral} />
      <div class="bor-dos">
        <div class="bor-col-doc" ref={hoja}>
          <h2 class="solo-lectura">Texto del borrador</h2>
          <Documento vista={vista} citas={citasPorId} seleccionada={seleccionada} origen={origen} alCita={elegirCita} />
        </div>
        <Riel
          indice={indice}
          activa={activa}
          alSeccion={alSeccion}
          origen={origen}
          alOrigen={setOrigen}
          citas={vista.citas}
          items={items}
          alVerCita={verEnTexto}
          puedeCorregir={corrigible}
          motivoNoCorregir={motivo}
          alCorregir={() => setCorrigiendo(true)}
          avisoEstado={estadoFallo ? "No se pudieron leer las alertas del caso; se muestran solo las citas." : null}
          detalle={cita ? <DetalleCita cita={cita} titulo={tituloDetalle} onCerrar={cerrarDetalle} /> : null}
        />
      </div>
      <div class="bor-accion">
        <div>
          <span class="bor-accion-texto">Las alertas no bloquean la decisión. Revíselas antes de firmar el fallo.</span>
          <Boton variante="sello" grande href={enlaceEtapa(caso, "decision")} disabled={enCurso}>
            Pasar a la decisión
          </Boton>
        </div>
      </div>
      <DialogoCorrecciones
        abierto={corrigiendo}
        caso={caso}
        onCerrar={() => setCorrigiendo(false)}
        onEnviado={(jobId) => {
          casoActual.value = caso;
          jobActual.value = jobId;
          setCorrigiendo(false);
          navegar(enlaceEtapa(caso, "proceso"));
        }}
      />
    </div>
  );
}
