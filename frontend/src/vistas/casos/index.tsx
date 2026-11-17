import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { api, cancelable, esAbortado } from "../../api";
import type { CasoResumen } from "../../api/contrato";
import { versionCasos } from "../../estado";
import { Aviso, Boton, Cargando, Migas, Vacio } from "../../ui";
import type { PropsVista } from "../tipos";
import { IconoProceso } from "./iconos";
import { ListaCasos } from "./ListaCasos";
import { NuevoCaso } from "./NuevoCaso";
import { useQuitados } from "./quitados";
import { mensajeError } from "./subida";
import "./estilos.css";

const MIGAS = [{ texto: "Inicio", href: "#/" }, { texto: "Fallo de tutela de segunda instancia" }];

export default function Casos(_props: PropsVista) {
  const [casos, setCasos] = useState<CasoResumen[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nuevaSenal = useRef(cancelable()).current;
  const quitados = useQuitados();

  const cargar = useCallback(async () => {
    const signal = nuevaSenal();
    const carga = quitados.iniciar();
    setError(null);
    try {
      const lista = await api.get<CasoResumen[]>("/api/casos", { signal });
      setCasos(quitados.filtrar(carga, lista));
    } catch (e) {
      if (!esAbortado(e)) setError(mensajeError(e, "No se pudo cargar la lista de casos."));
    }
  }, [nuevaSenal, quitados]);

  const version = versionCasos.value;
  useEffect(() => {
    void cargar();
    return () => void nuevaSenal();
  }, [cargar, nuevaSenal, version]);

  const quitar = useCallback(
    (id: string) => {
      quitados.quitar(id);
      setCasos((lista) => lista && lista.filter((c) => c.id !== id));
    },
    [quitados],
  );

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
      <ListaCasos
        casos={casos ?? []}
        proceso="segunda"
        aviso={
          error ? (
            <Aviso tipo="error" titulo="No se pudieron cargar los casos" acciones={<Boton onClick={() => void cargar()}>Reintentar</Boton>}>
              {error}
            </Aviso>
          ) : casos === null ? (
            <Cargando texto="Cargando casos…" />
          ) : undefined
        }
        vacio={<Vacio titulo="Aún no hay casos">Cree uno soltando la carpeta 01PrimeraInstancia.</Vacio>}
        alEliminado={quitar}
      />
    </div>
  );
}
