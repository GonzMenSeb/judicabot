import { porcentaje } from "../../estado";
import { Chip, cx } from "../../ui";
import type { EstadoComparacion, FilaJev } from "./tipos";

const MARCA: Record<EstadoComparacion, { tono: "ok" | "alerta" | "neutro"; icono: string; texto: string }> = {
  coincide: { tono: "ok", icono: "✓", texto: "Coincide" },
  difiere: { tono: "alerta", icono: "≠", texto: "Difiere" },
  sin_comparar: { tono: "neutro", icono: "?", texto: "Sin comparar" },
};

export interface PropsTarjetaJev {
  filas: FilaJev[];
  umbral?: number;
}

export function TarjetaJev({ filas, umbral }: PropsTarjetaJev) {
  if (filas.length === 0) return null;
  const difiere = filas.some((f) => f.estado === "difiere");
  return (
    <section class={cx("bor-jev", difiere && "difiere")} aria-labelledby="bor-jev-titulo">
      <h2 id="bor-jev-titulo">Segunda lectura de Jev</h2>
      <p class="bor-jev-ayuda">
        Jev leyó por su cuenta el fallo de primera instancia y el escrito de impugnación. Aquí se compara lo que entendió
        con lo que dice el borrador.
        {umbral !== undefined && ` Solo se compara cuando Jev tiene al menos ${porcentaje(umbral)} de confianza.`}
      </p>
      <div class="bor-tabla-caja">
        <table class="bor-jev-tabla">
          <thead>
            <tr>
              <th scope="col">
                <span class="solo-lectura">Dato</span>
              </th>
              <th scope="col">El borrador dice</th>
              <th scope="col">Jev lee en el fallo</th>
              <th scope="col">Coincide</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((fila) => {
              const marca = MARCA[fila.estado];
              return (
                <tr key={fila.id} class={fila.estado}>
                  <th scope="row">{fila.etiqueta}</th>
                  <td data-th="El borrador dice">
                    <b>{fila.borrador.principal ?? "Sin dato"}</b>
                    {fila.borrador.secundario && <small>{fila.borrador.secundario}</small>}
                  </td>
                  <td data-th="Jev lee en el fallo">
                    <b>{fila.jev.principal ?? "Sin lectura"}</b>
                    {fila.jev.confianza !== null && <small>{porcentaje(fila.jev.confianza)} de confianza</small>}
                    {fila.jev.nota && <small>{fila.jev.nota}</small>}
                  </td>
                  <td data-th="Coincide">
                    <Chip tono={marca.tono}>
                      <span aria-hidden="true">{marca.icono} </span>
                      {marca.texto}
                    </Chip>
                    {fila.motivo && <small>{fila.motivo}</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {difiere && <p class="bor-jev-nota">Donde dice «Difiere», revise esa frase del borrador antes de decidir.</p>}
    </section>
  );
}
