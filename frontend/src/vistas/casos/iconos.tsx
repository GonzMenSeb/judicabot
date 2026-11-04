export type TipoProceso = "primera" | "segunda" | "desacato" | "penal";

const ATRIBUTOS = { width: 30, height: 30, viewBox: "0 0 32 32", fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" } as const;

export function IconoProceso({ tipo }: { tipo: TipoProceso }) {
  switch (tipo) {
    case "primera":
      return (
        <svg {...ATRIBUTOS}>
          <path d="M8 4h11l6 6v18H8z" />
          <path d="M19 4v6h6" />
          <path d="M12 16h9M12 20h9M12 24h5" />
        </svg>
      );
    case "segunda":
      return (
        <svg {...ATRIBUTOS}>
          <path d="M6 10v18h14" />
          <path d="M11 4h10l5 5v15H11z" />
          <path d="M21 4v5h5" />
          <path d="M18.5 19v-7M15.5 15l3-3 3 3" />
        </svg>
      );
    case "desacato":
      return (
        <svg {...ATRIBUTOS}>
          <path d="M18 28H8V4h11l6 6v5" />
          <path d="M19 4v6h6" />
          <path d="M12 15h7M12 19h4" />
          <circle cx="23.5" cy="23" r="5.5" />
          <path d="M23.5 20.3v3.2l2 1.3" />
        </svg>
      );
    case "penal":
      return (
        <svg {...ATRIBUTOS}>
          <path d="M16 5v22M10 27h12M7 9h18" />
          <path d="M7 9l-4 9a4 4 0 0 0 8 0z" />
          <path d="M25 9l-4 9a4 4 0 0 0 8 0z" />
        </svg>
      );
  }
}

export function IconoCarpeta({ color = "#6f8791" }: { color?: string }) {
  return (
    <svg width="18" height="15" viewBox="0 0 18 15" fill="none" aria-hidden="true">
      <path
        d="M1 3a1.5 1.5 0 0 1 1.5-1.5h4l1.6 2h7.4A1.5 1.5 0 0 1 17 5v7.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 1 12.5z"
        fill="#fff"
        stroke={color}
        stroke-width="1.4"
        stroke-linejoin="round"
      />
    </svg>
  );
}

const BANDA: Record<string, string> = { pdf: "#a8281f", docx: "#1e5a6e" };

export function IconoArchivo({ nombre }: { nombre: string }) {
  const extension = nombre.split(".").pop()?.toLowerCase() ?? "";
  return (
    <svg width="14" height="17" viewBox="0 0 24 30" fill="none" aria-hidden="true">
      <path d="M3 1h12l7 7v21H3z" fill="#fff" stroke="#8da0a9" stroke-width="2" stroke-linejoin="round" />
      <rect x="6" y="17" width="12" height="5" rx="1" fill={BANDA[extension] ?? "#8da0a9"} />
    </svg>
  );
}

export function IconoLupa() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4-4" />
    </svg>
  );
}
