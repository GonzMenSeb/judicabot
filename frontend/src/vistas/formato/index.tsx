import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, ErrorApi, esAbortado } from "../../api";
import type { CampoFormato, Despacho, FormatoRespuesta } from "../../api/contrato";
import { mostrarToast } from "../../estado";
import { Aviso, Boton, Cargando, Dialogo, Migas } from "../../ui";
import { Formulario } from "./Formulario";
import { Previa } from "./Previa";
import { useGuardiaSalida } from "./guardia";
import { agrupar, cuerpoParaGuardar, esSucio, leerErrores, SIN_ERRORES } from "./modelo";
import type { ErroresFormato, EstadoFormato, Plantilla } from "./modelo";
import "./estilos.css";

interface Carga {
  campos: CampoFormato[];
  documentos: FormatoRespuesta["documentos"];
  guardado: EstadoFormato;
}

const aCarga = (r: FormatoRespuesta): Carga => ({
  campos: r.campos,
  documentos: r.documentos,
  guardado: { valores: r.valores, plantilla: r.plantilla_gen },
});

const mensajeDe = (e: unknown) => (e instanceof Error ? e.message : "Error desconocido");

function sinErroresEditados(errores: ErroresFormato, antes: Despacho, despues: Despacho): ErroresFormato {
  const registro = (v: Despacho) => v as unknown as Record<string, unknown>;
  const porCampo = { ...errores.porCampo };
  let cambio = false;
  for (const clave of Object.keys(porCampo)) {
    if (JSON.stringify(registro(antes)[clave]) !== JSON.stringify(registro(despues)[clave])) {
      delete porCampo[clave];
      cambio = true;
    }
  }
  return cambio ? { ...errores, porCampo } : errores;
}

export default function Formato() {
  const [carga, setCarga] = useState<Carga | null>(null);
  const [actual, setActual] = useState<EstadoFormato | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [intento, setIntento] = useState(0);
  const [documento, setDocumento] = useState("fallo");
  const [foco, setFoco] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [errores, setErrores] = useState<ErroresFormato>(SIN_ERRORES);
  const [errorGuardado, setErrorGuardado] = useState<string | null>(null);
  const enfocarError = useRef(false);

  useEffect(() => {
    const control = new AbortController();
    setErrorCarga(null);
    api.get<FormatoRespuesta>("/api/formato", { signal: control.signal }).then(
      (r) => {
        const nueva = aCarga(r);
        setCarga(nueva);
        setActual(nueva.guardado);
        setDocumento(r.documentos.some((d) => d.id === "fallo") ? "fallo" : (r.documentos[0]?.id ?? "fallo"));
      },
      (e: unknown) => {
        if (!esAbortado(e)) setErrorCarga(mensajeDe(e));
      },
    );
    return () => control.abort();
  }, [intento]);

  const secciones = useMemo(() => (carga ? agrupar(carga.campos) : []), [carga]);
  const sucio = carga !== null && actual !== null && esSucio(actual, carga.guardado);
  const guardia = useGuardiaSalida(sucio);

  useLayoutEffect(() => {
    if (!enfocarError.current || !carga) return;
    enfocarError.current = false;
    const primero = carga.campos.find((c) => errores.porCampo[c.clave]);
    const control = primero ? document.getElementById(`f-${primero.clave}`) : null;
    (control?.matches("input, textarea") ? control : control?.querySelector<HTMLElement>("input"))?.focus();
  }, [errores, carga]);

  if (errorCarga !== null) {
    return (
      <div data-vista="formato">
        <Aviso
          tipo="error"
          titulo="No se pudo cargar el formato de los documentos"
          acciones={
            <Boton onClick={() => setIntento((n) => n + 1)}>Reintentar</Boton>
          }
        >
          {errorCarga}
        </Aviso>
      </div>
    );
  }
  if (!carga || !actual) {
    return (
      <div data-vista="formato">
        <Cargando texto="Cargando el formato…" />
      </div>
    );
  }

  const cambiarValores = (valores: Despacho) => {
    setErrores((e) => sinErroresEditados(e, actual.valores, valores));
    setActual({ ...actual, valores });
  };
  const cambiarPlantilla = (plantilla: Plantilla) => {
    setActual({ ...actual, plantilla });
    setDocumento("fallo");
    setFoco(null);
  };
  const alEnfocar = (campo: CampoFormato) => {
    setFoco(campo.clave);
    const primero = campo.documentos[0];
    if (!campo.documentos.includes(documento) && primero) setDocumento(primero);
  };
  const ver = (campo: CampoFormato, id: string) => {
    setFoco(campo.clave);
    setDocumento(id);
  };
  const descartar = () => {
    setActual(carga.guardado);
    setErrores(SIN_ERRORES);
    setErrorGuardado(null);
    setFoco(null);
  };
  const guardar = async () => {
    if (guardando) return;
    setGuardando(true);
    setErrorGuardado(null);
    try {
      const respuesta = await api.put<FormatoRespuesta>("/api/formato", cuerpoParaGuardar(actual, carga.campos));
      const nueva = aCarga(respuesta);
      setCarga(nueva);
      setActual(nueva.guardado);
      setErrores(SIN_ERRORES);
      mostrarToast("Formato guardado", { tipo: "ok" });
    } catch (e) {
      const detalle = e instanceof ErrorApi && e.estado === 422 ? leerErrores(e.detalle, carga.campos) : null;
      if (detalle) {
        setErrores(detalle);
        enfocarError.current = true;
      } else {
        setErrorGuardado(mensajeDe(e));
      }
    } finally {
      setGuardando(false);
    }
  };

  const nErrores = Object.keys(errores.porCampo).length;
  return (
    <div data-vista="formato" data-sucio={sucio ? "" : undefined}>
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Formato de documentos" }]} />
      <h1 class="titulo">Formato de los documentos</h1>
      <p class="sub fmt-intro">Lo que escriba aquí aparece en el fallo, el auto, el oficio y los correos. La vista previa muestra dónde.</p>
      <Aviso class="fmt-aviso">
        <strong>Los cambios aplican solo a casos nuevos.</strong> Cada caso conserva el formato que tenía cuando se creó.
      </Aviso>
      {(nErrores > 0 || errores.generales.length > 0) && (
        <Aviso tipo="error" titulo="El servidor no aceptó el formato" class="fmt-aviso">
          {errores.generales.map((g) => (
            <p key={g}>{g}</p>
          ))}
          {nErrores > 0 && <p>Revise los campos marcados.</p>}
        </Aviso>
      )}
      {errorGuardado !== null && (
        <Aviso tipo="error" titulo="No se pudo guardar el formato" class="fmt-aviso">
          {errorGuardado}
        </Aviso>
      )}
      <div class="fmt-dos">
        <Formulario
          secciones={secciones}
          documentos={carga.documentos}
          valores={actual.valores}
          plantilla={actual.plantilla}
          errores={errores}
          onValores={cambiarValores}
          onPlantilla={cambiarPlantilla}
          onFoco={alEnfocar}
          onVer={ver}
        />
        <Previa
          documentos={carga.documentos}
          campos={carga.campos}
          documento={documento}
          valores={actual.valores}
          plantilla={actual.plantilla}
          foco={foco}
          onDocumento={setDocumento}
        />
      </div>
      {sucio && (
        <div class="fmt-barra" role="region" aria-label="Cambios sin guardar">
          <div>
            <p role="status">
              <b>Hay cambios sin guardar.</b> Se aplican a los casos nuevos.
            </p>
            <Boton onClick={descartar} disabled={guardando}>
              Descartar
            </Boton>
            <Boton variante="primario" grande cargando={guardando} onClick={guardar}>
              Guardar formato
            </Boton>
          </div>
        </div>
      )}
      <Dialogo
        abierto={guardia.destino !== null}
        titulo="Hay cambios sin guardar"
        onCerrar={guardia.quedarse}
        acciones={
          <>
            <Boton data-enfoque onClick={guardia.quedarse}>
              Seguir editando
            </Boton>
            <Boton variante="peligro" onClick={guardia.salir}>
              Salir sin guardar
            </Boton>
          </>
        }
      >
        <p>Si sale ahora, pierde los cambios que hizo en el formato de los documentos.</p>
      </Dialogo>
    </div>
  );
}
