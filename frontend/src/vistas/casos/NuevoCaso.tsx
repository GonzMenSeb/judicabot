import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import { api, ErrorApi, esAbortado } from "../../api";
import { mostrarToast, plural } from "../../estado";
import { navegar, precargar } from "../../rutas/router";
import { Aviso, Boton, cx } from "../../ui";
import { Arbol, ArbolEjemplo } from "./Arbol";
import { archivosElegidos, archivosSoltados, formatoTamano, nombreGenerico, resumirSeleccion, sinOcultos } from "./carpeta";
import type { ArchivoSeleccionado } from "./carpeta";
import { useSoltarGlobal } from "./soltar";
import { cuerpoCaso, mensajeError, subirCaso } from "./subida";

type Fase = "vacio" | "leyendo" | "listo" | "subiendo";

const SIN_ARCHIVOS = "No se encontraron archivos en lo que eligió.";

export function NuevoCaso() {
  const [fase, setFase] = useState<Fase>("vacio");
  const [seleccion, setSeleccion] = useState<ArchivoSeleccionado[]>([]);
  const [nombre, setNombre] = useState("");
  const [progreso, setProgreso] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const carpetaRef = useRef<HTMLInputElement>(null);
  const archivosRef = useRef<HTMLInputElement>(null);
  const controlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (carpetaRef.current) carpetaRef.current.webkitdirectory = true;
    return () => controlRef.current?.abort();
  }, []);

  const fijar = (lista: ArchivoSeleccionado[]) => {
    const limpia = sinOcultos(lista);
    setSeleccion(limpia);
    setFase(limpia.length > 0 ? "listo" : "vacio");
    setError(limpia.length > 0 ? null : SIN_ARCHIVOS);
  };

  const alSoltar = async (dt: DataTransfer) => {
    setFase("leyendo");
    setError(null);
    try {
      fijar(await archivosSoltados(dt));
    } catch (e) {
      setSeleccion([]);
      setFase("vacio");
      setError(`No se pudo leer la carpeta${e instanceof Error && e.message ? `: ${e.message}` : "."}`);
    }
  };

  const arrastrando = useSoltarGlobal((dt) => void alSoltar(dt), fase !== "subiendo" && fase !== "leyendo");

  const alElegir = (ev: JSX.TargetedEvent<HTMLInputElement>) => {
    const input = ev.currentTarget;
    const lista = archivosElegidos(input.files);
    input.value = "";
    fijar(lista);
  };

  const reiniciar = () => {
    setSeleccion([]);
    setNombre("");
    setError(null);
    setFase("vacio");
  };

  const cancelar = () => controlRef.current?.abort();

  const crear = async (ev: Event) => {
    ev.preventDefault();
    if (seleccion.length === 0 || fase === "subiendo") return;
    const control = new AbortController();
    controlRef.current = control;
    setFase("subiendo");
    setProgreso(0);
    setError(null);
    void precargar("documentos");
    try {
      const creado = await subirCaso(cuerpoCaso(seleccion, nombre), setProgreso, control.signal);
      mostrarToast(`Caso «${creado.id}» creado con ${plural(creado.n_insumos, "archivo")}.`, { tipo: "ok" });
      const base = `/api/casos/${encodeURIComponent(creado.id)}`;
      try {
        await api.post(`${base}/run`, { cmd: "nuevo" });
      } catch (e) {
        if (!(e instanceof ErrorApi && e.estado === 409)) {
          mostrarToast(mensajeError(e, "No se pudo iniciar la lectura del expediente."), { tipo: "error" });
        }
      }
      navegar(`#/segunda/${encodeURIComponent(creado.id)}/documentos`);
      reiniciar();
    } catch (e) {
      if (!esAbortado(e)) setError(mensajeError(e, "No se pudo crear el caso."));
      setFase("listo");
    }
  };

  const resumen = useMemo(() => resumirSeleccion(seleccion), [seleccion]);
  const rutas = useMemo(() => seleccion.map((x) => x.ruta), [seleccion]);
  const subiendo = fase === "subiendo";
  const porcentaje = Math.round(progreso * 100);
  const sugerido = resumen.raiz ?? "caso";
  const ayudaNombre = nombreGenerico(sugerido)
    ? `Si lo deja vacío se llamará «${sugerido}». Escriba un nombre para encontrarlo después en esta lista.`
    : `Si lo deja vacío se llamará «${sugerido}».`;

  return (
    <>
      <section class={cx("nuevo-caso", arrastrando && "activa")} aria-labelledby="nuevo-caso-titulo">
        {fase === "listo" || fase === "subiendo" ? (
          <form class="detectado" onSubmit={(ev) => void crear(ev)}>
            <h2 id="nuevo-caso-titulo">Carpeta lista</h2>
            <div class="resumen">
              <span>{resumen.raiz ?? "Archivos seleccionados"}</span>
              <span>
                {plural(resumen.total, "archivo")} ({formatoTamano(resumen.bytes)})
              </span>
            </div>
            <div class="campo">
              <label for="nombre-caso">Nombre del caso (opcional)</label>
              <input
                id="nombre-caso"
                type="text"
                autocomplete="off"
                placeholder={resumen.raiz ?? "Por ejemplo: Tutela 2026-00412"}
                value={nombre}
                disabled={subiendo}
                onInput={(ev) => setNombre(ev.currentTarget.value)}
              />
              <small>{ayudaNombre}</small>
            </div>
            {error && <Aviso tipo="error">{error}</Aviso>}
            {subiendo && (
              <div class="subida">
                <p role="status">{progreso >= 1 ? "Guardando los archivos en el servidor…" : `Subiendo ${plural(resumen.total, "archivo")}…`}</p>
                <div class="barra-subida" role="progressbar" aria-label="Progreso de la subida" aria-valuemin={0} aria-valuemax={100} aria-valuenow={porcentaje}>
                  <i style={{ width: `${porcentaje}%` }} />
                </div>
                <span class="porcentaje" aria-hidden="true">
                  {porcentaje} %
                </span>
              </div>
            )}
            <div class="acciones">
              <Boton type="submit" variante="primario" cargando={subiendo}>
                Crear caso y revisar documentos
              </Boton>
              {subiendo ? (
                <Boton variante="fantasma" onClick={cancelar}>
                  Cancelar
                </Boton>
              ) : (
                <Boton variante="fantasma" onClick={reiniciar}>
                  Elegir otra carpeta
                </Boton>
              )}
            </div>
          </form>
        ) : (
          <div class="texto">
            <h2 id="nuevo-caso-titulo">Nuevo caso</h2>
            <p class="sub">
              Suelte en cualquier parte de esta página la carpeta <b>01PrimeraInstancia</b> o la carpeta completa del caso.
            </p>
            <div class="acciones">
              <Boton variante="primario" onClick={() => carpetaRef.current?.click()}>
                Elegir carpeta
              </Boton>
              <Boton variante="fantasma" onClick={() => archivosRef.current?.click()}>
                Elegir archivos
              </Boton>
              <span class="sub nota">Se conservan las subcarpetas.</span>
            </div>
            {fase === "leyendo" && <p class="sub" role="status">Leyendo la carpeta…</p>}
            {error && <Aviso tipo="error">{error}</Aviso>}
          </div>
        )}
        <div class="ilus">{seleccion.length > 0 ? <Arbol rutas={rutas} /> : <ArbolEjemplo />}</div>
        <input ref={carpetaRef} type="file" multiple hidden tabIndex={-1} aria-hidden="true" onChange={alElegir} />
        <input ref={archivosRef} type="file" multiple hidden tabIndex={-1} aria-hidden="true" onChange={alElegir} />
      </section>
      {arrastrando && (
        <div class="soltar-global" aria-hidden="true">
          <div>
            <h2>Suelte la carpeta</h2>
            <p>Se creará un caso nuevo con ella.</p>
          </div>
        </div>
      )}
    </>
  );
}
