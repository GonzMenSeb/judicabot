import { describe, expect, it } from "vitest";
import type { ApoderadosRespuesta, ApoderadoVista } from "../../api/contrato";
import {
  admiteCedula,
  admiteCertificado,
  admiteDescartar,
  admitePoderManual,
  apoderadosEnTexto,
  aplicarRevisiones,
  avisoPausa,
  avisoSubida,
  bloqueantes,
  claveApoderado,
  conRevision,
  consultaAutomatica,
  debeConsultar,
  documentosConocidos,
  ETIQUETA_ESTADO_APODERADO,
  ETIQUETA_FASE,
  ETIQUETA_PODER,
  ETIQUETA_VIGENCIA,
  etiquetaVigencia,
  formatoTarjeta,
  idDeClave,
  intervaloSondeo,
  itemsApoderados,
  lineaApoderado,
  lineaPoder,
  lineaVigencia,
  listaNombres,
  mascaraCedula,
  mensajeBloqueo,
  momentoConsulta,
  necesitaCertificado,
  noInscritoEnRojo,
  partirResaltado,
  pedidoVisor,
  progresoConsulta,
  puedeReintentar,
  reemplazarApoderado,
  resumenApoderados,
  revisadosDelServidor,
  segmentosEstado,
  SONDEO_ACTIVO_MS,
  SONDEO_AYUDA_MS,
  SONDEO_ERROR_MS,
  subtituloApoderado,
  tonoPoder,
  tonoVigencia,
  tratamiento,
} from "./apoderados";
import { APODERADOS_BORRADOR, NO_INSCRITO, VISTA_BORRADOR } from "./mock";

const datos = (): ApoderadosRespuesta => structuredClone(APODERADOS_BORRADOR);
const porNombre = (d: ApoderadosRespuesta, nombre: string): ApoderadoVista => {
  const ap = d.apoderados.find((a) => a.nombre.startsWith(nombre));
  if (!ap) throw new Error(`falta ${nombre}`);
  return ap;
};
const ROJO = () => porNombre(datos(), "CARLOS");
const AMBAR = () => porNombre(datos(), "LUIS");
const VERDE = () => porNombre(datos(), "ANDREA");
const HOY = new Date(2026, 10, 17, 15, 0).getTime();

describe("mascaraCedula y formatoTarjeta", () => {
  it.each([
    ["43000021", "43.•••.•21"],
    ["1037000088", "1.037.•••.•88"],
    ["16.000.040", "16.•••.•40"],
    ["1 017 234 568", "1.017.•••.•68"],
    ["123456", "•••.•56"],
    ["12345", "••.•45"],
  ])("%s → %s", (cedula, esperado) => {
    expect(mascaraCedula(cedula)).toBe(esperado);
  });

  it("devuelve vacío sin cédula y nunca deja ver los dígitos del medio", () => {
    expect(mascaraCedula(null)).toBe("");
    expect(mascaraCedula("")).toBe("");
    expect(mascaraCedula("C.C.")).toBe("");
    expect(mascaraCedula("1017234568")).not.toContain("2345");
  });

  it("agrupa la tarjeta profesional por miles y conserva los ceros a la izquierda", () => {
    expect(formatoTarjeta("287415")).toBe("287.415");
    expect(formatoTarjeta("097551")).toBe("097.551");
    expect(formatoTarjeta("T.P. 1234")).toBe("1.234");
    expect(formatoTarjeta(null)).toBe("");
  });
});

describe("etiquetas", () => {
  it("nombra los tres estados, todas las vigencias, poderes y fases", () => {
    expect(Object.values(ETIQUETA_ESTADO_APODERADO)).toEqual(["Verificado", "Por revisar", "No verificado"]);
    expect(Object.keys(ETIQUETA_VIGENCIA)).toHaveLength(9);
    expect(Object.keys(ETIQUETA_PODER)).toHaveLength(6);
    expect(ETIQUETA_FASE.necesita_ayuda).toBe("Necesita su ayuda");
  });

  it("la vigencia muestra la fase mientras la consulta está en curso", () => {
    const ap = AMBAR();
    expect(etiquetaVigencia(ap)).toBe("Sin consultar");
    ap.vigencia.fase = "consultando";
    expect(etiquetaVigencia(ap)).toBe("Consultando…");
    ap.vigencia.fase = "en_cola";
    expect(etiquetaVigencia(ap)).toBe("En cola");
  });
});

describe("momentoConsulta", () => {
  it("dice hoy con la hora si es del mismo día y la fecha si no", () => {
    expect(momentoConsulta(new Date(2026, 10, 17, 10, 42).toISOString(), HOY)).toMatch(/^hoy 10:42$/);
    expect(momentoConsulta(new Date(2026, 10, 3, 9, 5).toISOString(), HOY)).toMatch(/^3 .*nov.* 09:05$/);
  });

  it("sin fecha o con una inválida no dice nada", () => {
    expect(momentoConsulta(null, HOY)).toBe("");
    expect(momentoConsulta("no es fecha", HOY)).toBe("");
  });
});

describe("líneas de vigencia, poder y fila", () => {
  it("la vigencia lleva la T.P., la cédula enmascarada y cuándo se consultó", () => {
    const ap = VERDE();
    ap.vigencia.consultado_en = new Date(2026, 10, 17, 10, 42).toISOString();
    expect(lineaVigencia(ap, HOY)).toMatch(/^T\.P\. 287\.415 · C\.C\. 1\.017\.•••\.•68 · consultado hoy 10:42$/);
    expect(lineaVigencia(ap, HOY)).not.toContain("1017234568");
  });

  it("sin consulta ni datos lo dice", () => {
    const ap = AMBAR();
    expect(lineaVigencia(ap, HOY)).toBe("T.P. 198.344 · C.C. 71.•••.•20");
    ap.tarjeta = null;
    ap.cedula = null;
    expect(lineaVigencia(ap, HOY)).toBe("No constan la tarjeta profesional ni la cédula en el expediente.");
  });

  it("el poder nombra el documento, la página y quién lo otorga", () => {
    expect(lineaPoder(VERDE())).toBe("Poder · Doc. 1a-007, p. 4 · lo otorga JUAN CARLOS RESTREPO URIBE, representante legal");
    expect(lineaPoder(AMBAR())).toBe("Poder · Doc. 1a-002, p. 6 · lo otorga MARTA INÉS QUINTERO BEDOYA");
    const ajeno = ROJO();
    ajeno.poder = { ...ajeno.poder, estado: "ajeno", parte: "EPS HORIZONTE SALUD S.A.S.", otorgante: "JUAN" };
    expect(lineaPoder(ajeno)).toBe("Poder · Doc. 1a-011, p. 5 · para EPS HORIZONTE SALUD S.A.S.");
    const sin = AMBAR();
    sin.poder = { ...sin.poder, estado: "sin_poder", evidencia: null };
    expect(lineaPoder(sin)).toBeNull();
  });

  it("la fila resume la tarjeta y el poder en una línea", () => {
    expect(lineaApoderado(VERDE())).toBe("Tarjeta vigente · poder (Doc. 1a-007, p. 4)");
    expect(lineaApoderado(ROJO())).toBe("Tarjeta profesional no vigente · poder (Doc. 1a-011, p. 5)");
    const sin = AMBAR();
    sin.poder = { ...sin.poder, estado: "sin_poder", evidencia: null };
    expect(lineaApoderado(sin)).toBe("Tarjeta sin consultar · no se halló poder en el expediente");
    // Mientras se consulta, la tarjeta la dice la etiqueta de la fila: la línea queda para el poder.
    sin.vigencia.fase = "consultando";
    expect(lineaApoderado(sin)).toBe("No se halló poder en el expediente");
    sin.vigencia.fase = "en_cola";
    expect(lineaApoderado(VERDE())).toBe("Tarjeta vigente · poder (Doc. 1a-007, p. 4)");
    expect(lineaApoderado(sin)).toBe("No se halló poder en el expediente");
    const sustitucion = VERDE();
    sustitucion.poder = { ...sustitucion.poder, estado: "hallado_reserva", tipo: "sustitucion" };
    expect(lineaApoderado(sustitucion)).toBe("Tarjeta vigente · sustitución de poder sin confirmar quién lo otorga (Doc. 1a-007, p. 4)");
  });
});

describe("itemsApoderados y claves", () => {
  it("arma una fila por apoderado con clave apoderado-<id> y el nivel según el estado", () => {
    const items = itemsApoderados(datos());
    expect(items.map((i) => [i.clave, i.nivel])).toEqual([
      ["apoderado-ap-c47d19e6a8", "mal"],
      ["apoderado-ap-81be04c5f2", "alerta"],
      ["apoderado-ap-3f9c2a71d0", "ok"],
    ]);
    expect(items[0]).toMatchObject({
      origen: "Apoderado · CLÍNICA SANTA AURORA S.A.S.",
      titulo: "CARLOS EDUARDO PINEDA RUIZ",
      grupo: "apoderados",
      marca: { tipo: "apoderado", id: "ap-c47d19e6a8" },
      lineaCompleta: false,
      detalle: { tipo: "apoderado", apoderado: { id: "ap-c47d19e6a8" } },
    });
    expect(itemsApoderados(null)).toEqual([]);
  });

  it("la fila cerrada de quien necesita ayuda lo dice con un chip, como en la mesa Consulta", () => {
    const d = datos();
    const items = itemsApoderados(d);
    const ayuda = items.find((i) => i.titulo.startsWith("LUIS"));
    expect(porNombre(d, "LUIS").vigencia.fase).toBe("necesita_ayuda");
    expect(ayuda?.etiqueta).toEqual({ texto: "Necesita su ayuda", tono: "alerta" });
    expect(items.filter((i) => i.etiqueta).map((i) => i.titulo)).toEqual([ayuda?.titulo]);
  });

  it("en cola lleva un chip y consultando, el renglón con giro de la mesa Consulta", () => {
    const d = datos();
    porNombre(d, "LUIS").vigencia.fase = "en_cola";
    porNombre(d, "CARLOS").vigencia.fase = "consultando";
    const items = itemsApoderados(d);
    expect(items.find((i) => i.titulo.startsWith("LUIS"))?.etiqueta).toEqual({ texto: "En cola", tono: "neutro" });
    expect(items.find((i) => i.titulo.startsWith("LUIS"))?.linea).toBe("Poder (Doc. 1a-002, p. 6)");
    expect(items.find((i) => i.titulo.startsWith("CARLOS"))?.etiqueta).toEqual({ texto: "Consultando vigencia en la Rama Judicial…", tono: "info", giro: true });
    expect(items.find((i) => i.titulo.startsWith("ANDREA"))?.etiqueta).toBeUndefined();
  });

  it("convierte entre clave e id y no confunde las alertas del nodo", () => {
    expect(claveApoderado("ap-1")).toBe("apoderado-ap-1");
    expect(idDeClave("apoderado-ap-1")).toBe("ap-1");
    expect(idDeClave("alerta-apoderados-0")).toBeNull();
    expect(idDeClave("cita-c1")).toBeNull();
  });

  it("toma del servidor qué apoderados están revisados", () => {
    const d = datos();
    expect(revisadosDelServidor(d)).toEqual([]);
    porNombre(d, "LUIS").revisado = true;
    expect(revisadosDelServidor(d)).toEqual(["apoderado-ap-81be04c5f2"]);
    expect(revisadosDelServidor(null)).toEqual([]);
  });
});

describe("resumen y progreso", () => {
  it("cuenta apoderados por estado y omite los ceros", () => {
    expect(resumenApoderados(datos())).toEqual({ total: "3 apoderados", partes: ["1 verificado", "1 por revisar", "1 no verificado"] });
    const d = datos();
    d.apoderados = [AMBAR(), AMBAR()];
    expect(resumenApoderados(d)).toEqual({ total: "2 apoderados", partes: ["2 por revisar"] });
  });

  it("solo describe el progreso mientras hay consultas en curso", () => {
    const d = datos();
    expect(progresoConsulta(d)).toBeNull();
    d.consulta.activa = true;
    porNombre(d, "LUIS").fase = "consultando";
    expect(progresoConsulta(d)).toBe("2 de 3 listos · consultando la Rama Judicial");
    porNombre(d, "CARLOS").fase = "en_cola";
    porNombre(d, "LUIS").fase = "en_cola";
    expect(progresoConsulta(d)).toBe("1 de 3 listo · en cola para consultar");
    expect(progresoConsulta(null)).toBeNull();
  });

  it("ordena la barra de estados de lo más grave a lo verificado", () => {
    const d = datos();
    expect(segmentosEstado(d)).toEqual(["s-mal", "s-alerta", "s-ok"]);
    porNombre(d, "ANDREA").fase = "consultando";
    expect(segmentosEstado(d)).toEqual(["s-mal", "s-alerta", "s-curso"]);
  });
});

describe("revisiones optimistas", () => {
  it("marcar al no verificado lo deja de bloquear y recalcula el bloqueo del caso", () => {
    const d = datos();
    expect(d.bloquea_decision).toBe(true);
    const r = aplicarRevisiones(d, new Map([["ap-c47d19e6a8", true]]));
    expect(porNombre(r, "CARLOS")).toMatchObject({ revisado: true, bloquea: false, revision_vencida: false });
    expect(r.bloquea_decision).toBe(false);
    expect(d.bloquea_decision).toBe(true);
  });

  it("sin pendientes devuelve el mismo objeto y desmarcar a un ámbar no lo hace bloquear", () => {
    const d = datos();
    expect(aplicarRevisiones(d, new Map())).toBe(d);
    const ambar = conRevision({ ...AMBAR(), revisado: true }, false);
    expect(ambar).toMatchObject({ revisado: false, bloquea: false });
    const vencida = conRevision({ ...ROJO(), revision_vencida: true }, false);
    expect(vencida).toMatchObject({ revisado: false, bloquea: true, revision_vencida: true });
  });

  it("reemplaza al apoderado con la respuesta del servidor", () => {
    const d = datos();
    const vista = { ...ROJO(), revisado: true, bloquea: false, huella: "nueva" };
    const r = reemplazarApoderado(d, vista);
    expect(porNombre(r, "CARLOS").huella).toBe("nueva");
    expect(r.bloquea_decision).toBe(false);
    expect(r.apoderados).toHaveLength(3);
  });
});

describe("bloqueo", () => {
  it("lista los que bloquean y arma el mensaje en singular y plural", () => {
    const d = datos();
    expect(bloqueantes(d).map((a) => a.nombre)).toEqual(["CARLOS EDUARDO PINEDA RUIZ"]);
    expect(mensajeBloqueo(bloqueantes(d))).toBe(
      "CARLOS EDUARDO PINEDA RUIZ no pudo verificarse. Márquelo como revisado en la pestaña Apoderados para pasar a la decisión.",
    );
    const otro = { ...ROJO(), id: "ap-2", nombre: "ANA RUIZ" };
    const tercero = { ...ROJO(), id: "ap-3", nombre: "BEATRIZ LOPEZ" };
    expect(mensajeBloqueo([ROJO(), otro, tercero])).toBe(
      "CARLOS EDUARDO PINEDA RUIZ, ANA RUIZ y BEATRIZ LOPEZ no pudieron verificarse. Márquelos como revisados en la pestaña Apoderados para pasar a la decisión.",
    );
    expect(mensajeBloqueo([])).toBeNull();
    expect(bloqueantes(null)).toEqual([]);
  });

  it("une nombres a la manera castellana", () => {
    expect(listaNombres([])).toBe("");
    expect(listaNombres(["A"])).toBe("A");
    expect(listaNombres(["A", "B"])).toBe("A y B");
    expect(listaNombres(["A", "B", "C"])).toBe("A, B y C");
  });
});

describe("intervaloSondeo", () => {
  it("consulta cada 3 s si hay consultas en curso", () => {
    const d = datos();
    d.consulta.activa = true;
    expect(intervaloSondeo(d, false)).toBe(SONDEO_ACTIVO_MS);
  });

  it("cada 15 s si alguien necesita ayuda y la extensión no está conectada", () => {
    const d = datos();
    expect(intervaloSondeo(d, false)).toBe(SONDEO_AYUDA_MS);
    d.consulta.extension = "desactualizada";
    expect(intervaloSondeo(d, false)).toBe(SONDEO_AYUDA_MS);
    d.consulta.extension = "conectada";
    expect(intervaloSondeo(d, false)).toBeNull();
  });

  it("deja de consultar si nada está pendiente y espera 30 s tras un error", () => {
    const d = datos();
    for (const a of d.apoderados) a.fase = "listo";
    expect(intervaloSondeo(d, false)).toBeNull();
    expect(intervaloSondeo(null, false)).toBeNull();
    expect(intervaloSondeo(d, true)).toBe(SONDEO_ERROR_MS);
    expect(intervaloSondeo(null, true)).toBe(SONDEO_ERROR_MS);
  });
});

describe("partirResaltado", () => {
  const marcados = (texto: string, nombre: string) => partirResaltado(texto, nombre).filter((p) => p.marcado).map((p) => p.texto);

  it("encuentra el nombre sin distinguir mayúsculas, tildes ni espacios y conserva el texto original", () => {
    const texto = "confiero poder a la doctora ANDREA PAOLA GIRALDO\n MONTOYA, identificada con cédula";
    const pedazos = partirResaltado(texto, "Andrea Paola Giraldo Montoya");
    expect(pedazos.map((p) => p.texto).join("")).toBe(texto);
    expect(marcados(texto, "Andrea Paola Giraldo Montoya")).toEqual(["ANDREA PAOLA GIRALDO\n MONTOYA"]);
    expect(marcados("al doctor CARLOS PEÑA RUÍZ.", "carlos pena ruiz")).toEqual(["CARLOS PEÑA RUÍZ"]);
    expect(marcados("el doctor Jose Peña", "JOSÉ PEÑA")).toEqual(["Jose Peña"]);
  });

  it("marca cada aparición y respeta los bordes de palabra", () => {
    expect(marcados("ANA RUIZ y luego Ana Ruiz otra vez", "Ana Ruiz")).toEqual(["ANA RUIZ", "Ana Ruiz"]);
    expect(marcados("MARIANA RUIZES no es ella", "Ana Ruiz")).toEqual([]);
  });

  it("con tildes escritas aparte (NFD) se queda con la tilde de la última letra", () => {
    const texto = "la doctora RUI\u0301Z firmo\u0301";
    expect(marcados(texto, "Ruíz")).toEqual(["RUI\u0301Z"]);
    expect(marcados("el doctor PEN\u0303A", "Peña")).toEqual(["PEN\u0303A"]);
    expect(marcados("Jose\u0301 dijo", "José")).toEqual(["Jose\u0301"]);
  });

  it("devuelve texto plano: las etiquetas HTML de la cita quedan como texto alrededor del nombre", () => {
    expect(partirResaltado("poder a <b>ANA RUIZ</b>.", "Ana Ruiz")).toEqual([
      { texto: "poder a <b>", marcado: false },
      { texto: "ANA RUIZ", marcado: true },
      { texto: "</b>.", marcado: false },
    ]);
  });

  it("sin nombre o sin texto no marca nada", () => {
    expect(partirResaltado("algo", "")).toEqual([{ texto: "algo", marcado: false }]);
    expect(partirResaltado("", "Ana")).toEqual([]);
    expect(partirResaltado("Ana", "—")).toEqual([{ texto: "Ana", marcado: false }]);
  });
});

describe("tratamiento y subtítulo del detalle", () => {
  it("la llama apoderada si el expediente dice «la doctora» antes de su nombre", () => {
    const d = datos();
    expect(tratamiento(porNombre(d, "ANDREA"))).toBe("Apoderada");
    expect(tratamiento(porNombre(d, "LUIS"))).toBe("Apoderado");
    expect(tratamiento(porNombre(d, "CARLOS"))).toBe("Apoderado");
  });

  it("sin palabra que lo diga queda en masculino genérico", () => {
    const ap = porNombre(datos(), "ANDREA");
    ap.poder.evidencia = { ...ap.poder.evidencia!, cita: "confiero poder a ANDREA PAOLA GIRALDO MONTOYA" };
    ap.poder.mencion = null;
    expect(tratamiento(ap)).toBe("Apoderado");
  });

  it("dice la parte y su rol, y «Dice ser» cuando no hay poder que lo respalde", () => {
    const d = datos();
    expect(subtituloApoderado(porNombre(d, "ANDREA"))).toBe("Apoderada de EPS HORIZONTE SALUD S.A.S. · accionada");
    expect(subtituloApoderado(porNombre(d, "LUIS"))).toBe("Apoderado de MARTA INÉS QUINTERO BEDOYA · accionante");
    const sin = porNombre(d, "CARLOS");
    sin.poder = { ...sin.poder, estado: "sin_poder", evidencia: null };
    expect(subtituloApoderado(sin)).toBe("Dice ser apoderado de CLÍNICA SANTA AURORA S.A.S. · vinculada");
  });
});

describe("tonos, ayuda y evidencia para el visor", () => {
  it("el chip de la tarjeta y el del poder toman el tono de su estado", () => {
    const d = datos();
    expect([tonoVigencia(porNombre(d, "ANDREA")), tonoVigencia(porNombre(d, "LUIS")), tonoVigencia(porNombre(d, "CARLOS"))]).toEqual(["ok", "alerta", "mal"]);
    const consultando = porNombre(d, "LUIS");
    consultando.vigencia.fase = "consultando";
    expect(tonoVigencia(consultando)).toBe("info");
    const ap = porNombre(d, "ANDREA");
    expect(tonoPoder(ap)).toBe("ok");
    expect(tonoPoder({ ...ap, poder: { ...ap.poder, estado: "ajeno" } })).toBe("mal");
    expect(tonoPoder({ ...ap, poder: { ...ap.poder, estado: "sin_poder" } })).toBe("alerta");
  });

  it("cédula no inscrita: «No inscrito», rojo si el servidor la da por grave y ámbar si no", () => {
    const rojo = structuredClone(NO_INSCRITO);
    expect([rojo.estado, rojo.vigencia.grave]).toEqual(["no_verificado", true]);
    expect(ETIQUETA_VIGENCIA.no_inscrito).toBe("No inscrito");
    expect(etiquetaVigencia(rojo)).toBe("No inscrito");
    expect(tonoVigencia(rojo)).toBe("mal");
    expect(lineaApoderado(rojo)).toBe("No inscrito en el Registro Nacional de Abogados · poder (Doc. 1a-011, p. 5)");
    const ambar: ApoderadoVista = { ...rojo, estado: "revisar", bloquea: false, vigencia: { ...rojo.vigencia, grave: false } };
    expect(tonoVigencia(ambar)).toBe("alerta");
    expect(noInscritoEnRojo(ambar)).toBe(false);
    expect(lineaApoderado(ambar)).toContain("No inscrito en el Registro Nacional de Abogados");
    // Sin verificar por un poder de otra parte, con una cédula que pudo leerse mal: la vigencia sigue en ámbar.
    const ajeno: ApoderadoVista = { ...ambar, estado: "no_verificado", bloquea: true, poder: { ...rojo.poder, estado: "ajeno" } };
    expect([tonoVigencia(ajeno), noInscritoEnRojo(ajeno)]).toEqual(["alerta", false]);
    // Un certificado más reciente puede reemplazarlo, pero no hace falta pedirlo como si la vigencia no se hubiera obtenido.
    expect(necesitaCertificado(rojo)).toBe(false);
    expect(admiteCertificado(rojo)).toBe(true);
  });

  it("hace falta el certificado si la vigencia no se obtuvo y nada la está consultando", () => {
    const d = datos();
    expect(necesitaCertificado(porNombre(d, "LUIS"))).toBe(true);
    expect(necesitaCertificado(porNombre(d, "ANDREA"))).toBe(false);
    expect(necesitaCertificado(porNombre(d, "CARLOS"))).toBe(false);
    const ap = porNombre(d, "LUIS");
    for (const estado of ["inaccesible", "ilegible", "otra_persona", "sin_cedula", "sin_consultar"] as const) {
      expect(necesitaCertificado({ ...ap, vigencia: { ...ap.vigencia, estado, fase: "listo" } }), estado).toBe(true);
    }
    expect(necesitaCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "sin_consultar", fase: "en_cola" } })).toBe(false);
    expect(necesitaCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "vigente_obs", fase: "listo" } })).toBe(false);
    expect(necesitaCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "no_vigente", fase: "necesita_ayuda" } })).toBe(true);
  });

  it("ofrece subir el certificado si la tarjeta no consta vigente y nada la está consultando", () => {
    const d = datos();
    expect(admiteCertificado(porNombre(d, "LUIS"))).toBe(true);
    expect(admiteCertificado(porNombre(d, "ANDREA"))).toBe(false);
    // No vigente: un certificado más reciente puede reemplazar al que se leyó.
    expect(admiteCertificado(porNombre(d, "CARLOS"))).toBe(true);
    const ap = porNombre(d, "LUIS");
    for (const estado of ["inaccesible", "ilegible", "otra_persona", "sin_cedula", "sin_consultar", "no_vigente", "vigente_obs"] as const) {
      expect(admiteCertificado({ ...ap, vigencia: { ...ap.vigencia, estado, fase: "listo" } }), estado).toBe(true);
    }
    expect(admiteCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "sin_consultar", fase: "en_cola" } })).toBe(false);
    expect(admiteCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "sin_consultar", fase: "consultando" } })).toBe(false);
    expect(admiteCertificado({ ...ap, vigencia: { ...ap.vigencia, estado: "vigente", fase: "listo" } })).toBe(false);
  });

  it("arma el título y el subtítulo del visor para el poder, el certificado y el escrito", () => {
    const ap = porNombre(datos(), "ANDREA");
    expect(pedidoVisor(ap, "poder")).toEqual({
      apoderado: ap.id,
      evidencia: ap.poder.evidencia,
      titulo: "Poder especial · Doc. 1a-007",
      subtitulo: "Evidencia de que ANDREA PAOLA GIRALDO MONTOYA representa a EPS HORIZONTE SALUD S.A.S.",
    });
    expect(pedidoVisor(ap, "certificado")).toMatchObject({
      evidencia: { pagina: 6 },
      titulo: "Certificado de existencia · Doc. 1a-007",
      subtitulo: "Evidencia de que JUAN CARLOS RESTREPO URIBE es representante legal de EPS HORIZONTE SALUD S.A.S.",
    });
    expect(pedidoVisor(ap, "escrito")).toMatchObject({
      evidencia: { pagina: 1 },
      titulo: "Escrito de ANDREA PAOLA GIRALDO MONTOYA · Doc. 1a-007",
      subtitulo: "Donde ANDREA PAOLA GIRALDO MONTOYA dice actuar por EPS HORIZONTE SALUD S.A.S.",
    });
    const natural = porNombre(datos(), "LUIS");
    expect(pedidoVisor(natural, "certificado")).toBeNull();
    expect(pedidoVisor(natural, "escrito")).toBeNull();
    expect(pedidoVisor({ ...natural, poder: { ...natural.poder, evidencia: null } }, "poder")).toBeNull();
  });

  it("lista los abogados cuyo nombre está marcado en el texto", () => {
    expect([...apoderadosEnTexto(VISTA_BORRADOR)].sort()).toEqual(["ap-3f9c2a71d0", "ap-81be04c5f2", "ap-c47d19e6a8"]);
  });
});

describe("avisoSubida", () => {
  it("anuncia lo que dice el certificado subido, con el tono del resultado", () => {
    const con = (estado: ApoderadoVista["vigencia"]["estado"]) => {
      const ap = AMBAR();
      ap.vigencia.estado = estado;
      return avisoSubida(ap);
    };
    expect(con("vigente")).toEqual({ texto: "Certificado leído: la tarjeta profesional de LUIS FERNANDO OSPINA ARANGO está vigente.", tipo: "ok" });
    expect(con("no_vigente")).toEqual({ texto: "Certificado leído: la tarjeta profesional de LUIS FERNANDO OSPINA ARANGO no está vigente.", tipo: "alerta" });
    expect(con("vigente_obs").texto).toContain("está vigente, con observaciones");
    expect(con("otra_persona").texto).toBe("Certificado leído: está a nombre de otra persona, no de LUIS FERNANDO OSPINA ARANGO.");
    expect(con("ilegible")).toMatchObject({ tipo: "alerta" });
    expect(con("sin_consultar")).toEqual({ texto: "Certificado de LUIS FERNANDO OSPINA ARANGO guardado.", tipo: "info" });
    expect(con("no_inscrito")).toEqual({
      texto: "Certificado leído: la cédula de LUIS FERNANDO OSPINA ARANGO no está inscrita en el Registro Nacional de Abogados.",
      tipo: "alerta",
    });
  });

  it("no lleva la cédula", () => {
    const ap = AMBAR();
    ap.vigencia.estado = "vigente";
    expect(avisoSubida(ap).texto).not.toMatch(/\d{5}/);
  });
});

describe("intervaloSondeo: modos y pausa", () => {
  it("con la consulta apagada, directa o simulada no espera a ninguna extensión", () => {
    for (const modo of ["apagada", "directa", "fake"] as const) {
      const d = datos();
      d.consulta.modo = modo;
      expect(intervaloSondeo(d, false)).toBeNull();
    }
  });

  it("si la Rama Judicial está en pausa y alguien necesita ayuda vuelve a mirar cada 15 s, aunque la extensión esté conectada", () => {
    const d = datos();
    d.consulta = { ...d.consulta, extension: "conectada", pausa_hasta: "2026-11-17T15:42:00-05:00" };
    expect(intervaloSondeo(d, false)).toBe(SONDEO_AYUDA_MS);
    d.consulta.modo = "directa";
    expect(intervaloSondeo(d, false)).toBe(SONDEO_AYUDA_MS);
    for (const a of d.apoderados) a.fase = "listo";
    expect(intervaloSondeo(d, false)).toBeNull();
  });
});

describe("consulta automática", () => {
  const sinConsultar = () => {
    const d = datos();
    d.consulta.extension = "conectada";
    return d;
  };

  it("al abrir pide consultar si alguien sigue sin consultar, nada está en curso y la consulta está encendida", () => {
    expect(debeConsultar(sinConsultar())).toBe(true);
    // Sin extensión también: la cola espera a que se conecte y sigue sola.
    expect(debeConsultar(datos())).toBe(true);
  });

  it.each([
    ["la consulta está apagada", (d: ApoderadosRespuesta) => (d.consulta.modo = "apagada")],
    ["ya hay consultas en curso", (d: ApoderadosRespuesta) => (d.consulta.activa = true)],
    ["el caso no admite cambios", (d: ApoderadosRespuesta) => (d.editable = false)],
    ["no hay identificación", (d: ApoderadosRespuesta) => (d.identificacion = "no_disponible")],
    ["nadie está sin consultar", (d: ApoderadosRespuesta) => (porNombre(d, "LUIS").vigencia.estado = "inaccesible")],
    ["el abogado ya está en cola", (d: ApoderadosRespuesta) => (porNombre(d, "LUIS").vigencia.fase = "en_cola")],
    ["no hay cédula que consultar", (d: ApoderadosRespuesta) => (porNombre(d, "LUIS").cedula = null)],
  ])("no lo pide si %s", (_, cambiar) => {
    const d = sinConsultar();
    cambiar(d);
    expect(debeConsultar(d)).toBe(false);
  });

  it("no lo pide sin datos", () => {
    expect(debeConsultar(null)).toBe(false);
  });

  it("reintentar exige consulta encendida que pueda salir, cédula y nada en curso", () => {
    const d = datos();
    d.consulta.extension = "conectada";
    const ap = porNombre(d, "LUIS");
    expect(puedeReintentar(ap, d.consulta)).toBe(true);
    // Sin una extensión que sepa consultar, nada saldría: la cola sigue sola al conectarse.
    expect(puedeReintentar(ap, { ...d.consulta, extension: "no_conectada" })).toBe(false);
    expect(puedeReintentar(ap, { ...d.consulta, extension: "desactualizada" })).toBe(false);
    expect(puedeReintentar(ap, { ...d.consulta, modo: "directa", extension: "no_conectada" })).toBe(true);
    expect(puedeReintentar(ap, { ...d.consulta, modo: "apagada" })).toBe(false);
    expect(puedeReintentar(ap, null)).toBe(false);
    expect(puedeReintentar({ ...ap, cedula: null }, d.consulta)).toBe(false);
    expect(puedeReintentar({ ...ap, vigencia: { ...ap.vigencia, fase: "consultando" } }, d.consulta)).toBe(false);
    expect(consultaAutomatica(d.consulta)).toBe(true);
    expect(consultaAutomatica({ ...d.consulta, modo: "apagada" })).toBe(false);
  });

  it("la pausa se anuncia con la hora local del reintento", () => {
    const d = datos();
    expect(avisoPausa(d.consulta)).toBeNull();
    const hasta = new Date(2026, 10, 17, 15, 42);
    expect(avisoPausa({ ...d.consulta, pausa_hasta: hasta.toISOString() })).toBe("La Rama Judicial no respondió; se reintenta a las 15:42.");
    expect(avisoPausa({ ...d.consulta, pausa_hasta: "no es una fecha" })).toBeNull();
    expect(avisoPausa(null)).toBeNull();
  });
});

describe("correcciones a mano", () => {
  it("«No es correcto…» solo cuando se muestra un poder; señalarlo a mano cuando falta uno que lo respalde", () => {
    const verde = VERDE();
    expect([admiteDescartar(verde), admitePoderManual(verde)]).toEqual([true, false]);
    const estados = ["hallado_reserva", "ajeno", "sin_poder", "descartado", "manual"] as const;
    const resultado = estados.map((estado) => {
      const ap = VERDE();
      ap.poder = { ...ap.poder, estado, evidencia: estado === "sin_poder" || estado === "descartado" ? null : ap.poder.evidencia };
      return [estado, admiteDescartar(ap), admitePoderManual(ap)];
    });
    expect(resultado).toEqual([
      ["hallado_reserva", true, true],
      ["ajeno", true, true],
      ["sin_poder", false, true],
      ["descartado", false, true],
      ["manual", true, false],
    ]);
  });

  it("la cédula se escribe a mano solo si el expediente no la trae", () => {
    expect(admiteCedula(VERDE())).toBe(false);
    expect(admiteCedula({ ...VERDE(), cedula: null })).toBe(true);
    expect(admiteCedula({ ...VERDE(), cedula: "C.C." })).toBe(true);
  });

  it("los documentos conocidos salen de las evidencias de todos los abogados, sin repetir y en orden", () => {
    expect(documentosConocidos(datos()).map((d) => [d.doc_id, d.total])).toEqual([
      ["1a-002", 6],
      ["1a-007", 12],
      ["1a-011", 7],
    ]);
    expect(documentosConocidos(datos())[0]?.documento).toBe("002_002EscritoTutelaQuinteroBedoya.pdf");
    expect(documentosConocidos(null)).toEqual([]);
  });
});
