import { useState } from "preact/hooks";
import { api, ErrorApi } from "../../api";
import { cargarEstadoServidor } from "../../estado";
import { Aviso, Boton, Dialogo } from "../../ui";

export interface PropsDialogoClave {
  abierto: boolean;
  onCerrar: () => void;
  onGuardada: () => void;
}

export function DialogoClave({ abierto, onCerrar, onGuardada }: PropsDialogoClave) {
  const [clave, setClave] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  const guardar = async (e?: Event) => {
    e?.preventDefault();
    const valor = clave.trim();
    if (!valor) {
      setError("Escriba la clave de la API de Anthropic.");
      return;
    }
    setGuardando(true);
    setError(null);
    try {
      await api.post("/api/api-key", { key: valor });
      await cargarEstadoServidor(true);
      setClave("");
      onGuardada();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo guardar la clave.");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Dialogo
      abierto={abierto}
      titulo="Falta la clave de la API"
      onCerrar={onCerrar}
      acciones={
        <>
          <Boton onClick={onCerrar}>Cancelar</Boton>
          <Boton variante="primario" onClick={() => void guardar()} cargando={guardando}>
            Guardar y continuar
          </Boton>
        </>
      }
    >
      <form id="docs-form-clave" class="docs-form-clave" onSubmit={(e) => void guardar(e)} autocomplete="off">
        <p class="sub">Para redactar, el modelo necesita la clave de la API de Anthropic. Se guarda solo en la memoria del servidor mientras esté encendido.</p>
        <div class="campo">
          <label for="docs-clave">Clave de la API</label>
          <input
            id="docs-clave"
            type="password"
            data-enfoque
            autocomplete="off"
            spellcheck={false}
            value={clave}
            onInput={(e) => setClave(e.currentTarget.value)}
          />
        </div>
        {error && <Aviso tipo="error">{error}</Aviso>}
      </form>
    </Dialogo>
  );
}
