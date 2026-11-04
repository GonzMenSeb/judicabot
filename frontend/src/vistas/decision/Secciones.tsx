import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { Boton, Chip } from "../../ui";
import {
  admiteOrdenes,
  agregarDerecho,
  agregarLibre,
  agregarOrden,
  CARENCIAS,
  CAUSALES,
  fechaLarga,
  DISPOSICIONES_DERECHO,
  DISPOSICIONES_REPARO,
  elegirSustitutiva,
  SUSTITUTIVAS,
  RESULTADOS,
  sustitutivaEfectiva,
  UNIDADES,
  VERBOS,
} from "./formulario";
import type { Causal, Formulario, OrdenForm, PayloadDecision, SustitutivaForm } from "./tipos";

export type Cambiar = (fn: (f: Formulario) => Formulario) => void;

export interface PropsSeccion {
  f: Formulario;
  cambiar: Cambiar;
  err: (campo: string) => string | undefined;
}

function atributos(id: string, error?: string, ayuda?: boolean) {
  const descripcion = [ayuda ? `${id}-ayuda` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ");
  return { id, "aria-invalid": error ? ("true" as const) : undefined, "aria-describedby": descripcion || undefined };
}

interface PropsCampo {
  id: string;
  etiqueta: string;
  ayuda?: string;
  error?: string | undefined;
  class?: string;
  children: ComponentChildren;
}

function Campo({ id, etiqueta, ayuda, error, class: clase, children }: PropsCampo) {
  return (
    <div class={`campo${clase ? ` ${clase}` : ""}`}>
      <label for={id}>{etiqueta}</label>
      {children}
      {ayuda && <small id={`${id}-ayuda`}>{ayuda}</small>}
      {error && (
        <small class="dec-error" id={`${id}-error`}>
          {error}
        </small>
      )}
    </div>
  );
}

function Casilla({ id, checked, onChange, children }: { id: string; checked: boolean; onChange: (v: boolean) => void; children: ComponentChildren }) {
  return (
    <label class="dec-interr" for={id}>
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.currentTarget.checked)} />
      <span>{children}</span>
    </label>
  );
}

function Seccion({ titulo, sub, id, children, oculta }: { titulo: string; sub?: string; id: string; children: ComponentChildren; oculta?: boolean }) {
  if (oculta) return null;
  return (
    <section class="dec-sec" aria-labelledby={`${id}-t`}>
      <h2 id={`${id}-t`}>{titulo}</h2>
      {sub && <p class="sub">{sub}</p>}
      {children}
    </section>
  );
}

const OPCIONES_CAUSAL: readonly (readonly [Causal | "", string])[] = [["", "Sin causal"], ...CAUSALES];

export function QueDecide({ f, cambiar, err }: PropsSeccion) {
  const noConfirma = f.resultado !== "" && f.resultado !== "CONFIRMAR";
  const enCarencia = f.sustitutiva === "CARENCIA" || f.sustitutiva.startsWith("CARENCIA_");
  const errResultado = err("resultado");
  const errSust = err("sustitutiva");
  const errEje = err("eje");
  const elegir = (s: SustitutivaForm) => cambiar((x) => elegirSustitutiva(x, s));
  return (
    <Seccion id="dec-decide" titulo="Qué decide" sub="Frente a la sentencia de primera instancia.">
      <div class="dec-seg" role="radiogroup" aria-label="Resultado" id="dec-resultado" aria-invalid={errResultado ? "true" : undefined} aria-describedby={errResultado ? "dec-resultado-error" : undefined}>
        {RESULTADOS.map(([valor, texto]) => (
          <label key={valor} class={f.resultado === valor ? "activa" : ""}>
            <input type="radio" name="dec-resultado" class="solo-lectura" value={valor} checked={f.resultado === valor} onChange={() => cambiar((x) => ({ ...x, resultado: valor }))} />
            {texto}
          </label>
        ))}
      </div>
      {errResultado && (
        <small class="dec-error" id="dec-resultado-error">
          {errResultado}
        </small>
      )}
      {noConfirma && (
        <div class="dec-hijo">
          <p class="dec-etiqueta" id="dec-sust-t">
            En su lugar, el Despacho
          </p>
          <div class="dec-opciones" role="radiogroup" aria-labelledby="dec-sust-t" id="dec-sustitutiva" aria-invalid={errSust ? "true" : undefined} aria-describedby={errSust ? "dec-sustitutiva-error" : undefined}>
            {SUSTITUTIVAS.map(([valor, titulo, detalle]) => {
              const activa = valor === "CARENCIA" ? enCarencia : f.sustitutiva === valor;
              return (
                <label key={valor} class={`dec-opcion${activa ? " activa" : ""}`}>
                  <input type="radio" name="dec-sustitutiva" class="solo-lectura" value={valor} checked={activa} onChange={() => (valor === "CARENCIA" && enCarencia ? undefined : elegir(valor))} />
                  <span class="rad" aria-hidden="true" />
                  <span>
                    <b>{titulo}</b>
                    <small class="sub">{detalle}</small>
                  </span>
                </label>
              );
            })}
          </div>
          {errSust && (
            <small class="dec-error" id="dec-sustitutiva-error">
              {errSust}
            </small>
          )}
          {enCarencia && (
            <div class="dec-carencias" role="radiogroup" aria-label="Tipo de carencia actual de objeto">
              {CARENCIAS.map(([valor, texto]) => (
                <label key={valor} class={f.sustitutiva === valor ? "activa" : ""}>
                  <input type="radio" name="dec-carencia" class="solo-lectura" value={valor} checked={f.sustitutiva === valor} onChange={() => elegir(valor)} />
                  {texto}
                </label>
              ))}
            </div>
          )}
          {f.sustitutiva === "IMPROCEDENTE" && (
            <div class="dec-causal">
              <p class="dec-etiqueta" id="dec-causal-t">
                Causal de la improcedencia <small class="sub">(opcional; se refleja en el motivo y en el encabezado)</small>
              </p>
              <div class="dec-carencias" role="radiogroup" aria-labelledby="dec-causal-t" id="dec-causal">
                {OPCIONES_CAUSAL.map(([valor, texto]) => (
                  <label key={valor} class={f.causal === valor ? "activa" : ""}>
                    <input type="radio" name="dec-causal" class="solo-lectura" value={valor} checked={f.causal === valor} onChange={() => cambiar((x) => ({ ...x, causal: valor }))} />
                    {texto}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      <Campo
        class="dec-hijo"
        id="dec-eje"
        etiqueta="Por qué, en pocas líneas"
        ayuda="Obligatorio. Las consideraciones del caso concreto desarrollan este eje. Los datos que no constan en el expediente de 1.ª instancia (p. ej. consultas de esta instancia) escríbalos aquí para que el caso concreto pueda usarlos."
        error={errEje}
      >
        <textarea {...atributos("dec-eje", errEje, true)} rows={5} placeholder="De 2 a 5 líneas. El caso concreto desarrolla este eje." value={f.eje} onInput={(e) => cambiar((x) => ({ ...x, eje: e.currentTarget.value }))} />
      </Campo>
    </Seccion>
  );
}

export function Reparos({ f, cambiar, payload }: PropsSeccion & { payload: PayloadDecision | null }) {
  const sintesis = new Map((payload?.reparos ?? []).map((r) => [r.id, r.sintesis ?? ""]));
  const editar = (id: string, parche: Partial<Formulario["reparos"][number]>) =>
    cambiar((x) => ({ ...x, reparos: x.reparos.map((r) => (r.id === id ? { ...r, ...parche } : r)) }));
  return (
    <Seccion id="dec-reparos" titulo="Reparos de la impugnación" sub="Qué hace con cada uno.">
      {f.reparos.length === 0 && <p class="dec-vacio">No se recibieron reparos extraídos.</p>}
      {f.reparos.map((r) => (
        <div class="dec-reparo" key={r.id}>
          <div>
            <div class="quien">{r.id}</div>
            <div class="que">{sintesis.get(r.id)}</div>
          </div>
          <select aria-label={`Disposición del reparo ${r.id}`} value={r.disposicion} onChange={(e) => editar(r.id, { disposicion: e.currentTarget.value as typeof r.disposicion })}>
            {DISPOSICIONES_REPARO.map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
          <input type="text" placeholder="Nota (opcional)" aria-label={`Nota del reparo ${r.id}`} value={r.nota} onInput={(e) => editar(r.id, { nota: e.currentTarget.value })} />
        </div>
      ))}
    </Seccion>
  );
}

export function Derechos({ f, cambiar }: PropsSeccion) {
  const [nuevo, setNuevo] = useState("");
  const sust = sustitutivaEfectiva(f);
  const agregar = () => {
    cambiar((x) => agregarDerecho(x, nuevo));
    setNuevo("");
  };
  return (
    <Seccion id="dec-derechos" titulo="Derechos invocados" sub="Se piden solo al amparar o negar." oculta={sust !== "AMPARAR" && sust !== "NEGAR"}>
      {f.derechos.length === 0 && <p class="dec-vacio">No se recibieron derechos extraídos.</p>}
      {f.derechos.map((d) => (
        <div class="dec-reparo dec-derecho" key={d.id}>
          <div class="quien">{d.nombre}</div>
          <select
            aria-label={`Disposición del derecho ${d.nombre}`}
            value={d.disposicion}
            onChange={(e) => cambiar((x) => ({ ...x, derechos: x.derechos.map((y) => (y.id === d.id ? { ...y, disposicion: e.currentTarget.value as typeof d.disposicion } : y)) }))}
          >
            {DISPOSICIONES_DERECHO.map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
          {d.propio && (
            <Boton variante="fantasma" aria-label={`Quitar el derecho ${d.nombre}`} onClick={() => cambiar((x) => ({ ...x, derechos: x.derechos.filter((y) => y.id !== d.id) }))}>
              Quitar
            </Boton>
          )}
        </div>
      ))}
      <div class="dec-agregar">
        <input
          type="text"
          placeholder="Otro derecho"
          aria-label="Otro derecho"
          value={nuevo}
          onInput={(e) => setNuevo(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            agregar();
          }}
        />
        <Boton onClick={agregar}>Agregar derecho</Boton>
      </div>
    </Seccion>
  );
}

function TarjetaOrden({ o, i, cambiar, err }: { o: OrdenForm; i: number; cambiar: Cambiar; err: PropsSeccion["err"] }) {
  const editar = (parche: Partial<OrdenForm>) => cambiar((x) => ({ ...x, ordenes: x.ordenes.map((y) => (y.id === o.id ? { ...y, ...parche } : y)) }));
  const eDest = err(`ordenes.${i}.destinatario`);
  const eConducta = err(`ordenes.${i}.conducta`);
  const ePlazo = err(`ordenes.${i}.plazo.n`);
  const base = `dec-orden-${o.id}`;
  return (
    <div class="dec-orden" role="group" aria-label={`Orden ${i + 1}`}>
      <div class="dec-orden-fila">
        <Campo id={`${base}-destinatario`} etiqueta="Destinatario" ayuda="Con artículo: «el BANCO X», «la EPS Y»." error={eDest}>
          <input {...atributos(`${base}-destinatario`, eDest, true)} type="text" placeholder="la EPS HORIZONTE SALUD S.A.S." value={o.destinatario} onInput={(e) => editar({ destinatario: e.currentTarget.value })} />
        </Campo>
        <Campo id={`${base}-plazo`} etiqueta="Plazo" error={ePlazo}>
          <input {...atributos(`${base}-plazo`, ePlazo)} type="number" min="1" value={o.n} disabled={o.mismo} onInput={(e) => editar({ n: e.currentTarget.value })} />
        </Campo>
        <Campo id={`${base}-unidad`} etiqueta="Unidad">
          <select id={`${base}-unidad`} value={o.unidad} disabled={o.mismo} onChange={(e) => editar({ unidad: e.currentTarget.value as typeof o.unidad })}>
            {UNIDADES.map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
        </Campo>
      </div>
      <Campo id={`${base}-conducta`} etiqueta="Qué debe hacer" error={eConducta}>
        <textarea {...atributos(`${base}-conducta`, eConducta)} rows={3} placeholder="Autorizar y entregar el medicamento prescrito sin dilaciones" value={o.conducta} onInput={(e) => editar({ conducta: e.currentTarget.value })} />
      </Campo>
      <details class="dec-mas">
        <summary>Más opciones</summary>
        <div class="dec-orden-mas">
          <Campo id={`${base}-verbo`} etiqueta="Verbo">
            <select id={`${base}-verbo`} value={o.verbo} onChange={(e) => editar({ verbo: e.currentTarget.value as typeof o.verbo })}>
              {VERBOS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </Campo>
          <Campo id={`${base}-condicion`} etiqueta="Condición">
            <input id={`${base}-condicion`} type="text" placeholder="Opcional" value={o.condicion} onInput={(e) => editar({ condicion: e.currentTarget.value })} />
          </Campo>
          <Casilla id={`${base}-mismo`} checked={o.mismo} onChange={(v) => editar({ mismo: v })}>
            Mismo término de la orden anterior
          </Casilla>
        </div>
      </details>
      <div class="dec-orden-pie">
        <Casilla id={`${base}-via`} checked={o.via} onChange={(v) => editar({ via: v })}>
          A través de su representante legal
        </Casilla>
        <Boton variante="fantasma" onClick={() => cambiar((x) => ({ ...x, ordenes: x.ordenes.filter((y) => y.id !== o.id) }))}>
          Quitar orden
        </Boton>
      </div>
    </div>
  );
}

export function Ordenes({ f, cambiar, err }: PropsSeccion) {
  const errGeneral = err("ordenes");
  const sub =
    sustitutivaEfectiva(f) === "AMPARAR"
      ? "Qué debe hacer cada destinatario y en cuánto tiempo."
      : "Opcionales si no se ampara: por ejemplo, ADVERTIR o PREVENIR a un destinatario (elija el verbo en «Más opciones»).";
  return (
    <Seccion id="dec-ordenes" titulo="Órdenes" sub={sub} oculta={!admiteOrdenes(f)}>
      {f.ordenes.map((o, i) => (
        <TarjetaOrden key={o.id} o={o} i={i} cambiar={cambiar} err={err} />
      ))}
      {errGeneral && (
        <small class="dec-error" role="alert">
          {errGeneral}
        </small>
      )}
      <Boton id="dec-agregar-orden" onClick={() => cambiar(agregarOrden)}>
        Agregar orden
      </Boton>
    </Seccion>
  );
}

export function Otras({ f, cambiar, err }: PropsSeccion) {
  const eRespecto = err("compulsa.respecto_de");
  return (
    <Seccion id="dec-otras" titulo="Otras determinaciones" sub="Se agregan al RESUELVE en el orden que vea a la derecha.">
      <Casilla id="dec-notificar" checked={f.notificar} onChange={(v) => cambiar((x) => ({ ...x, notificar: v }))}>
        Notificar a las partes <small>art. 30 del Decreto 2591 de 1991</small>
      </Casilla>
      <Casilla id="dec-remitir" checked={f.remitir} onChange={(v) => cambiar((x) => ({ ...x, remitir: v }))}>
        Remitir a la Corte Constitucional <small>art. 32 del Decreto 2591 de 1991</small>
      </Casilla>
      <Casilla id="dec-compulsar" checked={f.compulsa} onChange={(v) => cambiar((x) => ({ ...x, compulsa: v }))}>
        Compulsar copias
      </Casilla>
      {f.compulsa && (
        <div class="dec-hijo dec-pila">
          <Campo id="dec-compulsa-respecto" etiqueta="Respecto de quién" error={eRespecto}>
            <input {...atributos("dec-compulsa-respecto", eRespecto)} type="text" value={f.respectoDe} onInput={(e) => cambiar((x) => ({ ...x, respectoDe: e.currentTarget.value }))} />
          </Campo>
          <Campo id="dec-compulsa-organo" etiqueta="Órgano" ayuda="Opcional. Por defecto: Comisión Seccional de Disciplina Judicial de Antioquia.">
            <input id="dec-compulsa-organo" type="text" value={f.organo} onInput={(e) => cambiar((x) => ({ ...x, organo: e.currentTarget.value }))} />
          </Campo>
          <Campo id="dec-compulsa-hechos" etiqueta="Hechos de referencia" ayuda="Opcional.">
            <textarea id="dec-compulsa-hechos" rows={2} value={f.hechosRef} onInput={(e) => cambiar((x) => ({ ...x, hechosRef: e.currentTarget.value }))} />
          </Campo>
        </div>
      )}
      <div class="dec-fila-2 dec-hijo">
        <Campo id="dec-desvincular" etiqueta="Desvincular">
          <textarea id="dec-desvincular" rows={2} placeholder="Una entidad por línea" value={f.desvincular} onInput={(e) => cambiar((x) => ({ ...x, desvincular: e.currentTarget.value }))} />
        </Campo>
        <Campo id="dec-prevenir" etiqueta="Prevenir">
          <textarea id="dec-prevenir" rows={2} placeholder="Un destinatario por línea" value={f.prevenir} onInput={(e) => cambiar((x) => ({ ...x, prevenir: e.currentTarget.value }))} />
        </Campo>
      </div>
      <div class="dec-hijo">
        <Boton variante="fantasma" onClick={() => cambiar(agregarLibre)}>
          Agregar un numeral de texto libre
        </Boton>
      </div>
      {f.libres.map((l, i) => {
        const e = err(`numerales_libres.${i}`);
        return (
          <div class="dec-libre" key={l.id}>
            <Campo id={`dec-libre-${l.id}`} etiqueta={`Numeral libre ${i + 1}`} error={e}>
              <textarea {...atributos(`dec-libre-${l.id}`, e)} rows={2} value={l.texto} onInput={(ev) => cambiar((x) => ({ ...x, libres: x.libres.map((y) => (y.id === l.id ? { ...y, texto: ev.currentTarget.value } : y)) }))} />
            </Campo>
            <Boton variante="fantasma" aria-label={`Quitar el numeral libre ${i + 1}`} onClick={() => cambiar((x) => ({ ...x, libres: x.libres.filter((y) => y.id !== l.id) }))}>
              Quitar
            </Boton>
          </div>
        );
      })}
    </Seccion>
  );
}

export function Salida({ f, cambiar, err, fechaHoy, avisaDecididoPor }: PropsSeccion & { fechaHoy?: string; avisaDecididoPor: boolean }) {
  const eFecha = err("fecha_fallo");
  const eOficio = err("fecha_oficio");
  const porDefecto = f.fechaFallo === "";
  const ayudaFecha = porDefecto
    ? `Si no la cambia, se usa la fecha de hoy${fechaHoy ? ` (${fechaLarga(fechaHoy)})` : ""}.`
    : "Fecha elegida por usted.";
  return (
    <Seccion id="dec-salida" titulo="Fecha y documentos de salida">
      <div class="dec-fila-2">
        <Campo id="dec-fecha-fallo" etiqueta="Fecha del fallo" ayuda={ayudaFecha} error={eFecha}>
          <div class="dec-fecha">
            <input {...atributos("dec-fecha-fallo", eFecha, true)} type="date" value={f.fechaFallo} onInput={(e) => cambiar((x) => ({ ...x, fechaFallo: e.currentTarget.value }))} />
            {porDefecto ? (
              <Chip tono="alerta">hoy (por defecto)</Chip>
            ) : (
              <Boton variante="fantasma" onClick={() => cambiar((x) => ({ ...x, fechaFallo: "" }))}>
                Usar la de hoy
              </Boton>
            )}
          </div>
        </Campo>
        <Campo id="dec-por" etiqueta="Decidido por" ayuda="Queda en la declaración de uso de IA.">
          <input
            id="dec-por"
            class={avisaDecididoPor ? "dec-con-aviso" : undefined}
            aria-describedby={avisaDecididoPor ? "dec-por-ayuda dec-avisos" : "dec-por-ayuda"}
            type="text"
            value={f.decididoPor}
            onInput={(e) => cambiar((x) => ({ ...x, decididoPor: e.currentTarget.value }))}
          />
        </Campo>
      </div>
      <Casilla id="dec-formato" checked={f.generarFormato} onChange={(v) => cambiar((x) => ({ ...x, generarFormato: v }))}>
        Generar el Formato Factor Calidad
      </Casilla>
      <details class="dec-mas">
        <summary>Más opciones</summary>
        <div class="dec-fila-2 dec-hijo">
          <Campo id="dec-fecha-oficio" etiqueta="Fecha del oficio a la Corte" ayuda="Opcional." error={eOficio}>
            <input {...atributos("dec-fecha-oficio", eOficio, true)} type="date" value={f.fechaOficio} onInput={(e) => cambiar((x) => ({ ...x, fechaOficio: e.currentTarget.value }))} />
          </Campo>
          <Campo id="dec-etiqueta" etiqueta="Etiqueta del encabezado" ayuda="Opcional. Reemplaza la etiqueta calculada de la decisión.">
            <input id="dec-etiqueta" aria-describedby="dec-etiqueta-ayuda" type="text" value={f.etiqueta} onInput={(e) => cambiar((x) => ({ ...x, etiqueta: e.currentTarget.value }))} />
          </Campo>
        </div>
      </details>
    </Seccion>
  );
}
