import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ErrorApi } from "../../api";
import type { AjusteCuerpo, ApoderadoVista } from "../../api/contrato";
import { toasts } from "../../estado";
import { documentosConocidos } from "./apoderados";
import DialogoAjuste, { cedulaEscrita, type PropsDialogoAjuste } from "./DialogoAjuste";
import { APODERADOS_BORRADOR } from "./mock";

const VERDE = "ap-3f9c2a71d0";
const abogado = (id = VERDE): ApoderadoVista => structuredClone(APODERADOS_BORRADOR.apoderados.find((a) => a.id === id) as ApoderadoVista);
const DOCUMENTOS = documentosConocidos(structuredClone(APODERADOS_BORRADOR));

beforeAll(() => {
  // jsdom no implementa <dialog>: basta con que se abra y se cierre.
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => {
  toasts.value = [];
  vi.restoreAllMocks();
});

function montar(tipo: PropsDialogoAjuste["tipo"], extra: Partial<PropsDialogoAjuste> = {}) {
  const alGuardar = vi.fn<(cuerpo: AjusteCuerpo) => Promise<ApoderadoVista>>(async () => abogado());
  const alCerrar = vi.fn();
  const resultado = render(<DialogoAjuste tipo={tipo} apoderado={abogado()} documentos={DOCUMENTOS} alGuardar={alGuardar} alCerrar={alCerrar} {...extra} />);
  return { ...resultado, alGuardar, alCerrar, dialogo: () => screen.getByRole("dialog") };
}

const guardar = (nombre: string) => fireEvent.click(screen.getByRole("button", { name: nombre }));

describe("cedulaEscrita", () => {
  it.each([
    ["1017234568", "1017234568"],
    ["1.017.234.568", "1017234568"],
    [" 43 000 021 ", "43000021"],
    ["12345", "12345"],
  ])("acepta %s", (texto, digitos) => {
    expect(cedulaEscrita(texto)).toBe(digitos);
  });

  it.each(["1234", "12345678901", "C.C. 1017234568", "10172x4568", "", "..."])("rechaza %s", (texto) => {
    expect(cedulaEscrita(texto)).toBeNull();
  });
});

describe("DialogoAjuste: «No es correcto…»", () => {
  it("explica qué deja de contar, pide confirmar y envía el descarte con la nota", async () => {
    const { alGuardar, alCerrar, dialogo } = montar("descartar");
    expect(within(dialogo()).getByRole("heading", { name: "¿El poder no es correcto?" })).toBeTruthy();
    expect(dialogo().textContent).toContain(
      "Judicabot dejará de tomar el poder del Doc. 1a-007, p. 4, como evidencia de que ANDREA PAOLA GIRALDO MONTOYA representa a EPS HORIZONTE SALUD S.A.S.",
    );
    fireEvent.input(screen.getByLabelText("Por qué no es correcto (opcional)"), { target: { value: "  Es de otro proceso.  " } });
    guardar("Descartar el poder");
    await waitFor(() => expect(alCerrar).toHaveBeenCalledOnce());
    expect(alGuardar).toHaveBeenCalledWith({ poder_descartado: true, nota: "Es de otro proceso." });
    expect(toasts.value.map((t) => t.texto)).toEqual(["Poder descartado: ANDREA PAOLA GIRALDO MONTOYA queda por revisar."]);
  });

  it("no duplica el punto de una parte como «S.A.S.»", () => {
    const { dialogo } = montar("descartar");
    expect(dialogo().textContent).toContain("representa a EPS HORIZONTE SALUD S.A.S. Quedará por revisar");
    expect(dialogo().textContent).not.toContain("S.A.S..");
  });

  it("Cancelar cierra sin enviar nada", () => {
    const { alGuardar, alCerrar } = montar("descartar");
    guardar("Cancelar");
    expect(alCerrar).toHaveBeenCalledOnce();
    expect(alGuardar).not.toHaveBeenCalled();
  });
});

describe("DialogoAjuste: señalar el poder a mano", () => {
  it("parte del documento y la página del poder conocido y envía lo elegido", async () => {
    const { alGuardar, alCerrar } = montar("poder");
    const documento = screen.getByLabelText("Documento del expediente") as HTMLSelectElement;
    expect([...documento.options].map((o) => o.textContent)).toEqual([
      "Doc. 1a-002 · 002_002EscritoTutelaQuinteroBedoya.pdf",
      "Doc. 1a-007 · 007_007RespuestaEPSHorizonteSaludSAS_ContestacionTutela_Radicado2026-00412_Anexos.pdf",
      "Doc. 1a-011 · 011_011RespuestaClinicaSantaAurora.pdf",
      "Otro documento…",
    ]);
    expect(documento.value).toBe("1a-007");
    expect(document.activeElement).toBe(documento);
    const pagina = screen.getByLabelText("Página") as HTMLInputElement;
    expect(pagina.value).toBe("4");
    expect(pagina.max).toBe("12");
    fireEvent.input(pagina, { target: { value: "5" } });
    guardar("Señalar el poder");
    await waitFor(() => expect(alCerrar).toHaveBeenCalledOnce());
    expect(alGuardar).toHaveBeenCalledWith({ poder_manual: { doc_id: "1a-007", pagina: 5 }, nota: "" });
    expect(toasts.value.map((t) => t.texto)).toEqual(["Poder de ANDREA PAOLA GIRALDO MONTOYA señalado a mano: Doc. 1a-007, p. 5."]);
  });

  it("con otro documento pide su número y lo valida antes de enviar", async () => {
    const { alGuardar } = montar("poder");
    fireEvent.change(screen.getByLabelText("Documento del expediente"), { target: { value: "" } });
    const otro = screen.getByLabelText("Número del documento") as HTMLInputElement;
    fireEvent.input(otro, { target: { value: "documento 4" } });
    fireEvent.input(screen.getByLabelText("Página"), { target: { value: "2" } });
    guardar("Señalar el poder");
    expect(alGuardar).not.toHaveBeenCalled();
    expect(otro.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Escriba el número del documento, p. ej. 1a-014.");
    expect(document.activeElement).toBe(otro);
    fireEvent.input(otro, { target: { value: " 1A-004 " } });
    guardar("Señalar el poder");
    await waitFor(() => expect(alGuardar).toHaveBeenCalledWith({ poder_manual: { doc_id: "1a-004", pagina: 2 }, nota: "" }));
  });

  it("no envía una página que no existe en el documento", () => {
    const { alGuardar } = montar("poder");
    const pagina = screen.getByLabelText("Página");
    fireEvent.input(pagina, { target: { value: "13" } });
    guardar("Señalar el poder");
    expect(screen.getByRole("alert").textContent).toBe("Indique una página entre 1 y 12.");
    fireEvent.input(pagina, { target: { value: "0" } });
    guardar("Señalar el poder");
    expect(alGuardar).not.toHaveBeenCalled();
  });

  it("si el nombre no aparece en esa página lo dice dentro del diálogo y deja corregir", async () => {
    const { alGuardar, alCerrar } = montar("poder");
    alGuardar.mockRejectedValueOnce(new ErrorApi(422, "El nombre del abogado no aparece en esa página.", "El nombre del abogado no aparece en esa página."));
    // En el navegador, el botón que queda inactivo mientras se envía suelta el foco a <body> (jsdom no lo suelta): se parte de ahí.
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    guardar("Señalar el poder");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("El nombre del abogado no aparece en esa página."));
    expect(alCerrar).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Señalar el poder" }) as HTMLButtonElement).disabled).toBe(false);
    // El foco vuelve a la página, que es lo que hay que corregir, y no queda en <body>, fuera del diálogo.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Página")));
    fireEvent.input(screen.getByLabelText("Página"), { target: { value: "6" } });
    guardar("Señalar el poder");
    await waitFor(() => expect(alCerrar).toHaveBeenCalledOnce());
  });

  it("sin documentos conocidos empieza por «Otro documento…»", () => {
    const ap = abogado();
    ap.poder = { ...ap.poder, evidencia: null, mencion: null };
    montar("poder", { apoderado: ap, documentos: [] });
    expect((screen.getByLabelText("Documento del expediente") as HTMLSelectElement).value).toBe("");
    expect(screen.getByLabelText("Número del documento")).toBeTruthy();
  });
});

describe("DialogoAjuste: escribir la cédula", () => {
  it("envía solo los dígitos y avisa si la tarjeta se va a consultar", async () => {
    const enCola: ApoderadoVista = { ...abogado(), vigencia: { ...abogado().vigencia, fase: "en_cola" } };
    const { alGuardar, alCerrar } = montar("cedula");
    alGuardar.mockResolvedValueOnce(enCola);
    const campo = screen.getByLabelText("Número de cédula") as HTMLInputElement;
    expect(campo.getAttribute("inputmode")).toBe("numeric");
    expect(campo.getAttribute("autocomplete")).toBe("off");
    fireEvent.input(campo, { target: { value: "1.017.234.568" } });
    guardar("Guardar la cédula");
    await waitFor(() => expect(alCerrar).toHaveBeenCalledOnce());
    expect(alGuardar).toHaveBeenCalledWith({ cedula: "1017234568", nota: "" });
    expect(toasts.value.map((t) => t.texto)).toEqual(["Cédula guardada: se consultará la tarjeta de ANDREA PAOLA GIRALDO MONTOYA en la Rama Judicial."]);
  });

  it("valida de 5 a 10 dígitos sin repetir lo escrito en el mensaje", () => {
    const { alGuardar } = montar("cedula");
    const campo = screen.getByLabelText("Número de cédula");
    fireEvent.input(campo, { target: { value: "98765" + "43210" + "1" } });
    guardar("Guardar la cédula");
    expect(alGuardar).not.toHaveBeenCalled();
    const alerta = screen.getByRole("alert");
    expect(alerta.textContent).toBe("La cédula debe tener entre 5 y 10 dígitos.");
    expect(alerta.textContent).not.toContain("98765");
    expect(campo.getAttribute("aria-invalid")).toBe("true");
    expect(campo.getAttribute("aria-describedby")).toBe(alerta.id);
  });

  it("muestra el rechazo del servidor (la cédula ya consta en el expediente)", async () => {
    const { alGuardar } = montar("cedula");
    alGuardar.mockRejectedValueOnce(new ErrorApi(409, "La cédula del abogado consta en el expediente; no se puede cambiar a mano.", ""));
    fireEvent.input(screen.getByLabelText("Número de cédula"), { target: { value: "43000021" } });
    guardar("Guardar la cédula");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("consta en el expediente"));
  });

  it("sin conexión lo explica", async () => {
    const { alGuardar } = montar("cedula");
    alGuardar.mockRejectedValueOnce(new ErrorApi(0, null, "sin red"));
    fireEvent.input(screen.getByLabelText("Número de cédula"), { target: { value: "43000021" } });
    guardar("Guardar la cédula");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/No se pudo conectar con el servidor/));
  });
});
