import { act, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agregarEvento, conCursor, MAX_EVENTOS, useEventos } from "./eventos";
import type { Evento } from "./eventos";

class FuenteSimulada {
  static instancias: FuenteSimulada[] = [];
  readonly url: string;
  cerrada = false;
  private oyentes = new Map<string, Array<(ev: Event) => void>>();

  constructor(url: string) {
    this.url = url;
    FuenteSimulada.instancias.push(this);
  }

  addEventListener(tipo: string, oyente: (ev: Event) => void) {
    this.oyentes.set(tipo, [...(this.oyentes.get(tipo) ?? []), oyente]);
  }

  close() {
    this.cerrada = true;
  }

  emitir(tipo: string, datos?: unknown) {
    const ev = datos === undefined ? new Event(tipo) : new MessageEvent(tipo, { data: JSON.stringify(datos) });
    this.oyentes.get(tipo)?.forEach((o) => o(ev));
  }
}

const evento = (n: number, texto = `evento ${n}`): Evento => ({
  n,
  t: "2026-11-03T12:00:00Z",
  etapa: "ingesta",
  tipo: "lee",
  texto,
  datos: null,
});

const vistos: { renders: number; ultimos: Evento[][] } = { renders: 0, ultimos: [] };

function Panel({ url }: { url: string | null }) {
  const { eventos, fin, conexion } = useEventos(url);
  vistos.renders += 1;
  vistos.ultimos.push(eventos);
  return (
    <div>
      <output data-testid="conexion">{conexion}</output>
      <output data-testid="fin">{fin ? fin.estado : ""}</output>
      <ul>
        {eventos.map((e) => (
          <li key={e.n}>{e.texto}</li>
        ))}
      </ul>
    </div>
  );
}

const ultima = () => FuenteSimulada.instancias[FuenteSimulada.instancias.length - 1]!;
const textos = () => screen.queryAllByRole("listitem").map((li) => li.textContent);

describe("conCursor", () => {
  it("no agrega cursor antes del primer evento", () => {
    expect(conCursor("/api/jobs/a/eventos", -1)).toBe("/api/jobs/a/eventos");
  });

  it("agrega el cursor con ? o & según la URL", () => {
    expect(conCursor("/api/jobs/a/eventos", 7)).toBe("/api/jobs/a/eventos?desde=7");
    expect(conCursor("/api/jobs/a/eventos?x=1", 0)).toBe("/api/jobs/a/eventos?x=1&desde=0");
  });
});

describe("useEventos", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FuenteSimulada.instancias = [];
    vi.stubGlobal("EventSource", FuenteSimulada);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("acumula los eventos en orden e ignora repetidos", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    expect(ultima().url).toBe("/api/jobs/a/eventos");

    act(() => {
      ultima().emitir("open");
      ultima().emitir("evento", evento(1));
      ultima().emitir("evento", evento(2));
      ultima().emitir("evento", evento(2, "repetido"));
    });
    expect(textos()).toEqual(["evento 1", "evento 2"]);
    expect(screen.getByTestId("conexion").textContent).toBe("abierto");
  });

  it("reconecta con el cursor del último evento", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    const primera = ultima();
    act(() => {
      primera.emitir("evento", evento(1));
      primera.emitir("evento", evento(2));
      primera.emitir("error");
    });
    expect(primera.cerrada).toBe(true);
    expect(screen.getByTestId("conexion").textContent).toBe("conectando");

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(FuenteSimulada.instancias).toHaveLength(2);
    expect(ultima().url).toBe("/api/jobs/a/eventos?desde=2");

    act(() => {
      ultima().emitir("open");
      ultima().emitir("evento", evento(3));
    });
    expect(textos()).toEqual(["evento 1", "evento 2", "evento 3"]);
  });

  it("cierra sin reconectar al recibir fin", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    const fuente = ultima();
    act(() => {
      fuente.emitir("evento", evento(1));
      fuente.emitir("fin", { estado: "terminado", error: null });
    });
    expect(fuente.cerrada).toBe(true);
    expect(screen.getByTestId("fin").textContent).toBe("terminado");
    expect(screen.getByTestId("conexion").textContent).toBe("cerrado");

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(FuenteSimulada.instancias).toHaveLength(1);
  });

  it("se declara fallido tras demasiados errores seguidos", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    for (let i = 0; i < 9; i++) {
      act(() => {
        ultima().emitir("error");
        vi.advanceTimersByTime(5000);
      });
    }
    expect(screen.getByTestId("conexion").textContent).toBe("fallido");
    expect(FuenteSimulada.instancias).toHaveLength(9);
  });

  it("cierra la conexión al desmontar y no abre nada sin URL", () => {
    const { unmount } = render(<Panel url="/api/jobs/a/eventos" />);
    const fuente = ultima();
    unmount();
    expect(fuente.cerrada).toBe(true);

    FuenteSimulada.instancias = [];
    render(<Panel url={null} />);
    expect(FuenteSimulada.instancias).toHaveLength(0);
  });
});

describe("ráfagas de eventos", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FuenteSimulada.instancias = [];
    vistos.renders = 0;
    vistos.ultimos = [];
    vi.stubGlobal("EventSource", FuenteSimulada);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("procesa 2500 eventos y el fin en una ráfaga y conserva los últimos 2000 en orden", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    const fuente = ultima();
    const antes = vistos.renders;
    act(() => {
      fuente.emitir("open");
      for (let n = 1; n <= 2500; n++) fuente.emitir("evento", evento(n));
      fuente.emitir("fin", { estado: "terminado", error: null });
    });

    const lista = textos();
    expect(lista).toHaveLength(MAX_EVENTOS);
    expect(lista[0]).toBe("evento 501");
    expect(lista[lista.length - 1]).toBe("evento 2500");
    expect(screen.getByTestId("fin").textContent).toBe("terminado");
    expect(screen.getByTestId("conexion").textContent).toBe("cerrado");
    expect(vistos.renders - antes).toBeLessThanOrEqual(2);
  });

  it("no vuelve a copiar la lista cuando solo cambia la conexión", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    act(() => {
      for (let n = 1; n <= 50; n++) ultima().emitir("evento", evento(n));
    });
    const antes = vistos.ultimos[vistos.ultimos.length - 1];
    act(() => {
      ultima().emitir("error");
    });
    expect(screen.getByTestId("conexion").textContent).toBe("conectando");
    expect(vistos.ultimos[vistos.ultimos.length - 1]).toBe(antes);
  });

  it("entrega una lista nueva en cada cambio de eventos, sin mutar la anterior", () => {
    render(<Panel url="/api/jobs/a/eventos" />);
    act(() => ultima().emitir("evento", evento(1)));
    const primera = vistos.ultimos[vistos.ultimos.length - 1]!;
    act(() => ultima().emitir("evento", evento(2)));
    const segunda = vistos.ultimos[vistos.ultimos.length - 1]!;
    expect(segunda).not.toBe(primera);
    expect(primera.map((e) => e.n)).toEqual([1]);
    expect(segunda.map((e) => e.n)).toEqual([1, 2]);
  });

  it("vacía los eventos al cambiar de URL", () => {
    const { rerender } = render(<Panel url="/api/jobs/a/eventos" />);
    act(() => ultima().emitir("evento", evento(1)));
    expect(textos()).toEqual(["evento 1"]);
    rerender(<Panel url="/api/jobs/b/eventos" />);
    expect(textos()).toEqual([]);
    act(() => ultima().emitir("evento", evento(1, "otro job")));
    expect(textos()).toEqual(["otro job"]);
  });
});

describe("agregarEvento", () => {
  it("agrega en el mismo arreglo sin copiarlo y acota la memoria a 2 × MAX_EVENTOS", () => {
    const buffer: Evento[] = [];
    const original = buffer;
    for (let n = 1; n <= 10_000; n++) {
      agregarEvento(buffer, evento(n));
      expect(buffer.length).toBeLessThanOrEqual(MAX_EVENTOS * 2);
    }
    expect(buffer).toBe(original);
    expect(buffer.slice(-MAX_EVENTOS).map((e) => e.n)).toEqual(Array.from({ length: MAX_EVENTOS }, (_, i) => 8001 + i));
  });
});
