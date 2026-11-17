import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { useState } from "preact/hooks";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorApi } from "../../api";
import type { ApoderadoVista } from "../../api/contrato";
import { AyudaVigencia, MAX_CERTIFICADO_BYTES, URL_CERTIFICADO_VIGENCIA, validarCertificado } from "./AyudaVigencia";
import { APODERADOS_BORRADOR } from "./mock";

const CEDULA = "71654320";

const necesitaAyuda = APODERADOS_BORRADOR.apoderados.find((a) => a.fase === "necesita_ayuda");
if (!necesitaAyuda) throw new Error("el mock debe traer un apoderado que necesita ayuda");

const apoderado = (cambios: Partial<ApoderadoVista> = {}): ApoderadoVista => ({ ...structuredClone(necesitaAyuda), cedula: CEDULA, ...cambios });

const pdf = (nombre = "certificado.pdf", tipo = "application/pdf") => new File(["%PDF-1.7 sintetico"], nombre, { type: tipo });

function conTamano(archivo: File, bytes: number): File {
  Object.defineProperty(archivo, "size", { value: bytes });
  return archivo;
}

function diferida() {
  let resolver: () => void = () => {};
  let rechazar: (e: unknown) => void = () => {};
  const promesa = new Promise<void>((ok, mal) => {
    resolver = ok;
    rechazar = mal;
  });
  return { promesa, resolver, rechazar };
}

type Props = Partial<Parameters<typeof AyudaVigencia>[0]>;

function montar(props: Props = {}) {
  const alSubir = vi.fn<(archivo: File) => Promise<void>>(async () => undefined);
  const vista = render(<AyudaVigencia apoderado={apoderado()} editable alSubir={alSubir} {...props} />);
  return { alSubir, ...vista };
}

const zona = () => screen.getByRole("group", { name: /Subir el certificado de vigencia/ });
const campo = (contenedor: Element) => contenedor.querySelector<HTMLInputElement>("input[type=file]") as HTMLInputElement;
const elegir = (contenedor: Element, archivo: File) => fireEvent.change(campo(contenedor), { target: { files: [archivo] } });
const arrastre = (archivos: File[] = []) => ({ dataTransfer: { types: ["Files"], items: [], files: archivos } });

function simularPortapapeles(escribir: (texto: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText: escribir }, configurable: true });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("AyudaVigencia: contenido", () => {
  it("explica qué hacer y enlaza a la página oficial en una pestaña nueva y sin referrer", () => {
    montar();
    expect(screen.getByText("Descargue el certificado en la página oficial y súbalo aquí; Judicabot lo lee y lo guarda como evidencia.")).toBeTruthy();
    const enlace = screen.getByRole("link", { name: "Abrir Certificado de vigencia" });
    expect(enlace.getAttribute("href")).toBe("https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx");
    expect(enlace.getAttribute("href")).toBe(URL_CERTIFICADO_VIGENCIA);
    expect(enlace.getAttribute("target")).toBe("_blank");
    expect(enlace.getAttribute("rel")).toBe("noopener noreferrer");
    expect(enlace.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("no ofrece reintentar la consulta automática", () => {
    montar();
    expect(screen.queryByRole("button", { name: /Reintentar/ })).toBeNull();
    expect(screen.queryByText(/Reintentar consulta/)).toBeNull();
  });

  it("la variante compacta usa la misma ayuda con una clase propia para el popover", () => {
    const { container } = montar({ compacta: true });
    expect(container.querySelector(".apo-ayuda.compacta")).not.toBeNull();
    expect(screen.getByRole("button", { name: "o elija un archivo" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Abrir Certificado de vigencia" })).toBeTruthy();
  });

  it("la zona lleva el nombre del abogado para quien navega por grupos", () => {
    montar({ apoderado: apoderado({ nombre: "CARLOS EDUARDO PINEDA RUIZ" }) });
    expect(screen.getByRole("group", { name: "Subir el certificado de vigencia de CARLOS EDUARDO PINEDA RUIZ" })).toBeTruthy();
  });
});

describe("AyudaVigencia: copiar la C.C.", () => {
  it("el botón muestra la cédula enmascarada, pero copia los dígitos completos y lo confirma", async () => {
    const escribir = vi.fn(async (_texto: string) => undefined);
    simularPortapapeles(escribir);
    montar();
    const boton = screen.getByRole("button", { name: "Copiar C.C. 71.•••.•20" });
    expect(document.body.textContent).not.toContain(CEDULA);
    fireEvent.click(boton);
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("C.C. copiada"));
    expect(escribir).toHaveBeenCalledExactlyOnceWith(CEDULA);
  });

  it("copia solo los dígitos aunque la cédula venga con puntos", async () => {
    const escribir = vi.fn(async (_texto: string) => undefined);
    simularPortapapeles(escribir);
    montar({ apoderado: apoderado({ cedula: "71.654.320" }) });
    fireEvent.click(screen.getByRole("button", { name: /Copiar C\.C\./ }));
    await waitFor(() => expect(escribir).toHaveBeenCalledWith(CEDULA));
  });

  it("la confirmación se quita sola a los pocos segundos", async () => {
    vi.useFakeTimers();
    simularPortapapeles(async () => undefined);
    montar();
    fireEvent.click(screen.getByRole("button", { name: /Copiar C\.C\./ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("status").textContent).toContain("C.C. copiada");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("si el navegador no deja copiar lo dice y no deja ver la cédula", async () => {
    simularPortapapeles(async () => {
      throw new DOMException("denegado", "NotAllowedError");
    });
    montar();
    fireEvent.click(screen.getByRole("button", { name: /Copiar C\.C\./ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("No se pudo copiar"));
    expect(document.body.textContent).not.toContain(CEDULA);
  });

  it("si el navegador no tiene portapapeles tampoco falla", async () => {
    montar();
    fireEvent.click(screen.getByRole("button", { name: /Copiar C\.C\./ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("No se pudo copiar"));
  });

  it("sin cédula en el expediente oculta el botón y lo explica", () => {
    montar({ apoderado: apoderado({ cedula: null }) });
    expect(screen.queryByRole("button", { name: /Copiar C\.C\./ })).toBeNull();
    expect(screen.getByText(/No se encontró la C\.C\. del abogado en el expediente/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "o elija un archivo" })).toBeTruthy();
  });
});

describe("AyudaVigencia: elegir un archivo", () => {
  it("el botón visible abre el selector del input oculto, que solo acepta PDF", () => {
    const { container } = montar();
    const entrada = campo(container);
    expect(entrada.getAttribute("accept")).toBe("application/pdf");
    expect(entrada.classList.contains("solo-lectura")).toBe(true);
    expect(entrada.tabIndex).toBe(-1);
    const abrir = vi.spyOn(entrada, "click");
    fireEvent.click(screen.getByRole("button", { name: "o elija un archivo" }));
    expect(abrir).toHaveBeenCalledTimes(1);
  });

  it("entrega el archivo elegido y deja volver a elegir el mismo", () => {
    const { container, alSubir } = montar();
    const archivo = pdf();
    elegir(container, archivo);
    expect(alSubir).toHaveBeenCalledExactlyOnceWith(archivo);
    expect(campo(container).value).toBe("");
  });

  it("mientras lee el certificado muestra el avance y deshabilita todo", async () => {
    const lectura = diferida();
    const { container, alSubir } = montar();
    alSubir.mockReturnValue(lectura.promesa);
    elegir(container, pdf());
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Leyendo el certificado…"));
    expect(container.querySelector(".apo-ayuda-estado .giro")).not.toBeNull();
    expect(zona().getAttribute("aria-busy")).toBe("true");
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(true);
    expect(campo(container).disabled).toBe(true);
    // Una segunda subida no sale mientras la primera sigue en curso.
    elegir(container, pdf("otro.pdf"));
    fireEvent.drop(zona(), arrastre([pdf("otro.pdf")]));
    expect(alSubir).toHaveBeenCalledTimes(1);

    await act(async () => {
      lectura.resolver();
      await lectura.promesa;
    });
    expect(screen.getByRole("status").textContent).toBe("");
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(false);
    expect(campo(container).disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AyudaVigencia: soltar un archivo", () => {
  it("entrega el PDF soltado sobre la zona", () => {
    const { alSubir } = montar();
    const archivo = pdf();
    fireEvent.dragEnter(zona(), arrastre());
    const libre = fireEvent.drop(zona(), arrastre([archivo]));
    expect(libre).toBe(false);
    expect(alSubir).toHaveBeenCalledExactlyOnceWith(archivo);
    expect(zona().classList.contains("arrastrando")).toBe(false);
  });

  it("resalta la zona mientras se arrastra un archivo y mantiene el resalte hasta que salga de todos los hijos", () => {
    montar();
    fireEvent.dragEnter(zona(), arrastre());
    fireEvent.dragEnter(within(zona()).getByText("Arrastre aquí el PDF del certificado"), arrastre());
    expect(zona().classList.contains("arrastrando")).toBe(true);
    fireEvent.dragLeave(zona(), arrastre());
    expect(zona().classList.contains("arrastrando")).toBe(true);
    fireEvent.dragLeave(zona(), arrastre());
    expect(zona().classList.contains("arrastrando")).toBe(false);
  });

  it("ofrece copiar mientras pasa por encima", () => {
    montar();
    const encima = arrastre();
    fireEvent.dragOver(zona(), encima);
    expect(encima.dataTransfer).toMatchObject({ dropEffect: "copy" });
    expect(zona().classList.contains("arrastrando")).toBe(true);
  });

  it("ignora los arrastres que no traen archivos", () => {
    const { alSubir } = montar();
    const texto = { dataTransfer: { types: ["text/plain"], items: [], files: [] } };
    expect(fireEvent.dragEnter(zona(), texto)).toBe(true);
    expect(zona().classList.contains("arrastrando")).toBe(false);
    expect(fireEvent.drop(zona(), texto)).toBe(true);
    expect(alSubir).not.toHaveBeenCalled();
  });

  it("apaga el resalte si el arrastre termina sin eventos de salida", () => {
    vi.useFakeTimers();
    montar();
    act(() => {
      fireEvent.dragEnter(zona(), arrastre());
    });
    expect(zona().classList.contains("arrastrando")).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1600);
    });
    expect(zona().classList.contains("arrastrando")).toBe(false);
  });

  it("ignora lo soltado mientras hay un diálogo modal abierto, sin dejar que el navegador abra el PDF", () => {
    const { alSubir } = montar();
    const dialogo = document.createElement("dialog");
    dialogo.setAttribute("open", "");
    document.body.append(dialogo);
    try {
      fireEvent.dragEnter(zona(), arrastre());
      expect(zona().classList.contains("arrastrando")).toBe(false);
      expect(fireEvent.drop(zona(), arrastre([pdf()]))).toBe(false);
      expect(alSubir).not.toHaveBeenCalled();
    } finally {
      dialogo.remove();
    }
  });

  it("acepta el soltado si el diálogo abierto es el que contiene la ayuda", () => {
    const dialogo = document.createElement("dialog");
    dialogo.setAttribute("open", "");
    document.body.append(dialogo);
    try {
      const alSubir = vi.fn<(archivo: File) => Promise<void>>(async () => undefined);
      render(<AyudaVigencia apoderado={apoderado()} editable alSubir={alSubir} />, { container: dialogo });
      fireEvent.drop(zona(), arrastre([pdf()]));
      expect(alSubir).toHaveBeenCalledTimes(1);
    } finally {
      dialogo.remove();
    }
  });

  it("rechaza más de un archivo y no sube ninguno", () => {
    const { alSubir } = montar();
    fireEvent.drop(zona(), arrastre([pdf("a.pdf"), pdf("b.pdf")]));
    expect(screen.getByRole("alert").textContent).toContain("Suelte un solo archivo");
    expect(alSubir).not.toHaveBeenCalled();
  });

  it("avisa si lo soltado no trae ningún archivo", () => {
    const { alSubir } = montar();
    fireEvent.drop(zona(), arrastre([]));
    expect(screen.getByRole("alert").textContent).toContain("No se recibió ningún archivo");
    expect(alSubir).not.toHaveBeenCalled();
  });
});

describe("AyudaVigencia: comprobaciones antes de subir", () => {
  it("rechaza lo que no es PDF, por tipo y por extensión, sin llamar al servidor", () => {
    const { container, alSubir } = montar();
    elegir(container, pdf("certificado.png", "image/png"));
    expect(screen.getByRole("alert").textContent).toContain("El archivo no es un PDF");
    fireEvent.drop(zona(), arrastre([pdf("notas.txt", "text/plain")]));
    expect(screen.getByRole("alert").textContent).toContain("El archivo no es un PDF");
    expect(alSubir).not.toHaveBeenCalled();
  });

  it("acepta un PDF sin tipo declarado si la extensión lo es, o con tipo PDF y otro nombre", () => {
    expect(validarCertificado({ name: "CERTIFICADO.PDF", type: "", size: 10 })).toBeNull();
    expect(validarCertificado({ name: "descarga", type: "application/pdf", size: 10 })).toBeNull();
  });

  it("rechaza lo que pasa de 2 MiB y acepta exactamente 2 MiB", () => {
    const { container, alSubir } = montar();
    elegir(container, conTamano(pdf(), MAX_CERTIFICADO_BYTES + 1));
    expect(screen.getByRole("alert").textContent).toContain("más de 2 MB");
    expect(alSubir).not.toHaveBeenCalled();
    const justo = conTamano(pdf(), MAX_CERTIFICADO_BYTES);
    elegir(container, justo);
    expect(alSubir).toHaveBeenCalledExactlyOnceWith(justo);
    expect(MAX_CERTIFICADO_BYTES).toBe(2 * 1024 * 1024);
  });

  it("rechaza un archivo vacío", () => {
    const { container, alSubir } = montar();
    elegir(container, conTamano(pdf(), 0));
    expect(screen.getByRole("alert").textContent).toContain("vacío");
    expect(alSubir).not.toHaveBeenCalled();
  });
});

describe("AyudaVigencia: respuesta del servidor", () => {
  it("muestra en un aviso el mensaje del servidor cuando rechaza el certificado", async () => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValue(new ErrorApi(422, "El certificado es de otra persona.", "El certificado es de otra persona."));
    elegir(container, pdf());
    const aviso = await screen.findByRole("alert");
    expect(aviso.textContent).toBe("El certificado es de otra persona.");
    expect(aviso.classList.contains("error")).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("");
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each([
    [413, "El archivo es demasiado grande."],
    [422, "El archivo no es un PDF."],
    [422, "No se pudo leer el certificado."],
    [409, "El caso ya no está esperando la decisión."],
  ])("muestra el detalle de un %i tal como lo escribe el servidor", async (estado, detalle) => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValue(new ErrorApi(estado, detalle, detalle));
    elegir(container, pdf());
    expect((await screen.findByRole("alert")).textContent).toBe(detalle);
  });

  it("si no hay red lo dice con el mensaje de conexión", async () => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValue(new TypeError("Failed to fetch"));
    elegir(container, pdf());
    expect((await screen.findByRole("alert")).textContent).toMatch(/No se pudo conectar con el servidor/);
  });

  it("ante un error desconocido usa un mensaje propio", async () => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValue(new Error("raro"));
    elegir(container, pdf());
    expect((await screen.findByRole("alert")).textContent).toBe("No se pudo subir el certificado.");
  });

  it("devuelve el foco al botón tras un fallo para poder reintentar con el teclado", async () => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValue(new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado."));
    elegir(container, pdf());
    await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "o elija un archivo" })));
  });

  it("una subida que sale bien quita el error de la anterior", async () => {
    const { container, alSubir } = montar();
    alSubir.mockRejectedValueOnce(new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado."));
    elegir(container, pdf());
    expect((await screen.findByRole("alert")).textContent).toBe("No se pudo leer el certificado.");
    alSubir.mockResolvedValueOnce(undefined);
    elegir(container, pdf("corregido.pdf"));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(alSubir).toHaveBeenCalledTimes(2);
  });

  it("un archivo que no pasa las comprobaciones se corrige y el aviso desaparece al subir uno bueno", async () => {
    const { container, alSubir } = montar();
    elegir(container, pdf("foto.jpg", "image/jpeg"));
    expect(screen.getByRole("alert")).toBeTruthy();
    elegir(container, pdf());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(alSubir).toHaveBeenCalledTimes(1);
  });

  it("si el componente se desmonta durante la lectura no falla al terminar", async () => {
    const lectura = diferida();
    const { container, alSubir, unmount } = montar();
    alSubir.mockReturnValue(lectura.promesa);
    elegir(container, pdf());
    unmount();
    await act(async () => {
      lectura.rechazar(new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado."));
      await lectura.promesa.catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AyudaVigencia: cuando el caso ya no admite cambios", () => {
  it("deshabilita todo y explica por qué", () => {
    const { container, alSubir } = montar({ editable: false });
    expect(screen.getByText("El certificado solo se puede subir mientras el caso espera la decisión.")).toBeTruthy();
    const enlace = screen.getByText("Abrir Certificado de vigencia").closest("a");
    expect(enlace?.getAttribute("aria-disabled")).toBe("true");
    expect(enlace?.hasAttribute("href")).toBe(false);
    expect((screen.getByRole("button", { name: /Copiar C\.C\./ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(true);
    expect(campo(container).disabled).toBe(true);
    expect(alSubir).not.toHaveBeenCalled();
  });

  it("no sube nada ni resalta la zona aunque se suelte o se fuerce el cambio del input, pero no deja que el navegador abra el PDF", () => {
    const { container, alSubir } = montar({ editable: false });
    fireEvent.dragEnter(zona(), arrastre());
    expect(zona().classList.contains("arrastrando")).toBe(false);
    const encima = arrastre();
    fireEvent.dragOver(zona(), encima);
    expect(encima.dataTransfer).toMatchObject({ dropEffect: "none" });
    expect(fireEvent.drop(zona(), arrastre([pdf()]))).toBe(false);
    elegir(container, pdf());
    expect(alSubir).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("al volver a ser editable reactiva los controles", () => {
    const { container, rerender, alSubir } = montar({ editable: false });
    rerender(<AyudaVigencia apoderado={apoderado()} editable alSubir={alSubir} />);
    expect(screen.queryByText("El certificado solo se puede subir mientras el caso espera la decisión.")).toBeNull();
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(false);
    expect(campo(container).disabled).toBe(false);
    expect(screen.getByRole("link", { name: "Abrir Certificado de vigencia" }).getAttribute("href")).toBe(URL_CERTIFICADO_VIGENCIA);
  });
});

describe("AyudaVigencia: foco y aviso tras la lectura", () => {
  it("si la ayuda sigue a la vista tras una subida que sale bien, el foco vuelve al botón", async () => {
    const lectura = diferida();
    const { container, alSubir } = montar();
    alSubir.mockReturnValue(lectura.promesa);
    elegir(container, pdf());
    // Como en el navegador cuando el botón se deshabilita: nadie tiene el foco mientras se lee el certificado.
    expect(document.activeElement).toBe(document.body);
    await act(async () => {
      lectura.resolver();
      await lectura.promesa;
    });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "o elija un archivo" })));
  });

  function ConLlamador({ alSubir }: { alSubir?: () => void }) {
    const [necesita, setNecesita] = useState(true);
    return (
      <>
        <h3 id="destino-foco" tabIndex={-1}>
          Título del detalle
        </h3>
        <button type="button">Otro control</button>
        {necesita && (
          <AyudaVigencia
            apoderado={apoderado()}
            editable
            compacta
            alSubir={async () => {
              alSubir?.();
              // Con el resultado, el llamador deja de mostrar la ayuda: la tarjeta ya consta.
              setNecesita(false);
            }}
            destinoFoco={() => document.getElementById("destino-foco")}
          />
        )}
      </>
    );
  }

  it("si la ayuda desaparece con el resultado, el foco va al destino que da el llamador y no queda en <body>", async () => {
    const { container } = render(<ConLlamador />);
    elegir(container, pdf());
    await waitFor(() => expect(container.querySelector(".apo-ayuda")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById("destino-foco")));
  });

  it("no le quita el foco a un control que el usuario eligió mientras se leía el certificado", async () => {
    const { container } = render(<ConLlamador alSubir={() => screen.getByRole("button", { name: "Otro control" }).focus()} />);
    elegir(container, pdf());
    await waitFor(() => expect(container.querySelector(".apo-ayuda")).toBeNull());
    await new Promise((listo) => requestAnimationFrame(() => listo(undefined)));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Otro control" }));
  });

  it("si la subida falla y la ayuda ya no está (se cerró el detalle), no mueve el foco", async () => {
    const lectura = diferida();
    const destino = vi.fn(() => null);
    const alSubir = vi.fn<(archivo: File) => Promise<void>>(() => lectura.promesa);
    const { container, unmount } = render(<AyudaVigencia apoderado={apoderado()} editable alSubir={alSubir} destinoFoco={destino} />);
    elegir(container, pdf());
    unmount();
    await act(async () => {
      lectura.rechazar(new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado."));
      await lectura.promesa.catch(() => undefined);
    });
    await new Promise((listo) => requestAnimationFrame(() => listo(undefined)));
    expect(destino).not.toHaveBeenCalled();
  });

  it("el error de la subida va encima de la zona, donde se mira al soltar o elegir", async () => {
    const { container, alSubir } = montar({ compacta: true });
    alSubir.mockRejectedValue(new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado."));
    elegir(container, pdf());
    const aviso = await screen.findByRole("alert");
    expect(aviso.compareDocumentPosition(zona()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lleva el error a la vista desplazando solo el cuerpo del detalle, no la ventana", async () => {
    const caja = (top: number, alto: number) => ({ top, bottom: top + alto, height: alto, left: 0, right: 300, width: 300, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("bor-pop-cuerpo")) return caja(100, 300);
      if (this.classList.contains("apo-ayuda-error")) return caja(420, 40);
      return caja(0, 0);
    });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const ventana = vi.spyOn(window, "scrollBy").mockImplementation(() => undefined);
    try {
      const cuerpo = document.createElement("div");
      cuerpo.className = "bor-pop-cuerpo";
      document.body.append(cuerpo);
      const alSubir = vi.fn<(archivo: File) => Promise<void>>(async () => {
        throw new ErrorApi(422, "No se pudo leer el certificado.", "No se pudo leer el certificado.");
      });
      const { container } = render(<AyudaVigencia apoderado={apoderado()} editable compacta alSubir={alSubir} />, { container: cuerpo });
      elegir(container, pdf());
      await screen.findByRole("alert");
      await waitFor(() => expect(cuerpo.scrollTop).toBe(460 - 400 + 8));
      expect(scroll).not.toHaveBeenCalled();
      expect(ventana).not.toHaveBeenCalled();
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });
});

describe("AyudaVigencia: reintentar la consulta automática", () => {
  const conReintento = (extra: Props = {}) => {
    const alReintentar = vi.fn<() => Promise<void>>(async () => undefined);
    return { alReintentar, ...montar({ alReintentar, ...extra }) };
  };

  it("cuando la Rama Judicial no respondió lo dice y ofrece reintentar debajo de la zona para soltar", () => {
    const { container } = conReintento({ apoderado: apoderado({ vigencia: { ...apoderado().vigencia, estado: "inaccesible" } }) });
    expect(container.querySelector(".apo-ayuda-texto")?.textContent).toBe(
      "La consulta automática no obtuvo respuesta. Descargue el certificado en la página oficial y súbalo aquí; Judicabot lo lee y lo guarda como evidencia.",
    );
    const boton = screen.getByRole("button", { name: "Reintentar consulta automática" });
    expect(zona().compareDocumentPosition(boton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("mientras se pide lo anuncia y deshabilita la subida; al terminar libera todo", async () => {
    const pedido = diferida();
    const { alReintentar, container } = conReintento();
    alReintentar.mockReturnValue(pedido.promesa);
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta automática" }));
    expect(alReintentar).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Pidiendo la consulta automática…"));
    expect((screen.getByRole("button", { name: "Reintentar consulta automática" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "o elija un archivo" }) as HTMLButtonElement).disabled).toBe(true);
    // Ni otro reintento ni una subida salen mientras tanto.
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta automática" }));
    elegir(container, pdf());
    expect(alReintentar).toHaveBeenCalledOnce();
    await act(async () => {
      pedido.resolver();
      await pedido.promesa;
    });
    expect(screen.getByRole("status").textContent).toBe("");
    expect((screen.getByRole("button", { name: "Reintentar consulta automática" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("si el servidor lo rechaza muestra su detalle", async () => {
    const { alReintentar } = conReintento();
    alReintentar.mockRejectedValue(new ErrorApi(409, "La consulta automática de la vigencia está apagada.", "La consulta automática de la vigencia está apagada."));
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta automática" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("La consulta automática de la vigencia está apagada."));
  });

  it("si con el pedido la ayuda desaparece, el foco va al destino", async () => {
    const destino = document.createElement("button");
    document.body.append(destino);
    function Contenedor() {
      const [visible, setVisible] = useState(true);
      return visible ? (
        <AyudaVigencia
          apoderado={apoderado()}
          editable
          alSubir={async () => undefined}
          alReintentar={async () => setVisible(false)}
          destinoFoco={() => destino}
        />
      ) : null;
    }
    render(<Contenedor />);
    const boton = screen.getByRole("button", { name: "Reintentar consulta automática" });
    boton.focus();
    fireEvent.click(boton);
    await waitFor(() => expect(document.activeElement).toBe(destino));
    destino.remove();
  });

  it("sin edición no se ofrece", () => {
    conReintento({ editable: false });
    expect(screen.queryByRole("button", { name: "Reintentar consulta automática" })).toBeNull();
  });
});
