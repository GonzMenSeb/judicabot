import { describe, expect, it } from "vitest";
import type { ApoderadosRespuesta, ApoderadoVista, PaginaExpediente } from "./contrato";
import { agregarMocks, resolverMock } from "./mock";
import type { MockRuta } from "./mock";

const peticion = (metodo: "GET" | "POST", ruta: string, cuerpo: unknown = undefined) => ({ metodo, ruta, cuerpo });
// Como en el cliente, que llama a resolverMock dentro de una función asíncrona: un manejador que lanza da una promesa rechazada.
const poner = async (ruta: string, cuerpo: unknown) => resolverMock({ metodo: "PUT", ruta, cuerpo });

describe("mocks", () => {
  it("incluye el estado del servidor por defecto", async () => {
    const respuesta = (await resolverMock(peticion("GET", "/api/estado-servidor"))) as { proveedor: string; modelos: string[]; modelos_gemini: string[] };
    expect(respuesta.modelos).toContain("claude-sonnet-5-5");
    expect(respuesta.proveedor).toBe("anthropic");
    expect(respuesta.modelos_gemini).toContain("gemini-4-argon");
  });

  it("empareja rutas de texto exactas con o sin consulta y respeta el método", async () => {
    agregarMocks([{ metodo: "GET", ruta: "/api/prueba-a", respuesta: { a: 1 } }]);
    expect(await resolverMock(peticion("GET", "/api/prueba-a"))).toEqual({ a: 1 });
    expect(await resolverMock(peticion("GET", "/api/prueba-a?x=1"))).toEqual({ a: 1 });
    expect(resolverMock(peticion("POST", "/api/prueba-a"))).toBeNull();
    expect(resolverMock(peticion("GET", "/api/prueba-a/otra"))).toBeNull();
  });

  it("empareja expresiones regulares y pasa la petición al manejador", async () => {
    const mock: MockRuta = {
      metodo: "POST",
      ruta: /^\/api\/prueba-regex\/([^/]+)\/run$/,
      respuesta: (p) => ({ ruta: p.ruta, cuerpo: p.cuerpo }),
    };
    agregarMocks([mock]);
    expect(await resolverMock(peticion("POST", "/api/prueba-regex/c1/run", { cmd: "nuevo" }))).toEqual({
      ruta: "/api/prueba-regex/c1/run",
      cuerpo: { cmd: "nuevo" },
    });
  });

  it("resuelve el resumen de cada caso de demostración y deja pasar los desconocidos", async () => {
    const lista = (await resolverMock(peticion("GET", "/api/casos"))) as { id: string }[];
    const ids = [...lista.map((c) => c.id), "quintero-eps-horizonte", "sin-fallo"];
    for (const id of ids) {
      const resumen = (await resolverMock(peticion("GET", `/api/casos/${id}/resumen`))) as { id: string; nombre: string; etapa: number };
      expect(resumen.id).toBe(id);
      expect(resumen.nombre).toBeTruthy();
      expect(resumen.etapa).toBeGreaterThanOrEqual(0);
    }
    expect(resolverMock(peticion("GET", "/api/casos/no-existe/resumen"))).toBeNull();
  });

  it("los apoderados con un abogado que bloquea son solo del caso del borrador; los demás casos no se bloquean", async () => {
    const { CASO_MOCK_BORRADOR } = await import("../vistas/borrador/mock");
    const delBorrador = (await resolverMock(peticion("GET", `/api/casos/${CASO_MOCK_BORRADOR}/apoderados`))) as ApoderadosRespuesta;
    expect(delBorrador.bloquea_decision).toBe(true);
    for (const otro of ["quintero-bedoya", "demo-sin-leer"]) {
      const respuesta = (await resolverMock(peticion("GET", `/api/casos/${otro}/apoderados`))) as ApoderadosRespuesta;
      expect(respuesta).toMatchObject({ identificacion: "no_disponible", apoderados: [], bloquea_decision: false });
    }
    await expect(poner("/api/casos/quintero-bedoya/apoderados/ap-c47d19e6a8/revision", { revisado: false })).rejects.toMatchObject({ estado: 404 });
  });

  it("el mock rechaza marcar revisado con la huella de otro estado, como el servidor", async () => {
    const { CASO_MOCK_BORRADOR, APODERADOS_BORRADOR } = await import("../vistas/borrador/mock");
    const [rojo] = APODERADOS_BORRADOR.apoderados.filter((a) => a.bloquea);
    const ruta = `/api/casos/${CASO_MOCK_BORRADOR}/apoderados/${rojo?.id ?? ""}/revision`;
    await expect(poner(ruta, { revisado: true, huella: "otra" })).rejects.toMatchObject({ estado: 409 });
    const marcado = (await poner(ruta, { revisado: true, huella: rojo?.huella })) as { revisado: boolean };
    expect(marcado.revisado).toBe(true);
    await poner(ruta, { revisado: false });
  });

  it("las páginas del expediente simulado traen la cita del poder; las de otros casos no existen", async () => {
    const { CASO_MOCK_BORRADOR, APODERADOS_BORRADOR } = await import("../vistas/borrador/mock");
    const poder = APODERADOS_BORRADOR.apoderados[0]?.poder.evidencia;
    if (!poder) throw new Error("el mock perdió el poder del primer abogado");
    const base = `/api/casos/${CASO_MOCK_BORRADOR}/expediente/${poder.doc_id}/paginas`;
    const pagina = (await resolverMock(peticion("GET", `${base}/${poder.pagina}`))) as PaginaExpediente;
    expect(pagina).toMatchObject({ doc_id: poder.doc_id, pagina: poder.pagina, total: poder.total_paginas, es_pdf: true, ocr: false });
    expect(pagina.texto.replace(/\s+/g, " ")).toContain(poder.cita);
    const otra = (await resolverMock(peticion("GET", `${base}/1`))) as PaginaExpediente;
    expect(otra.texto).not.toContain(poder.cita);
    await expect(async () => resolverMock(peticion("GET", `${base}/99`))).rejects.toMatchObject({ estado: 404 });
    await expect(async () => resolverMock(peticion("GET", `/api/casos/${CASO_MOCK_BORRADOR}/expediente/9z-999/paginas/1`))).rejects.toMatchObject({ estado: 404 });
    await expect(async () => resolverMock(peticion("GET", `/api/casos/otro/expediente/${poder.doc_id}/paginas/1`))).rejects.toMatchObject({ estado: 404 });
  });

  it("subir el certificado decide por el contenido del PDF, como haría el servidor al leerlo", async () => {
    const { CASO_MOCK_BORRADOR, reiniciarApoderadosMock } = await import("../vistas/borrador/mock");
    const ruta = (id: string) => `/api/casos/${CASO_MOCK_BORRADOR}/apoderados/${id}/certificado`;
    const subir = (id: string, contenido: string) => {
      const cuerpo = new FormData();
      cuerpo.append("archivo", new File([contenido], "certificado.pdf", { type: "application/pdf" }));
      return poner(ruta(id), cuerpo);
    };
    try {
      await expect(subir("ap-81be04c5f2", "hola")).rejects.toMatchObject({ estado: 422, message: "El archivo no es un PDF." });
      await expect(subir("ap-81be04c5f2", "%PDF-1.7 sin final")).rejects.toMatchObject({ estado: 422, message: "No se pudo leer el certificado." });
      await expect(subir("ap-0000000000", "%PDF-1.7\n%%EOF")).rejects.toMatchObject({ estado: 404 });
      await expect(poner(`/api/casos/otro/apoderados/ap-81be04c5f2/certificado`, new FormData())).rejects.toMatchObject({ estado: 404 });

      const verde = (await subir("ap-81be04c5f2", "%PDF-1.7\nVIGENTE\n%%EOF")) as ApoderadoVista;
      expect(verde).toMatchObject({ estado: "verificado", bloquea: false, motivos: [], vigencia: { estado: "vigente", origen: "manual", fase: "listo" } });
      expect(verde.vigencia.certificado_url).toBeTruthy();
      expect(await resolverMock(peticion("GET", ruta("ap-81be04c5f2")))).toBeInstanceOf(Blob);

      const rojo = (await subir("ap-3f9c2a71d0", "%PDF-1.7\nESTADO: NO VIGENTE\n%%EOF")) as ApoderadoVista;
      expect(rojo).toMatchObject({ estado: "no_verificado", bloquea: true, vigencia: { estado: "no_vigente" } });
      const datos = (await resolverMock(peticion("GET", `/api/casos/${CASO_MOCK_BORRADOR}/apoderados`))) as ApoderadosRespuesta;
      expect(datos.apoderados.find((a) => a.id === "ap-3f9c2a71d0")?.estado).toBe("no_verificado");
      expect(datos.bloquea_decision).toBe(true);
    } finally {
      reiniciarApoderadosMock();
    }
    await expect(async () => resolverMock(peticion("GET", ruta("ap-81be04c5f2")))).rejects.toMatchObject({ estado: 404 });
  });

  it("la consulta simulada pasa por en cola y consultando hasta dejar vigente al abogado", async () => {
    const { CASO_MOCK_BORRADOR, reiniciarApoderadosMock } = await import("../vistas/borrador/mock");
    const base = `/api/casos/${CASO_MOCK_BORRADOR}/apoderados`;
    const luis = (d: ApoderadosRespuesta) => d.apoderados.find((a) => a.id === "ap-81be04c5f2");
    const leer = async () => (await resolverMock(peticion("GET", base))) as ApoderadosRespuesta;
    reiniciarApoderadosMock();
    try {
      const pedida = (await resolverMock(peticion("POST", `${base}/consultar`, { forzar: false }))) as ApoderadosRespuesta;
      expect(pedida.consulta).toMatchObject({ activa: true, extension: "conectada" });
      expect(luis(pedida)?.vigencia.fase).toBe("en_cola");
      expect(luis(await leer())?.vigencia.fase).toBe("consultando");
      const lista = await leer();
      expect(luis(lista)).toMatchObject({ estado: "verificado", fase: "listo", vigencia: { estado: "vigente", origen: "extension" } });
      expect(lista.consulta.activa).toBe(false);
      // Ya consultado, pedirlo de nuevo sin forzar no lo vuelve a poner en cola.
      const otra = (await resolverMock(peticion("POST", `${base}/consultar`, { forzar: false }))) as ApoderadosRespuesta;
      expect(otra.consulta.activa).toBe(false);
    } finally {
      reiniciarApoderadosMock();
    }
  });

  it("los ajustes simulados descartan el poder, lo señalan a mano comprobando el nombre y validan la cédula", async () => {
    const { CASO_MOCK_BORRADOR, reiniciarApoderadosMock } = await import("../vistas/borrador/mock");
    const ruta = (id: string) => `/api/casos/${CASO_MOCK_BORRADOR}/apoderados/${id}/ajustes`;
    reiniciarApoderadosMock();
    try {
      const descartado = (await poner(ruta("ap-3f9c2a71d0"), { poder_descartado: true, nota: "" })) as ApoderadoVista;
      expect(descartado).toMatchObject({ estado: "revisar", poder: { estado: "descartado", evidencia: null } });
      await expect(poner(ruta("ap-3f9c2a71d0"), { poder_descartado: true })).rejects.toMatchObject({ estado: 409 });
      await expect(poner(ruta("ap-3f9c2a71d0"), { poder_manual: { doc_id: "1a-007", pagina: 2 } })).rejects.toMatchObject({
        estado: 422,
        message: "El nombre del abogado no aparece en esa página.",
      });
      await expect(poner(ruta("ap-3f9c2a71d0"), { poder_manual: { doc_id: "9z-999", pagina: 1 } })).rejects.toMatchObject({ estado: 422 });
      const manual = (await poner(ruta("ap-3f9c2a71d0"), { poder_manual: { doc_id: "1a-007", pagina: 4 }, nota: "" })) as ApoderadoVista;
      expect(manual).toMatchObject({ estado: "verificado", poder: { estado: "manual", evidencia: { doc_id: "1a-007", pagina: 4 } } });
      expect(manual.poder.evidencia?.cita).toContain("ANDREA PAOLA GIRALDO MONTOYA");
      await expect(poner(ruta("ap-3f9c2a71d0"), { nota: "nada" })).rejects.toMatchObject({ estado: 422 });
      await expect(poner(ruta("ap-3f9c2a71d0"), { cedula: "123" })).rejects.toMatchObject({ estado: 422, message: "La cédula debe tener entre 5 y 10 dígitos." });
      await expect(poner(ruta("ap-3f9c2a71d0"), { cedula: "43000021" })).rejects.toMatchObject({ estado: 409 });
      await expect(poner(`/api/casos/otro/apoderados/ap-3f9c2a71d0/ajustes`, { cedula: "43000021" })).rejects.toMatchObject({ estado: 404 });
    } finally {
      reiniciarApoderadosMock();
    }
  });

  it("las variantes ?consulta= del simulacro: apagada, ayuda y sin identificar", async () => {
    const { CASO_MOCK_BORRADOR, reiniciarApoderadosMock } = await import("../vistas/borrador/mock");
    const base = `/api/casos/${CASO_MOCK_BORRADOR}/apoderados`;
    const leer = async () => (await resolverMock(peticion("GET", base))) as ApoderadosRespuesta;
    const conVariante = (valor: string) => {
      history.replaceState(null, "", `/?consulta=${valor}`);
      reiniciarApoderadosMock();
    };
    try {
      conVariante("apagada");
      expect((await leer()).consulta.modo).toBe("apagada");
      await expect(async () => resolverMock(peticion("POST", `${base}/consultar`, {}))).rejects.toMatchObject({ estado: 409 });

      conVariante("ayuda");
      await resolverMock(peticion("POST", `${base}/consultar`, { forzar: false }));
      await leer();
      const sinRespuesta = await leer();
      const luis = sinRespuesta.apoderados.find((a) => a.id === "ap-81be04c5f2");
      expect(luis).toMatchObject({ fase: "necesita_ayuda", vigencia: { estado: "inaccesible" } });
      expect(sinRespuesta.consulta.pausa_hasta).toBeTruthy();
      await resolverMock(peticion("POST", `${base}/consultar`, { ids: ["ap-81be04c5f2"], forzar: true }));
      await leer();
      const resuelta = await leer();
      expect(resuelta.apoderados.find((a) => a.id === "ap-81be04c5f2")?.vigencia.estado).toBe("vigente");
      expect(resuelta.consulta.pausa_hasta).toBeNull();

      conVariante("sin_identificar");
      expect((await leer()).identificacion).toBe("no_disponible");
      const trabajo = (await resolverMock(peticion("POST", `${base}/identificar`))) as ApoderadosRespuesta;
      expect(trabajo.editable).toBe(false);
      await expect(async () => resolverMock(peticion("POST", `${base}/identificar`))).rejects.toMatchObject({ estado: 409 });
      // Mientras corre el trabajo, como el servidor: la lectura no admite cambios y las escrituras responden 409.
      expect(await leer()).toMatchObject({ identificacion: "no_disponible", editable: false });
      await expect(async () => resolverMock(peticion("POST", `${base}/consultar`, {}))).rejects.toMatchObject({ estado: 409 });
      await expect(poner(`${base}/ap-3f9c2a71d0/ajustes`, { cedula: "1017234568" })).rejects.toMatchObject({ estado: 409 });
      const identificada = await leer();
      expect(identificada).toMatchObject({ identificacion: "lista", editable: true });
      expect(identificada.apoderados).toHaveLength(3);
    } finally {
      history.replaceState(null, "", "/");
      reiniciarApoderadosMock();
    }
  });

  it("la variante ?consulta=no_inscrito sigue en rojo, con su motivo, cuando el simulador vuelve a evaluar al abogado", async () => {
    const { CASO_MOCK_BORRADOR, NO_INSCRITO, reiniciarApoderadosMock } = await import("../vistas/borrador/mock");
    const ruta = `/api/casos/${CASO_MOCK_BORRADOR}/apoderados/${NO_INSCRITO.id}/ajustes`;
    history.replaceState(null, "", "/?consulta=no_inscrito");
    reiniciarApoderadosMock();
    try {
      const descartado = (await poner(ruta, { poder_descartado: true, nota: "" })) as ApoderadoVista;
      expect(descartado).toMatchObject({ estado: "no_verificado", bloquea: true, poder: { estado: "descartado" }, vigencia: { estado: "no_inscrito", grave: true } });
      expect(descartado.motivos[0]).toBe(NO_INSCRITO.motivos[0]);
      const devuelto = (await poner(ruta, { poder_descartado: false, nota: "" })) as ApoderadoVista;
      expect(devuelto).toMatchObject({ estado: "no_verificado", bloquea: true, motivos: NO_INSCRITO.motivos, vigencia: { grave: true } });
    } finally {
      history.replaceState(null, "", "/");
      reiniciarApoderadosMock();
    }
  });

  it("identificar en otro caso que no es el del borrador responde 409, como un caso que no espera la decisión", async () => {
    await expect(async () => resolverMock(peticion("POST", "/api/casos/quintero-bedoya/apoderados/identificar"))).rejects.toMatchObject({ estado: 409 });
    await expect(async () => resolverMock(peticion("POST", "/api/casos/quintero-bedoya/apoderados/consultar", {}))).rejects.toMatchObject({ estado: 409 });
  });

  it("entrega copias de las respuestas estáticas", async () => {
    agregarMocks([{ metodo: "GET", ruta: "/api/prueba-c", respuesta: { lista: [1] } }]);
    const primera = (await resolverMock(peticion("GET", "/api/prueba-c"))) as { lista: number[] };
    primera.lista.push(2);
    expect(await resolverMock(peticion("GET", "/api/prueba-c"))).toEqual({ lista: [1] });
  });
});
