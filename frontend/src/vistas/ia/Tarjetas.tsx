import { cx } from "../../ui";

export interface OpcionTarjeta {
  valor: string;
  titulo: string;
  detalle?: string;
}

export interface PropsTarjetas {
  nombre: string;
  legenda: string;
  opciones: readonly OpcionTarjeta[];
  valor: string;
  onCambio: (valor: string) => void;
  idDescripcion?: string;
  idError?: string;
}

export function Tarjetas({ nombre, legenda, opciones, valor, onCambio, idDescripcion, idError }: PropsTarjetas) {
  const describe = [idDescripcion, idError].filter(Boolean).join(" ") || undefined;
  return (
    <fieldset class="ia-tarjetas" aria-describedby={describe}>
      <legend class="solo-lectura">{legenda}</legend>
      {opciones.map((o) => (
        <label key={o.valor} class={cx("ia-op", valor === o.valor && "sel")}>
          <input type="radio" class="solo-lectura" name={nombre} value={o.valor} checked={valor === o.valor} onChange={() => onCambio(o.valor)} />
          <b>{o.titulo}</b>
          {o.detalle && <small>{o.detalle}</small>}
        </label>
      ))}
    </fieldset>
  );
}
