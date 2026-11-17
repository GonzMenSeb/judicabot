import { useEffect, useId, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado } from "../../api";
import type { ApoderadoVista, EvidenciaVista, PaginaExpediente } from "../../api/contrato";
import { Aviso, Boton, Cargando, Dialogo, VisorPagina } from "../../ui";
import { resaltar } from "./resaltar";
import "./visor.css";

export interface PropsVisorEvidencia {
  casoId: string;
  apoderado: ApoderadoVista;
  /** La evidencia que se abre primero: su página y su cita. */
  evidencia: EvidenciaVista;
  titulo: string;
  subtitulo: string;
  editable: boolean;
  revisado: boolean;
  alRevisar: (revisado: boolean) => void;
  /** «No es correcto…» sobre el poder que se muestra: cierra el visor y pide confirmar el descarte. */
  alNoEsCorrecto?: () => void;
  alCerrar: () => void;
}

const MENSAJE_PAGINA = "No se pudo cargar la página.";
const MENSAJE_COPIA = "Cita copiada.";
const MENSAJE_SIN_COPIA = "No se pudo copiar. Seleccione la cita y cópiela a mano.";
const MENSAJE_SOLO_LECTURA = "Solo se puede cambiar mientras el caso espera la decisión.";
const AVISO_MS = 3500;

const LECTURA_COTEJO = { ok: "Coincide: ", mal: "No coincide: ", nulo: "No se pudo cotejar: " } as const;
const TRAZO_COTEJO = { ok: "M5 12.5l4.5 4.5L19 7.5", mal: "M7 7l10 10M17 7L7 17", nulo: "M7 12h10" } as const;

const tonoCotejo = (ok: boolean | null): keyof typeof LECTURA_COTEJO => (ok === true ? "ok" : ok === false ? "mal" : "nulo");

const mismaEvidencia = (a: EvidenciaVista, b: EvidenciaVista): boolean => a.doc_id === b.doc_id && a.pagina === b.pagina && a.cita === b.cita;
const claveEvidencia = (e: EvidenciaVista): string => `${e.doc_id}:${e.pagina}:${e.inicio ?? ""}:${e.fin ?? ""}`;

const reducirMovimiento = (): boolean => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

const urlArchivo = (casoId: string, docId: string, pagina: number): string =>
  `/api/casos/${encodeURIComponent(casoId)}/expediente/${encodeURIComponent(docId)}/archivo#page=${pagina}`;

function subtituloCertificado(apoderado: ApoderadoVista): string {
  const { otorgante, cargo } = apoderado.poder.cadena ?? { otorgante: "", cargo: "" };
  return otorgante
    ? `Evidencia de que ${otorgante} es ${cargo || "representante"} de ${apoderado.parte}`
    : `Evidencia de la representación de ${apoderado.parte}`;
}

function Icono({ trazo, tamano, grosor = 2 }: { trazo: string; tamano: number; grosor?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={grosor} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={trazo} />
    </svg>
  );
}

function MarcaCotejo({ tono }: { tono: keyof typeof LECTURA_COTEJO }) {
  return (
    <span class={`visor-ev-marca ${tono}`} aria-hidden="true">
      <Icono trazo={TRAZO_COTEJO[tono]} tamano={10} grosor={3.4} />
    </span>
  );
}

export default function VisorEvidencia({
  casoId,
  apoderado,
  evidencia,
  titulo,
  subtitulo,
  editable,
  revisado,
  alRevisar,
  alNoEsCorrecto,
  alCerrar,
}: PropsVisorEvidencia) {
  const idCotejo = useId();
  const idCita = useId();
  const idAyuda = useId();
  const marca = useRef<HTMLElement>(null);
  const lienzo = useRef<HTMLDivElement>(null);

  const certificado = apoderado.poder.cadena?.evidencia ?? null;
  const otra = certificado && !mismaEvidencia(evidencia, certificado) ? certificado : null;
  const claveInicial = claveEvidencia(evidencia);
  const [cambio, setCambio] = useState<string | null>(null);
  const enCertificado = otra !== null && cambio === claveInicial;
  const ev = enCertificado ? otra : evidencia;
  const claveEv = claveEvidencia(ev);
  const tituloActual = enCertificado ? `Certificado de existencia · Doc. ${ev.doc_id}` : titulo;
  const subtituloActual = enCertificado ? subtituloCertificado(apoderado) : subtitulo;

  const [navegada, setNavegada] = useState<{ clave: string; n: number } | null>(null);
  const n = navegada?.clave === claveEv ? navegada.n : ev.pagina;
  const docLlave = `${casoId}/${ev.doc_id}`;
  const llave = `${docLlave}/${n}`;

  const [paginas, setPaginas] = useState<ReadonlyMap<string, PaginaExpediente>>(() => new Map());
  const [fallo, setFallo] = useState<{ llave: string; mensaje: string } | null>(null);
  const [intento, setIntento] = useState(0);
  const guardadas = useRef(paginas);
  guardadas.current = paginas;

  const pagina = paginas.get(llave) ?? null;
  const delDoc = pagina ?? [...paginas].find(([k]) => k.startsWith(`${docLlave}/`))?.[1] ?? null;
  const total = delDoc?.total ?? ev.total_paginas;
  const errorPagina = fallo?.llave === llave ? fallo.mensaje : null;

  useEffect(() => {
    if (guardadas.current.has(llave)) return;
    const control = new AbortController();
    setFallo((f) => (f?.llave === llave ? null : f));
    api.get<PaginaExpediente>(`/api/casos/${encodeURIComponent(casoId)}/expediente/${encodeURIComponent(ev.doc_id)}/paginas/${n}`, { signal: control.signal }).then(
      (leida) => {
        if (control.signal.aborted) return;
        setPaginas((previas) => new Map(previas).set(llave, leida));
      },
      (e: unknown) => {
        if (esAbortado(e) || control.signal.aborted) return;
        setFallo({ llave, mensaje: e instanceof ErrorApi && e.message ? e.message : MENSAJE_PAGINA });
      },
    );
    return () => control.abort();
  }, [llave, intento]);

  const enCitada = n === ev.pagina;
  const segmentos = useMemo(() => (pagina && enCitada ? resaltar(pagina.texto, ev) : null), [pagina, enCitada, claveEv, ev.cita]);
  const primera = segmentos ? segmentos.findIndex((s) => s.marcado) : -1;
  const buscaba = ev.cita.trim() !== "" || ev.inicio !== null;
  const paginaVacia = pagina !== null && pagina.texto.trim() === "";
  const sinPasaje = segmentos !== null && primera < 0 && buscaba && !paginaVacia;

  useEffect(() => {
    const el = marca.current;
    if (primera >= 0 && el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: reducirMovimiento() ? "auto" : "smooth" });
    else if (lienzo.current) lienzo.current.scrollTop = 0;
  }, [pagina, claveEv, primera]);

  const [copia, setCopia] = useState<{ ok: boolean; texto: string } | null>(null);
  const temporizador = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    setCopia(null);
  }, [claveEv]);
  useEffect(() => () => clearTimeout(temporizador.current), []);

  async function copiar() {
    let ok = true;
    try {
      await navigator.clipboard.writeText(ev.cita);
    } catch {
      ok = false;
    }
    setCopia({ ok, texto: ok ? MENSAJE_COPIA : MENSAJE_SIN_COPIA });
    clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => setCopia(null), AVISO_MS);
  }

  const ir = (destino: number) => setNavegada({ clave: claveEv, n: destino });
  const hayAnterior = n > 1;
  const haySiguiente = total !== null && n < total;
  const flecha = (trazo: string) => <Icono trazo={trazo} tamano={14} grosor={2.4} />;
  const poder = apoderado.poder.evidencia;
  const descartable = editable && alNoEsCorrecto !== undefined && poder !== null && mismaEvidencia(ev, poder);

  return (
    <Dialogo abierto titulo={tituloActual} onCerrar={alCerrar} class="visor-ev">
      <span class="visor-ev-ico" aria-hidden="true">
        <Icono trazo="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4" tamano={22} />
      </span>
      <p class="visor-ev-sub">{subtituloActual}</p>
      <div class="visor-ev-ctl">
        <div class="visor-ev-nav" role="group" aria-label="Páginas del documento">
          <button
            type="button"
            class="btn chico"
            aria-label="Página anterior"
            aria-disabled={hayAnterior ? undefined : "true"}
            onClick={() => hayAnterior && ir(n - 1)}
          >
            {flecha("M15 6l-6 6 6 6")}
          </button>
          <span class="visor-ev-pag" aria-live="polite">
            {total !== null ? `Página ${n} de ${total}` : `Página ${n}`}
          </span>
          <button
            type="button"
            class="btn chico"
            aria-label="Página siguiente"
            aria-disabled={haySiguiente ? undefined : "true"}
            onClick={() => haySiguiente && ir(n + 1)}
          >
            {flecha("M9 6l6 6-6 6")}
          </button>
        </div>
        {delDoc?.es_pdf && (
          <a class="btn chico" href={urlArchivo(casoId, ev.doc_id, n)} target="_blank" rel="noopener noreferrer">
            Abrir PDF original
            <Icono trazo="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" tamano={13} />
            <span class="solo-lectura"> (se abre en una pestaña nueva)</span>
          </a>
        )}
        <button type="button" class="visor-ev-cerrar" aria-label="Cerrar visor" onClick={alCerrar}>
          <Icono trazo="M6 6l12 12M18 6L6 18" tamano={18} />
        </button>
      </div>

      <div class="visor-ev-cuerpo">
        <div class="visor-ev-lienzo" ref={lienzo} tabIndex={0} role="region" aria-label="Texto de la página" aria-busy={pagina || errorPagina ? undefined : "true"}>
          {!pagina && !errorPagina && <Cargando texto="Cargando la página…" />}
          {errorPagina && (
            <Aviso
              tipo="error"
              acciones={
                <Boton
                  class="chico"
                  onClick={() => {
                    setFallo(null);
                    setIntento((i) => i + 1);
                  }}
                >
                  Reintentar
                </Boton>
              }
            >
              {errorPagina}
            </Aviso>
          )}
          {pagina?.ocr && <p class="visor-ev-ocr">Página leída por reconocimiento de texto (OCR): puede tener errores de lectura.</p>}
          {sinPasaje && (
            <Aviso tipo="alerta">
              No se encontró el pasaje en la página {ev.pagina}. Compárelo con el texto{delDoc?.es_pdf ? " o abra el PDF original" : ""}.
            </Aviso>
          )}
          {paginaVacia && <Aviso>Esta página no tiene texto legible{delDoc?.es_pdf ? ": abra el PDF original para verla" : ""}.</Aviso>}
          {pagina && !paginaVacia && (
            <VisorPagina numero={pagina.pagina} total={pagina.total} class="visor-ev-pagina">
              <div class="visor-ev-texto">
                {(segmentos ?? [{ texto: pagina.texto, marcado: false }]).map((s, i) =>
                  s.marcado ? (
                    <mark key={i} ref={i === primera ? marca : undefined}>
                      {s.texto}
                    </mark>
                  ) : (
                    <span key={i}>{s.texto}</span>
                  ),
                )}
              </div>
            </VisorPagina>
          )}
        </div>

        <aside class="visor-ev-lado" aria-label="Detalle de la evidencia">
          <div class="visor-ev-detalle">
            <section aria-labelledby={idCotejo}>
              <h3 id={idCotejo}>Lo que se cotejó</h3>
              {apoderado.cotejos.length > 0 ? (
                <ul class="visor-ev-cotejos">
                  {apoderado.cotejos.map((c, i) => (
                    <li key={i}>
                      <MarcaCotejo tono={tonoCotejo(c.ok)} />
                      <span>
                        <span class="solo-lectura">{LECTURA_COTEJO[tonoCotejo(c.ok)]}</span>
                        {c.texto}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p class="visor-ev-vacio">No hay comprobaciones automáticas para este apoderado.</p>
              )}
            </section>

            <section class="visor-ev-cita" aria-labelledby={idCita}>
              <h3 id={idCita}>Cita textual</h3>
              {ev.cita && <q>{ev.cita}</q>}
              <p class="visor-ev-fuente">
                {tituloActual} · página {ev.pagina}
              </p>
              {!enCitada && (
                <p class="visor-ev-fuente">
                  Está viendo la página {n}.{" "}
                  <button
                    type="button"
                    class="visor-ev-enlace"
                    onClick={() => {
                      ir(ev.pagina);
                      lienzo.current?.focus();
                    }}
                  >
                    Ir a la página citada
                  </button>
                </p>
              )}
              <div class="visor-ev-acciones">
                {ev.cita && (
                  <Boton class="chico" onClick={() => void copiar()}>
                    Copiar cita
                  </Boton>
                )}
                {otra && (
                  <Boton class="chico" variante="fantasma" onClick={() => setCambio(enCertificado ? null : claveInicial)}>
                    {enCertificado ? "Volver a la evidencia inicial" : "Ver certificado de existencia"}
                  </Boton>
                )}
              </div>
              <p class={copia && !copia.ok ? "visor-ev-estado mal" : "visor-ev-estado"} role="status">
                {copia?.texto}
              </p>
            </section>
          </div>

          <div class="visor-ev-pie">
            {descartable && (
              <Boton class="chico" onClick={alNoEsCorrecto}>
                No es correcto…
              </Boton>
            )}
            <Boton
              class="chico visor-ev-revisar"
              variante={revisado ? "secundario" : "primario"}
              aria-pressed={revisado}
              aria-describedby={editable ? undefined : idAyuda}
              disabled={!editable}
              onClick={() => alRevisar(!revisado)}
            >
              {revisado && <Icono trazo="M5 12.5l4.5 4.5L19 7.5" tamano={13} grosor={3} />}
              Marcar revisado
            </Boton>
            {!editable && (
              <p id={idAyuda} class="visor-ev-vacio">
                {MENSAJE_SOLO_LECTURA}
              </p>
            )}
          </div>
        </aside>
      </div>
    </Dialogo>
  );
}
