import { useEffect, useId, useRef, useState } from "preact/hooks";
import { api, esAbortado } from "../../api";
import type { ModoJev, PreferenciasIa } from "../../api/contrato";
import { cargarEstadoServidor, mostrarToast, nombreModelo, porcentaje, useTitulo } from "../../estado";
import { Aviso, Boton, Cargando, Migas } from "../../ui";
import { DATOS_CLAVE, DialogoClave } from "./DialogoClave";
import type { TipoClave } from "./DialogoClave";
import { aCuerpo, aFormulario, CAMPOS_AVANZADOS, ESFUERZOS, igual, leerErrorServidor, MAX_REINTENTOS, MAX_TOKENS, validar } from "./formulario";
import type { CampoForm, ErroresForm, Formulario } from "./formulario";
import { opcionesModelo, OPCIONES_JEV } from "./modelos";
import { Tarjetas } from "./Tarjetas";
import "./estilos.css";

const MIGAS = [{ texto: "Inicio", href: "#/" }, { texto: "Inteligencia artificial" }];

function EstadoClave({ hay, textoSi, textoNo, accion, onAccion }: { hay: boolean; textoSi: string; textoNo: string; accion: [string, string]; onAccion: () => void }) {
  return (
    <div class="ia-clave">
      <div class="estado-clave" role="status">
        <span class={hay ? "punto" : "punto mal"} aria-hidden="true" />
        <span>{hay ? textoSi : textoNo}</span>
      </div>
      <Boton onClick={onAccion}>{hay ? accion[0] : accion[1]}</Boton>
    </div>
  );
}

const describe = (id: string, error?: string) => (error ? `${id}-d ${id}-e` : `${id}-d`);

function MensajeError({ id, texto }: { id: string; texto?: string }) {
  return texto ? (
    <p class="ia-error" id={id}>
      {texto}
    </p>
  ) : null;
}

export default function InteligenciaArtificial() {
  useTitulo("Inteligencia artificial");
  const raiz = useRef<HTMLFormElement>(null);
  const [base, setBase] = useState<PreferenciasIa | null>(null);
  const [form, setForm] = useState<Formulario | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [intento, setIntento] = useState(0);
  const [intentado, setIntentado] = useState(false);
  const [errServidor, setErrServidor] = useState<ErroresForm>({});
  const [generales, setGenerales] = useState<string[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [guardado, setGuardado] = useState(false);
  const [avanzado, setAvanzado] = useState(false);
  const [claveAbierta, setClaveAbierta] = useState<TipoClave | null>(null);
  const idUmbral = useId();
  const idTokens = useId();
  const idReintentos = useId();
  const idEsfuerzo = useId();
  const idModelo = useId();
  const idModo = useId();
  const idProximamente = useId();

  useEffect(() => {
    const controlador = new AbortController();
    setErrorCarga(null);
    api.get<PreferenciasIa>("/api/ia", { signal: controlador.signal }).then(
      (datos) => {
        setBase(datos);
        setForm(aFormulario(datos));
      },
      (err: unknown) => {
        if (!esAbortado(err)) setErrorCarga(leerErrorServidor(err, "No se pudo conectar con el servidor.").generales.join(" "));
      },
    );
    return () => controlador.abort();
  }, [intento]);

  const enfocarInvalido = () => {
    setTimeout(() => raiz.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);
  };

  const editar = (cambios: Partial<Formulario>, campos: CampoForm[]) => {
    setForm((f) => (f ? { ...f, ...cambios } : f));
    setGuardado(false);
    setGenerales([]);
    setErrServidor((e) => {
      const nuevo = { ...e };
      for (const c of campos) delete nuevo[c];
      return nuevo;
    });
  };

  const mostrarErrores = (errores: ErroresForm) => {
    if (CAMPOS_AVANZADOS.some((c) => errores[c])) setAvanzado(true);
    enfocarInvalido();
  };

  const guardar = async (e: Event) => {
    e.preventDefault();
    if (!base || !form) return;
    setGuardado(false);
    setGenerales([]);
    const locales = validar(form, base.modelos);
    setIntentado(true);
    if (Object.keys(locales).length) {
      mostrarErrores(locales);
      return;
    }
    if (igual(form, aFormulario(base))) return;
    setGuardando(true);
    try {
      const nuevo = await api.put<PreferenciasIa>("/api/ia", aCuerpo(form));
      setBase(nuevo);
      setForm(aFormulario(nuevo));
      setErrServidor({});
      setIntentado(false);
      setGuardado(true);
      mostrarToast("Preferencias guardadas.", { tipo: "ok" });
      void cargarEstadoServidor(true);
    } catch (err) {
      const { campos, generales: otros } = leerErrorServidor(err, "No se pudieron guardar las preferencias.");
      setErrServidor(campos);
      setGenerales(otros);
      mostrarErrores(campos);
    } finally {
      setGuardando(false);
    }
  };

  const claveGuardada = (tipo: TipoClave) => {
    setBase((b) => (b ? { ...b, api_key: tipo === "anthropic" || b.api_key, jev_key: tipo === "jev" || b.jev_key } : b));
    setClaveAbierta(null);
    mostrarToast(`Clave de ${DATOS_CLAVE[tipo].proveedor} guardada.`, { tipo: "ok" });
    void cargarEstadoServidor(true);
  };

  const cabecera = (
    <>
      <Migas items={MIGAS} />
      <h1 class="titulo">Inteligencia artificial</h1>
      <p class="sub ia-intro">Qué modelo redacta los borradores y con qué clave.</p>
    </>
  );

  if (errorCarga) {
    return (
      <div data-vista="ia" class="ia">
        {cabecera}
        <Aviso tipo="error" titulo="No se pudieron cargar las preferencias" acciones={<Boton onClick={() => setIntento((n) => n + 1)}>Reintentar</Boton>}>
          {errorCarga}
        </Aviso>
      </div>
    );
  }

  if (!base || !form) {
    return (
      <div data-vista="ia" class="ia">
        {cabecera}
        <Cargando texto="Cargando preferencias…" />
      </div>
    );
  }

  const errores: ErroresForm = { ...(intentado ? validar(form, base.modelos) : {}), ...errServidor };
  const cambios = !igual(form, aFormulario(base));
  const encendido = form.modo !== "apagado";
  const sinModelos = base.modelos.length === 0;
  const modeloNoPermitido = !base.modelos.includes(base.modelo);
  const estado = cambios ? "Hay cambios sin guardar." : guardado ? "Cambios guardados." : "";

  return (
    <div data-vista="ia" class="ia">
      {cabecera}
      <form ref={raiz} onSubmit={guardar} noValidate>
        <section class="ia-sec" aria-labelledby={`${idModelo}-t`}>
          <h2 id={`${idModelo}-t`}>Modelo</h2>
          <p class="sub" id={`${idModelo}-d`}>
            Vale para todos los casos desde la siguiente redacción.
          </p>
          {sinModelos ? (
            <Aviso class="ia-aviso-modelo" tipo="alerta" titulo="No hay modelos permitidos en este servidor">
              La configuración del servidor (TUTELA2_MODELOS_PERMITIDOS) no deja ningún modelo disponible, así que la redacción no funcionará hasta que se corrija.
            </Aviso>
          ) : (
            modeloNoPermitido && (
              <Aviso class="ia-aviso-modelo" tipo="alerta" titulo="El modelo guardado no está permitido en este servidor">
                El modelo guardado ({nombreModelo(base.modelo)}) no está entre los que este servidor permite, y la redacción fallará mientras no elija uno de los disponibles y guarde.
              </Aviso>
            )
          )}
          {!sinModelos && (
            <Tarjetas
              nombre="modelo"
              legenda="Modelo"
              opciones={opcionesModelo(base.modelos)}
              valor={form.modelo}
              onCambio={(v) => editar({ modelo: v }, ["modelo"])}
              idDescripcion={`${idModelo}-d`}
              idError={errores.modelo ? `${idModelo}-e` : undefined}
            />
          )}
          <MensajeError id={`${idModelo}-e`} texto={errores.modelo} />
        </section>

        <section class="ia-sec" aria-labelledby="ia-clave-t">
          <h2 id="ia-clave-t">Clave de Anthropic</h2>
          <p class="sub">Vive solo en la memoria del servidor: no se guarda en disco y se pierde al reiniciarlo.</p>
          <EstadoClave
            hay={base.api_key}
            textoSi="Hay una clave lista."
            textoNo="No hay clave. Sin ella no se puede redactar."
            accion={["Reemplazar clave", "Agregar clave"]}
            onAccion={() => setClaveAbierta("anthropic")}
          />
        </section>

        <section class="ia-sec" aria-labelledby={`${idModo}-t`}>
          <h2 id={`${idModo}-t`}>Jev, segunda opinión</h2>
          <p class="sub" id={`${idModo}-d`}>
            Verifica los roles de los documentos y los datos del fallo de primera instancia. Nunca decide el sentido del fallo.
          </p>
          <Tarjetas
            nombre="jev"
            legenda="Modo de Jev"
            opciones={OPCIONES_JEV}
            valor={form.modo}
            onCambio={(v) => editar({ modo: v as ModoJev }, ["modo"])}
            idDescripcion={`${idModo}-d`}
            idError={errores.modo ? `${idModo}-e` : undefined}
          />
          <MensajeError id={`${idModo}-e`} texto={errores.modo} />
          {encendido && (
            <div class="ia-jev-detalle">
              <Aviso tipo="alerta" titulo="Esta información sale del despacho">
                Con Jev encendido se envían a TypeSafe AI fragmentos del expediente: la cabecera de cada documento y la cola del fallo de primera instancia, nunca el expediente completo. Antes de usarlo con
                casos reales, confirme que sus términos cumplen el artículo 8.6 del Acuerdo PCSJA24-12243.
              </Aviso>
              <div class="campo">
                <label for={idUmbral}>Confianza mínima de Jev</label>
                <div class="ia-rango">
                  <input
                    id={idUmbral}
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={form.umbral}
                    aria-valuetext={porcentaje(form.umbral / 100)}
                    aria-describedby={describe(idUmbral, errores.umbral)}
                    aria-invalid={errores.umbral ? "true" : undefined}
                    onInput={(ev) => editar({ umbral: Number(ev.currentTarget.value) }, ["umbral"])}
                  />
                  <output for={idUmbral}>{porcentaje(form.umbral / 100)}</output>
                </div>
                <small id={`${idUmbral}-d`}>Jev solo se tiene en cuenta cuando su confianza llega a este valor; por debajo, su opinión se ignora.</small>
                <MensajeError id={`${idUmbral}-e`} texto={errores.umbral} />
              </div>
              <EstadoClave
                hay={base.jev_key}
                textoSi="Hay una clave de Jev lista."
                textoNo="No hay clave de Jev. Sin ella no se le consulta, aunque esté encendido."
                accion={["Reemplazar clave", "Agregar clave"]}
                onAccion={() => setClaveAbierta("jev")}
              />
            </div>
          )}
        </section>

        <section class="ia-sec">
          <details class="avanzado" open={avanzado} onToggle={(ev) => setAvanzado(ev.currentTarget.open)}>
            <summary>Opciones avanzadas</summary>
            <div class="ia-campos">
              <div class="campo">
                <label for={idEsfuerzo}>Esfuerzo de razonamiento</label>
                <select
                  id={idEsfuerzo}
                  value={form.effort}
                  aria-describedby={describe(idEsfuerzo, errores.effort)}
                  aria-invalid={errores.effort ? "true" : undefined}
                  onChange={(ev) => editar({ effort: ev.currentTarget.value as Formulario["effort"] }, ["effort"])}
                >
                  {ESFUERZOS.map((o) => (
                    <option key={o.valor} value={o.valor}>
                      {o.texto}
                    </option>
                  ))}
                </select>
                <small id={`${idEsfuerzo}-d`}>Más esfuerzo razona más a fondo, pero tarda más y cuesta más.</small>
                <MensajeError id={`${idEsfuerzo}-e`} texto={errores.effort} />
              </div>
              <div class="campo">
                <label for={idTokens}>Máximo de tokens de salida</label>
                <input
                  id={idTokens}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={MAX_TOKENS}
                  step={1}
                  value={form.maxTokens}
                  aria-describedby={describe(idTokens, errores.max_tokens)}
                  aria-invalid={errores.max_tokens ? "true" : undefined}
                  onInput={(ev) => editar({ maxTokens: ev.currentTarget.value }, ["max_tokens"])}
                />
                <small id={`${idTokens}-d`}>Entre 1 y 64.000. Súbalo si una respuesta se corta.</small>
                <MensajeError id={`${idTokens}-e`} texto={errores.max_tokens} />
              </div>
              <div class="campo">
                <label for={idReintentos}>Reintentos por llamada</label>
                <input
                  id={idReintentos}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={MAX_REINTENTOS}
                  step={1}
                  value={form.maxRetries}
                  aria-describedby={describe(idReintentos, errores.max_retries)}
                  aria-invalid={errores.max_retries ? "true" : undefined}
                  onInput={(ev) => editar({ maxRetries: ev.currentTarget.value }, ["max_retries"])}
                />
                <small id={`${idReintentos}-d`}>Entre 0 y {MAX_REINTENTOS}. Veces que se vuelve a intentar una llamada al modelo si falla.</small>
                <MensajeError id={`${idReintentos}-e`} texto={errores.max_retries} />
              </div>
              <div class="campo">
                <span class="ia-etiqueta">Instrucciones del modelo</span>
                <div class="ia-prox">
                  <Boton disabled aria-describedby={idProximamente}>
                    Editar instrucciones
                  </Boton>
                  <span id={idProximamente} class="ia-proximamente">
                    Próximamente
                  </span>
                </div>
              </div>
            </div>
          </details>
        </section>

        {generales.length > 0 && (
          <Aviso class="ia-aviso-guardar" tipo="error" titulo="No se pudo guardar">
            {generales.map((g) => (
              <p key={g}>{g}</p>
            ))}
          </Aviso>
        )}
        <div class="ia-guardar">
          <p class="ia-estado" role="status">
            {estado}
          </p>
          <Boton variante="primario" type="submit" cargando={guardando}>
            Guardar cambios
          </Boton>
        </div>
      </form>
      <DialogoClave
        tipo={claveAbierta}
        existente={claveAbierta === "jev" ? base.jev_key : base.api_key}
        onCerrar={() => setClaveAbierta(null)}
        onGuardada={claveGuardada}
      />
    </div>
  );
}
