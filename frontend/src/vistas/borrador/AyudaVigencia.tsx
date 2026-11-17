import type { JSX } from "preact";
import { useEffect, useId, useRef, useState } from "preact/hooks";
import type { ApoderadoVista } from "../../api/contrato";
import { Aviso, Boton, cx } from "../../ui";
import { mensajeError } from "../casos/subida";
import { mascaraCedula } from "./apoderados";
import "./apoderados.css";
import { mostrarDentro } from "./desplazar";

export const URL_CERTIFICADO_VIGENCIA = "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx";
/** El mismo tope que aplica el servidor: un certificado de vigencia pesa unas decenas de KB. */
export const MAX_CERTIFICADO_BYTES = 2 * 1024 * 1024;

const ESPERA_SIN_MOVIMIENTO_MS = 1500;
const VISIBLE_AVISO_MS = 5000;

const digitos = (texto: string | null | undefined): string => (texto ?? "").replace(/\D/g, "");

/** Revisa en el navegador lo que el servidor volverá a revisar, para no subir de balde un archivo que no sirve. */
export function validarCertificado(archivo: Pick<File, "name" | "size" | "type">): string | null {
  if (archivo.type !== "application/pdf" && !/\.pdf$/i.test(archivo.name)) {
    return "El archivo no es un PDF. Suba el certificado tal como lo descargó de la página oficial.";
  }
  if (archivo.size === 0) return "El archivo está vacío.";
  if (archivo.size > MAX_CERTIFICADO_BYTES) return "El archivo pesa más de 2 MB; un certificado de vigencia es mucho más liviano.";
  return null;
}

const traeArchivos = (dt: DataTransfer | null): dt is DataTransfer => dt !== null && Array.from(dt.types ?? []).includes("Files");

/**
 * La misma guarda de vistas/casos/soltar.ts, pero sobre el elemento y no sobre la página: solo reacciona a
 * arrastres de archivos, cuenta los dragenter/dragleave de los hijos, se apaga si el arrastre termina sin
 * eventos de salida y no deja que el navegador abra el PDF aunque la zona esté inactiva.
 */
function useSoltarEnZona(alSoltar: (dt: DataTransfer) => void, permitido: () => boolean) {
  const [arrastrando, setArrastrando] = useState(false);
  const profundidad = useRef(0);
  const vigilante = useRef<ReturnType<typeof setTimeout>>();
  const alSoltarRef = useRef(alSoltar);
  const permitidoRef = useRef(permitido);
  alSoltarRef.current = alSoltar;
  permitidoRef.current = permitido;

  useEffect(() => () => clearTimeout(vigilante.current), []);

  const ocultar = () => {
    profundidad.current = 0;
    clearTimeout(vigilante.current);
    setArrastrando(false);
  };
  const mostrar = () => {
    clearTimeout(vigilante.current);
    vigilante.current = setTimeout(ocultar, ESPERA_SIN_MOVIMIENTO_MS);
    if (permitidoRef.current()) setArrastrando(true);
  };

  return {
    arrastrando,
    eventos: {
      onDragEnter: (ev: DragEvent) => {
        if (!traeArchivos(ev.dataTransfer)) return;
        ev.preventDefault();
        profundidad.current += 1;
        mostrar();
      },
      onDragOver: (ev: DragEvent) => {
        if (!traeArchivos(ev.dataTransfer)) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = permitidoRef.current() ? "copy" : "none";
        if (profundidad.current === 0) profundidad.current = 1;
        mostrar();
      },
      onDragLeave: (ev: DragEvent) => {
        if (!traeArchivos(ev.dataTransfer)) return;
        profundidad.current = Math.max(0, profundidad.current - 1);
        if (profundidad.current === 0) ocultar();
      },
      onDrop: (ev: DragEvent) => {
        if (!traeArchivos(ev.dataTransfer)) return;
        ev.preventDefault();
        const dt = ev.dataTransfer;
        ocultar();
        if (permitidoRef.current()) alSoltarRef.current(dt);
      },
    },
  };
}

function IconoExterno() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

function IconoSubir() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
    </svg>
  );
}

export interface PropsAyudaVigencia {
  apoderado: ApoderadoVista;
  editable: boolean;
  compacta?: boolean;
  alSubir: (archivo: File) => Promise<void>;
  /**
   * «Reintentar consulta automática»: vuelve a pedir la consulta de la vigencia de este abogado. Sin ella (la consulta
   * automática está apagada o no hay cédula que consultar) no se ofrece.
   */
  alReintentar?: () => Promise<void>;
  /**
   * Adónde llevar el foco si, tras una subida que sale bien, la ayuda desaparece porque la tarjeta ya consta (el título
   * del detalle o la fila del abogado en el panel). Sin él, el foco se queda donde lo deje el navegador.
   */
  destinoFoco?: () => HTMLElement | null;
}

/** El botón que se deshabilitó durante la lectura le quitó el foco al teclado, o el elemento que lo tenía ya no está. */
const focoPerdido = (): boolean => {
  const activo = document.activeElement;
  return activo === null || activo === document.body || !activo.isConnected;
};

/** Lo que se le ofrece al despacho cuando la consulta automática no pudo traer la tarjeta: ir a la página oficial y subir el PDF. */
export function AyudaVigencia({ apoderado, editable, compacta = false, alSubir, alReintentar, destinoFoco }: PropsAyudaVigencia) {
  const [subiendo, setSubiendo] = useState(false);
  const [reintentando, setReintentando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copia, setCopia] = useState<{ texto: string } | null>(null);
  const zona = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLInputElement>(null);
  const aviso = useRef<HTMLDivElement>(null);
  const montado = useRef(true);
  const devolverFoco = useRef(false);
  const destino = useRef(destinoFoco);
  destino.current = destinoFoco;
  const idNuevaPestana = useId();
  const cedula = digitos(apoderado.cedula);
  const inactivo = !editable || subiendo || reintentando;
  const inactivoRef = useRef(inactivo);
  inactivoRef.current = inactivo;

  // Si la ayuda desaparece con el resultado de la subida, el foco va al destino que dio el llamador, ya pintado.
  const enfocarDestino = () => {
    requestAnimationFrame(() => {
      if (focoPerdido()) destino.current?.()?.focus();
    });
  };

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      if (devolverFoco.current) {
        devolverFoco.current = false;
        enfocarDestino();
      }
    };
  }, []);

  useEffect(() => {
    if (!copia) return;
    const espera = setTimeout(() => setCopia(null), VISIBLE_AVISO_MS);
    return () => clearTimeout(espera);
  }, [copia]);

  // Al terminar la lectura (o el pedido de reintentar), salga bien o mal, el foco vuelve al botón que se deshabilitó mientras tanto.
  useEffect(() => {
    if (subiendo || reintentando || !devolverFoco.current) return;
    devolverFoco.current = false;
    if (focoPerdido()) zona.current?.querySelector("button")?.focus();
  }, [subiendo, reintentando]);

  // El error queda a la vista dentro del cuerpo que se desplaza (el del detalle tiene un alto máximo), sin mover la ventana.
  useEffect(() => {
    const el = aviso.current;
    const contenedor = el?.closest<HTMLElement>(".bor-pop-cuerpo, .bor-panel-cuerpo");
    if (el && contenedor) mostrarDentro(contenedor, el);
  }, [error]);

  const subir = async (archivo: File) => {
    // Nada sale si el caso ya no admite cambios o si hay una lectura en curso, venga el archivo de donde venga.
    if (inactivoRef.current) return;
    const motivo = validarCertificado(archivo);
    if (motivo) {
      setError(motivo);
      return;
    }
    setError(null);
    inactivoRef.current = true;
    setSubiendo(true);
    let bien = false;
    try {
      await alSubir(archivo);
      bien = true;
    } catch (e) {
      if (montado.current) setError(mensajeError(e, "No se pudo subir el certificado."));
    } finally {
      if (montado.current) {
        // Si con el resultado la ayuda deja de hacer falta, se desmonta en el próximo pintado y el foco va al destino.
        devolverFoco.current = true;
        setSubiendo(false);
      } else if (bien) {
        enfocarDestino();
      }
    }
  };

  const reintentar = async () => {
    if (!alReintentar || inactivoRef.current) return;
    setError(null);
    inactivoRef.current = true;
    setReintentando(true);
    let bien = false;
    try {
      await alReintentar();
      bien = true;
    } catch (e) {
      if (montado.current) setError(mensajeError(e, "No se pudo pedir de nuevo la consulta automática."));
    } finally {
      if (montado.current) {
        // Con la consulta en cola la ayuda deja de hacer falta y se desmonta: el foco va al destino.
        devolverFoco.current = true;
        setReintentando(false);
      } else if (bien) {
        enfocarDestino();
      }
    }
  };

  const copiar = async () => {
    try {
      if (!navigator.clipboard) throw new Error("Sin portapapeles");
      await navigator.clipboard.writeText(cedula);
      if (montado.current) setCopia({ texto: "C.C. copiada: péguela en la página oficial." });
    } catch {
      if (montado.current) setCopia({ texto: "No se pudo copiar la C.C. al portapapeles." });
    }
  };

  const alSoltar = (dt: DataTransfer) => {
    const archivos = Array.from(dt.files ?? []);
    const [archivo] = archivos;
    if (!archivo) setError("No se recibió ningún archivo.");
    else if (archivos.length > 1) setError("Suelte un solo archivo: el PDF del certificado.");
    else void subir(archivo);
  };

  const permitido = () => {
    if (inactivoRef.current) return false;
    const modal = document.querySelector("dialog[open]");
    return modal === null || (zona.current !== null && modal.contains(zona.current));
  };

  const { arrastrando, eventos } = useSoltarEnZona(alSoltar, permitido);

  const alElegir = (ev: JSX.TargetedEvent<HTMLInputElement, Event>) => {
    const campo = ev.currentTarget;
    const archivo = campo.files?.[0];
    // Se vacía para que elegir otra vez el mismo archivo (tras corregirlo) vuelva a disparar el cambio.
    campo.value = "";
    if (archivo) void subir(archivo);
  };

  return (
    <div class={cx("apo-ayuda", compacta && "compacta")}>
      <p class="apo-ayuda-texto">
        {apoderado.vigencia.estado === "inaccesible" && "La consulta automática no obtuvo respuesta. "}
        Descargue el certificado en la página oficial y súbalo aquí; Judicabot lo lee y lo guarda como evidencia.
      </p>
      <div class="apo-ayuda-acciones">
        <a
          class="btn"
          href={editable ? URL_CERTIFICADO_VIGENCIA : undefined}
          target="_blank"
          rel="noopener noreferrer"
          aria-describedby={idNuevaPestana}
          aria-disabled={editable ? undefined : "true"}
        >
          Abrir Certificado de vigencia
          <IconoExterno />
        </a>
        <span id={idNuevaPestana} class="solo-lectura">
          Se abre en una pestaña nueva.
        </span>
        {cedula ? (
          <Boton variante="fantasma" disabled={!editable} onClick={() => void copiar()}>
            Copiar C.C. {mascaraCedula(cedula)}
          </Boton>
        ) : (
          <span class="apo-ayuda-sin-cc">No se encontró la C.C. del abogado en el expediente: escríbala en la página oficial.</span>
        )}
      </div>
      <p class="apo-ayuda-estado" role="status">
        {subiendo || reintentando ? (
          <>
            <span class="giro" aria-hidden="true" />
            {subiendo ? "Leyendo el certificado…" : "Pidiendo la consulta automática…"}
          </>
        ) : (
          copia?.texto
        )}
      </p>
      {/* Encima de la zona, donde se mira al soltar o elegir: debajo, el cuerpo del detalle lo dejaría fuera de la vista. */}
      {error && (
        <div ref={aviso} class="apo-ayuda-error">
          <Aviso tipo="error">{error}</Aviso>
        </div>
      )}
      <div
        ref={zona}
        class={cx("apo-soltar", arrastrando && "arrastrando", inactivo && "inactiva")}
        role="group"
        aria-label={`Subir el certificado de vigencia de ${apoderado.nombre}`}
        aria-busy={subiendo ? "true" : undefined}
        {...eventos}
      >
        <IconoSubir />
        <span>Arrastre aquí el PDF del certificado</span>
        <Boton variante="fantasma" disabled={inactivo} onClick={() => entrada.current?.click()}>
          o elija un archivo
        </Boton>
        <input ref={entrada} type="file" accept="application/pdf" class="solo-lectura" tabIndex={-1} aria-hidden="true" disabled={inactivo} onChange={alElegir} />
      </div>
      {alReintentar && editable && (
        <div>
          <Boton variante="fantasma" class="chico" disabled={inactivo} onClick={() => void reintentar()}>
            Reintentar consulta automática
          </Boton>
        </div>
      )}
      {!editable && <p class="apo-ayuda-nota">El certificado solo se puede subir mientras el caso espera la decisión.</p>}
    </div>
  );
}
