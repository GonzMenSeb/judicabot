import type { ComponentChildren } from "preact";
import type { TipoEvento } from "../../api/contrato";
import type { EstadoEtapa } from "./modelo";

function Svg({ tam, ancho = 2, children }: { tam: number; ancho?: number; children: ComponentChildren }) {
  return (
    <svg
      width={tam}
      height={tam}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width={ancho}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export function IconoTipo({ tipo }: { tipo: TipoEvento }) {
  switch (tipo) {
    case "lee":
      return (
        <Svg tam={14}>
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
        </Svg>
      );
    case "razona":
      return (
        <Svg tam={14}>
          <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" />
        </Svg>
      );
    case "escribe":
      return (
        <Svg tam={14}>
          <path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1z" />
          <path d="M14 7l3 3" />
        </Svg>
      );
    case "verifica":
      return (
        <Svg tam={14}>
          <circle cx="12" cy="12" r="9" />
          <path d="M8 12.5l2.7 2.7L16 9.5" />
        </Svg>
      );
    case "error":
      return (
        <Svg tam={14}>
          <path d="M12 3l10 18H2L12 3z" />
          <path d="M12 10v4.5M12 17.6v.01" />
        </Svg>
      );
    default:
      return (
        <Svg tam={14}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M7 9.5l3 2.5-3 2.5M13 15h4" />
        </Svg>
      );
  }
}

export function IconoEtapa({ estado }: { estado: EstadoEtapa }) {
  if (estado === "actual") return <span class="giro tz-giro" aria-hidden="true" />;
  if (estado === "hecho") {
    return (
      <span class="tz-marca hecho" aria-hidden="true">
        <Svg tam={12} ancho={3.4}>
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </Svg>
      </span>
    );
  }
  if (estado === "error") {
    return (
      <span class="tz-marca error" aria-hidden="true">
        <Svg tam={12} ancho={3.4}>
          <path d="M12 6v7M12 17.5v.01" />
        </Svg>
      </span>
    );
  }
  return <span class="tz-marca espera" aria-hidden="true" />;
}
