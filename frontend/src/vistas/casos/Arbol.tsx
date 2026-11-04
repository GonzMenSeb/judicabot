import { useMemo } from "preact/hooks";
import { plural } from "../../estado";
import { construirArbol, contarArchivos, esCarpetaPrimera, esCarpetaSegunda } from "./carpeta";
import type { NodoCarpeta } from "./carpeta";
import { IconoArchivo, IconoCarpeta } from "./iconos";

const MAX_LISTADOS = 3;

function Archivos({ nombres }: { nombres: string[] }) {
  if (nombres.length === 0) return null;
  if (nombres.length <= MAX_LISTADOS) {
    return (
      <>
        {nombres.map((nombre) => (
          <li key={nombre}>
            <span class="n archivos">
              <IconoArchivo nombre={nombre} /> {nombre}
            </span>
          </li>
        ))}
      </>
    );
  }
  const primero = nombres[0] ?? "";
  const ultimo = nombres[nombres.length - 1] ?? "";
  return (
    <li>
      <span class="n archivos">
        <IconoArchivo nombre={primero} /> {primero} … {ultimo}
        <small>{plural(nombres.length, "archivo")}</small>
      </span>
    </li>
  );
}

function Carpeta({ nodo, nombre }: { nodo: NodoCarpeta; nombre: string }) {
  const ignorada = esCarpetaSegunda(nodo.nombre) && !esCarpetaPrimera(nodo.nombre);
  const objetivo = !ignorada && esCarpetaPrimera(nodo.nombre);
  const clase = ignorada ? "ignorada" : objetivo ? "objetivo" : undefined;
  return (
    <li class={clase}>
      <span class="n">
        <IconoCarpeta color={objetivo ? "#1e5a6e" : ignorada ? "#a9b6bd" : undefined} /> {nombre}
        {objetivo && <span class="etq">esta</span>}
      </span>
      {ignorada && <small>se ignora · {plural(contarArchivos(nodo), "archivo")}</small>}
      {!ignorada && (nodo.carpetas.length > 0 || nodo.archivos.length > 0) && (
        <ul>
          {nodo.carpetas.map((hija) => (
            <Carpeta key={hija.ruta} nodo={hija} nombre={hija.nombre} />
          ))}
          <Archivos nombres={nodo.archivos} />
        </ul>
      )}
    </li>
  );
}

export function Arbol({ rutas }: { rutas: string[] }) {
  const raiz = useMemo(() => construirArbol(rutas), [rutas]);
  return (
    <ul class="arbol" aria-label="Contenido de la carpeta">
      <Carpeta nodo={raiz} nombre={raiz.nombre || "Archivos seleccionados"} />
    </ul>
  );
}

export function ArbolEjemplo() {
  return (
    <ul class="arbol" aria-hidden="true">
      <li>
        <span class="n">
          <IconoCarpeta /> Tutela 2026-00412
        </span>
        <ul>
          <li class="objetivo">
            <span class="n">
              <IconoCarpeta color="#1e5a6e" /> 01PrimeraInstancia <span class="etq">esta</span>
            </span>
            <ul>
              <li>
                <span class="n">
                  <IconoCarpeta /> C01Principal
                </span>
                <ul>
                  <li>
                    <span class="n archivos">
                      <IconoArchivo nombre="001.pdf" /> 001.pdf … 009.pdf
                    </span>
                  </li>
                </ul>
              </li>
            </ul>
          </li>
          <li class="ignorada">
            <span class="n">
              <IconoCarpeta color="#a9b6bd" /> 02SegundaInstancia
            </span>
            <small>se ignora</small>
          </li>
        </ul>
      </li>
    </ul>
  );
}
