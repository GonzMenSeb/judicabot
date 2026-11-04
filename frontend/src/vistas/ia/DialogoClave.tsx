import { useId, useState } from "preact/hooks";
import { api } from "../../api";
import { Aviso, Boton, Dialogo } from "../../ui";
import { leerErrorServidor } from "./formulario";

export type TipoClave = "anthropic" | "jev";

interface DatosClave {
  ruta: string;
  proveedor: string;
  etiqueta: string;
  marcador: string;
  vacio: string;
}

export const DATOS_CLAVE: Record<TipoClave, DatosClave> = {
  anthropic: {
    ruta: "/api/api-key",
    proveedor: "Anthropic",
    etiqueta: "Clave de la API de Anthropic",
    marcador: "sk-ant-…",
    vacio: "Escriba la clave de la API de Anthropic.",
  },
  jev: {
    ruta: "/api/jev-key",
    proveedor: "Jev",
    etiqueta: "Clave de Jev",
    marcador: "",
    vacio: "Escriba la clave de Jev.",
  },
};

export interface PropsDialogoClave {
  tipo: TipoClave | null;
  existente: boolean;
  onCerrar: () => void;
  onGuardada: (tipo: TipoClave) => void;
}

export function DialogoClave({ tipo, existente, onCerrar, onGuardada }: PropsDialogoClave) {
  const datos = tipo ? DATOS_CLAVE[tipo] : null;
  const titulo = datos ? `${existente ? "Reemplazar" : "Agregar"} la clave de ${datos.proveedor}` : "Clave";
  return (
    <Dialogo abierto={tipo !== null} titulo={titulo} onCerrar={onCerrar}>
      {tipo && datos && <FormularioClave tipo={tipo} datos={datos} onCerrar={onCerrar} onGuardada={onGuardada} />}
    </Dialogo>
  );
}

interface PropsFormulario {
  tipo: TipoClave;
  datos: DatosClave;
  onCerrar: () => void;
  onGuardada: (tipo: TipoClave) => void;
}

function FormularioClave({ tipo, datos, onCerrar, onGuardada }: PropsFormulario) {
  const [clave, setClave] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const idCampo = useId();

  const guardar = async (e: Event) => {
    e.preventDefault();
    const valor = clave.trim();
    if (!valor) {
      setError(datos.vacio);
      return;
    }
    setGuardando(true);
    setError(null);
    try {
      await api.post(datos.ruta, { key: valor });
      setClave("");
      onGuardada(tipo);
    } catch (err) {
      setError(leerErrorServidor(err, "No se pudo guardar la clave.").generales.join(" "));
      setGuardando(false);
    }
  };

  return (
    <form class="ia-form-clave" onSubmit={guardar} autocomplete="off" noValidate>
      <p class="sub">Se guarda solo en la memoria del servidor: no queda en disco, no se vuelve a mostrar y se pierde al reiniciarlo.</p>
      <div class="campo">
        <label for={idCampo}>{datos.etiqueta}</label>
        <input
          id={idCampo}
          type="password"
          data-enfoque
          autocomplete="off"
          autocapitalize="off"
          spellcheck={false}
          placeholder={datos.marcador}
          value={clave}
          aria-invalid={error ? "true" : undefined}
          onInput={(e) => {
            setClave(e.currentTarget.value);
            setError(null);
          }}
        />
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      <div class="acciones">
        <Boton onClick={onCerrar}>Cancelar</Boton>
        <Boton variante="primario" type="submit" cargando={guardando}>
          Guardar clave
        </Boton>
      </div>
    </form>
  );
}
