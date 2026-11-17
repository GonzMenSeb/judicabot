import type { JSX } from "preact";
import { useEffect, useId, useRef, useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import type { EdicionCuerpo, EdicionesRespuesta } from "../../api/contrato";
import { Boton } from "../../ui";
import "./editor.css";

export interface BorradorParrafo {
  clave: string;
  original: string;
  texto: string;
  error: string | null;
}

export interface PropsEditorParrafo {
  caso: string;
  pieza: string;
  parrafo: number;
  borrador: BorradorParrafo;
  actual: string;
  restaurable: boolean;
  recargar: () => Promise<void>;
  onCerrar: () => void;
  alSucio?: ((sucio: boolean) => void) | undefined;
}

const AYUDA = "Deje una línea en blanco entre párrafos. Las fichas ⟦…⟧ son citas e imágenes: no se pueden cambiar.";
const AYUDA_TITULO = "El título ocupa una sola línea.";
const AVISO_RESTAURAR = "Restaura todos los párrafos de este texto, no solo el que está editando.";
const AVISO_409 = "El borrador ya se recargó.";
const AVISO_DESFASE = "Este párrafo cambió mientras lo editaba. Ahora dice:";
const NOTA_DESFASE = "Reemplaza esa versión por lo que usted escribió arriba. Cancelar descarta lo que escribió.";

function mensajeDe(e: unknown): string {
  if (!(e instanceof ErrorApi)) return "No se pudo guardar. Revise la conexión e intente de nuevo.";
  return typeof e.detalle !== "string" && e.estado === 422 ? "El texto no es válido." : e.message;
}

export function EditorParrafo({ caso, pieza, parrafo, borrador, actual, restaurable, recargar, onCerrar, alSucio }: PropsEditorParrafo) {
  const { original } = borrador;
  const [texto, setTexto] = useState(borrador.texto);
  const [ocupado, setOcupado] = useState(false);
  const desfasado = !ocupado && actual !== "" && actual !== original;
  const [error, setError] = useState(borrador.error);
  const campo = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  const montado = useRef(true);
  const id = useId();
  const titulo = pieza.endsWith(".titulo");
  const ruta = `/api/casos/${encodeURIComponent(caso)}/ediciones/${encodeURIComponent(pieza)}`;

  useEffect(() => {
    const el = campo.current;
    el?.focus();
    el?.setSelectionRange(el.value.length, el.value.length);
    alSucio?.(borrador.texto !== borrador.original);
    return () => {
      montado.current = false;
      alSucio?.(false);
    };
  }, []);

  const cambiarTexto = (nuevo: string) => {
    borrador.texto = nuevo;
    setTexto(nuevo);
    alSucio?.(nuevo !== original);
  };
  const fallar = (mensaje: string | null) => {
    borrador.error = mensaje;
    if (montado.current) setError(mensaje);
  };

  async function enviar(peticion: () => Promise<EdicionesRespuesta>) {
    setOcupado(true);
    fallar(null);
    campo.current?.focus();
    try {
      await peticion();
    } catch (e) {
      if (montado.current) setOcupado(false);
      if (e instanceof ErrorApi && e.estado === 409) {
        fallar(`${e.message} ${AVISO_409}`);
        await recargar();
      } else {
        fallar(mensajeDe(e));
      }
      if (montado.current) campo.current?.focus();
      return;
    }
    await recargar();
    onCerrar();
  }

  const guardar = (base: string) => {
    if (ocupado) return;
    const cuerpo: EdicionCuerpo = { parrafo, original: base, texto };
    void enviar(() => api.put<EdicionesRespuesta>(ruta, cuerpo));
  };
  const restaurar = () => {
    if (!ocupado) void enviar(() => api.delete<EdicionesRespuesta>(ruta));
  };
  const cancelar = () => {
    if (!ocupado) onCerrar();
  };

  const alTeclear = (e: JSX.TargetedKeyboardEvent<HTMLFormElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      cancelar();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      guardar(original);
    }
  };

  const idAyuda = `${id}-ayuda`;
  const idRestaurar = `${id}-restaurar`;
  const comun = {
    ref: campo,
    value: texto,
    readOnly: ocupado,
    spellcheck: true,
    lang: "es",
    "aria-describedby": idAyuda,
    onInput: (e: JSX.TargetedEvent<HTMLTextAreaElement | HTMLInputElement>) => cambiarTexto(e.currentTarget.value),
  };

  return (
    <form
      class="bor-editor"
      onSubmit={(e) => {
        e.preventDefault();
        guardar(original);
      }}
      onKeyDown={alTeclear}
      aria-busy={ocupado}
    >
      {titulo ? (
        <input type="text" autocomplete="off" aria-label="Título del bloque" {...comun} />
      ) : (
        <textarea rows={Math.min(16, Math.max(4, Math.ceil(texto.length / 80) + texto.split("\n").length - 1))} aria-label="Texto del párrafo" {...comun} />
      )}
      <p id={idAyuda} class="bor-editor-ayuda">
        {titulo ? AYUDA_TITULO : AYUDA}
      </p>
      {error && (
        <p class="bor-error" role="alert">
          {error}
        </p>
      )}
      {desfasado && (
        <div class="bor-editor-desfase">
          <p>{AVISO_DESFASE}</p>
          <div class="bor-editor-actual">{actual}</div>
          <Boton onClick={() => guardar(actual)} disabled={ocupado}>
            Guardar sobre la versión actual
          </Boton>
          <small class="bor-editor-nota">{NOTA_DESFASE}</small>
        </div>
      )}
      <div class="bor-editor-acciones">
        <Boton type="submit" variante="primario" cargando={ocupado}>
          Guardar
        </Boton>
        <Boton onClick={cancelar} disabled={ocupado}>
          Cancelar
        </Boton>
        {restaurable && (
          <>
            <Boton variante="fantasma" onClick={restaurar} disabled={ocupado} title={AVISO_RESTAURAR} aria-describedby={idRestaurar}>
              Restaurar el texto de la IA
            </Boton>
            <small id={idRestaurar} class="bor-editor-nota">
              {AVISO_RESTAURAR}
            </small>
          </>
        )}
      </div>
    </form>
  );
}
