import { act, render } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApoderadosRespuesta, ApoderadoVista } from "../../api/contrato";
import { toasts } from "../../estado";
import { conRevision, SONDEO_ACTIVO_MS, SONDEO_AYUDA_MS, SONDEO_ERROR_MS } from "./apoderados";
import { APODERADOS_BORRADOR } from "./mock";
import { useApoderados, type EstadoApoderados } from "./useApoderados";

const CASO = "caso-1";
const ID_ROJO = "ap-c47d19e6a8";
const ID_AYUDA = APODERADOS_BORRADOR.apoderados.find((a) => a.vigencia.fase === "necesita_ayuda")?.id ?? "";

let actual: EstadoApoderados;

function Sonda({ caso, alIdentificar }: { caso: string; alIdentificar?: () => void }) {
  actual = useApoderados(caso, alIdentificar);
  return null;
}

const json = (datos: unknown, estado = 200) => new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });

type Respuesta = ApoderadosRespuesta | number | Promise<Response>;

/** Lo que responden los POST (consultar, identificar) y el PUT de ajustes; por omisión, la consulta está apagada. */
interface Escrituras {
  post?: (url: string, cuerpo: unknown) => Response | Promise<Response>;
  ajuste?: (cuerpo: unknown) => Response | Promise<Response>;
}

const APAGADA = "La consulta automática de la vigencia está apagada en esta instalación.";

function red(
  lecturas: Respuesta[],
  revision?: (cuerpo: { revisado: boolean }) => Response | Promise<Response>,
  subida?: (cuerpo: FormData) => Response | Promise<Response>,
  { post, ajuste }: Escrituras = {},
) {
  const llamadas: { url: string; metodo: string; cuerpo: unknown; cabeceras: unknown }[] = [];
  let n = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const metodo = init.method ?? "GET";
      const cuerpo: unknown = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
      llamadas.push({ url, metodo, cuerpo, cabeceras: init.headers });
      if (metodo === "POST") return post ? post(url, cuerpo) : json({ detail: APAGADA }, 409);
      if (metodo === "PUT" && url.endsWith("/ajustes")) return ajuste ? ajuste(cuerpo) : json({ detail: "no" }, 404);
      if (metodo === "PUT" && url.endsWith("/certificado")) return subida ? subida(cuerpo as FormData) : json({ detail: "no" }, 404);
      if (metodo === "PUT") return revision ? revision(cuerpo as { revisado: boolean }) : json({ detail: "no" }, 404);
      const r = lecturas[Math.min(n, lecturas.length - 1)] as Respuesta;
      n += 1;
      if (typeof r === "number") return json({ detail: `Error ${r}` }, r);
      return r instanceof Promise ? r : json(r);
    }),
  );
  return {
    lecturas: () => llamadas.filter((l) => l.metodo === "GET").length,
    posts: () => llamadas.filter((l) => l.metodo === "POST"),
    llamadas,
  };
}

function diferida() {
  let liberar: (r: Response) => void = () => {};
  const promesa = new Promise<Response>((ok) => {
    liberar = ok;
  });
  return { promesa, liberar };
}

const base = (): ApoderadosRespuesta => structuredClone(APODERADOS_BORRADOR);
const listos = (): ApoderadosRespuesta => {
  const d = base();
  d.apoderados = d.apoderados.map((a) => ({ ...a, fase: "listo", vigencia: { ...a.vigencia, fase: "listo" } }));
  return d;
};
const activos = (): ApoderadosRespuesta => ({ ...listos(), consulta: { ...base().consulta, activa: true } });
const rojo = (d: ApoderadosRespuesta | null): ApoderadoVista | undefined => d?.apoderados.find((a) => a.id === ID_ROJO);
const ayuda = (d: ApoderadosRespuesta | null): ApoderadoVista | undefined => d?.apoderados.find((a) => a.id === ID_AYUDA);
const certificado = (nombre = "CV_RNA-TPA_71654320.pdf") => new File(["%PDF-1.7 sintetico"], nombre, { type: "application/pdf" });
const conCertificado = (a: ApoderadoVista): ApoderadoVista => ({
  ...a,
  estado: "verificado",
  fase: "listo",
  motivos: [],
  bloquea: false,
  huella: "con-certificado",
  vigencia: {
    ...a.vigencia,
    estado: "vigente",
    fase: "listo",
    origen: "manual",
    certificado_url: `/api/casos/${CASO}/apoderados/${a.id}/certificado`,
  },
});
const esperar = (ms = 0) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useApoderados: lectura y sondeo", () => {
  it("lee al montar, vuelve a leer cada 3 s mientras hay consultas en curso y para cuando terminan", async () => {
    const { lecturas, llamadas } = red([activos(), activos(), listos()]);
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(llamadas[0]?.url).toBe(`/api/casos/${CASO}/apoderados`);
    expect(lecturas()).toBe(1);
    expect(actual.datos?.consulta.activa).toBe(true);
    await esperar(SONDEO_ACTIVO_MS - 1);
    expect(lecturas()).toBe(1);
    await esperar(1);
    expect(lecturas()).toBe(2);
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(3);
    await esperar(60_000);
    expect(lecturas()).toBe(3);
    expect(actual.datos?.consulta.activa).toBe(false);
  });

  it("lee cada 15 s mientras alguien necesita ayuda y la extensión no está conectada", async () => {
    const { lecturas } = red([base()]);
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(lecturas()).toBe(1);
    await esperar(SONDEO_AYUDA_MS - 1);
    expect(lecturas()).toBe(1);
    await esperar(1);
    expect(lecturas()).toBe(2);
  });

  it("tras un error conserva lo último leído y reintenta a los 30 s", async () => {
    const { lecturas } = red([base(), 500, listos()]);
    render(<Sonda caso={CASO} />);
    await esperar();
    await esperar(SONDEO_AYUDA_MS);
    expect(lecturas()).toBe(2);
    expect(actual.error).toBe("Error 500");
    expect(actual.datos?.apoderados).toHaveLength(3);
    await esperar(SONDEO_ERROR_MS - 1);
    expect(lecturas()).toBe(2);
    await esperar(1);
    expect(lecturas()).toBe(3);
    expect(actual.error).toBeNull();
  });

  it("recargar lee de inmediato y desmontar detiene el sondeo", async () => {
    const { lecturas } = red([base()]);
    const { unmount } = render(<Sonda caso={CASO} />);
    await esperar();
    act(() => actual.recargar());
    await esperar();
    expect(lecturas()).toBe(2);
    unmount();
    await esperar(SONDEO_ERROR_MS * 2);
    expect(lecturas()).toBe(2);
  });
});

describe("useApoderados: revisión", () => {
  it("marca al instante, envía el PUT y adopta la respuesta del servidor", async () => {
    const put = diferida();
    const { llamadas } = red([listos()], () => put.promesa);
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(actual.datos?.bloquea_decision).toBe(true);
    act(() => actual.revisar(ID_ROJO, true));
    expect(rojo(actual.datos)).toMatchObject({ revisado: true, bloquea: false });
    expect(actual.datos?.bloquea_decision).toBe(false);
    const envio = llamadas.find((l) => l.metodo === "PUT");
    expect(envio?.url).toBe(`/api/casos/${CASO}/apoderados/${ID_ROJO}/revision`);
    const original = rojo(base());
    if (!original) throw new Error("falta el apoderado");
    expect(envio?.cuerpo).toEqual({ revisado: true, nota: "", huella: original.huella });
    put.liberar(json({ ...conRevision(original, true), huella: "nueva" }));
    await esperar();
    expect(rojo(actual.datos)).toMatchObject({ revisado: true, huella: "nueva" });
    expect(actual.datos?.bloquea_decision).toBe(false);
    expect(actual.errorRevision).toBeNull();
  });

  it("los clics seguidos sobre un apoderado salen de a uno, en orden, y queda lo del último", async () => {
    const original = rojo(base());
    if (!original) throw new Error("falta el apoderado");
    const envios = [diferida(), diferida(), diferida()];
    let n = 0;
    const { llamadas } = red([listos()], () => (envios[n++] as ReturnType<typeof diferida>).promesa);
    const puts = () => llamadas.filter((l) => l.metodo === "PUT").map((l) => (l.cuerpo as { revisado: boolean }).revisado);
    render(<Sonda caso={CASO} />);
    await esperar();

    act(() => actual.revisar(ID_ROJO, true));
    act(() => actual.revisar(ID_ROJO, false));
    act(() => actual.revisar(ID_ROJO, true));
    await esperar();
    expect(puts()).toEqual([true]);
    expect(rojo(actual.datos)).toMatchObject({ revisado: true, bloquea: false });

    envios[0]?.liberar(json(conRevision(original, true)));
    await esperar();
    expect(puts()).toEqual([true, false]);
    envios[1]?.liberar(json(conRevision(original, false)));
    await esperar();
    expect(puts()).toEqual([true, false, true]);
    // Las respuestas de los clics ya superados no se aplican: sigue la marca optimista del último.
    expect(rojo(actual.datos)).toMatchObject({ revisado: true, bloquea: false });
    envios[2]?.liberar(json({ ...conRevision(original, true), huella: "del-servidor" }));
    await esperar();
    expect(rojo(actual.datos)).toMatchObject({ revisado: true, bloquea: false, huella: "del-servidor" });
    expect(llamadas.filter((l) => l.metodo === "PUT").every((l) => (l.cuerpo as { huella: string }).huella === original.huella)).toBe(true);
  });

  it("si el PUT falla revierte la marca, informa el motivo y vuelve a leer", async () => {
    const { lecturas } = red([listos()], () => json({ detail: "El caso no está esperando la decisión." }, 409));
    render(<Sonda caso={CASO} />);
    await esperar();
    act(() => actual.revisar(ID_ROJO, true));
    await esperar();
    expect(rojo(actual.datos)).toMatchObject({ revisado: false, bloquea: true });
    expect(actual.datos?.bloquea_decision).toBe(true);
    expect(actual.errorRevision).toBe("El caso no está esperando la decisión.");
    expect(lecturas()).toBe(2);
  });

  it("descarta una lectura que empezó antes de que terminara la revisión y vuelve a leer", async () => {
    const vieja = diferida();
    const revisado = listos();
    revisado.apoderados = revisado.apoderados.map((a) => (a.id === ID_ROJO ? conRevision(a, true) : a));
    revisado.bloquea_decision = false;
    const { lecturas } = red([activos(), vieja.promesa, revisado], (c) => {
      const original = rojo(base());
      if (!original) throw new Error("falta el apoderado");
      return json(conRevision(original, c.revisado));
    });
    render(<Sonda caso={CASO} />);
    await esperar();
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(2);
    act(() => actual.revisar(ID_ROJO, true));
    await esperar();
    expect(rojo(actual.datos)?.revisado).toBe(true);
    vieja.liberar(json(activos()));
    await esperar();
    expect(rojo(actual.datos)?.revisado).toBe(true);
    expect(actual.datos?.bloquea_decision).toBe(false);
    expect(lecturas()).toBe(3);
  });
});

describe("useApoderados: subir el certificado", () => {
  it("envía el PDF como FormData con el campo archivo a la ruta del apoderado, sin fijar el Content-Type", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const { llamadas } = red([listos()], undefined, () => json(conCertificado(original)));
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.subir(ID_AYUDA, certificado());
    });
    const envio = llamadas.find((l) => l.metodo === "PUT");
    expect(envio?.url).toBe(`/api/casos/${CASO}/apoderados/${ID_AYUDA}/certificado`);
    expect(envio?.cuerpo).toBeInstanceOf(FormData);
    const archivo = (envio?.cuerpo as FormData).get("archivo");
    expect(archivo).toBeInstanceOf(File);
    expect(await (archivo as File).text()).toBe("%PDF-1.7 sintetico");
    expect(Array.from((envio?.cuerpo as FormData).keys())).toEqual(["archivo"]);
    // El navegador pone el multipart con su frontera: el cliente no debe fijar el tipo.
    expect(Object.keys(envio?.cabeceras as Record<string, string>).map((k) => k.toLowerCase())).not.toContain("content-type");
  });

  it("no manda al servidor el nombre original del archivo, que suele llevar la cédula", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const { llamadas } = red([listos()], undefined, () => json(conCertificado(original)));
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.subir(ID_AYUDA, certificado("CV_RNA-TPA_71654320.pdf"));
    });
    const archivo = ((llamadas.find((l) => l.metodo === "PUT")?.cuerpo as FormData).get("archivo")) as File;
    expect(archivo.name).toBe("certificado.pdf");
    expect(JSON.stringify(llamadas.map((l) => l.url))).not.toContain("71654320");
  });

  it("al terminar reemplaza solo a ese apoderado y recalcula si algo bloquea la decisión", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const subida = diferida();
    red([listos()], undefined, () => subida.promesa);
    render(<Sonda caso={CASO} />);
    await esperar();
    const antes = listos();
    let terminada = false;
    act(() => {
      void actual.subir(ID_AYUDA, certificado()).then(() => {
        terminada = true;
      });
    });
    await esperar();
    expect(terminada).toBe(false);
    expect(ayuda(actual.datos)).toEqual(ayuda(antes));
    subida.liberar(json(conCertificado(original)));
    await esperar();
    expect(terminada).toBe(true);
    expect(ayuda(actual.datos)).toMatchObject({ estado: "verificado", bloquea: false, huella: "con-certificado" });
    expect(ayuda(actual.datos)?.vigencia).toMatchObject({ estado: "vigente", origen: "manual", certificado_url: `/api/casos/${CASO}/apoderados/${ID_AYUDA}/certificado` });
    expect(rojo(actual.datos)).toEqual(rojo(antes));
    expect(actual.datos?.apoderados).toHaveLength(antes.apoderados.length);
    expect(actual.datos?.bloquea_decision).toBe(true);
    expect(actual.errorRevision).toBeNull();
  });

  it("anuncia el resultado en un aviso de la página, que sobrevive aunque la ayuda desaparezca", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    toasts.value = [];
    red([listos()], undefined, () => json(conCertificado(original)));
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.subir(ID_AYUDA, certificado());
    });
    expect(toasts.value.map(({ texto, tipo }) => ({ texto, tipo }))).toEqual([
      { texto: `Certificado leído: la tarjeta profesional de ${original.nombre} está vigente.`, tipo: "ok" },
    ]);
    toasts.value = [];
  });

  it("si el servidor rechaza el certificado no anuncia nada: el error lo muestra la ayuda", async () => {
    toasts.value = [];
    red([listos()], undefined, () => json({ detail: "El certificado es de otra persona." }, 422));
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await expect(actual.subir(ID_AYUDA, certificado())).rejects.toThrow("El certificado es de otra persona.");
    });
    expect(toasts.value).toEqual([]);
  });

  it("si lo subido desbloquea el último apoderado bloqueante, la decisión deja de estar bloqueada", async () => {
    const original = rojo(base());
    if (!original) throw new Error("falta el apoderado rojo");
    red([listos()], undefined, () => json({ ...conCertificado(original), estado: "verificado", bloquea: false }));
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(actual.datos?.bloquea_decision).toBe(true);
    await act(async () => {
      await actual.subir(ID_ROJO, certificado());
    });
    expect(rojo(actual.datos)).toMatchObject({ estado: "verificado", bloquea: false });
    expect(actual.datos?.bloquea_decision).toBe(false);
  });

  it("si el servidor lo rechaza lanza un error con su detalle y deja el estado como estaba", async () => {
    red([listos()], undefined, () => json({ detail: "El certificado es de otra persona." }, 422));
    render(<Sonda caso={CASO} />);
    await esperar();
    const antes = actual.datos;
    await act(async () => {
      await expect(actual.subir(ID_AYUDA, certificado())).rejects.toMatchObject({
        name: "ErrorApi",
        estado: 422,
        message: "El certificado es de otra persona.",
      });
    });
    expect(actual.datos).toEqual(antes);
    expect(actual.error).toBeNull();
    expect(actual.errorRevision).toBeNull();
  });

  it.each([
    [413, "El archivo es demasiado grande."],
    [409, "El caso no está esperando la decisión."],
    [404, "Apoderado no encontrado."],
  ])("lanza el detalle de un %i tal cual", async (estado, detalle) => {
    red([listos()], undefined, () => json({ detail: detalle }, estado));
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await expect(actual.subir(ID_AYUDA, certificado())).rejects.toThrow(detalle);
    });
  });

  it("si no hay red lanza el error de conexión", async () => {
    red([listos()]);
    render(<Sonda caso={CASO} />);
    await esperar();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await act(async () => {
      await expect(actual.subir(ID_AYUDA, certificado())).rejects.toMatchObject({ estado: 0 });
    });
  });

  it("descarta una lectura que salió antes de que el servidor guardara el certificado y vuelve a leer", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const vieja = diferida();
    const despues = listos();
    despues.apoderados = despues.apoderados.map((a) => (a.id === ID_AYUDA ? conCertificado(a) : a));
    const { lecturas } = red([activos(), vieja.promesa, despues], undefined, () => json(conCertificado(original)));
    render(<Sonda caso={CASO} />);
    await esperar();
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(2);
    await act(async () => {
      await actual.subir(ID_AYUDA, certificado());
    });
    expect(ayuda(actual.datos)?.estado).toBe("verificado");
    vieja.liberar(json(activos()));
    await esperar();
    expect(ayuda(actual.datos)?.estado).toBe("verificado");
    expect(lecturas()).toBe(3);
    expect(actual.datos?.consulta.activa).toBe(false);
  });

  it("no aplica la respuesta al estado de otro caso si se cambió de caso durante la subida", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const subida = diferida();
    red([listos()], undefined, () => subida.promesa);
    const { rerender } = render(<Sonda caso={CASO} />);
    await esperar();
    let terminada = false;
    act(() => {
      void actual.subir(ID_AYUDA, certificado()).then(() => {
        terminada = true;
      });
    });
    rerender(<Sonda caso="caso-2" />);
    await esperar();
    expect(ayuda(actual.datos)?.estado).toBe("revisar");
    subida.liberar(json(conCertificado(original)));
    await esperar();
    expect(terminada).toBe(true);
    expect(ayuda(actual.datos)?.estado).toBe("revisar");
  });

  it("deja intacto el comportamiento de revisar: una revisión posterior a la subida sigue enviándose con la huella nueva", async () => {
    const original = ayuda(base());
    if (!original) throw new Error("falta el apoderado que necesita ayuda");
    const { llamadas } = red(
      [listos()],
      (c) => json({ ...conRevision(conCertificado(original), c.revisado), huella: "revisado" }),
      () => json({ ...conCertificado(original), estado: "revisar", bloquea: false, huella: "tras-subir" }),
    );
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.subir(ID_AYUDA, certificado());
    });
    act(() => actual.revisar(ID_AYUDA, true));
    await esperar();
    const revision = llamadas.find((l) => l.url.endsWith("/revision"));
    expect(revision?.cuerpo).toEqual({ revisado: true, nota: "", huella: "tras-subir" });
    expect(ayuda(actual.datos)).toMatchObject({ revisado: true, huella: "revisado" });
  });
});

const enCola = (d: ApoderadosRespuesta = base()): ApoderadosRespuesta => ({
  ...d,
  consulta: { ...d.consulta, activa: true, extension: "conectada" },
  apoderados: d.apoderados.map((a) => (a.id === ID_AYUDA ? { ...a, fase: "en_cola", vigencia: { ...a.vigencia, fase: "en_cola" } } : a)),
});

describe("useApoderados: consulta automática", () => {
  it("al abrir pide una sola vez la consulta de quien sigue sin consultar y sigue la cola cada 3 s", async () => {
    const { posts, lecturas } = red([base(), enCola(), listos()], undefined, undefined, { post: () => json(enCola(), 202) });
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(posts().map((p) => [p.url, p.cuerpo])).toEqual([[`/api/casos/${CASO}/apoderados/consultar`, { forzar: false }]]);
    expect(ayuda(actual.datos)?.vigencia.fase).toBe("en_cola");
    expect(actual.datos?.consulta.activa).toBe(true);
    expect(lecturas()).toBe(1);
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(2);
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(3);
    expect(actual.datos?.consulta.activa).toBe(false);
    await esperar(SONDEO_AYUDA_MS * 4);
    expect(lecturas()).toBe(3);
    expect(posts()).toHaveLength(1);
  });

  it("no la vuelve a pedir en las lecturas siguientes ni al recargar", async () => {
    const { posts } = red([base()]);
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(posts()).toHaveLength(1);
    await esperar(SONDEO_AYUDA_MS * 3);
    act(() => actual.recargar());
    await esperar();
    expect(posts()).toHaveLength(1);
    // Que el servidor la rechace (apagada) no es un error de la pestaña: la ayuda para subir el certificado ya está.
    expect(actual.error).toBeNull();
    expect(actual.datos?.apoderados).toHaveLength(3);
  });

  it.each([
    ["la consulta está apagada", (d: ApoderadosRespuesta) => (d.consulta.modo = "apagada")],
    ["ya hay consultas en curso", (d: ApoderadosRespuesta) => (d.consulta.activa = true)],
    ["el caso no admite cambios", (d: ApoderadosRespuesta) => (d.editable = false)],
    ["nadie está sin consultar", (d: ApoderadosRespuesta) => (d.apoderados = d.apoderados.filter((a) => a.vigencia.estado !== "sin_consultar"))],
  ])("no la pide si %s", async (_, cambiar) => {
    const d = base();
    cambiar(d);
    const { posts } = red([d]);
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(posts()).toEqual([]);
  });

  it("vuelve a pedirla al cambiar de caso", async () => {
    const { posts } = red([base()]);
    const { rerender } = render(<Sonda caso={CASO} />);
    await esperar();
    rerender(<Sonda caso="caso-2" />);
    await esperar();
    expect(posts().map((p) => p.url)).toEqual([`/api/casos/${CASO}/apoderados/consultar`, "/api/casos/caso-2/apoderados/consultar"]);
  });

  it("«Reintentar consulta automática» fuerza la de ese abogado, adopta la respuesta y sigue la cola", async () => {
    // La Rama Judicial no respondió: necesita ayuda, pero ya se consultó (no se pide sola al abrir).
    const sinRespuesta = listos();
    sinRespuesta.apoderados = sinRespuesta.apoderados.map((a) =>
      a.id === ID_AYUDA ? { ...a, fase: "necesita_ayuda", vigencia: { ...a.vigencia, estado: "inaccesible", fase: "necesita_ayuda" } } : a,
    );
    const { posts, lecturas } = red([sinRespuesta, sinRespuesta], undefined, undefined, { post: () => json(enCola(listos()), 202) });
    render(<Sonda caso={CASO} />);
    await esperar();
    expect(posts()).toEqual([]);
    await act(async () => {
      await actual.consultar([ID_AYUDA], true);
    });
    expect(posts().map((p) => p.cuerpo)).toEqual([{ ids: [ID_AYUDA], forzar: true }]);
    expect(ayuda(actual.datos)?.vigencia.fase).toBe("en_cola");
    const antes = lecturas();
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(antes + 1);
  });

  it("si el servidor rechaza el reintento lanza su detalle y deja el estado como estaba", async () => {
    red([listos()], undefined, undefined, { post: () => json({ detail: APAGADA }, 409) });
    render(<Sonda caso={CASO} />);
    await esperar();
    const antes = actual.datos;
    await act(async () => {
      await expect(actual.consultar([ID_AYUDA], true)).rejects.toMatchObject({ estado: 409, message: APAGADA });
    });
    expect(actual.datos).toEqual(antes);
    expect(actual.error).toBeNull();
  });

  it("descarta una lectura que salió antes de que la cola aceptara la consulta", async () => {
    const vieja = diferida();
    const { lecturas } = red([listos(), vieja.promesa, enCola(listos())], undefined, undefined, { post: () => json(enCola(listos()), 202) });
    render(<Sonda caso={CASO} />);
    await esperar();
    act(() => actual.recargar());
    await act(async () => {
      await actual.consultar([ID_AYUDA], true);
    });
    vieja.liberar(json(listos()));
    await esperar();
    expect(ayuda(actual.datos)?.vigencia.fase).toBe("en_cola");
    expect(lecturas()).toBe(3);
  });
});

describe("useApoderados: correcciones a mano", () => {
  it("envía el ajuste a la ruta del abogado, adopta la respuesta y vuelve a leer enseguida", async () => {
    const original = rojo(base());
    if (!original) throw new Error("falta el apoderado");
    const corregido: ApoderadoVista = { ...original, estado: "revisar", bloquea: false, poder: { ...original.poder, estado: "descartado", evidencia: null } };
    const { llamadas, lecturas } = red([listos()], undefined, undefined, { ajuste: () => json(corregido) });
    render(<Sonda caso={CASO} />);
    await esperar();
    let devuelto: ApoderadoVista | null = null;
    await act(async () => {
      devuelto = await actual.ajustar(ID_ROJO, { poder_descartado: true, nota: "Es de otro proceso." });
    });
    const envio = llamadas.find((l) => l.url.endsWith("/ajustes"));
    expect(envio).toMatchObject({ url: `/api/casos/${CASO}/apoderados/${ID_ROJO}/ajustes`, metodo: "PUT", cuerpo: { poder_descartado: true, nota: "Es de otro proceso." } });
    expect(devuelto).toEqual(corregido);
    expect(rojo(actual.datos)?.poder.estado).toBe("descartado");
    expect(actual.datos?.bloquea_decision).toBe(false);
    await esperar();
    expect(lecturas()).toBe(2);
  });

  it("si el servidor rechaza la corrección lanza su detalle sin tocar el estado", async () => {
    red([listos()], undefined, undefined, { ajuste: () => json({ detail: "El nombre del abogado no aparece en esa página." }, 422) });
    render(<Sonda caso={CASO} />);
    await esperar();
    const antes = actual.datos;
    await act(async () => {
      await expect(actual.ajustar(ID_ROJO, { poder_manual: { doc_id: "1a-011", pagina: 2 } })).rejects.toMatchObject({
        estado: 422,
        message: "El nombre del abogado no aparece en esa página.",
      });
    });
    expect(actual.datos).toEqual(antes);
  });
});

describe("useApoderados: identificar un caso anterior", () => {
  const sinIdentificar = (editable = true): ApoderadosRespuesta => ({
    ...listos(),
    identificacion: "no_disponible",
    apoderados: [],
    sin_apoderado: [],
    bloquea_decision: false,
    editable,
  });

  it("pide la identificación, la sigue cada 3 s mientras el trabajo corre y al terminar avisa una vez", async () => {
    const alIdentificar = vi.fn();
    const { posts, lecturas } = red([sinIdentificar(), sinIdentificar(false), listos()], undefined, undefined, {
      post: () => json(sinIdentificar(false), 202),
    });
    render(<Sonda caso={CASO} alIdentificar={alIdentificar} />);
    await esperar();
    await act(async () => {
      await actual.identificar();
    });
    expect(posts().map((p) => p.url)).toEqual([`/api/casos/${CASO}/apoderados/identificar`]);
    expect(actual.identificando).toBe(true);
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(2);
    expect(actual.identificando).toBe(true);
    await esperar(SONDEO_ACTIVO_MS);
    expect(lecturas()).toBe(3);
    expect(actual.identificando).toBe(false);
    expect(actual.datos?.identificacion).toBe("lista");
    expect(alIdentificar).toHaveBeenCalledOnce();
    expect(actual.errorIdentificacion).toBeNull();
    await esperar(SONDEO_AYUDA_MS * 4);
    expect(alIdentificar).toHaveBeenCalledOnce();
  });

  it("con el simulacro (?consulta=sin_identificar) la identificación termina con los abogados y sin error", async () => {
    const { resolverMock } = await import("../../api/mock");
    const { reiniciarApoderadosMock, CASO_MOCK_BORRADOR } = await import("./mock");
    history.replaceState(null, "", "/?consulta=sin_identificar");
    reiniciarApoderadosMock();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const cuerpo: unknown = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
        try {
          const datos = await resolverMock({ metodo: (init.method ?? "GET") as "GET" | "POST" | "PUT", ruta: url, cuerpo });
          return json(datos, init.method === "POST" ? 202 : 200);
        } catch (e) {
          const estado = (e as { estado?: number }).estado ?? 500;
          return json({ detail: (e as Error).message }, estado);
        }
      }),
    );
    try {
      const alIdentificar = vi.fn();
      render(<Sonda caso={CASO_MOCK_BORRADOR} alIdentificar={alIdentificar} />);
      await esperar();
      expect(actual.datos?.identificacion).toBe("no_disponible");
      await act(async () => {
        await actual.identificar();
      });
      expect(actual.identificando).toBe(true);
      for (let i = 0; i < 3 && actual.identificando; i += 1) await esperar(SONDEO_ACTIVO_MS);
      expect(actual.identificando).toBe(false);
      expect(actual.errorIdentificacion).toBeNull();
      expect(actual.datos).toMatchObject({ identificacion: "lista", editable: true });
      expect(actual.datos?.apoderados).toHaveLength(3);
      expect(alIdentificar).toHaveBeenCalledOnce();
    } finally {
      history.replaceState(null, "", "/");
      reiniciarApoderadosMock();
    }
  });

  it("si ya estaban identificados (200) avisa enseguida, sin sondear", async () => {
    const alIdentificar = vi.fn();
    const { lecturas } = red([sinIdentificar()], undefined, undefined, { post: () => json(listos()) });
    render(<Sonda caso={CASO} alIdentificar={alIdentificar} />);
    await esperar();
    await act(async () => {
      await actual.identificar();
    });
    expect(actual.identificando).toBe(false);
    expect(alIdentificar).toHaveBeenCalledOnce();
    await esperar(SONDEO_ACTIVO_MS * 3);
    expect(lecturas()).toBe(1);
  });

  it("si el servidor la rechaza muestra su detalle y deja intentarlo de nuevo", async () => {
    const { posts } = red([sinIdentificar()], undefined, undefined, { post: () => json({ detail: "Ya hay una ejecución en curso para este caso." }, 409) });
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.identificar();
    });
    expect(actual.identificando).toBe(false);
    expect(actual.errorIdentificacion).toBe("Ya hay una ejecución en curso para este caso.");
    await act(async () => {
      await actual.identificar();
    });
    expect(posts()).toHaveLength(2);
  });

  it("si el trabajo termina sin identificación lo dice; si falla, la pestaña muestra la identificación fallida", async () => {
    const alIdentificar = vi.fn();
    red([sinIdentificar(), sinIdentificar()], undefined, undefined, { post: () => json(sinIdentificar(false), 202) });
    render(<Sonda caso={CASO} alIdentificar={alIdentificar} />);
    await esperar();
    await act(async () => {
      await actual.identificar();
    });
    await esperar(SONDEO_ACTIVO_MS);
    expect(actual.identificando).toBe(false);
    expect(actual.errorIdentificacion).toBe("No se pudieron identificar los apoderados; inténtelo de nuevo.");
    expect(alIdentificar).not.toHaveBeenCalled();
  });

  it("deja de esperar si el trabajo no termina en 15 minutos", async () => {
    const { lecturas } = red([sinIdentificar(), sinIdentificar(false)], undefined, undefined, { post: () => json(sinIdentificar(false), 202) });
    render(<Sonda caso={CASO} />);
    await esperar();
    await act(async () => {
      await actual.identificar();
    });
    await esperar(15 * 60_000 + SONDEO_ACTIVO_MS);
    expect(actual.identificando).toBe(false);
    expect(actual.errorIdentificacion).toMatch(/tarda más de lo esperado/);
    const despues = lecturas();
    await esperar(SONDEO_ACTIVO_MS * 5);
    expect(lecturas()).toBe(despues);
  });
});
