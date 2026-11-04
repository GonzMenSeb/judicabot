import { useLayoutEffect, useRef } from "preact/hooks";
import type { CampoFormato, Despacho, FormatoRespuesta } from "../../api/contrato";
import { cx } from "../../ui";
import { con, lineas, nombreCorto, nuevaClave, texto } from "./modelo";
import type { ErroresFormato, Plantilla, Seccion } from "./modelo";

const SUBTITULOS: Record<string, string> = {
  Despacho: "Cómo se nombra el juzgado en los documentos.",
  Firmas: "Quién firma cada documento y con qué cargo.",
  Contacto: "Aparecen en la firma de los borradores de correo.",
  "Cierres y pies de página": "La fórmula que antecede la firma y el texto al pie de cada página.",
};

interface PropsFormulario {
  secciones: Seccion[];
  documentos: FormatoRespuesta["documentos"];
  valores: Despacho;
  plantilla: Plantilla;
  errores: ErroresFormato;
  onValores: (valores: Despacho) => void;
  onPlantilla: (plantilla: Plantilla) => void;
  onFoco: (campo: CampoFormato) => void;
  onVer: (campo: CampoFormato, documento: string) => void;
}

const PLANTILLAS: { id: Plantilla; titulo: string; ancho: number; alto: number; puntos: string[] }[] = [
  {
    id: "A",
    titulo: "Generación A",
    ancho: 21.6,
    alto: 33,
    puntos: ["Página de 21,6 × 33 cm", "Fallo recurrido, Impugnación, Consideraciones del juzgado", "Parte resolutiva «en nombre del Pueblo y por mandato Constitucional»"],
  },
  {
    id: "B",
    titulo: "Generación B",
    ancho: 21.1,
    alto: 34.1,
    puntos: ["Página de 21,1 × 34,1 cm", "La sentencia impugnada, La impugnación, Consideraciones", "Número de página en el pie"],
  },
];

function SelectorPlantilla({ plantilla, onPlantilla }: Pick<PropsFormulario, "plantilla" | "onPlantilla">) {
  return (
    <section class="fmt-seccion" aria-labelledby="fmt-h-plantilla">
      <h2 id="fmt-h-plantilla">Plantilla del fallo</h2>
      <p class="sub">Define el tamaño de la página y los títulos de las secciones.</p>
      <div class="fmt-plantillas" role="radiogroup" aria-labelledby="fmt-h-plantilla">
        {PLANTILLAS.map((p) => (
          <label key={p.id} class="fmt-plantilla" data-activa={plantilla === p.id}>
            <input type="radio" name="plantilla_gen" value={p.id} checked={plantilla === p.id} onChange={() => onPlantilla(p.id)} />
            <span class="fmt-pag" style={{ width: `${p.ancho * 0.16}rem`, height: `${p.alto * 0.16}rem` }} aria-hidden="true" />
            <span>
              <b>{p.titulo}</b>
              <ul>
                {p.puntos.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

interface PropsEditorLista {
  campo: CampoFormato;
  lineas: string[];
  error: string | undefined;
  onCambio: (lineas: string[]) => void;
  onFoco: () => void;
}

function Icono({ d }: { d: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function EditorLista({ campo, lineas: valor, error, onCambio, onFoco }: PropsEditorLista) {
  const ids = useRef<number[]>([]);
  const pendiente = useRef<number | "agregar" | null>(null);
  const raiz = useRef<HTMLDivElement>(null);
  if (ids.current.length !== valor.length) ids.current = valor.map(() => nuevaClave());

  useLayoutEffect(() => {
    const destino = pendiente.current;
    if (destino === null) return;
    pendiente.current = null;
    if (destino === "agregar") raiz.current?.querySelector<HTMLButtonElement>("[data-agregar]")?.focus();
    else raiz.current?.querySelectorAll<HTMLInputElement>("input")[destino]?.focus();
  });

  const cambiar = (siguientes: string[], nuevosIds: number[], foco: number | "agregar") => {
    ids.current = nuevosIds;
    pendiente.current = foco;
    onCambio(siguientes);
  };
  const editar = (i: number, v: string) => onCambio(valor.map((l, j) => (j === i ? v : l)));
  const agregar = () => cambiar([...valor, ""], [...ids.current, nuevaClave()], valor.length);
  const quitar = (i: number) => {
    const quedan = valor.filter((_, j) => j !== i);
    cambiar(quedan, ids.current.filter((_, j) => j !== i), quedan.length === 0 ? "agregar" : Math.min(i, quedan.length - 1));
  };
  const mover = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= valor.length) return;
    const l = [...valor];
    const k = [...ids.current];
    [l[i], l[j]] = [l[j] as string, l[i] as string];
    [k[i], k[j]] = [k[j] as number, k[i] as number];
    cambiar(l, k, j);
  };

  const idError = `f-${campo.clave}-error`;
  return (
    <div class="fmt-lista" id={`f-${campo.clave}`} ref={raiz} role="group" aria-labelledby={`f-${campo.clave}-etq`}>
      {valor.map((linea, i) => (
        <div class="fmt-linea" key={ids.current[i]}>
          <input
            type="text"
            value={linea}
            aria-label={`${campo.etiqueta}, línea ${i + 1} de ${valor.length}`}
            aria-invalid={error ? "true" : undefined}
            aria-describedby={error ? idError : undefined}
            onFocus={onFoco}
            onInput={(e) => editar(i, e.currentTarget.value)}
          />
          <div class="fmt-linea-acciones">
            <button type="button" class="fmt-icono" disabled={i === 0} aria-label={`Subir línea ${i + 1} de ${campo.etiqueta}`} onClick={() => mover(i, -1)}>
              <Icono d="M6 15l6-6 6 6" />
            </button>
            <button type="button" class="fmt-icono" disabled={i === valor.length - 1} aria-label={`Bajar línea ${i + 1} de ${campo.etiqueta}`} onClick={() => mover(i, 1)}>
              <Icono d="M6 9l6 6 6-6" />
            </button>
            <button type="button" class="fmt-icono" aria-label={`Quitar línea ${i + 1} de ${campo.etiqueta}`} onClick={() => quitar(i)}>
              <Icono d="M6 6l12 12M18 6L6 18" />
            </button>
          </div>
        </div>
      ))}
      <button type="button" class="btn fantasma fmt-agregar" data-agregar onClick={agregar}>
        <Icono d="M12 5v14M5 12h14" /> Agregar línea
      </button>
    </div>
  );
}

interface PropsCampo {
  campo: CampoFormato;
  documentos: FormatoRespuesta["documentos"];
  valores: Despacho;
  error: string | undefined;
  onValores: (valores: Despacho) => void;
  onFoco: (campo: CampoFormato) => void;
  onVer: (campo: CampoFormato, documento: string) => void;
}

function Campo({ campo, documentos, valores, error, onValores, onFoco, onVer }: PropsCampo) {
  const id = `f-${campo.clave}`;
  const idError = `${id}-error`;
  const idAyuda = `${id}-ayuda`;
  const describe = [campo.ayuda ? idAyuda : null, error ? idError : null].filter(Boolean).join(" ") || undefined;
  const alFocar = () => onFoco(campo);
  const comunes = { id, "aria-invalid": error ? ("true" as const) : undefined, "aria-describedby": describe, onFocus: alFocar };

  let control;
  if (campo.tipo === "lista") {
    control = (
      <EditorLista campo={campo} lineas={lineas(valores, campo.clave)} error={error} onCambio={(l) => onValores(con(valores, campo.clave, l))} onFoco={alFocar} />
    );
  } else if (campo.tipo === "texto_largo") {
    control = <textarea {...comunes} rows={2} value={texto(valores, campo.clave)} onInput={(e) => onValores(con(valores, campo.clave, e.currentTarget.value))} />;
  } else {
    control = <input {...comunes} type="text" value={texto(valores, campo.clave)} onInput={(e) => onValores(con(valores, campo.clave, e.currentTarget.value))} />;
  }

  return (
    <div class={cx("fmt-campo", campo.tipo !== "texto" && "ancho", error && "con-error")}>
      {campo.tipo === "lista" ? <span id={`${id}-etq`} class="fmt-etiqueta">{campo.etiqueta}</span> : <label for={id}>{campo.etiqueta}</label>}
      {control}
      {campo.ayuda && (
        <small id={idAyuda}>{campo.ayuda}</small>
      )}
      {error && (
        <p id={idError} class="fmt-error">
          {error}
        </p>
      )}
      {campo.documentos.length > 0 && (
        <div class="fmt-aparece" role="group" aria-label={`Documentos donde aparece: ${campo.etiqueta}`}>
          <span aria-hidden="true">Aparece en</span>
          {campo.documentos.map((d) => (
            <button type="button" key={d} title={`Ver en la vista previa: ${documentos.find((x) => x.id === d)?.nombre ?? d}`} onClick={() => onVer(campo, d)}>
              {nombreCorto(d, documentos)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Formulario(props: PropsFormulario) {
  return (
    <div class="fmt-form">
      <SelectorPlantilla plantilla={props.plantilla} onPlantilla={props.onPlantilla} />
      {props.secciones.map((s, i) => (
        <section class="fmt-seccion" key={s.grupo} aria-labelledby={`fmt-h-${i}`}>
          <h2 id={`fmt-h-${i}`}>{s.grupo}</h2>
          {SUBTITULOS[s.grupo] && <p class="sub">{SUBTITULOS[s.grupo]}</p>}
          <div class="fmt-campos">
            {s.campos.map((c) => (
              <Campo
                key={c.clave}
                campo={c}
                documentos={props.documentos}
                valores={props.valores}
                error={props.errores.porCampo[c.clave]}
                onValores={props.onValores}
                onFoco={props.onFoco}
                onVer={props.onVer}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
