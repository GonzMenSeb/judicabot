import type * as C from "./contrato";
import type { Evento as EventoSse, Fin } from "./eventos";
import type { components } from "./schema";

type S = components["schemas"];

type Igual<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Afirmar<T extends true> = T;
type Sin<T, K extends keyof T> = Omit<T, K>;

export type VerificacionContrato = [
  CasoResumen: Afirmar<Igual<C.CasoResumen, S["CasoResumen"]>>,
  CrearCasoRespuesta: Afirmar<Igual<C.CrearCasoRespuesta, S["CasoCreado"]>>,
  CampoFormato: Afirmar<Igual<C.CampoFormato, S["CampoFormato"]>>,
  Despacho: Afirmar<Igual<C.Despacho, S["Despacho"]>>,
  FormatoRespuesta: Afirmar<Igual<C.FormatoRespuesta, S["FormatoRespuesta"]>>,
  FormatoCuerpo: Afirmar<Igual<C.FormatoCuerpo, S["FormatoCuerpo"]>>,
  Evento: Afirmar<Igual<C.Evento, S["Evento"]>>,
  EventoSse: Afirmar<Igual<EventoSse, S["Evento"]>>,
  FinSse: Afirmar<Igual<Fin, C.FinJob>>,
  FinJobEstado: Afirmar<Igual<C.FinJob["estado"], Exclude<S["EventosJob"]["estado"], "corriendo">>>,
  FinJobError: Afirmar<Igual<C.FinJob["error"], S["EventosJob"]["error"]>>,
  EventosJson: Afirmar<Igual<C.EventosJson, S["EventosJob"]>>,
  Segmento: Afirmar<Igual<C.Segmento, S["Segmento"]>>,
  Fuente: Afirmar<Igual<C.Fuente, S["Fuente"]>>,
  Bloque: Afirmar<Igual<C.Bloque, S["Bloque"]>>,
  PaginaVista: Afirmar<Igual<C.PaginaVista, S["PaginaVista"]>>,
  CitaVista: Afirmar<Igual<C.CitaVista, S["CitaVista"]>>,
  Vista: Afirmar<Igual<C.Vista, S["Vista"]>>,
  NumeralVista: Afirmar<Igual<C.NumeralVista, S["NumeralVista"]>>,
  DecisionVistaRespuesta: Afirmar<Igual<C.DecisionVistaRespuesta, S["DecisionVistaRespuesta"]>>,
  DecisionVistaAdvertencia: Afirmar<Igual<C.DecisionVistaRespuesta["advertencias"][number], S["FaltanteDecision"]>>,
  PiezaEdicion: Afirmar<Igual<C.PiezaEdicion, S["PiezaEdicion"]>>,
  TrozoOk: Afirmar<Igual<C.TrozoOk, S["TrozoOk"]>>,
  TrozoConflicto: Afirmar<Igual<C.TrozoConflicto, S["TrozoConflicto"]>>,
  ConflictoEdicion: Afirmar<Igual<C.ConflictoEdicion, S["ConflictoEdicion"]>>,
  EdicionesRespuesta: Afirmar<Igual<C.EdicionesRespuesta, S["EdicionesRespuesta"]>>,
  EdicionCuerpo: Afirmar<Igual<C.EdicionCuerpo, S["EdicionCuerpo"]>>,
  ResolverCuerpo: Afirmar<Igual<C.ResolverCuerpo, S["ResolverCuerpo"]>>,
  ModoJev: Afirmar<Igual<C.ModoJev, S["IAJev"]["modo"]>>,
  Effort: Afirmar<Igual<C.Effort, S["IAEstado"]["effort"]>>,
  Proveedor: Afirmar<Igual<C.Proveedor, S["IAEstado"]["proveedor"]>>,
  RazonamientoGemini: Afirmar<Igual<C.RazonamientoGemini, S["IAGemini"]["razonamiento"]>>,
  PreferenciasIa: Afirmar<Igual<Sin<C.PreferenciasIa, "modelo" | "gemini">, Sin<S["IAEstado"], "modelo" | "gemini">>>,
  PreferenciasIaModelo: Afirmar<S["IAEstado"]["modelo"] extends C.PreferenciasIa["modelo"] ? true : false>,
  PreferenciasIaGemini: Afirmar<Igual<Sin<C.PreferenciasGemini, "modelo">, Sin<S["IAGemini"], "modelo">>>,
  PreferenciasIaGeminiModelo: Afirmar<S["IAGemini"]["modelo"] extends C.PreferenciasGemini["modelo"] ? true : false>,
  PreferenciasIaCuerpoCampos: Afirmar<Igual<keyof C.PreferenciasIaCuerpo, keyof S["Preferencias"]>>,
  PreferenciasIaCuerpo: Afirmar<Sin<C.PreferenciasIaCuerpo, "modelo" | "gemini"> extends Sin<S["Preferencias"], "modelo" | "gemini"> ? true : false>,
  PreferenciasIaCuerpoModelo: Afirmar<NonNullable<S["Preferencias"]["modelo"]> extends NonNullable<C.PreferenciasIaCuerpo["modelo"]> ? true : false>,
  PreferenciasIaCuerpoGeminiCampos: Afirmar<Igual<keyof C.PreferenciasGemini, keyof S["GeminiPreferencias"]>>,
  PreferenciasIaCuerpoGemini: Afirmar<Sin<C.PreferenciasGemini, "modelo"> extends Sin<S["GeminiPreferencias"], "modelo"> ? true : false>,
  PreferenciasIaCuerpoGeminiModelo: Afirmar<NonNullable<S["GeminiPreferencias"]["modelo"]> extends C.PreferenciasGemini["modelo"] ? true : false>,
  RunCuerpo: Afirmar<Igual<Sin<C.RunCuerpo, "forzar" | "decision">, Sin<S["RunBody"], "forzar" | "decision">>>,
  RunCuerpoForzar: Afirmar<Igual<NonNullable<C.RunCuerpo["forzar"]>, S["RunBody"]["forzar"]>>,
  RunCuerpoDecision: Afirmar<C.RunCuerpo["decision"] extends S["RunBody"]["decision"] ? true : false>,
  EstadoServidor: Afirmar<Igual<C.EstadoServidor, S["EstadoServidor"]>>,
  EstadoDataset: Afirmar<Igual<C.EstadoDataset, S["EstadoDataset"]>>,
  JobInicio: Afirmar<Igual<C.JobInicio, S["JobInicio"]>>,
  ErroresCampo: Afirmar<Igual<C.ErroresCampo["errores"], S["FormatoErroresDetalle"]["errores"]>>,
];
