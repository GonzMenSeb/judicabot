import { CLAVES_AUTO } from "./tipos";
import type { ClaveAuto, DatosAuto, DocResumen, RevisionCuerpo } from "./tipos";

export type CambiosRoles = Record<string, string>;
export type EdicionAuto = Partial<Record<ClaveAuto, string>>;

export function cambiosAuto(base: DatosAuto, edicion: EdicionAuto): Partial<DatosAuto> {
  const cambios: Partial<DatosAuto> = {};
  for (const clave of CLAVES_AUTO) {
    const valor = edicion[clave];
    if (valor === undefined) continue;
    const limpio = valor.trim();
    if (limpio !== (base[clave] ?? "")) cambios[clave] = limpio || null;
  }
  return cambios;
}

export function cuerpoRevision(roles: CambiosRoles, base: DatosAuto, edicion: EdicionAuto): RevisionCuerpo {
  const cuerpo: RevisionCuerpo = {};
  if (Object.keys(roles).length) cuerpo.roles = { ...roles };
  const auto = cambiosAuto(base, edicion);
  if (Object.keys(auto).length) cuerpo.auto = auto;
  return cuerpo;
}

export const hayCambios = (cuerpo: RevisionCuerpo): boolean => Boolean(cuerpo.roles || cuerpo.auto);

export const sinConfirmar = (documentos: readonly DocResumen[], roles: CambiosRoles): DocResumen[] =>
  documentos.filter((d) => d.revisar && !(d.doc_id in roles));
