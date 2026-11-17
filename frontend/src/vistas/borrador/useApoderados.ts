import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado } from "../../api";
import type { AjusteCuerpo, ApoderadosRespuesta, ApoderadoVista, ConsultarCuerpo, RevisionCuerpo } from "../../api/contrato";
import { mostrarToast } from "../../estado";
import { aplicarRevisiones, avisoSubida, debeConsultar, intervaloSondeo, reemplazarApoderado, SONDEO_ACTIVO_MS } from "./apoderados";

/** Si la identificación de un caso anterior no termina en este tiempo, se deja de esperar y se avisa. */
export const ESPERA_MAX_IDENTIFICACION_MS = 15 * 60_000;

export const MENSAJE_IDENTIFICACION_FALLIDA = "No se pudieron identificar los apoderados; inténtelo de nuevo.";
export const MENSAJE_IDENTIFICACION_LENTA = "La identificación de los apoderados tarda más de lo esperado. Vuelva a cargar la página en unos minutos.";

export interface EstadoApoderados {
  datos: ApoderadosRespuesta | null;
  error: string | null;
  errorRevision: string | null;
  revisar: (id: string, revisado: boolean) => void;
  /**
   * Sube el PDF del certificado de vigencia, deja en el estado al apoderado que devuelve el servidor y anuncia el
   * resultado en un aviso de la página (la ayuda que lo subió puede desaparecer con él). Si falla, lanza el error
   * del servidor.
   */
  subir: (apId: string, archivo: File) => Promise<void>;
  /**
   * Pide la consulta automática de la vigencia (todos los abogados, o los de `ids`; `forzar` es «Reintentar consulta
   * automática»). El servidor responde enseguida y la consulta se sigue con el sondeo. Si falla, lanza el error.
   */
  consultar: (ids?: string[], forzar?: boolean) => Promise<void>;
  /** Guarda una corrección a mano del apoderado y devuelve cómo quedó. Si el servidor la rechaza, lanza su error. */
  ajustar: (apId: string, cuerpo: AjusteCuerpo) => Promise<ApoderadoVista>;
  /** Identifica a los apoderados de un caso anterior a la identificación; el resultado se sigue con el sondeo. */
  identificar: () => Promise<void>;
  identificando: boolean;
  errorIdentificacion: string | null;
  recargar: () => void;
}

const SIN_PENDIENTES: ReadonlyMap<string, boolean> = new Map();

const mensajeDe = (e: unknown, porDefecto: string): string => (e instanceof ErrorApi && e.message ? e.message : porDefecto);

const rutaCaso = (caso: string): string => `/api/casos/${encodeURIComponent(caso)}/apoderados`;

/**
 * El estado de los apoderados del caso: lo lee al montar y lo vuelve a leer mientras algo puede cambiar sin que la
 * persona haga nada (consultas en curso, alguien que necesita ayuda sin extensión, una identificación en marcha).
 * `alIdentificar` se llama cuando termina bien la identificación de un caso anterior: el borrador previo cambió.
 */
export function useApoderados(caso: string | undefined, alIdentificar?: () => void): EstadoApoderados {
  const [servidor, setServidor] = useState<ApoderadosRespuesta | null>(null);
  const [pendientes, setPendientes] = useState<ReadonlyMap<string, boolean>>(SIN_PENDIENTES);
  const [error, setError] = useState<string | null>(null);
  const [errorRevision, setErrorRevision] = useState<string | null>(null);
  const [identificando, setIdentificando] = useState(false);
  const [errorIdentificacion, setErrorIdentificacion] = useState<string | null>(null);
  const [ciclo, setCiclo] = useState(0);
  const escrituras = useRef(0);
  const ultimaRevision = useRef(new Map<string, number>());
  // Las revisiones de un mismo apoderado salen de a una: el servidor las aplica en el orden de los
  // clics y la respuesta de la última es la que queda guardada.
  const colas = useRef(new Map<string, Promise<void>>());
  const casoVigente = useRef(caso);
  casoVigente.current = caso;
  const servidorVigente = useRef(servidor);
  servidorVigente.current = servidor;
  const alIdentificarRef = useRef(alIdentificar);
  alIdentificarRef.current = alIdentificar;
  /** Reprograma la próxima lectura del sondeo en marcha (null la cancela); lo fija el efecto de lectura. */
  const programarLectura = useRef<(ms: number | null) => void>(() => {});
  /** Desde cuándo se espera la identificación, o null si no se espera ninguna. */
  const identificandoDesde = useRef<number | null>(null);
  const autoConsultado = useRef(false);
  const consultarRef = useRef<EstadoApoderados["consultar"]>(async () => {});

  useEffect(() => {
    ultimaRevision.current = new Map();
    colas.current = new Map();
    identificandoDesde.current = null;
    autoConsultado.current = false;
    setServidor(null);
    setPendientes(SIN_PENDIENTES);
    setError(null);
    setErrorRevision(null);
    setIdentificando(false);
    setErrorIdentificacion(null);
  }, [caso]);

  /** Mientras se identifica, la respuesta dice si el trabajo terminó (el caso vuelve a admitir cambios). */
  const seguirIdentificacion = useCallback((respuesta: ApoderadosRespuesta): boolean => {
    const desde = identificandoDesde.current;
    if (desde === null) return false;
    if (!respuesta.editable && Date.now() - desde < ESPERA_MAX_IDENTIFICACION_MS) return true;
    identificandoDesde.current = null;
    setIdentificando(false);
    if (!respuesta.editable) setErrorIdentificacion(MENSAJE_IDENTIFICACION_LENTA);
    else if (respuesta.identificacion === "lista") alIdentificarRef.current?.();
    // Una identificación fallida la explica la pestaña, con su botón para intentarlo de nuevo.
    else if (respuesta.identificacion === "no_disponible") setErrorIdentificacion(MENSAJE_IDENTIFICACION_FALLIDA);
    return false;
  }, []);

  useEffect(() => {
    if (!caso) return;
    const control = new AbortController();
    let temporizador: ReturnType<typeof setTimeout> | undefined;
    const programar = (ms: number | null) => {
      clearTimeout(temporizador);
      temporizador = ms === null ? undefined : setTimeout(leer, ms);
    };
    const leer = () => {
      const desde = escrituras.current;
      api.get<ApoderadosRespuesta>(rutaCaso(caso), { signal: control.signal }).then(
        (respuesta) => {
          if (control.signal.aborted) return;
          if (desde !== escrituras.current) {
            leer();
            return;
          }
          setServidor(respuesta);
          setError(null);
          const esperando = seguirIdentificacion(respuesta);
          programar(esperando ? SONDEO_ACTIVO_MS : intervaloSondeo(respuesta, false));
          if (!autoConsultado.current) {
            // Una sola vez al abrir: recupera la cola si el servidor se reinició. Si falla, la pestaña ya ofrece la ayuda.
            autoConsultado.current = true;
            if (debeConsultar(respuesta)) consultarRef.current().catch(() => undefined);
          }
        },
        (e: unknown) => {
          if (esAbortado(e) || control.signal.aborted) return;
          setError(mensajeDe(e, "No se pudo leer el estado de los apoderados."));
          programar(intervaloSondeo(null, true));
        },
      );
    };
    programarLectura.current = programar;
    leer();
    return () => {
      control.abort();
      clearTimeout(temporizador);
      programarLectura.current = () => {};
    };
  }, [caso, ciclo, seguirIdentificacion]);

  const recargar = useCallback(() => {
    setError(null);
    setCiclo((n) => n + 1);
  }, []);

  /** Lo que respondió una escritura reemplaza lo leído: una lectura que salió antes trae el estado anterior y se descarta. */
  const adoptar = useCallback((respuesta: ApoderadosRespuesta) => {
    escrituras.current += 1;
    setServidor(respuesta);
    setError(null);
  }, []);

  const revisar = useCallback(
    (id: string, revisado: boolean) => {
      if (!caso) return;
      const n = (ultimaRevision.current.get(id) ?? 0) + 1;
      ultimaRevision.current.set(id, n);
      escrituras.current += 1;
      setErrorRevision(null);
      setPendientes((p) => new Map(p).set(id, revisado));
      const vigente = () => casoVigente.current === caso && ultimaRevision.current.get(id) === n;
      const terminar = () => {
        escrituras.current += 1;
        setPendientes((p) => {
          if (!p.has(id)) return p;
          const siguiente = new Map(p);
          siguiente.delete(id);
          return siguiente;
        });
      };
      // La huella del estado que se ve al hacer clic: si el servidor tiene otro, responde 409 y se vuelve a leer.
      const huella = servidorVigente.current?.apoderados.find((a) => a.id === id)?.huella ?? null;
      const cuerpo: RevisionCuerpo = { revisado, nota: "", huella };
      const url = `${rutaCaso(caso)}/${encodeURIComponent(id)}/revision`;
      const colasDelCaso = colas.current;
      const previa = colasDelCaso.get(id);
      const enviar = () => api.put<ApoderadoVista>(url, cuerpo);
      const envio = previa ? previa.then(enviar) : enviar();
      const enCola = envio.then(
        () => undefined,
        () => undefined,
      );
      colasDelCaso.set(id, enCola);
      void enCola.then(() => {
        if (colasDelCaso.get(id) === enCola) colasDelCaso.delete(id);
      });
      envio.then(
        (vista) => {
          if (!vigente()) return;
          setServidor((s) => (s ? reemplazarApoderado(s, vista) : s));
          terminar();
        },
        (e: unknown) => {
          if (!vigente()) return;
          terminar();
          setErrorRevision(mensajeDe(e, "No se pudo guardar la revisión del apoderado."));
          setCiclo((c) => c + 1);
        },
      );
    },
    [caso],
  );

  const subir = useCallback(
    async (apId: string, archivo: File) => {
      if (!caso) return;
      // El nombre que trae el archivo suele llevar la cédula (CV_RNA-TPA_<cc>.pdf): al servidor solo viaja el contenido.
      const cuerpo = new FormData();
      cuerpo.append("archivo", archivo, "certificado.pdf");
      const vista = await api.put<ApoderadoVista>(`${rutaCaso(caso)}/${encodeURIComponent(apId)}/certificado`, cuerpo);
      if (casoVigente.current !== caso) return;
      // Una lectura que salió antes de que el servidor guardara el certificado trae el estado anterior: se descarta.
      escrituras.current += 1;
      setServidor((s) => (s ? reemplazarApoderado(s, vista) : s));
      const { texto, tipo } = avisoSubida(vista);
      mostrarToast(texto, { tipo });
    },
    [caso],
  );

  const consultar = useCallback(
    async (ids?: string[], forzar = false) => {
      if (!caso) return;
      const cuerpo: ConsultarCuerpo = ids ? { ids, forzar } : { forzar };
      const respuesta = await api.post<ApoderadosRespuesta>(`${rutaCaso(caso)}/consultar`, cuerpo);
      if (casoVigente.current !== caso) return;
      adoptar(respuesta);
      programarLectura.current(intervaloSondeo(respuesta, false));
    },
    [caso, adoptar],
  );
  consultarRef.current = consultar;

  const ajustar = useCallback(
    async (apId: string, cuerpo: AjusteCuerpo) => {
      if (!caso) throw new Error("Sin caso");
      const vista = await api.put<ApoderadoVista>(`${rutaCaso(caso)}/${encodeURIComponent(apId)}/ajustes`, cuerpo);
      if (casoVigente.current === caso) {
        escrituras.current += 1;
        setServidor((s) => (s ? reemplazarApoderado(s, vista) : s));
        // Una cédula escrita a mano entra en la cola de consultas: se vuelve a leer para seguirla.
        programarLectura.current(0);
      }
      return vista;
    },
    [caso],
  );

  const identificar = useCallback(async () => {
    if (!caso || identificandoDesde.current !== null) return;
    identificandoDesde.current = Date.now();
    setIdentificando(true);
    setErrorIdentificacion(null);
    try {
      // 202 mientras el trabajo corre (el caso deja de admitir cambios); 200 si ya estaban identificados.
      const respuesta = await api.post<ApoderadosRespuesta>(`${rutaCaso(caso)}/identificar`);
      if (casoVigente.current !== caso) return;
      adoptar(respuesta);
      programarLectura.current(seguirIdentificacion(respuesta) ? SONDEO_ACTIVO_MS : intervaloSondeo(respuesta, false));
    } catch (e) {
      if (casoVigente.current !== caso) return;
      identificandoDesde.current = null;
      setIdentificando(false);
      setErrorIdentificacion(mensajeDe(e, MENSAJE_IDENTIFICACION_FALLIDA));
    }
  }, [caso, adoptar, seguirIdentificacion]);

  const datos = useMemo(() => (servidor ? aplicarRevisiones(servidor, pendientes) : null), [servidor, pendientes]);

  return { datos, error, errorRevision, revisar, subir, consultar, ajustar, identificar, identificando, errorIdentificacion, recargar };
}
