import type { ComponentChildren, VNode } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { Bloque, CitaVista, PaginaVista, Segmento, Vista } from "../../api/contrato";
import { plural } from "../../estado";
import { cx, VisorPagina } from "../../ui";

type Citas = Map<string, CitaVista>;

const AVISO_CITA: Record<CitaVista["estado"], string> = {
  verificada: "",
  revisar: " (cita con alerta)",
  rechazada: " (cita sin verificar)",
};

function Texto({ segmento, citas }: { segmento: Segmento; citas: Citas }) {
  let nodo: ComponentChildren = segmento.texto;
  if (segmento.cursiva) nodo = <em>{nodo}</em>;
  if (segmento.negrita) nodo = <strong>{nodo}</strong>;
  if (segmento.cita_id) {
    const cita = citas.get(segmento.cita_id);
    const estado = cita?.estado ?? "rechazada";
    nodo = (
      <span class={cx("cita", estado !== "verificada" && estado)} title={cita?.detalle ?? undefined}>
        {nodo}
        {estado !== "verificada" && <span class="solo-lectura">{AVISO_CITA[estado]}</span>}
      </span>
    );
  }
  return <>{nodo}</>;
}

function Segmentos({ segmentos, citas }: { segmentos: Segmento[]; citas: Citas }) {
  return (
    <>
      {segmentos.map((s, i) => (
        <Texto key={i} segmento={s} citas={citas} />
      ))}
    </>
  );
}

function BloqueTexto({ bloque, citas }: { bloque: Bloque; citas: Citas }) {
  const contenido = <Segmentos segmentos={bloque.segmentos} citas={citas} />;
  switch (bloque.tipo) {
    case "titulo":
      return <p class="tit">{contenido}</p>;
    case "encabezado":
      return <p class="sub-f">{contenido}</p>;
    case "cita_bloque":
      return <blockquote>{contenido}</blockquote>;
    case "firma":
      return <p class="c n">{contenido}</p>;
    case "parrafo":
      return <p class={cx(bloque.seccion === null && "c")}>{contenido}</p>;
    default:
      return <p>{contenido}</p>;
  }
}

function Tabla({ filas, citas }: { filas: Bloque[]; citas: Citas }) {
  return (
    <table>
      <tbody>
        {filas.map((fila, i) => (
          <tr key={`${i}-${fila.id}`}>
            {fila.segmentos.map((s, k) =>
              k === 0 ? (
                <th key={k} scope="row">
                  <Texto segmento={s} citas={citas} />
                </th>
              ) : (
                <td key={k}>
                  <Texto segmento={s} citas={citas} />
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Lista({ items, citas }: { items: Bloque[]; citas: Citas }) {
  return (
    <ul>
      {items.map((b, i) => (
        <li key={`${i}-${b.id}`}>
          <Segmentos segmentos={b.segmentos} citas={citas} />
        </li>
      ))}
    </ul>
  );
}

function Cuerpo({ bloques, citas }: { bloques: Bloque[]; citas: Citas }) {
  const salida: VNode[] = [];
  let i = 0;
  while (i < bloques.length) {
    const bloque = bloques[i]!;
    const tipo = bloque.tipo;
    if (tipo === "tabla" || tipo === "lista") {
      let j = i;
      while (bloques[j]?.tipo === tipo) j++;
      const grupo = bloques.slice(i, j);
      salida.push(
        tipo === "tabla" ? <Tabla key={`${i}-t`} filas={grupo} citas={citas} /> : <Lista key={`${i}-l`} items={grupo} citas={citas} />,
      );
      i = j;
      continue;
    }
    salida.push(<BloqueTexto key={`${i}-${bloque.id}`} bloque={bloque} citas={citas} />);
    i++;
  }
  return <>{salida}</>;
}

const textoDe = (b: Bloque) => b.segmentos.map((s) => s.texto).join("");

function PaginaFallo({ pagina, citas }: { pagina: PaginaVista; citas: Citas }) {
  const cuerpo = pagina.bloques.filter((b) => b.tipo !== "pie");
  const pie = pagina.bloques.filter((b) => b.tipo === "pie");
  return (
    <>
      <div class="fallo-cuerpo">
        <Cuerpo bloques={cuerpo} citas={citas} />
      </div>
      {pie.length > 0 && (
        <footer class="pie-f">
          {pie.map((b, i) => (
            <p key={`${i}-${b.id}`}>{textoDe(b)}</p>
          ))}
        </footer>
      )}
    </>
  );
}

function Miniatura({ pagina }: { pagina: PaginaVista }) {
  const lineas = pagina.bloques.filter((b) => b.tipo !== "pie").slice(0, 14);
  return (
    <span class="mini-papel" aria-hidden="true">
      {lineas.map((b, i) => {
        const largo = textoDe(b).length;
        const ancho = b.tipo === "titulo" ? 60 : Math.min(100, Math.max(35, Math.round(largo / 4)));
        return <i key={i} class={cx(b.tipo === "titulo" && "t")} style={{ width: `${ancho}%` }} />;
      })}
    </span>
  );
}

const reducido = (): boolean => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function Visor({ vista }: { vista: Vista }) {
  const total = vista.paginas.length;
  const [actual, setActual] = useState(1);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const citas: Citas = new Map(vista.citas.map((c) => [c.id, c]));

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observador = new IntersectionObserver(
      (entradas) => {
        for (const e of entradas) {
          const n = Number((e.target as HTMLElement).dataset.pagina);
          if (e.isIntersecting && n) setActual(n);
        }
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    for (const el of refs.current) if (el) observador.observe(el);
    return () => observador.disconnect();
  }, [total]);

  const irA = (n: number) => {
    const destino = Math.min(Math.max(n, 1), total);
    setActual(destino);
    refs.current[destino - 1]?.scrollIntoView?.({ behavior: reducido() ? "auto" : "smooth", block: "start" });
  };

  const alTeclear = (e: KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      irA(actual + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      irA(actual - 1);
    }
  };

  return (
    <section class="fallo-visor" aria-labelledby="fallo-visor-titulo" onKeyDown={alTeclear}>
      <div class="visor-bar">
        <h2 id="fallo-visor-titulo">Vista previa del fallo</h2>
        <span>{plural(total, "página")}</span>
      </div>
      <nav class="paginas-nav" aria-label="Páginas del fallo">
        <button type="button" class="btn fantasma" onClick={() => irA(actual - 1)} disabled={actual <= 1} aria-label="Página anterior">
          ‹
        </button>
        <ol class="minis">
          {vista.paginas.map((pagina, i) => (
            <li key={i}>
              <button
                type="button"
                class="mini"
                aria-label={`Ir a la página ${i + 1}`}
                aria-current={actual === i + 1 ? "page" : undefined}
                onClick={() => irA(i + 1)}
              >
                <Miniatura pagina={pagina} />
                <span class="mini-num">{i + 1}</span>
              </button>
            </li>
          ))}
        </ol>
        <button type="button" class="btn fantasma" onClick={() => irA(actual + 1)} disabled={actual >= total} aria-label="Página siguiente">
          ›
        </button>
      </nav>
      <p class="solo-lectura" role="status" aria-live="polite">{`Página ${actual} de ${total}`}</p>
      <div class="visor" role="group" aria-label="Páginas del fallo, use las flechas izquierda y derecha para cambiar de página" tabIndex={0}>
        {vista.paginas.map((pagina, i) => (
          <div
            key={i}
            class="fallo-pagina"
            data-pagina={i + 1}
            ref={(el) => {
              refs.current[i] = el;
            }}
          >
            <VisorPagina numero={i + 1} total={total}>
              <PaginaFallo pagina={pagina} citas={citas} />
            </VisorPagina>
          </div>
        ))}
      </div>
      <p class="sub nota-visor">
        Vista previa aproximada. En Word se usa Bookman Old Style y la paginación puede variar.
      </p>
    </section>
  );
}
