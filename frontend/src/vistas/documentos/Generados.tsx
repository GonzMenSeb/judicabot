import { Boton } from "../../ui";
import { urlSalida } from "./tipos";
import type { SalidaPrevia } from "./tipos";

function IconoArchivo({ pdf }: { pdf: boolean }) {
  return (
    <svg class="docs-icono" viewBox="0 0 24 30" fill="none" aria-hidden="true">
      <path d="M3 1h12l7 7v21H3z" fill="#fff" stroke="#8da0a9" stroke-width="1.5" stroke-linejoin="round" />
      <path d="M15 1v7h7" stroke="#8da0a9" stroke-width="1.5" stroke-linejoin="round" />
      <rect x="6" y="17" width="12" height="5" rx="1" fill={pdf ? "#a8281f" : "#1e5a6e"} />
    </svg>
  );
}

export function Generados({ caso, salidas }: { caso: string; salidas: SalidaPrevia[] }) {
  if (!salidas.length) return null;
  return (
    <section class="docs-bloque" aria-labelledby="docs-gen-t">
      <h2 id="docs-gen-t">Ya generados</h2>
      <p class="sub">Salen de la lectura del expediente; no dependen del modelo.</p>
      <ul class="docs-archivos">
        {salidas.map((s) => (
          <li key={s.ruta} class="docs-archivo">
            <IconoArchivo pdf={/\.pdf$/i.test(s.archivo)} />
            <div>
              {s.titulo}
              <small>{s.archivo}</small>
            </div>
            <Boton href={urlSalida(caso, s.ruta)} download={s.archivo} aria-label={`Descargar ${s.titulo}`}>
              Descargar
            </Boton>
          </li>
        ))}
      </ul>
    </section>
  );
}
