import type { Ref } from "preact";
import { useRef } from "preact/hooks";
import type { CitaVista } from "../../api/contrato";
import { porcentaje } from "../../estado";
import { Chip } from "../../ui";
import type { TonoChip } from "../../ui";
import { ETIQUETA_ESTADO_CITA } from "./datos";
import "./documento.css";
import { usePosicionPopover } from "./posicion";

export interface PropsPopoverCita {
  cita: CitaVista;
  motivos: string[];
  ancla: HTMLElement;
  contenedor: HTMLElement;
  titulo: Ref<HTMLHeadingElement>;
  onCerrar: () => void;
}

const TONO: Record<CitaVista["estado"], { chip: TonoChip; color: string; trazo: string }> = {
  verificada: { chip: "ok", color: "#4f9a74", trazo: "M5 12.5l4.5 4.5L19 7.5" },
  revisar: { chip: "alerta", color: "#d29a2a", trazo: "M12 6v7M12 17.5v.5" },
  rechazada: { chip: "mal", color: "#c2463c", trazo: "M7 7l10 10M17 7L7 17" },
};

const mayuscula = (texto: string) => (texto ? texto[0]!.toUpperCase() + texto.slice(1) : texto);

function Icono({ trazo, tamano }: { trazo: string; tamano: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={trazo} />
    </svg>
  );
}

export function PopoverCita({ cita, motivos, ancla, contenedor, titulo, onCerrar }: PropsPopoverCita) {
  const caja = useRef<HTMLElement>(null);
  const nombre = cita.fuente ? mayuscula(cita.fuente) : cita.id;
  const tono = TONO[cita.estado];
  const relatoria = cita.estado === "verificada" && cita.url ? cita.url : null;
  const arriba = usePosicionPopover(caja, ancla, contenedor, cita.id);

  const cobertura = cita.cobertura;

  return (
    <section
      id="bor-detalle"
      role="dialog"
      ref={caja}
      class={arriba ? "bor-pop arriba" : "bor-pop"}
      aria-labelledby="bor-detalle-titulo"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        onCerrar();
      }}
    >
      <div class="bor-pop-cabeza">
        <div>
          <Chip tono={tono.chip}>
            <Icono trazo={tono.trazo} tamano={13} />
            {ETIQUETA_ESTADO_CITA[cita.estado]}
          </Chip>
          <h3 id="bor-detalle-titulo" ref={titulo} tabIndex={-1}>
            {nombre}
          </h3>
        </div>
        <button type="button" class="bor-pop-cerrar" aria-label="Cerrar" onClick={onCerrar}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div class="bor-pop-cuerpo">
        {cita.texto && <q>{cita.texto}</q>}
        <div class="bor-medidor">
          <span>Cobertura</span>
          <span class="bor-medidor-riel">
            <i style={{ width: `${Math.round((cobertura ?? 0) * 100)}%`, background: tono.color }} />
          </span>
          <b>{porcentaje(cobertura)}</b>
        </div>
        {motivos.length > 0 && (
          <ul class={`bor-motivos ${cita.estado}`}>
            {motivos.map((motivo, i) => (
              <li key={i}>{motivo}</li>
            ))}
          </ul>
        )}
        {relatoria && (
          <div class="bor-pop-acciones">
            <a class="btn" href={relatoria} target="_blank" rel="noopener noreferrer">
              Abrir en la relatoría
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
              </svg>
              <span class="solo-lectura"> (se abre en una pestaña nueva)</span>
            </a>
          </div>
        )}
      </div>
    </section>
  );
}
