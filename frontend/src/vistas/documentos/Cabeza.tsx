import { plural } from "../../estado";
import { Migas, Pasos } from "../../ui";
import type { EtapaPaso } from "../../ui";
import type { CasoResumen } from "../../api/contrato";

const LIMITE: Record<CasoResumen["etapa"], EtapaPaso> = {
  0: "documentos",
  1: "proceso",
  2: "decision",
  3: "decision",
  4: "fallo",
};

export function Cabeza({ caso, info, nDocs }: { caso: string; info: CasoResumen | null; nDocs?: number }) {
  const nombre = info?.nombre ?? caso;
  return (
    <>
      <Migas items={[{ texto: "Inicio", href: "#/" }, { texto: "Segunda instancia", href: "#/segunda" }, { texto: nombre }]} />
      <header class="docs-cabeza">
        <h1 class="titulo">{nombre}</h1>
        {info && (info.radicado || info.juzgado_a_quo) && (
          <div class="docs-meta">
            {info.radicado && <span>Radicado {info.radicado}</span>}
            {info.juzgado_a_quo && <span>{info.juzgado_a_quo}</span>}
          </div>
        )}
      </header>
      <Pasos
        caso={caso}
        actual="documentos"
        limite={info ? LIMITE[info.etapa] : "documentos"}
        detalles={nDocs === undefined ? undefined : { documentos: plural(nDocs, "documento") }}
      />
    </>
  );
}
