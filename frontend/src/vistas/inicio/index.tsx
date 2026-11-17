import { useCallback, useEffect, useMemo, useState } from "preact/hooks";
import { api, esAbortado } from "../../api";
import type { CasoResumen, Despacho } from "../../api/contrato";
import { versionCasos } from "../../estado";
import { Aviso, Boton } from "../../ui";
import { IconoProceso } from "../casos/iconos";
import type { TipoProceso } from "../casos/iconos";
import { ListaCasos } from "../casos/ListaCasos";
import { useQuitados } from "../casos/quitados";
import type { PropsVista } from "../tipos";
import "./estilos.css";

interface ProcesoProximo {
  tipo: TipoProceso;
  titulo: string;
}

const PROXIMOS_ANTES: ProcesoProximo[] = [{ tipo: "primera", titulo: "Fallo de tutela de primera instancia" }];
const PROXIMOS_DESPUES: ProcesoProximo[] = [
  { tipo: "desacato", titulo: "Incidente de desacato" },
  { tipo: "penal", titulo: "Penal" },
];

const fechaHoy = () => new Intl.DateTimeFormat("es-CO", { weekday: "long", day: "numeric", month: "long" }).format(new Date());

function Proximo({ tipo, titulo }: ProcesoProximo) {
  const id = `proceso-${tipo}`;
  return (
    <div class="proceso-t inactivo" role="group" aria-disabled="true" aria-labelledby={id}>
      <span class="ico" aria-hidden="true">
        <IconoProceso tipo={tipo} />
      </span>
      <h2 id={id}>{titulo}</h2>
      <p>Próximamente</p>
    </div>
  );
}

export default function Inicio(_props: PropsVista) {
  const [casos, setCasos] = useState<CasoResumen[] | null>(null);
  const [falloCasos, setFalloCasos] = useState(false);
  const [despacho, setDespacho] = useState<string | null>(null);
  const quitados = useQuitados();

  const cargarCasos = useCallback(async (signal?: AbortSignal) => {
    const carga = quitados.iniciar();
    setFalloCasos(false);
    try {
      const lista = await api.get<CasoResumen[]>("/api/casos", { signal });
      setCasos(quitados.filtrar(carga, lista));
    } catch (e) {
      if (!esAbortado(e)) setFalloCasos(true);
    }
  }, [quitados]);

  const version = versionCasos.value;
  useEffect(() => {
    const control = new AbortController();
    void cargarCasos(control.signal);
    return () => control.abort();
  }, [cargarCasos, version]);

  useEffect(() => {
    const control = new AbortController();
    api
      .get<{ valores: Pick<Despacho, "nombre_cuerpo"> }>("/api/formato", { signal: control.signal })
      .then((formato) => setDespacho(formato.valores.nombre_cuerpo || null))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  const quitar = useCallback(
    (id: string) => {
      quitados.quitar(id);
      setCasos((lista) => lista && lista.filter((c) => c.id !== id));
    },
    [quitados],
  );

  const { esperan, abiertos } = useMemo(() => {
    const lista = casos ?? [];
    return {
      esperan: lista.filter((c) => c.estado === "esperando_decision").length,
      abiertos: lista.filter((c) => c.estado !== "terminado").length,
    };
  }, [casos]);

  const encabezado = [despacho, fechaHoy()].filter(Boolean).join(", ");

  return (
    <div data-vista="inicio" class="bienvenida">
      <p class="despacho">{encabezado}</p>
      <h1>Elige el proceso a realizar</h1>
      <div class="procesos">
        {PROXIMOS_ANTES.map((p) => (
          <Proximo key={p.tipo} {...p} />
        ))}
        <article class="proceso-t activo">
          <span class="ico" aria-hidden="true">
            <IconoProceso tipo="segunda" />
          </span>
          <h2>
            <a class="enlace-tarjeta" href="#/segunda">
              Fallo de tutela de segunda instancia
            </a>
          </h2>
          <p>Resuelve la impugnación a partir de la carpeta de primera instancia.</p>
          <div class="pie-t">
            {casos !== null && esperan > 0 && (
              <span>
                <span class="punto-sello" aria-hidden="true" />
                {esperan === 1 ? "1 espera" : `${esperan} esperan`} su decisión
              </span>
            )}
            {casos !== null && <span class="sub">{abiertos === 1 ? "1 caso abierto" : `${abiertos} casos abiertos`}</span>}
            <span class="abrir" aria-hidden="true">
              Abrir
            </span>
          </div>
        </article>
        {PROXIMOS_DESPUES.map((p) => (
          <Proximo key={p.tipo} {...p} />
        ))}
      </div>
      {falloCasos && (
        <Aviso tipo="alerta" acciones={<Boton onClick={() => void cargarCasos()}>Reintentar</Boton>}>
          No se pudo cargar el resumen de los casos.
        </Aviso>
      )}
      {casos && casos.length > 0 && <ListaCasos casos={casos} alEliminado={quitar} />}
    </div>
  );
}
