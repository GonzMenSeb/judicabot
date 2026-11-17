import { useState } from "preact/hooks";
import type { CasoResumen } from "../../api/contrato";
import { diaIso, fechaCorta, plural } from "../../estado";
import { cx } from "../../ui";
import { actividad, conteoFechas, elegirDia, elegirPreset, FECHAS, fijarRango, pasa, rangoDe, type Filtros, type Predicado } from "./filtros";

export interface PropsFiltroFecha {
  filtros: Filtros;
  /** Todos los casos en alcance; los conteos ignoran el propio filtro de fecha. */
  casos: readonly CasoResumen[];
  preds: readonly Predicado[];
  hoy: Date;
  cambiar: (f: Filtros) => void;
}

const nombreDia = new Intl.DateTimeFormat("es-CO", { weekday: "long", day: "numeric", month: "long" });

const fechaDe = (iso: string) => {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a!, m! - 1, d);
};

/** Contenido del desplegable «Trabajado»: presets con conteo, histograma de 30 días y Desde/Hasta. */
export function FiltroFecha({ filtros, casos, preds, hoy, cambiar }: PropsFiltroFecha) {
  const [primerDia, setPrimerDia] = useState<string | null>(null);
  const conteos = conteoFechas(casos, preds, hoy);
  const dias = actividad(
    casos.filter((c) => pasa(c, preds, "fecha")),
    hoy,
  );
  const maximo = Math.max(1, ...dias.map((d) => d.n));
  const total = dias.reduce((suma, d) => suma + d.n, 0);
  const { desde, hasta } = rangoDe(filtros, hoy);
  // Solo espera el segundo toque mientras el filtro siga siendo ese día; «Quitar», Limpiar o Atrás lo descartan.
  const pendiente = filtros.fecha === "rango" && desde === primerDia && hasta === primerDia ? primerDia : null;
  const hoyIso = diaIso(hoy);
  const fijar = (f: Filtros) => {
    setPrimerDia(null);
    cambiar(f);
  };

  return (
    <>
      <div class="presets">
        {FECHAS.map((p) => (
          <button key={p.id} type="button" class="pre-f" aria-pressed={filtros.fecha === p.id} title={plural(conteos[p.id], "caso")} onClick={() => fijar(elegirPreset(filtros, p.id))}>
            {p.etiqueta}
            <span class="conteo" aria-hidden="true">
              {conteos[p.id]}
            </span>
          </button>
        ))}
      </div>
      <div class="histo">
        <p class="histo-pie">
          <b>Actividad por día</b>
          {plural(total, "caso")} en 30 días
        </p>
        <div class="barras">
          {dias.map((d) => {
            const texto = nombreDia.format(fechaDe(d.iso));
            const dentro = (desde || hasta) && (!desde || d.iso >= desde) && (!hasta || d.iso <= hasta);
            return (
              <button
                key={d.iso}
                type="button"
                class={cx("barra-d", d.n === 0 && "vacia", (d.diaSemana === 0 || d.diaSemana === 6) && "inhabil", dentro && "en")}
                style={{ height: `${d.n === 0 ? 4 : Math.round(10 + (d.n / maximo) * 46)}px` }}
                aria-label={`${texto}: ${plural(d.n, "caso")}`}
                aria-pressed={Boolean(dentro)}
                title={`${texto}: ${plural(d.n, "caso")}`}
                onClick={() => {
                  const r = elegirDia(filtros, d.iso, pendiente);
                  setPrimerDia(r.pendiente);
                  cambiar(r.filtros);
                }}
              />
            );
          })}
        </div>
        <p class="histo-pie" aria-hidden="true">
          {[0, 14, dias.length - 1].map((i) => (
            <span key={i}>{fechaCorta(dias[i]!.iso)}</span>
          ))}
        </p>
        <p class="histo-pie">{pendiente ? "Ahora toque el último día del rango." : "Toque un día, o dos para un rango. Rayado: fin de semana."}</p>
      </div>
      <div class="rango">
        <label>
          Desde
          <input type="date" value={desde} max={hoyIso} onChange={(e) => fijar(fijarRango(filtros, e.currentTarget.value, hasta))} />
        </label>
        <label>
          Hasta
          <input type="date" value={hasta} max={hoyIso} onChange={(e) => fijar(fijarRango(filtros, desde, e.currentTarget.value))} />
        </label>
      </div>
    </>
  );
}
