import { ErrorApi } from "../../api/cliente";
import type { CasoResumen } from "../../api/contrato";
import type { MockRuta } from "../../api/mock";
import { OBLIGATORIOS } from "./tipos";
import type { DatosAuto, DocResumen, EstadoCaso, JobEstado, ResumenIngesta, RolDoc } from "./tipos";

const PRINCIPAL = "02SegundaInstancia/C01Principal";

function doc(n: number, rol: RolDoc, paginas: number, evidencia: string, extra: Partial<DocResumen> = {}): DocResumen {
  const nombre = `${String(n).padStart(3, "0")}.pdf`;
  return {
    doc_id: `d${n}`,
    ruta: `01PrimeraInstancia/C01Principal/${nombre}`,
    nombre,
    rol,
    rol_origen: "contenido",
    evidencia,
    paginas,
    paginas_sin_texto: 0,
    ruido: false,
    ajeno: false,
    jev_rol: rol,
    jev_confianza: 0.97,
    jev_umbral: 0.9,
    ...extra,
  };
}

const AUTO: DatosAuto = {
  fecha: "2026-10-22",
  fecha_reparto: "2026-10-21",
  accionante: "MARTA INÉS QUINTERO BEDOYA",
  accionada: "EPS HORIZONTE SALUD S.A.S.",
};

function documentosRevision(acc = "MARTA INÉS QUINTERO BEDOYA", ada = "EPS HORIZONTE SALUD S.A.S."): DocResumen[] {
  return [
    doc(1, "acta_reparto_1a", 1, "ACTA INDIVIDUAL DE REPARTO. Fecha: 14/09/2026 4:48:30 p. m. NÚMERO RADICACIÓN…", { jev_confianza: 0.99 }),
    doc(2, "escrito_tutela", 2, `Referencia: ACCIÓN DE TUTELA de ${acc} contra ${ada}`, { jev_confianza: 0.98 }),
    doc(3, "auto_admisorio", 1, `En mérito de lo expuesto, SE ADMITE la presente acción de tutela promovida por ${acc}…`),
    doc(4, "contestacion", 2, "Referencia: Contestación de la acción de tutela. Radicado: 05001 40 88 009 2026 00412", { jev_confianza: 0.96 }),
    doc(5, "fallo_a_quo", 5, "Decisión: NIEGA. Fallo: 412/2026. Procede el Despacho a emitir el fallo…", { jev_confianza: 0.99 }),
    doc(6, "impugnacion", 2, "Referencia: Impugnación del fallo de tutela. Radicado: 05001 40 88 009 2026 00412", { jev_confianza: 0.98 }),
    doc(7, "auto_concede_impugnacion", 1, "Se presentó escrito de impugnación. Pase a Despacho. Medellín, 6 de octubre de 2026.", { jev_confianza: 0.93 }),
    doc(8, "notificacion", 1, "TUTELA 2026-00412 Desde Juzgado 9 Penal Municipal Control Garantías Medellín. Fecha Mar 06/10/2026 9:54 AM", { jev_confianza: 0.95 }),
    doc(9, "otro", 3, "Sin rasgos de ningún rol. Dos de tres páginas son imagen sin texto.", {
      paginas_sin_texto: 2,
      jev_rol: "memorial",
      jev_confianza: 0.94,
    }),
  ];
}

function documentosCardenas(): DocResumen[] {
  const sinJev = { jev_rol: null, jev_confianza: null, jev_umbral: null };
  return [
    doc(1, "acta_reparto_1a", 1, "ACTA INDIVIDUAL DE REPARTO. Fecha: 02/09/2026 10:12:08 a. m.", sinJev),
    doc(2, "escrito_tutela", 3, "Referencia: ACCIÓN DE TUTELA de JAIME CÁRDENAS OSPINA contra ASEGURADORA MONTAÑA AZUL S.A.", sinJev),
    doc(3, "impugnacion", 2, "Referencia: Impugnación del fallo de tutela. Radicado: 05001 40 88 002 2026 00398", sinJev),
    doc(4, "otro", 1, "Certificado de existencia y representación legal de la Cámara de Comercio.", { ...sinJev, ruido: true }),
    doc(5, "otro", 2, "Sus CUIs (05001 40 88 014 2025 00911) no corresponden al caso 05001 40 88 002 2026 00398; se trata como ajeno.", {
      ...sinJev,
      ajeno: true,
    }),
  ];
}

const ingesta = (documentos: DocResumen[], extra: Partial<ResumenIngesta> = {}): ResumenIngesta => {
  const presentes = new Set(documentos.filter((d) => !d.ajeno).map((d) => d.rol));
  return {
    n_documentos: documentos.length,
    documentos,
    faltantes: OBLIGATORIOS.filter((r) => !presentes.has(r)),
    esperados_faltantes: [],
    alertas: [],
    docs_ajenos: documentos.filter((d) => d.ajeno).map((d) => d.doc_id),
    auto: { ...AUTO },
    ...extra,
  };
};

interface CasoMock {
  resumen: CasoResumen;
  ingesta: ResumenIngesta | null;
  salidas: string[];
  job_activo?: string;
}

function resumenCaso(id: string, nombre: string, estado: CasoResumen["estado"], etapa: CasoResumen["etapa"], extra: Partial<CasoResumen> = {}): CasoResumen {
  return {
    id,
    nombre,
    radicado: "05001408800920260041200",
    accionante: null,
    accionadas: [],
    juzgado_a_quo: "Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín",
    estado,
    etapa,
    siguiente_paso: "",
    n_insumos: 9,
    n_alertas: 0,
    job_activo: null,
    actualizado: "2026-11-03T14:40:00Z",
    ...extra,
  };
}

const ACTA = `${PRINCIPAL}/001ActaRepartoSegunda.pdf`;
const AUTO_DOCX = `${PRINCIPAL}/002AutoAsumeSegunda202600412.docx`;

const casos: Record<string, CasoMock> = {
  "arango-londono": {
    resumen: resumenCaso("arango-londono", "Arango Londoño c. EPS Ceiba Salud", "revision", 0, { n_alertas: 1 }),
    ingesta: ingesta(documentosRevision("ÁLVARO ARANGO LONDOÑO", "EPS CEIBA SALUD S.A.S."), {
      alertas: ["d9 009.pdf (otro): páginas sin texto legible: 2, 3."],
      auto: { fecha: "2026-10-22", fecha_reparto: "2026-10-21", accionante: "ÁLVARO ARANGO LONDOÑO", accionada: "EPS CEIBA SALUD S.A.S." },
    }),
    salidas: [ACTA, AUTO_DOCX, "trabajo/previo.docx"],
  },
  "cardenas-ospina": {
    resumen: resumenCaso("cardenas-ospina", "Cárdenas Ospina c. Aseguradora Montaña Azul", "incompleto", 0, {
      radicado: "05001408800220260039800",
      juzgado_a_quo: "Juzgado Segundo Penal Municipal con Función de Conocimiento de Medellín",
      n_insumos: 5,
      n_alertas: 1,
    }),
    ingesta: ingesta(documentosCardenas(), {
      esperados_faltantes: ["auto_admisorio", "acta_reparto_2a"],
      alertas: ["d5 005.pdf: sus CUIs (05001 40 88 014 2025 00911) no corresponden al caso 05001 40 88 002 2026 00398; se trata como ajeno."],
      auto: { fecha: null, fecha_reparto: null, accionante: "JAIME CÁRDENAS OSPINA", accionada: null },
    }),
    salidas: ["trabajo/requerimiento.docx"],
  },
  "quintero-bedoya": {
    resumen: resumenCaso("quintero-bedoya", "Quintero Bedoya c. EPS Horizonte Salud", "esperando_decision", 2),
    ingesta: ingesta(documentosRevision()),
    salidas: [ACTA, AUTO_DOCX, "trabajo/previo.docx"],
  },
  "restrepo-gil": {
    resumen: resumenCaso("restrepo-gil", "Restrepo Gil c. Fondo Pensional Altamira", "corriendo", 1, { n_insumos: 7 }),
    ingesta: ingesta(documentosRevision("CARLOS RESTREPO GIL", "FONDO PENSIONAL ALTAMIRA S.A.")),
    salidas: [ACTA, AUTO_DOCX],
    job_activo: "job-iniciar-restrepo-gil",
  },
  "mejia-rios": {
    resumen: resumenCaso("mejia-rios", "Mejía Ríos c. Fondo Pensional Altamira", "terminado", 4, { n_insumos: 10 }),
    ingesta: ingesta(documentosRevision("LUIS MEJÍA RÍOS", "FONDO PENSIONAL ALTAMIRA S.A.")),
    salidas: [ACTA, AUTO_DOCX, `${PRINCIPAL}/003FalloSegunda202600412.docx`],
  },
  "demo-sin-leer": {
    resumen: resumenCaso("demo-sin-leer", "Zapata Henao c. EPS Sendero", "sin_iniciar", 0, { radicado: null, juzgado_a_quo: null, n_insumos: 6 }),
    ingesta: null,
    salidas: [],
  },
};

const trabajos = new Map<string, { caso: string; cmd: JobEstado["cmd"]; consultas: number }>([
  ["job-iniciar-restrepo-gil", { caso: "restrepo-gil", cmd: "iniciar", consultas: -1000 }],
]);

const idDe = (ruta: string) => decodeURIComponent(/^\/api\/casos\/([^/?]+)/.exec(ruta)?.[1] ?? "");

function entrada(id: string) {
  const caso = casos[id];
  if (!caso) throw new ErrorApi(404, "Caso no encontrado.", "Caso no encontrado.");
  return caso;
}

function estadoDe(id: string): EstadoCaso {
  const { resumen, ingesta: datos, salidas, job_activo } = entrada(id);
  const conHilo = resumen.estado === "esperando_decision" || resumen.estado === "terminado";
  return {
    ok: true,
    estado: resumen.estado === "corriendo" ? "revision" : (resumen.estado as EstadoCaso["estado"]),
    salidas,
    resumen: conHilo ? { alertas: [] } : datos,
    error: null,
    job_activo: job_activo ?? null,
    ...(conHilo && datos ? { ingesta: datos } : {}),
  };
}

export const mocks: MockRuta[] = [
  { metodo: "GET", ruta: "/api/casos", respuesta: () => Object.values(casos).map((c) => c.resumen) },
  ...Object.entries(casos).map(([id, caso]): MockRuta => ({ metodo: "GET", ruta: `/api/casos/${id}/resumen`, respuesta: caso.resumen })),
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/estado$/, respuesta: ({ ruta }) => estadoDe(idDe(ruta)) },
  { metodo: "GET", ruta: /^\/api\/casos\/[^/]+\/config$/, respuesta: () => ({ llm: { proveedor: "anthropic" } }) },
  {
    metodo: "PUT",
    ruta: /^\/api\/casos\/[^/]+\/revision$/,
    respuesta: ({ ruta, cuerpo }) => {
      const id = idDe(ruta);
      const caso = entrada(id);
      if (!caso.ingesta) throw new ErrorApi(422, "El caso no tiene ingesta; use nuevo.", "El caso no tiene ingesta; use nuevo.");
      const { roles, auto } = (cuerpo ?? {}) as { roles?: Record<string, RolDoc>; auto?: Partial<DatosAuto> };
      const documentos = caso.ingesta.documentos.map((d) => {
        const nuevo = roles?.[d.doc_id];
        return nuevo ? { ...d, rol: nuevo, rol_origen: "usuario" as const, evidencia: "Rol fijado por el usuario.", ajeno: false } : d;
      });
      caso.ingesta = ingesta(documentos, { auto: { ...caso.ingesta.auto, ...auto }, alertas: caso.ingesta.alertas, esperados_faltantes: caso.ingesta.esperados_faltantes });
      caso.resumen.estado = caso.ingesta.faltantes.length ? "incompleto" : "revision";
      return { ok: true, estado: caso.resumen.estado, payload: null, salidas: caso.salidas, resumen: caso.ingesta, error: null };
    },
  },
  {
    metodo: "POST",
    ruta: /^\/api\/casos\/[^/]+\/run$/,
    respuesta: ({ ruta, cuerpo }) => {
      const id = idDe(ruta);
      entrada(id);
      const { cmd } = cuerpo as { cmd: JobEstado["cmd"] };
      const job_id = `job-${cmd}-${id}`;
      trabajos.set(job_id, { caso: id, cmd, consultas: 0 });
      return { job_id };
    },
  },
  {
    metodo: "GET",
    ruta: /^\/api\/jobs\/[^/]+$/,
    respuesta: ({ ruta }) => {
      const id = decodeURIComponent(ruta.split("/").pop() ?? "");
      const trabajo = trabajos.get(id);
      if (!trabajo) throw new ErrorApi(404, "Job no encontrado.", "Job no encontrado.");
      trabajo.consultas += 1;
      const termino = trabajo.consultas > 3;
      if (termino && trabajo.cmd === "nuevo") {
        const caso = entrada(trabajo.caso);
        if (!caso.ingesta) {
          caso.ingesta = ingesta(documentosRevision());
          caso.resumen = { ...caso.resumen, estado: "revision", n_alertas: 0 };
          caso.salidas = [`${PRINCIPAL}/001ActaRepartoSegunda.pdf`, `${PRINCIPAL}/002AutoAsumeSegunda202600377.docx`];
        }
      }
      const job: JobEstado = { id, caso: trabajo.caso, cmd: trabajo.cmd, estado: termino ? "terminado" : "corriendo", error: null };
      return job;
    },
  },
];
