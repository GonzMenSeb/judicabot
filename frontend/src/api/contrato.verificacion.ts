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
  Bloque: Afirmar<Igual<C.Bloque, S["Bloque"]>>,
  PaginaVista: Afirmar<Igual<C.PaginaVista, S["PaginaVista"]>>,
  CitaVista: Afirmar<Igual<C.CitaVista, S["CitaVista"]>>,
  Vista: Afirmar<Igual<C.Vista, S["Vista"]>>,
  NumeralVista: Afirmar<Igual<C.NumeralVista, S["NumeralVista"]>>,
  DecisionVistaRespuesta: Afirmar<Igual<C.DecisionVistaRespuesta, S["DecisionVistaRespuesta"]>>,
  ModoJev: Afirmar<Igual<C.ModoJev, S["IAJev"]["modo"]>>,
  Effort: Afirmar<Igual<C.Effort, S["IAEstado"]["effort"]>>,
  PreferenciasIa: Afirmar<Igual<Sin<C.PreferenciasIa, "modelo">, Sin<S["IAEstado"], "modelo">>>,
  PreferenciasIaModelo: Afirmar<S["IAEstado"]["modelo"] extends C.PreferenciasIa["modelo"] ? true : false>,
  PreferenciasIaCuerpoCampos: Afirmar<Igual<keyof C.PreferenciasIaCuerpo, keyof S["Preferencias"]>>,
  PreferenciasIaCuerpo: Afirmar<Sin<C.PreferenciasIaCuerpo, "modelo"> extends Sin<S["Preferencias"], "modelo"> ? true : false>,
  PreferenciasIaCuerpoModelo: Afirmar<NonNullable<S["Preferencias"]["modelo"]> extends C.PreferenciasIaCuerpo["modelo"] ? true : false>,
  RunCuerpo: Afirmar<Igual<Sin<C.RunCuerpo, "forzar" | "decision">, Sin<S["RunBody"], "forzar" | "decision">>>,
  RunCuerpoForzar: Afirmar<Igual<NonNullable<C.RunCuerpo["forzar"]>, S["RunBody"]["forzar"]>>,
  RunCuerpoDecision: Afirmar<C.RunCuerpo["decision"] extends S["RunBody"]["decision"] ? true : false>,
  EstadoServidor: Afirmar<Igual<C.EstadoServidor, S["EstadoServidor"]>>,
  JobInicio: Afirmar<Igual<C.JobInicio, S["JobInicio"]>>,
  ErroresCampo: Afirmar<Igual<C.ErroresCampo["errores"], S["FormatoErroresDetalle"]["errores"]>>,
];
