import { createContext, Fragment } from "preact";
import type { JSX } from "preact";
import type { ComponentChildren } from "preact";
import { useContext } from "preact/hooks";
import type { CampoFormato, Despacho } from "../../api/contrato";
import { cx } from "../../ui";
import { lineas, texto } from "./modelo";
import type { Plantilla } from "./modelo";

export interface ContextoPrevia {
  valores: Despacho;
  plantilla: Plantilla;
  foco: string | null;
  campos: readonly CampoFormato[];
}

const Contexto = createContext<ContextoPrevia | null>(null);
export const ProveedorPrevia = Contexto.Provider;

const FECHA_LARGA = "tres (03) de noviembre de dos mil veintiséis (2026)";
const FECHA_AUTO = "ocho (08) de octubre de dos mil veintiséis (2026)";

function useContexto(): ContextoPrevia {
  const ctx = useContext(Contexto);
  if (!ctx) throw new Error("Falta el contexto de la vista previa");
  return ctx;
}

interface PropsV {
  k: string;
  mayus?: boolean;
}

function V({ k, mayus }: PropsV) {
  const { valores, foco, campos } = useContexto();
  const campo = campos.find((c) => c.clave === k);
  const partes = campo?.tipo === "lista" ? lineas(valores, k) : [texto(valores, k)];
  const llenas = partes.filter((p) => p.trim() !== "");
  const bloque = campo?.tipo === "lista";
  const clase = cx(foco === k && "foco", llenas.length === 0 && "fmt-hueco", bloque && "fmt-bloque");
  if (llenas.length === 0) {
    return (
      <span data-c={k} class={clase}>
        [{campo?.etiqueta ?? k}]
      </span>
    );
  }
  return (
    <span data-c={k} class={clase}>
      {partes.map((p, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {mayus ? p.toUpperCase() : p}
        </Fragment>
      ))}
    </span>
  );
}

function Lineas({ n, corta }: { n: number; corta?: "c8" | "c6" }) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} class={cx("fmt-ln", i === n - 1 && (corta ?? "c6"))} aria-hidden="true" />
      ))}
    </>
  );
}

function Logo() {
  return <div class="fmt-logo">Logo Rama Judicial</div>;
}

function Pagina({ etiqueta, correo, children, pie }: { etiqueta?: string; correo?: boolean; children: ComponentChildren; pie?: ComponentChildren }) {
  return (
    <div class={cx("fmt-pagina", correo && "fmt-correo")}>
      {etiqueta && <div class="fmt-etq">{etiqueta}</div>}
      <div class="fmt-cuerpo">{children}</div>
      {pie}
    </div>
  );
}

const TITULOS: Record<Plantilla, [string, string]> = {
  A: ["FALLO RECURRIDO", "CONSIDERACIONES DEL JUZGADO"],
  B: ["LA SENTENCIA IMPUGNADA", "CONSIDERACIONES"],
};

const MERITO: Record<Plantilla, string> = {
  A: "administrando justicia en nombre del Pueblo y por mandato Constitucional,",
  B: "administrando justicia en nombre de la República y por autoridad de la Ley,",
};

function PreviaFallo() {
  const { plantilla } = useContexto();
  const b = plantilla === "B";
  const pie = b ? (
    <>
      <div class="fmt-pie fmt-i">
        <V k="pie_fallo" />
      </div>
      <div class="fmt-num">1</div>
    </>
  ) : (
    <div class="fmt-pie fmt-i">
      <V k="pie" />
    </div>
  );
  const [recurrido, consideraciones] = TITULOS[plantilla];
  return (
    <>
      <Pagina etiqueta="Primera página" pie={pie}>
        <Logo />
        <p class="fmt-c fmt-n">
          <V k="nombre" mayus={b} />
        </p>
        <p class="fmt-c">
          <V k="ciudad" />, {FECHA_LARGA}
        </p>
        <table class="fmt-tabla">
          <tbody>
            <tr>
              <td>Radicado</td>
              <td>050014088009 2026 00412 01</td>
            </tr>
            <tr>
              <td>Accionante</td>
              <td>MARTA INÉS QUINTERO BEDOYA</td>
            </tr>
            <tr>
              <td>Accionada</td>
              <td>EPS HORIZONTE SALUD S.A.S.</td>
            </tr>
            <tr>
              <td>Decisión</td>
              <td>REVOCA</td>
            </tr>
          </tbody>
        </table>
        <p class="fmt-c fmt-n">I. ASUNTO</p>
        <Lineas n={3} corta="c8" />
        <p class="fmt-c fmt-n">II. ANTECEDENTES DEL CASO</p>
        <Lineas n={4} />
        <p class="fmt-c fmt-n">III. {recurrido}</p>
        <Lineas n={2} />
      </Pagina>
      <Pagina etiqueta="Última página" pie={pie}>
        <p class="fmt-c fmt-n">V. {consideraciones}</p>
        <Lineas n={3} />
        {!b && <p class="fmt-c fmt-n">PARTE RESOLUTIVA</p>}
        <p>
          En mérito de lo expuesto, el{" "}
          <b>
            <V k="nombre_cuerpo" />
          </b>
          , {MERITO[plantilla]}
        </p>
        <p class="fmt-c fmt-n">RESUELVE</p>
        <p>
          <b>PRIMERO: REVOCAR</b> la sentencia de primera instancia…
        </p>
        <Lineas n={2} />
        <p class="fmt-c fmt-n fmt-sep">
          <V k="cierre_fallo" />
        </p>
        <p class="fmt-c fmt-n fmt-firma">
          <V k="juez" mayus />
        </p>
        <p class="fmt-c fmt-n">
          <V k="cargo_juez" />
        </p>
      </Pagina>
    </>
  );
}

function PreviaAuto() {
  return (
    <Pagina
      pie={
        <div class="fmt-pie">
          <V k="pie_auto" />
        </div>
      }
    >
      <p class="fmt-compacto">Radicado: 05001408800920260041201</p>
      <p class="fmt-compacto">Accionante: MARTA INÉS QUINTERO BEDOYA</p>
      <p>Accionada: EPS HORIZONTE SALUD S.A.S.</p>
      <p class="fmt-n fmt-sep">CONSTANCIA:</p>
      <Lineas n={3} />
      <p>
        <V k="ciudad" />, {FECHA_AUTO}
      </p>
      <p class="fmt-n fmt-compacto">
        <V k="escribiente" />
      </p>
      <p>
        <V k="cargo_escribiente" />
      </p>
      <div class="fmt-sep">
        <Logo />
      </div>
      <p class="fmt-c fmt-n">
        <V k="nombre_corto" />
      </p>
      <p class="fmt-c">
        <V k="ciudad" />, {FECHA_AUTO}
      </p>
      <p class="fmt-c fmt-n">ASUNTO: AUTO ASUME CONOCIMIENTO DE IMPUGNACIÓN DE TUTELA</p>
      <Lineas n={2} />
      <p class="fmt-c fmt-n fmt-sep">
        <V k="cierre_auto" />
      </p>
      <p class="fmt-c fmt-n fmt-firma">
        <V k="juez" />
      </p>
      <p class="fmt-c fmt-n">
        <V k="cargo_juez" />
      </p>
    </Pagina>
  );
}

function PreviaOficio() {
  return (
    <Pagina>
      <Logo />
      <p class="fmt-c fmt-n fmt-i">
        <V k="nombre_corto" />
      </p>
      <p class="fmt-c">
        <V k="ciudad" />, {FECHA_LARGA}
      </p>
      <p>Asunto: REMISIÓN EXPEDIENTE DE TUTELA EN REVISIÓN</p>
      <p class="fmt-n fmt-compacto">
        Señores
        <br />
        HONORABLES MAGISTRADOS
        <br />
        Corte Constitucional – Sala de Revisión
        <br />
        Calle 12 N° 7 – 65
        <br />
        Bogotá D. C.
      </p>
      <p class="fmt-sep">Cordial Saludo</p>
      <Lineas n={3} />
      <p class="fmt-n fmt-sangria">
        Radicado: 05001408800920260041201
        <br />
        Accionante: MARTA INÉS QUINTERO BEDOYA
        <br />
        Accionado: EPS HORIZONTE SALUD S.A.S.
      </p>
      <p class="fmt-n fmt-sangria fmt-firma">
        <V k="firmante_oficio" />
      </p>
      <p class="fmt-n fmt-sangria">
        <V k="cargo_firmante_oficio" />
      </p>
    </Pagina>
  );
}

function FirmaCorreo() {
  return (
    <>
      <p class="fmt-compacto fmt-sep">
        <b>
          <V k="escribiente" />
        </b>
      </p>
      <p class="fmt-compacto">
        <V k="cargo_escribiente" />
      </p>
      <p class="fmt-compacto">
        <V k="firma_correo" />
      </p>
      <p class="fmt-compacto">
        <V k="correo" />
      </p>
      <p class="fmt-compacto">
        <V k="telefono_correo" />
      </p>
    </>
  );
}

function PreviaCorreos() {
  return (
    <>
      <Pagina etiqueta="Notificación del fallo" correo>
        <div class="fmt-enc">
          <span>Para: las partes</span>
          <span>Asunto: Notificación del fallo de tutela de segunda instancia, radicado 2026-00412</span>
        </div>
        <Lineas n={4} />
        <FirmaCorreo />
      </Pagina>
      <Pagina etiqueta="Remisión de compulsa de copias" correo>
        <div class="fmt-enc">
          <span>Para: Oficina de Reparto</span>
          <span>Asunto: Compulsa de copias, radicado 2026-00412</span>
        </div>
        <p>
          Por medio del presente, y dando cumplimiento a lo ordenado por el señor Juez <V k="juez" /> dentro del fallo adjunto me permito remitirle el link del expediente de la tutela…
        </p>
        <Lineas n={2} />
        <FirmaCorreo />
      </Pagina>
    </>
  );
}

function PreviaFormato() {
  return (
    <Pagina>
      <p class="fmt-c fmt-n">FORMATO FACTOR CALIDAD</p>
      <Lineas n={5} />
      <table class="fmt-tabla fmt-ancha">
        <tbody>
          <tr>
            <td>Nombre del evaluador</td>
            <td>
              <V k="juez" />
            </td>
          </tr>
          <tr>
            <td>Cargo</td>
            <td>
              <V k="cargo_evaluador" />
            </td>
          </tr>
        </tbody>
      </table>
    </Pagina>
  );
}

function PreviaGenerica({ id }: { id: string }) {
  const { campos } = useContexto();
  return (
    <Pagina>
      {campos
        .filter((c) => c.documentos.includes(id))
        .map((c) => (
          <p key={c.clave}>
            <b>{c.etiqueta}:</b> <V k={c.clave} />
          </p>
        ))}
    </Pagina>
  );
}

export const PREVIAS_CONOCIDAS: Record<string, () => JSX.Element> = {
  fallo: PreviaFallo,
  auto: PreviaAuto,
  oficio: PreviaOficio,
  correos: PreviaCorreos,
  formato: PreviaFormato,
};

export function PreviaDocumento({ id }: { id: string }) {
  const Conocida = PREVIAS_CONOCIDAS[id];
  return Conocida ? <Conocida /> : <PreviaGenerica id={id} />;
}
