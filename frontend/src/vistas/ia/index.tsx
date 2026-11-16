import { useEffect, useId, useRef, useState } from "preact/hooks";
import { api, esAbortado } from "../../api";
import type { ModoJev, PreferenciasIa, Proveedor, RazonamientoGemini } from "../../api/contrato";
import { cargarEstadoServidor, claveDe, DATOS_PROVEEDOR, mostrarToast, nombreModelo, porcentaje, useTitulo } from "../../estado";
import { Aviso, Boton, Cargando, Migas } from "../../ui";
import { DATOS_CLAVE, DialogoClave } from "./DialogoClave";
import type { TipoClave } from "./DialogoClave";
import {
  aCuerpo,
  aFormulario,
  CAMPOS_AVANZADOS,
  ESFUERZOS,
  igual,
  leerErrorServidor,
  MAX_REINTENTOS,
  MAX_TOKENS,
  NIVELES_GEMINI,
  nivelAjustado,
  nivelesDe,
  validar,
} from "./formulario";
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

const FAMILIA: Record<Proveedor, string> = { anthropic: "Modelos Claude", gemini: "Modelos Gemini" };

const opcionesProveedor = (p: PreferenciasIa) =>
  (["anthropic", "gemini"] as const).map((valor) => ({
    valor,
    titulo: DATOS_PROVEEDOR[valor].nombre,
    detalle: `${FAMILIA[valor]}. ${claveDe(p, valor) ? "Clave lista." : "Sin clave."}`,
  }));

const MEMORIA = "La clave vive solo en la memoria del servidor: no se guarda en disco y se pierde al reiniciarlo.";

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
  const idProveedor = useId();
  const idEsfuerzo = useId();
  const idModelo = useId();
  const idModeloGemini = useId();
  const idNivel = useId();
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
    const locales = validar(form, base);
    setIntentado(true);
    if (Object.keys(locales).length) {
      mostrarErrores(locales);
      return;
    }
    if (igual(form, aFormulario(base))) return;
    setGuardando(true);
    try {
      const nuevo = await api.put<PreferenciasIa>("/api/ia", aCuerpo(form, base));
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
    setBase((b) => (b ? { ...b, api_key: tipo === "anthropic" || b.api_key, gemini_key: tipo === "gemini" || b.gemini_key, jev_key: tipo === "jev" || b.jev_key } : b));
    setClaveAbierta(null);
    mostrarToast(`Clave de ${DATOS_CLAVE[tipo].proveedor} guardada.`, { tipo: "ok" });
    void cargarEstadoServidor(true);
  };

  const cabecera = (
    <>
      <Migas items={MIGAS} />
      <h1 class="titulo">Inteligencia artificial</h1>
      <p class="sub ia-intro">Qué modelo redacta los borradores, con qué clave y cómo se verifican las citas.</p>
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

  const errores: ErroresForm = { ...(intentado ? validar(form, base) : {}), ...errServidor };
  const cambios = !igual(form, aFormulario(base));
  const encendido = form.modo !== "apagado";
  const sinModelos = base.modelos.length === 0;
  const modeloNoPermitido = !base.modelos.includes(base.modelo);
  const sinModelosGemini = base.modelos_gemini.length === 0;
  const modeloGeminiNoPermitido = !base.modelos_gemini.includes(base.gemini.modelo);
  const nombreActivo = DATOS_PROVEEDOR[form.proveedor].nombre;
  const estado = cambios ? "Hay cambios sin guardar." : guardado ? "Cambios guardados." : "";

  return (
    <div data-vista="ia" class="ia">
      {cabecera}
      <form ref={raiz} onSubmit={guardar} noValidate>
        <section class="ia-sec" aria-labelledby={`${idProveedor}-t`}>
          <h2 id={`${idProveedor}-t`}>Proveedor</h2>
          <p class="sub" id={`${idProveedor}-d`}>
            Quién redacta los borradores. Vale para todos los casos desde la siguiente redacción.
          </p>
          <Tarjetas
            nombre="proveedor"
            legenda="Proveedor"
            class="ia-tarjetas-dos"
            opciones={opcionesProveedor(base)}
            valor={form.proveedor}
            onCambio={(v) => editar({ proveedor: v as Proveedor }, ["proveedor"])}
            idDescripcion={`${idProveedor}-d`}
            idError={errores.proveedor ? `${idProveedor}-e` : undefined}
          />
          <MensajeError id={`${idProveedor}-e`} texto={errores.proveedor} />
          {!claveDe(base, form.proveedor) && (
            <Aviso class="ia-aviso-clave" tipo="alerta" titulo={`Falta la clave de ${nombreActivo}`}>
              La redacción no funcionará hasta que agregue la clave en la sección {nombreActivo}, más abajo.
            </Aviso>
          )}
        </section>

        <section class="ia-sec" aria-labelledby="ia-anthropic-t">
          <h2 id="ia-anthropic-t">Anthropic</h2>
          <p class="sub">{MEMORIA}</p>
          <EstadoClave
            hay={base.api_key}
            textoSi="Hay una clave lista."
            textoNo="No hay clave. Agréguela para elegir el modelo de Anthropic."
            accion={["Reemplazar clave", "Agregar clave"]}
            onAccion={() => setClaveAbierta("anthropic")}
          />
          {base.api_key && (
            <div class="ia-opciones">
              <h3 id={`${idModelo}-t`}>Modelo</h3>
              {sinModelos ? (
                <Aviso tipo="alerta" titulo="No hay modelos permitidos en este servidor">
                  La configuración del servidor (TUTELA2_MODELOS_PERMITIDOS) no deja ningún modelo disponible, así que la redacción no funcionará hasta que se corrija.
                </Aviso>
              ) : (
                <>
                  {modeloNoPermitido && (
                    <Aviso tipo="alerta" titulo="El modelo guardado no está permitido en este servidor">
                      El modelo guardado ({nombreModelo(base.modelo)}) no está entre los que este servidor permite, y la redacción fallará mientras no elija uno de los disponibles y guarde.
                    </Aviso>
                  )}
                  <div>
                    <Tarjetas
                      nombre="modelo"
                      legenda="Modelo de Anthropic"
                      opciones={opcionesModelo(base.modelos)}
                      valor={form.modelo}
                      onCambio={(v) => editar({ modelo: v }, ["modelo"])}
                      idError={errores.modelo ? `${idModelo}-e` : undefined}
                    />
                    <MensajeError id={`${idModelo}-e`} texto={errores.modelo} />
                  </div>
                  <div class="campo ia-razonamiento">
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
                </>
              )}
            </div>
          )}
        </section>

        <section class="ia-sec" aria-labelledby="ia-gemini-t">
          <h2 id="ia-gemini-t">Gemini (Google)</h2>
          <p class="sub">{MEMORIA}</p>
          <Aviso class="ia-aviso-datos" tipo="alerta" titulo="Con una clave gratuita, Google puede usar lo que se envía">
            Si la clave es del nivel gratuito, Google puede usar el contenido que recibe y las respuestas para mejorar sus productos, y personas pueden revisarlo. Para casos reales use una clave de un
            proyecto de Google Cloud con la facturación activa: con ella Google no usa las instrucciones ni las respuestas para mejorar sus productos (
            <a href="https://aistudio.google.com/docs/terms.md" target="_blank" rel="noreferrer">
              Condiciones adicionales de la API de Gemini
            </a>
            ).
          </Aviso>
          <EstadoClave
            hay={base.gemini_key}
            textoSi="Hay una clave lista."
            textoNo="No hay clave. Agréguela para elegir el modelo de Gemini."
            accion={["Reemplazar clave", "Agregar clave"]}
            onAccion={() => setClaveAbierta("gemini")}
          />
          {base.gemini_key && (
            <div class="ia-opciones">
              <h3 id={`${idModeloGemini}-t`}>Modelo</h3>
              {sinModelosGemini ? (
                <Aviso tipo="alerta" titulo="No hay modelos de Gemini permitidos en este servidor">
                  La configuración del servidor (TUTELA2_MODELOS_PERMITIDOS) no deja ningún modelo de Gemini disponible, así que con este proveedor la redacción no funcionará hasta que se corrija.
                </Aviso>
              ) : (
                <>
                  {modeloGeminiNoPermitido && (
                    <Aviso tipo="alerta" titulo="El modelo de Gemini guardado no está permitido en este servidor">
                      El modelo guardado ({nombreModelo(base.gemini.modelo)}) no está entre los que este servidor permite, y la redacción con Gemini fallará mientras no elija uno de los disponibles y guarde.
                    </Aviso>
                  )}
                  <div>
                    <Tarjetas
                      nombre="modelo-gemini"
                      legenda="Modelo de Gemini"
                      opciones={opcionesModelo(base.modelos_gemini)}
                      valor={form.modeloGemini}
                      onCambio={(v) => editar({ modeloGemini: v, razonamiento: nivelAjustado(base, v, form.razonamiento) }, ["gemini_modelo", "razonamiento"])}
                      idError={errores.gemini_modelo ? `${idModeloGemini}-e` : undefined}
                    />
                    <MensajeError id={`${idModeloGemini}-e`} texto={errores.gemini_modelo} />
                  </div>
                  <div class="campo ia-razonamiento">
                    <label for={idNivel}>Nivel de razonamiento</label>
                    <select
                      id={idNivel}
                      value={form.razonamiento}
                      aria-describedby={describe(idNivel, errores.razonamiento)}
                      aria-invalid={errores.razonamiento ? "true" : undefined}
                      onChange={(ev) => editar({ razonamiento: ev.currentTarget.value as RazonamientoGemini }, ["razonamiento"])}
                    >
                      {NIVELES_GEMINI.filter((o) => nivelesDe(base, form.modeloGemini).includes(o.valor)).map((o) => (
                        <option key={o.valor} value={o.valor}>
                          {o.texto}
                        </option>
                      ))}
                    </select>
                    <small id={`${idNivel}-d`}>Solo los niveles que admite {nombreModelo(form.modeloGemini)}. Más razonamiento piensa más a fondo, pero tarda más y cuesta más.</small>
                    <MensajeError id={`${idNivel}-e`} texto={errores.razonamiento} />
                  </div>
                </>
              )}
            </div>
          )}
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

        <section class="ia-sec" aria-labelledby="ia-extension-t">
          <h2 id="ia-extension-t">Extensión de la relatoría</h2>
          <p class="sub">La relatoría de la Corte Constitucional rechaza las consultas de este servidor. La extensión las hace desde un navegador en Colombia para verificar las citas.</p>
          <Boton href="/api/extension/zip" download="">
            Descargar extensión (.zip)
          </Boton>
          <ol class="ia-pasos" aria-label="Pasos para instalar la extensión">
            <li>
              Descomprima el archivo descargado y mueva la carpeta <code>judicabot-relatoria</code> que queda adentro a un lugar fijo, por ejemplo Documentos. No la borre: el navegador la usa mientras la extensión esté instalada.
            </li>
            <li>
              En Chrome abra <code>chrome://extensions</code>; en Edge, <code>edge://extensions</code>.
            </li>
            <li>Active «Modo de desarrollador».</li>
            <li>
              Pulse «Cargar extensión sin empaquetar» (según el navegador puede decir «Cargar descomprimida» o «Cargar desempaquetado») y elija la carpeta <code>judicabot-relatoria</code> (la que contiene <code>manifest.json</code>).
            </li>
            <li>
              Abra la extensión desde el botón de extensiones del navegador. En «Servidor» debe quedar <code>{location.origin}</code>; escriba la contraseña de judicabot y pulse «Conectar». Debe aparecer «Conectada».
            </li>
            <li>Deje ese navegador abierto. Si se cierra, las citas que el servidor no pueda verificar quedan para revisar.</li>
          </ol>
          <p class="sub ia-nota-ext">
            Para actualizarla, descargue el archivo de nuevo, descomprímalo y copie el contenido de su carpeta <code>judicabot-relatoria</code> sobre la carpeta que ya instaló, reemplazando los archivos; después pulse el botón de volver a cargar (la flecha circular) en la tarjeta de la extensión. Si su equipo no deja activar el modo de desarrollador, pida ayuda a soporte técnico.
          </p>
        </section>

        <section class="ia-sec">
          <details class="avanzado" open={avanzado} onToggle={(ev) => setAvanzado(ev.currentTarget.open)}>
            <summary>Opciones avanzadas</summary>
            <div class="ia-campos">
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
        existente={claveAbierta === "jev" ? base.jev_key : claveAbierta === "gemini" ? base.gemini_key : base.api_key}
        onCerrar={() => setClaveAbierta(null)}
        onGuardada={claveGuardada}
      />
    </div>
  );
}
