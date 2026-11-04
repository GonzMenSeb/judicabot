import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, cancelable, esAbortado } from "../../api";
import type { CasoResumen } from "../../api/contrato";
import { plural } from "../../estado";
import { Aviso, Boton, Cargando, Migas, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import { Ficha } from "./Ficha";
import { IconoLupa, IconoProceso } from "./iconos";
import { NuevoCaso } from "./NuevoCaso";
import { agrupar, filtrar } from "./agrupar";
import { mensajeError } from "./subida";
import "./estilos.css";

const MIGAS = [{ texto: "Inicio", href: "#/" }, { texto: "Fallo de tutela de segunda instancia" }];

export default function Casos(_props: PropsVista) {
  const [casos, setCasos] = useState<CasoResumen[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [consulta, setConsulta] = useState("");
  const nuevaSenal = useRef(cancelable()).current;

  const cargar = useCallback(async () => {
    const signal = nuevaSenal();
    setError(null);
    try {
      setCasos(await api.get<CasoResumen[]>("/api/casos", { signal }));
    } catch (e) {
      if (!esAbortado(e)) setError(mensajeError(e, "No se pudo cargar la lista de casos."));
    }
  }, [nuevaSenal]);

  useEffect(() => {
    void cargar();
    return () => void nuevaSenal();
  }, [cargar, nuevaSenal]);

  const visibles = useMemo(() => (casos ? filtrar(casos, consulta) : []), [casos, consulta]);
  const grupos = useMemo(() => agrupar(visibles), [visibles]);

  return (
    <div data-vista="casos">
      <Migas items={MIGAS} />
      <header class="cabeza-proceso">
        <span class="ico" aria-hidden="true">
          <IconoProceso tipo="segunda" />
        </span>
        <h1 class="titulo">Fallos de tutela de segunda instancia</h1>
        <p class="sub">De la carpeta de primera instancia al fallo, con su decisión en el medio.</p>
      </header>
      <NuevoCaso />
      <section aria-labelledby="casos-titulo">
        <div class="herramientas">
          <h2 id="casos-titulo">Casos</h2>
          {casos && casos.length > 0 && (
            <label class="buscar">
              <IconoLupa />
              <input
                type="search"
                autocomplete="off"
                placeholder="Buscar por partes o radicado"
                aria-label="Buscar casos"
                value={consulta}
                onInput={(ev) => setConsulta(ev.currentTarget.value)}
              />
            </label>
          )}
        </div>
        {error ? (
          <Aviso tipo="error" titulo="No se pudieron cargar los casos" acciones={<Boton onClick={() => void cargar()}>Reintentar</Boton>}>
            {error}
          </Aviso>
        ) : casos === null ? (
          <Cargando texto="Cargando casos…" />
        ) : casos.length === 0 ? (
          <Vacio titulo="Aún no hay casos">Cree uno soltando la carpeta 01PrimeraInstancia.</Vacio>
        ) : (
          <>
            {consulta.trim() !== "" && (
              <p class="solo-lectura" role="status">
                {visibles.length === 0 ? "Ningún caso coincide." : `${plural(visibles.length, "caso")} encontrados.`}
              </p>
            )}
            {visibles.length === 0 ? (
              <p class="vacio-busqueda">Ningún caso coincide con «{consulta.trim()}».</p>
            ) : (
              grupos.map((grupo) => (
                <section key={grupo.id} class="grupo-casos" aria-labelledby={`grupo-${grupo.id}`}>
                  <h3 id={`grupo-${grupo.id}`}>
                    {grupo.titulo} <span>{grupo.casos.length}</span>
                  </h3>
                  <div class="fichas">
                    {grupo.casos.map((caso) => (
                      <Ficha key={caso.id} caso={caso} compacta={grupo.id === "terminados"} />
                    ))}
                  </div>
                </section>
              ))
            )}
          </>
        )}
      </section>
    </div>
  );
}
