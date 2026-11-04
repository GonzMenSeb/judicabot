import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { NumeralVista } from "../../api/contrato";
import { Aviso, Boton } from "../../ui";
import { ordinal } from "./formulario";

const FALTA = /⟦FALTA: ([^⟧]*)⟧/g;

interface Tramo {
  texto: string;
  negrita: boolean;
}

export function partirNegritas(texto: string, negritas: string[]): Tramo[] {
  const spans: [number, number][] = [];
  for (const n of negritas) {
    const i = n ? texto.indexOf(n) : -1;
    if (i >= 0) spans.push([i, i + n.length]);
  }
  spans.sort((a, b) => a[0] - b[0]);
  const fusion: [number, number][] = [];
  for (const [ini, fin] of spans) {
    const ultimo = fusion[fusion.length - 1];
    if (ultimo && ini <= ultimo[1]) ultimo[1] = Math.max(ultimo[1], fin);
    else fusion.push([ini, fin]);
  }
  const salida: Tramo[] = [];
  let pos = 0;
  for (const [ini, fin] of fusion) {
    if (ini > pos) salida.push({ texto: texto.slice(pos, ini), negrita: false });
    salida.push({ texto: texto.slice(ini, fin), negrita: true });
    pos = fin;
  }
  if (pos < texto.length) salida.push({ texto: texto.slice(pos), negrita: false });
  return salida;
}

function ConMarcas({ texto }: { texto: string }) {
  const partes: ComponentChildren[] = [];
  let pos = 0;
  for (const m of texto.matchAll(FALTA)) {
    const i = m.index ?? 0;
    if (i > pos) partes.push(texto.slice(pos, i));
    partes.push(
      <span class="dec-falta" key={i}>
        Falta: {m[1]}
      </span>,
    );
    pos = i + m[0].length;
  }
  if (pos < texto.length) partes.push(texto.slice(pos));
  return <>{partes}</>;
}

export function TextoNumeral({ texto, negritas }: { texto: string; negritas: string[] }) {
  return (
    <>
      {partirNegritas(texto, negritas).map((t, i) =>
        t.negrita ? (
          <b key={i}>
            <ConMarcas texto={t.texto} />
          </b>
        ) : (
          <ConMarcas key={i} texto={t.texto} />
        ),
      )}
    </>
  );
}

export interface PropsResuelve {
  numerales: NumeralVista[];
  vacio: boolean;
  pendiente: boolean;
  error: string | null;
  cierre: string;
  mensajes: string[];
  onReintentar: () => void;
  onMover: (clave: string, delta: number) => void;
  onSoltar: (origen: string, destino: string) => void;
}

export function Resuelve({ numerales, vacio, pendiente, error, cierre, mensajes, onReintentar, onMover, onSoltar }: PropsResuelve) {
  const [anuncio, setAnuncio] = useState("");
  const [arrastrada, setArrastrada] = useState<string | null>(null);
  const [encima, setEncima] = useState<string | null>(null);
  const foco = useRef<{ clave: string; delta: number } | null>(null);
  const lista = useRef<HTMLOListElement>(null);
  const previas = useRef<string[]>([]);
  const [nuevas, setNuevas] = useState<string[]>([]);

  const claves = numerales.map((n) => n.clave).join("|");
  useEffect(() => {
    const actuales = claves ? claves.split("|") : [];
    const agregadas = previas.current.length ? actuales.filter((k) => !previas.current.includes(k)) : [];
    previas.current = actuales;
    setNuevas(agregadas);
    const pedido = foco.current;
    foco.current = null;
    if (!pedido) return;
    const botones = lista.current?.querySelectorAll<HTMLButtonElement>(`button[data-clave="${pedido.clave}"]:not(:disabled)`);
    const preferido = Array.from(botones ?? []).find((b) => b.dataset.delta === String(pedido.delta)) ?? botones?.[0];
    preferido?.focus();
  }, [claves]);

  const mover = (n: NumeralVista, i: number, delta: number) => {
    foco.current = { clave: n.clave, delta };
    setAnuncio(`${ordinal(i + 1)} pasa a la posición ${i + delta + 1} de ${numerales.length}.`);
    onMover(n.clave, delta);
  };

  return (
    <aside class="hoja dec-hoja" aria-label="Vista previa del RESUELVE" aria-busy={pendiente}>
      <h3>RESUELVE</h3>
      {error && (
        <Aviso tipo="alerta" acciones={<Boton onClick={onReintentar}>Reintentar</Boton>}>
          No se pudo actualizar la vista previa. {error}
        </Aviso>
      )}
      {vacio || numerales.length === 0 ? (
        <p class="dec-vacio-hoja">Elija qué decide y esta parte del fallo se arma aquí a medida que avanza.</p>
      ) : (
        <>
          <ol class="dec-numerales" ref={lista} aria-label="Numerales del RESUELVE">
            {numerales.map((n, i) => (
              <li
                key={n.clave}
                class={`dec-numeral${nuevas.includes(n.clave) ? " nuevo" : ""}${arrastrada === n.clave ? " arrastrada" : ""}${encima === n.clave && arrastrada !== n.clave ? " encima" : ""}`}
                draggable
                onDragStart={(e) => {
                  setArrastrada(n.clave);
                  if (e.dataTransfer) {
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", n.clave);
                  }
                }}
                onDragOver={(e) => {
                  if (!arrastrada) return;
                  e.preventDefault();
                  setEncima(n.clave);
                }}
                onDragLeave={() => setEncima((k) => (k === n.clave ? null : k))}
                onDrop={(e) => {
                  e.preventDefault();
                  if (arrastrada && arrastrada !== n.clave) {
                    foco.current = null;
                    setAnuncio(`${ordinal(numerales.findIndex((x) => x.clave === arrastrada) + 1)} pasa a la posición ${i + 1} de ${numerales.length}.`);
                    onSoltar(arrastrada, n.clave);
                  }
                  setArrastrada(null);
                  setEncima(null);
                }}
                onDragEnd={() => {
                  setArrastrada(null);
                  setEncima(null);
                }}
              >
                <p>
                  <b>{ordinal(i + 1)}:</b> <TextoNumeral texto={n.texto} negritas={n.negritas} />
                </p>
                <span class="dec-mover">
                  <button
                    type="button"
                    data-clave={n.clave}
                    data-delta="-1"
                    aria-label={`Subir el numeral ${ordinal(i + 1)}`}
                    disabled={i === 0}
                    onClick={() => mover(n, i, -1)}
                  >
                    <Flecha arriba />
                  </button>
                  <button
                    type="button"
                    data-clave={n.clave}
                    data-delta="1"
                    aria-label={`Bajar el numeral ${ordinal(i + 1)}`}
                    disabled={i === numerales.length - 1}
                    onClick={() => mover(n, i, 1)}
                  >
                    <Flecha />
                  </button>
                </span>
              </li>
            ))}
          </ol>
          {cierre && <p class="dec-cierre">{cierre}</p>}
          {mensajes.length > 0 && (
            <ul class="dec-faltantes" aria-label="Lo que falta">
              {mensajes.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          <p class="dec-pie-hoja">Vista previa. El texto final lo arman las plantillas del despacho con estos mismos datos.</p>
        </>
      )}
      <p class="solo-lectura" role="status" aria-live="polite">
        {anuncio}
      </p>
    </aside>
  );
}

function Flecha({ arriba }: { arriba?: boolean }) {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={arriba ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
    </svg>
  );
}
