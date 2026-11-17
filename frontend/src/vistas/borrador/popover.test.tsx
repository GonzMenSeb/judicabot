import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import type { Ref } from "preact";
import { useRef, useState } from "preact/hooks";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApoderadoVista, EvidenciaVista } from "../../api/contrato";
import { APODERADOS_BORRADOR, NO_INSCRITO } from "./mock";
import {
  AVISO_NO_INSCRITO_AMBAR,
  AVISO_NO_INSCRITO_ROJO,
  PopoverApoderado,
  type PropsPopoverApoderado,
  URL_FIRMA_ELECTRONICA,
  URL_SANCIONES,
} from "./PopoverApoderado";

const ID_VERDE = "ap-3f9c2a71d0";
const ID_AMBAR = "ap-81be04c5f2";
const ID_ROJO = "ap-c47d19e6a8";

const abogado = (id: string): ApoderadoVista => structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === id) as ApoderadoVista);

function Montado(props: Omit<PropsPopoverApoderado, "ancla" | "contenedor" | "titulo">) {
  const titulo = useRef<HTMLHeadingElement>(null);
  const [{ ancla, contenedor }] = useState(() => {
    const ancla = document.createElement("span");
    const contenedor = document.createElement("div");
    document.body.append(contenedor);
    contenedor.append(ancla);
    return { ancla, contenedor };
  });
  return <PopoverApoderado {...props} ancla={ancla} contenedor={contenedor} titulo={titulo as Ref<HTMLHeadingElement>} />;
}

function montar(ap: ApoderadoVista, extra: Partial<PropsPopoverApoderado> = {}) {
  const acciones = {
    onCerrar: vi.fn(),
    alRevisar: vi.fn(),
    alVerEvidencia: vi.fn(),
    alSubir: vi.fn(async () => {}),
    alCorregir: vi.fn(),
    alRestaurarPoder: vi.fn(),
  };
  const salida = render(<Montado apoderado={ap} editable {...acciones} {...extra} />);
  const dialogo = screen.getByRole("dialog");
  const bloque = (nombre: string) => within(dialogo).getByRole("heading", { level: 4, name: nombre }).closest("section") as HTMLElement;
  return { ...acciones, ...salida, dialogo, tarjeta: () => bloque("Tarjeta profesional"), poder: () => bloque("Facultad para representar") };
}

const datos = (seccion: HTMLElement): Record<string, string> =>
  Object.fromEntries([...seccion.querySelectorAll("dt")].map((dt) => [dt.textContent ?? "", dt.nextElementSibling?.textContent ?? ""]));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PopoverApoderado: cabecera y pie", () => {
  it("es el diálogo #bor-detalle titulado con el nombre, con el estado y la parte que representa", () => {
    const { dialogo } = montar(abogado(ID_VERDE));
    expect(dialogo.id).toBe("bor-detalle");
    expect(screen.getByRole("dialog", { name: "ANDREA PAOLA GIRALDO MONTOYA" })).toBe(dialogo);
    const titulo = within(dialogo).getByRole("heading", { level: 3 });
    expect(titulo.getAttribute("tabindex")).toBe("-1");
    expect(within(dialogo).getByText("Abogada verificada", { selector: ".chip" }).className).toBe("chip ok");
    expect(within(dialogo).getByText("Apoderada de EPS HORIZONTE SALUD S.A.S. · accionada")).toBeTruthy();
    expect(within(dialogo).queryByRole("list")).toBeNull();
  });

  it("por revisar y no verificado llevan su chip y la lista de motivos", () => {
    const { dialogo, unmount } = montar(abogado(ID_AMBAR));
    expect(within(dialogo).getByText("Por revisar", { selector: ".chip" }).className).toBe("chip alerta");
    expect(within(dialogo).getByText("Apoderado de MARTA INÉS QUINTERO BEDOYA · accionante")).toBeTruthy();
    expect(within(dialogo).getByRole("list").className).toBe("bor-motivos revisar");
    unmount();
    const rojo = montar(abogado(ID_ROJO));
    expect(within(rojo.dialogo).getByText("No verificado", { selector: ".chip" }).className).toBe("chip mal");
    const motivos = within(rojo.dialogo).getByRole("list");
    expect(motivos.className).toBe("bor-motivos rechazada");
    expect(within(motivos).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["La tarjeta profesional 97551 figura como «SUSPENDIDA» en el certificado N.° 4471388."]);
  });

  it("avisa si la revisión venció porque cambió la evidencia", () => {
    const ap = { ...abogado(ID_ROJO), revision_vencida: true };
    const { dialogo } = montar(ap);
    expect(within(dialogo).getAllByRole("listitem")[0]?.textContent).toBe("Lo había marcado como revisado, pero la evidencia cambió: revíselo de nuevo.");
  });

  it("el pie recuerda cotejar el original y «Marcar revisado» alterna con aria-pressed", () => {
    const { dialogo, alRevisar, unmount } = montar(abogado(ID_ROJO));
    expect(within(dialogo).getByText("Cotejo automático. Confirme contra el documento original.")).toBeTruthy();
    const boton = within(dialogo).getByRole("button", { name: "Marcar revisado" });
    expect(boton.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(boton);
    expect(alRevisar).toHaveBeenCalledWith(true);
    unmount();
    const revisado = montar({ ...abogado(ID_ROJO), revisado: true, bloquea: false });
    const otro = within(revisado.dialogo).getByRole("button", { name: "Marcar revisado" });
    expect(otro.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(otro);
    expect(revisado.alRevisar).toHaveBeenCalledWith(false);
  });

  it("si el caso no admite cambios, «Marcar revisado» queda deshabilitado y lo explica", () => {
    const { dialogo } = montar(abogado(ID_ROJO), { editable: false });
    const boton = within(dialogo).getByRole("button", { name: "Marcar revisado" }) as HTMLButtonElement;
    expect(boton.disabled).toBe(true);
    expect(boton.title).toBe("Solo se puede cambiar mientras el caso espera la decisión");
  });

  it("Escape y el botón Cerrar llaman onCerrar; Escape no se propaga", () => {
    const fuera = vi.fn();
    document.addEventListener("keydown", fuera);
    const { dialogo, onCerrar } = montar(abogado(ID_VERDE));
    fireEvent.keyDown(dialogo, { key: "Escape" });
    expect(onCerrar).toHaveBeenCalledTimes(1);
    expect(fuera).not.toHaveBeenCalled();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Cerrar" }));
    expect(onCerrar).toHaveBeenCalledTimes(2);
    document.removeEventListener("keydown", fuera);
  });
});

describe("PopoverApoderado: bloque 1, tarjeta profesional", () => {
  it("vigente: chip, T.P., C.C. enmascarada, consulta, fuente y número de certificado", () => {
    const { tarjeta, container } = montar(abogado(ID_VERDE));
    expect(within(tarjeta()).getByText("Vigente", { selector: ".chip" }).className).toBe("chip ok");
    expect(tarjeta().className).toBe("ev");
    const filas = datos(tarjeta());
    expect(filas).toMatchObject({ Tarjeta: "T.P. 287.415", Documento: "C.C. 1.017.•••.•68", Fuente: "Rama Judicial · Certificado de vigencia", Certificado: "N.° 4471203" });
    expect(filas["Consultado"]).toMatch(/\d{2}:\d{2}$/);
    expect(container.textContent).not.toContain("1017234568");
    expect(within(tarjeta()).queryByRole("link")).toBeNull();
    expect(within(tarjeta()).queryByText(/Arrastre aquí/)).toBeNull();
  });

  it("con certificado guardado y código: «Ver certificado (PDF)» y el enlace para validar el código", () => {
    const ap = abogado(ID_VERDE);
    ap.vigencia = { ...ap.vigencia, origen: "manual", certificado_url: `/api/casos/c/apoderados/${ID_VERDE}/certificado`, codigo_verificacion: "ab12cd34" };
    const { tarjeta } = montar(ap);
    expect(datos(tarjeta())).toMatchObject({ Fuente: "Certificado subido por el despacho", Código: "ab12cd34" });
    const pdf = within(tarjeta()).getByRole("link", { name: /Ver certificado \(PDF\)/ });
    expect(pdf.getAttribute("href")).toBe(`/api/casos/c/apoderados/${ID_VERDE}/certificado`);
    expect(pdf.getAttribute("target")).toBe("_blank");
    expect(pdf.getAttribute("rel")).toBe("noopener noreferrer");
    expect(pdf.textContent).toContain("se abre en una pestaña nueva");
    const validar = within(tarjeta()).getByRole("link", { name: /Validar el código/ });
    expect(validar.getAttribute("href")).toBe(URL_FIRMA_ELECTRONICA);
    expect(validar.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("no vigente: bloque en rojo, aviso de sanciones y un enlace a la CNDJ que no lleva datos", () => {
    const { tarjeta } = montar(abogado(ID_ROJO));
    expect(tarjeta().className).toBe("ev mal");
    expect(within(tarjeta()).getByText("No vigente", { selector: ".chip" }).className).toBe("chip mal");
    expect(within(tarjeta()).getByText(/las sanciones disciplinarias antes de dar por válida su intervención/)).toBeTruthy();
    const cndj = within(tarjeta()).getByRole("link", { name: /Consultar sanciones \(CNDJ\)/ });
    expect(cndj.getAttribute("href")).toBe(URL_SANCIONES);
    expect(new URL(URL_SANCIONES).search).toBe("");
    expect(cndj.getAttribute("target")).toBe("_blank");
    expect(cndj.getAttribute("rel")).toBe("noopener noreferrer");
    // Un certificado más reciente se sube desde la fila del panel; el detalle no se alarga con la ayuda.
    expect(tarjeta().querySelector(".apo-ayuda")).toBeNull();
  });

  it("cédula no inscrita sin OCR: bloque en rojo, «No inscrito», su aviso y el enlace a la CNDJ", () => {
    const { tarjeta, dialogo } = montar(structuredClone(NO_INSCRITO));
    expect(tarjeta().className).toBe("ev mal");
    expect(within(tarjeta()).getByText("No inscrito", { selector: ".chip" }).className).toBe("chip mal");
    expect(within(tarjeta()).getByText(AVISO_NO_INSCRITO_ROJO)).toBeTruthy();
    expect(within(tarjeta()).getByRole("link", { name: /Consultar sanciones \(CNDJ\)/ }).getAttribute("href")).toBe(URL_SANCIONES);
    expect(datos(tarjeta())).toMatchObject({ Certificado: "N.° 4471391" });
    expect(dialogo.textContent).toContain("si actúa con licencia temporal, esta consulta no la cubre");
    expect(dialogo.textContent).not.toContain("16000040");
  });

  it("cédula no inscrita que pudo leerse o escribirse mal: ámbar, pide verificar el número y no ofrece la CNDJ", () => {
    const base = structuredClone(NO_INSCRITO);
    const ambar = { ...base, vigencia: { ...base.vigencia, grave: false } };
    for (const ap of [
      { ...ambar, estado: "revisar" as const, bloquea: false },
      // Sin verificar por un poder de otra parte: el abogado sigue en rojo, pero la vigencia no.
      { ...ambar, estado: "no_verificado" as const, bloquea: true, poder: { ...base.poder, estado: "ajeno" as const } },
    ]) {
      const { tarjeta, unmount } = montar(ap);
      expect(tarjeta().className).toBe("ev alerta");
      expect(within(tarjeta()).getByText("No inscrito", { selector: ".chip" }).className).toBe("chip alerta");
      expect(within(tarjeta()).getByText(AVISO_NO_INSCRITO_AMBAR)).toBeTruthy();
      expect(within(tarjeta()).queryByText(AVISO_NO_INSCRITO_ROJO)).toBeNull();
      expect(within(tarjeta()).queryByRole("link", { name: /Consultar sanciones/ })).toBeNull();
      unmount();
    }
  });

  it("mientras consulta muestra el giro con un estado; en cola lo dice", () => {
    const ap = abogado(ID_AMBAR);
    ap.vigencia = { ...ap.vigencia, fase: "consultando" };
    const { tarjeta, unmount } = montar({ ...ap, fase: "consultando" });
    expect(within(tarjeta()).getByText("Consultando…", { selector: ".chip" }).className).toBe("chip info");
    const estado = within(tarjeta()).getByRole("status");
    expect(estado.textContent).toBe("Consultando la Rama Judicial…");
    expect(estado.querySelector(".giro")).toBeTruthy();
    expect(within(tarjeta()).queryByText(/Arrastre aquí/)).toBeNull();
    unmount();
    ap.vigencia = { ...ap.vigencia, fase: "en_cola" };
    const enCola = montar({ ...ap, fase: "en_cola" });
    expect(within(enCola.tarjeta()).getByText("En cola para consultar la Rama Judicial.")).toBeTruthy();
  });

  it("si necesita su ayuda ofrece la ayuda compacta y sube el archivo para ese abogado", async () => {
    const { tarjeta, alSubir } = montar(abogado(ID_AMBAR));
    expect(tarjeta().className).toBe("ev alerta");
    const ayuda = tarjeta().querySelector(".apo-ayuda") as HTMLElement;
    expect(ayuda.classList.contains("compacta")).toBe(true);
    expect(within(ayuda).getByRole("link", { name: "Abrir Certificado de vigencia" })).toBeTruthy();
    const archivo = new File(["%PDF-1.7"], "cert.pdf", { type: "application/pdf" });
    const entrada = ayuda.querySelector("input[type=file]") as HTMLInputElement;
    Object.defineProperty(entrada, "files", { configurable: true, value: [archivo] });
    fireEvent.change(entrada);
    await waitFor(() => expect(alSubir).toHaveBeenCalledWith(archivo));
  });

  it("sin edición no ofrece subir el certificado", () => {
    const { tarjeta } = montar(abogado(ID_AMBAR), { editable: false });
    expect(tarjeta().querySelector(".apo-ayuda")).toBeNull();
  });

  it.each(["inaccesible", "ilegible", "otra_persona"] as const)("con la vigencia %s también ofrece subir el certificado", (estado) => {
    const ap = abogado(ID_AMBAR);
    ap.vigencia = { ...ap.vigencia, estado, fase: "listo" };
    const { tarjeta } = montar({ ...ap, fase: "listo" });
    expect(tarjeta().querySelector(".apo-ayuda")).toBeTruthy();
  });

  it("sin tarjeta ni cédula en el expediente lo dice en lugar de la tabla", () => {
    const ap = abogado(ID_AMBAR);
    ap.tarjeta = null;
    ap.cedula = null;
    ap.vigencia = { ...ap.vigencia, estado: "sin_cedula", cedula: null, tarjeta_registro: null };
    const { tarjeta } = montar(ap);
    expect(tarjeta().querySelector("dl")).toBeNull();
    expect(within(tarjeta()).getByText("No constan la tarjeta profesional ni la cédula en el expediente.")).toBeTruthy();
    expect(within(tarjeta()).getByText(/No se encontró la C\.C\. del abogado/)).toBeTruthy();
  });
});

describe("PopoverApoderado: bloque 2, facultad para representar", () => {
  it("poder de una entidad: cita con el nombre resaltado, fuente, cadena y los dos botones del visor", () => {
    const { poder, alVerEvidencia } = montar(abogado(ID_VERDE));
    expect(poder().className).toBe("ev");
    expect(within(poder()).getByText("Poder hallado", { selector: ".chip" }).className).toBe("chip ok");
    const cita = poder().querySelector("q") as HTMLElement;
    expect([...cita.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["ANDREA PAOLA GIRALDO MONTOYA"]);
    expect(within(poder()).getByText("Poder especial · Doc. 1a-007 · página 4")).toBeTruthy();
    expect(poder().querySelector(".ev-cadena")?.textContent).toBe(
      "Lo otorga JUAN CARLOS RESTREPO URIBE, representante legal, según el certificado de existencia y representación (Doc. 1a-007, p. 6).",
    );
    const verPoder = within(poder()).getByRole("button", { name: "Ver poder · p. 4" });
    fireEvent.click(verPoder);
    expect(alVerEvidencia).toHaveBeenLastCalledWith(
      expect.objectContaining({ apoderado: ID_VERDE, titulo: "Poder especial · Doc. 1a-007", evidencia: expect.objectContaining({ pagina: 4 }) }),
      verPoder,
    );
    const verCertificado = within(poder()).getByRole("button", { name: "Ver certificado de existencia · p. 6" });
    fireEvent.click(verCertificado);
    expect(alVerEvidencia).toHaveBeenLastCalledWith(
      expect.objectContaining({ titulo: "Certificado de existencia · Doc. 1a-007", evidencia: expect.objectContaining({ pagina: 6 }) }),
      verCertificado,
    );
  });

  it("persona natural: basta el poder firmado por ella y no hay certificado que abrir", () => {
    const { poder } = montar(abogado(ID_AMBAR));
    expect(poder().querySelector(".ev-cadena")?.textContent).toBe("Persona natural: basta el poder firmado por ella.");
    expect(within(poder()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Ver poder · p. 6", "No es correcto…"]);
  });

  it.each([
    ["sin_certificado", "No se halló el certificado de existencia y representación de CLÍNICA SANTA AURORA S.A.S.: no se pudo confirmar quién otorga el poder."],
    ["contradicha", "El certificado de existencia y representación no muestra a ANA LÓPEZ como representante de CLÍNICA SANTA AURORA S.A.S."],
    ["no_aplica", "Para esta parte no se exige certificado de existencia: basta el poder."],
  ] as const)("cadena %s", (estado, texto) => {
    const ap = abogado(ID_ROJO);
    ap.poder.cadena = { estado, otorgante: estado === "contradicha" ? "ANA LÓPEZ" : "", cargo: "", evidencia: null };
    const { poder } = montar(ap);
    expect(poder().querySelector(".ev-cadena")?.textContent).toBe(texto);
  });

  it("poder de otra parte: bloque en rojo y lo dice", () => {
    const ap = abogado(ID_ROJO);
    ap.poder = { ...ap.poder, estado: "ajeno", parte: "EPS HORIZONTE SALUD S.A.S." };
    const { poder } = montar(ap);
    expect(poder().className).toBe("ev mal");
    expect(within(poder()).getByText("Poder de otra parte", { selector: ".chip" }).className).toBe("chip mal");
    expect(within(poder()).getByText("El poder hallado es para EPS HORIZONTE SALUD S.A.S., no para CLÍNICA SANTA AURORA S.A.S.")).toBeTruthy();
    expect(poder().querySelector(".ev-cadena")).toBeNull();
  });

  it("sin poder: lo dice, cita su propio escrito y ofrece abrirlo", () => {
    const ap = abogado(ID_VERDE);
    ap.poder = { ...ap.poder, estado: "sin_poder", evidencia: null };
    const { poder, alVerEvidencia, dialogo } = montar(ap);
    expect(poder().className).toBe("ev alerta");
    expect(within(poder()).getByText("Sin poder", { selector: ".chip" })).toBeTruthy();
    expect(within(poder()).getByText("Se revisaron 14 documentos y ninguno le otorga poder para EPS HORIZONTE SALUD S.A.S.")).toBeTruthy();
    expect(within(poder()).getByText("Su escrito · Doc. 1a-007 · página 1")).toBeTruthy();
    expect(within(dialogo).getByText("Dice ser apoderado de EPS HORIZONTE SALUD S.A.S. · accionada")).toBeTruthy();
    const ver = within(poder()).getByRole("button", { name: "Ver su escrito · p. 1" });
    fireEvent.click(ver);
    expect(alVerEvidencia).toHaveBeenCalledWith(expect.objectContaining({ titulo: "Escrito de ANDREA PAOLA GIRALDO MONTOYA · Doc. 1a-007" }), ver);
  });

  it("sin poder ni escrito propio queda la explicación y las correcciones a mano", () => {
    const ap = abogado(ID_VERDE);
    ap.poder = { ...ap.poder, estado: "descartado", evidencia: null, mencion: null };
    const { poder } = montar(ap);
    expect(within(poder()).getByText("El poder se descartó en la revisión.")).toBeTruthy();
    expect(within(poder()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Señalar el poder a mano…", "Deshacer el descarte"]);
    expect(poder().querySelector("q")).toBeNull();
  });

  it("la cita del expediente se muestra como texto aunque traiga etiquetas", () => {
    const ap = abogado(ID_VERDE);
    const evidencia: EvidenciaVista = { ...ap.poder.evidencia!, cita: "confiero poder a <b>ANDREA PAOLA GIRALDO MONTOYA</b> <img src=x onerror=alert(1)>" };
    ap.poder.evidencia = evidencia;
    const { poder } = montar(ap);
    const cita = poder().querySelector("q") as HTMLElement;
    expect(cita.querySelector("b, img")).toBeNull();
    expect(cita.textContent).toBe(evidencia.cita);
    expect(cita.querySelector("mark")?.textContent).toBe("ANDREA PAOLA GIRALDO MONTOYA");
  });
});

describe("PopoverApoderado: correcciones a mano y consulta automática", () => {
  it("«No es correcto…» pide descartar el poder que se muestra, desde su botón", () => {
    const { poder, alCorregir } = montar(abogado(ID_VERDE));
    const boton = within(poder()).getByRole("button", { name: "No es correcto…" });
    fireEvent.click(boton);
    expect(alCorregir).toHaveBeenCalledWith("descartar", boton);
    expect(within(poder()).queryByRole("button", { name: "Señalar el poder a mano…" })).toBeNull();
  });

  it("sin poder ofrece señalarlo a mano junto a su escrito", () => {
    const ap = abogado(ID_VERDE);
    ap.poder = { ...ap.poder, estado: "sin_poder", evidencia: null };
    const { poder, alCorregir } = montar(ap);
    expect(within(poder()).queryByRole("button", { name: "No es correcto…" })).toBeNull();
    const boton = within(poder()).getByRole("button", { name: "Señalar el poder a mano…" });
    fireEvent.click(boton);
    expect(alCorregir).toHaveBeenCalledWith("poder", boton);
  });

  it("un poder descartado se puede volver a tomar", () => {
    const ap = abogado(ID_VERDE);
    ap.poder = { ...ap.poder, estado: "descartado", evidencia: null };
    const { poder, alRestaurarPoder } = montar(ap);
    fireEvent.click(within(poder()).getByRole("button", { name: "Deshacer el descarte" }));
    expect(alRestaurarPoder).toHaveBeenCalledOnce();
  });

  it("sin un poder hallado al que volver, el descarte no se ofrece deshacer", () => {
    const ap = abogado(ID_VERDE);
    ap.poder = { ...ap.poder, estado: "descartado", evidencia: null, hay_hallado: false };
    const { poder } = montar(ap);
    expect(within(poder()).getAllByRole("button").map((b) => b.textContent)).not.toContain("Deshacer el descarte");
    expect(within(poder()).getByRole("button", { name: "Señalar el poder a mano…" })).toBeTruthy();
  });

  it("sin cédula en el expediente ofrece escribirla en el bloque de la tarjeta", () => {
    const ap = abogado(ID_AMBAR);
    ap.cedula = null;
    ap.vigencia = { ...ap.vigencia, estado: "sin_cedula", cedula: null };
    const { tarjeta, alCorregir } = montar(ap);
    const boton = within(tarjeta()).getByRole("button", { name: "Escribir la cédula" });
    fireEvent.click(boton);
    expect(alCorregir).toHaveBeenCalledWith("cedula", boton);
  });

  it("con la cédula en el expediente no se ofrece escribirla", () => {
    const { tarjeta } = montar(abogado(ID_AMBAR));
    expect(within(tarjeta()).queryByRole("button", { name: "Escribir la cédula" })).toBeNull();
  });

  it("si el caso no admite cambios no ofrece ninguna corrección", () => {
    const ap = abogado(ID_VERDE);
    ap.cedula = null;
    const { dialogo } = montar(ap, { editable: false });
    for (const nombre of ["No es correcto…", "Señalar el poder a mano…", "Escribir la cédula", "Deshacer el descarte"]) {
      expect(within(dialogo).queryByRole("button", { name: nombre })).toBeNull();
    }
  });

  it("la ayuda compacta ofrece reintentar la consulta automática cuando se puede", async () => {
    const alReintentar = vi.fn(async () => {});
    const { tarjeta } = montar(abogado(ID_AMBAR), { alReintentar });
    fireEvent.click(within(tarjeta()).getByRole("button", { name: "Reintentar consulta automática" }));
    await waitFor(() => expect(alReintentar).toHaveBeenCalledOnce());
  });

  it("sin consulta automática (apagada) la ayuda no ofrece reintentarla", () => {
    const { tarjeta } = montar(abogado(ID_AMBAR));
    expect(within(tarjeta()).queryByRole("button", { name: "Reintentar consulta automática" })).toBeNull();
    expect(within(tarjeta()).getByRole("button", { name: "o elija un archivo" })).toBeTruthy();
  });
});
