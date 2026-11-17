from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from typing import Any, Iterable, Iterator, Protocol

from pydantic import BaseModel, ValidationError

from tutela2 import apoderados
from tutela2.config import (
    NODOS_LLM,
    RESPALDO_CLIENTE,
    VARIABLE_MODELOS_PERMITIDOS,
    Config,
    modelo_permitido,
    modelos_permitidos,
    niveles_admitidos,
)
from tutela2.ingest import ETIQUETA_CERTIFICADO
from tutela2.jev import clave_valida
from tutela2.models import (
    AbogadoLLM,
    AperturaLLM,
    ApoderadosLLM,
    BloqueLLM,
    CasoConcretoLLM,
    CitaPropuesta,
    ConsideracionesLLM,
    Contestacion,
    Evento,
    MencionLLM,
    MetadatosLLM,
    ParrafoLLM,
    ParteLLM,
    PoderLLM,
    Reparo,
)

try:
    import httpx2 as httpx
except ImportError:
    import httpx

log = logging.getLogger("tutela2")

BETA_FALLBACK = "server-side-fallback-2026-07-01"

CITAS_FAKE = {
    "c1": (
        "T-200 de 2022",
        "Esta hipótesis se presenta, cuando el juez constata (i) que la pretensión de la acción fue satisfecha "
        "y (ii) que esta satisfacción surgió voluntariamente por parte de la accionada.",
    ),
    "c2": (
        "SU-082 de 1995",
        "Pero, mientras no lo haya fijado, hay que considerar que es razonable el término que evite el abuso "
        "del poder informático y preserve las sanas prácticas crediticias, defendiendo así el interés general.",
    ),
}


class ErrorLLM(Exception):
    pass


class ErrorLLMDegenerado(ErrorLLM):
    pass


UNIDAD_MIN, UNIDAD_MAX = 4, 80
REPETICIONES_MIN = 12
TRAMO_MIN = 240
RACHA_MIN = 400
VENTANA_DEGENERACION = max(RACHA_MIN, UNIDAD_MAX * REPETICIONES_MIN, TRAMO_MIN)


def detectar_degeneracion(texto: str) -> bool:
    cola = texto[-VENTANA_DEGENERACION:]
    if len(cola) >= RACHA_MIN and not cola[-1].isalnum() and cola[-RACHA_MIN:] == cola[-1] * RACHA_MIN:
        return True
    for u in range(UNIDAD_MIN, UNIDAD_MAX + 1):
        largo = max(u * REPETICIONES_MIN, TRAMO_MIN)
        if len(cola) < largo:
            break
        if cola[-u:] != cola[-2 * u : -u] or len(set(cola[-u:])) < 2:
            continue
        tramo = cola[-largo:]
        if tramo[u:] == tramo[:-u]:
            return True
    return False


def _vigilar(trozos: Iterable[str]) -> None:
    cola = ""
    for trozo in trozos:
        cola = (cola + trozo)[-VENTANA_DEGENERACION:]
        if detectar_degeneracion(cola):
            raise ErrorLLMDegenerado("El modelo entró en un lazo de repetición y la respuesta se abortó.")


def _consumir(flujo: Any):
    _vigilar(flujo.text_stream)
    return flujo.get_final_message()


def _transmitir(abrir: Any, consumir: Any = _consumir):
    try:
        with abrir() as flujo:
            return consumir(flujo)
    except ErrorLLMDegenerado:
        log.warning("El modelo entró en un lazo de repetición; se repite la llamada una vez.")
    try:
        with abrir() as flujo:
            return consumir(flujo)
    except ErrorLLMDegenerado as e:
        raise ErrorLLM(
            "El modelo entró en un lazo de repetición en dos intentos consecutivos; use 'continuar' para reintentar."
        ) from e


class LLMClient(Protocol):
    def estructurado(
        self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config
    ) -> tuple[BaseModel, dict]: ...


def seccion(titulo: str, contenido: str) -> str:
    return f"=== {titulo} ===\n{contenido.strip()}\n"


def leer_secciones(user: str) -> dict[str, str]:
    partes = re.split(r"^=== ([A-ZÁÉÍÓÚÑ ]+) ===$", user, flags=re.M)
    return {partes[i]: partes[i + 1].strip() for i in range(1, len(partes) - 1, 2)}


class AnthropicClient:
    def __init__(self, client: Any = None):
        import anthropic

        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic()

    def estructurado(
        self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config
    ) -> tuple[BaseModel, dict]:
        from anthropic.lib._parse._transform import to_json_output_format

        anthropic = self._anthropic
        modelo = cfg.modelo_para(nodo)
        args = dict(
            model=modelo,
            max_tokens=cfg.llm.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg.effort_para(nodo), "format": to_json_output_format(schema)},
            timeout=cfg.llm.timeout_s,
        )
        cliente = self._client.with_options(max_retries=cfg.llm.max_retries)
        previos: list[Any] = []
        try:
            respaldo = RESPALDO_CLIENTE.get(modelo) if cfg.llm.fallbacks_default else None
            if respaldo and not modelo_permitido(respaldo):
                respaldo = None
            resp = self._llamar(cliente, args, cfg.llm.fallbacks_default and modelo not in RESPALDO_CLIENTE)
            if resp.stop_reason == "refusal" and respaldo:
                log.warning("%s rechazó la solicitud; se repite con %s.", modelo, respaldo)
                previos.append(resp)
                resp = self._llamar(cliente, {**args, "model": respaldo}, True)
                if resp.stop_reason == "refusal":
                    raise ErrorLLM(f"Los modelos {modelo} y {respaldo} rechazaron la solicitud (stop_reason=refusal).")
        except TypeError as e:
            if "authentication" not in str(e):
                raise
            raise ErrorLLM(f"No hay credenciales para el proveedor (ANTHROPIC_API_KEY): {e}") from e
        except (anthropic.AnthropicError, httpx.HTTPError) as e:
            raise ErrorLLM(f"Error del proveedor ({type(e).__name__}): {e}") from e
        if resp.stop_reason == "refusal":
            raise ErrorLLM("El modelo rechazó la solicitud (stop_reason=refusal).")
        if resp.stop_reason == "max_tokens":
            raise ErrorLLM(
                f"La respuesta se cortó por el límite de tokens ({cfg.llm.max_tokens}); aumente llm.max_tokens."
            )
        texto = "".join(b.text for b in resp.content if b.type == "text")
        if not texto.strip():
            raise ErrorLLM(f"El modelo no devolvió una salida estructurada (stop_reason={resp.stop_reason}).")
        try:
            salida = schema.model_validate_json(texto)
        except ValidationError as e:
            raise ErrorLLM(f"La respuesta del modelo no cumple el esquema: {_resumen_errores(e)}.") from e
        entrada = salida_tokens = 0
        for r in (*previos, resp):
            e, o = _tokens(r)
            entrada += e
            salida_tokens += o
        meta = {
            "modelo_efectivo": resp.model,
            "tokens_entrada": entrada,
            "tokens_salida": salida_tokens,
            "stop_reason": resp.stop_reason,
        }
        return salida, meta

    def _llamar(self, cliente: Any, args: dict, fallbacks: bool):
        if not fallbacks:
            return self._una(cliente, args)
        try:
            return _transmitir(lambda: cliente.beta.messages.stream(**args, betas=[BETA_FALLBACK], fallbacks="default"))
        except self._anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            log.warning("La API rechazó los fallbacks del servidor; se reintenta sin ellos: %s", e)
            return self._una(cliente, args)

    @staticmethod
    def _una(cliente: Any, args: dict):
        return _transmitir(lambda: cliente.messages.stream(**args))


_CLAVES_GEMINI = {
    "type", "format", "title", "description", "enum", "items", "prefixItems", "minItems", "maxItems",
    "minimum", "maximum", "anyOf", "properties", "additionalProperties", "required", "propertyOrdering",
}


def esquema_gemini(schema: type[BaseModel]) -> dict:
    raiz = schema.model_json_schema()
    defs = raiz.pop("$defs", {})

    def convertir(nodo: dict, pila: tuple[str, ...]) -> dict:
        if "$ref" in nodo:
            nombre = nodo["$ref"].removeprefix("#/$defs/")
            if nombre in pila:
                raise ValueError(f"Esquema recursivo: {nombre}.")
            hermanos = {k: v for k, v in nodo.items() if k != "$ref"}
            return convertir({**defs[nombre], **hermanos}, (*pila, nombre))
        salida: dict[str, Any] = {}
        for clave, valor in nodo.items():
            if clave == "oneOf":
                clave = "anyOf"
            elif clave == "const":
                clave, valor = "enum", [valor]
            if clave not in _CLAVES_GEMINI:
                continue
            if clave == "properties":
                valor = {k: convertir(v, pila) for k, v in valor.items()}
            elif clave in ("anyOf", "prefixItems"):
                valor = [convertir(v, pila) for v in valor]
            elif clave in ("items", "additionalProperties") and isinstance(valor, dict):
                valor = convertir(valor, pila)
            salida[clave] = valor
        return _anulable(salida)

    return convertir(raiz, ())


def _anulable(nodo: dict) -> dict:
    opciones = nodo.get("anyOf") or []
    nulo = {"type": "null"}
    if len(opciones) != 2 or nulo not in opciones:
        return nodo
    otro = opciones[1 - opciones.index(nulo)]
    if not isinstance(otro.get("type"), str) or otro["type"] == "null" or "enum" in otro or "anyOf" in otro:
        return nodo
    return {**otro, **{k: v for k, v in nodo.items() if k != "anyOf"}, "type": [otro["type"], "null"]}


class _RespuestaGemini:
    def __init__(self) -> None:
        self.texto: list[str] = []
        self.uso: Any = None
        self.modelo: str | None = None
        self.fin: Any = None
        self.bloqueo: Any = None

    def leer(self, flujo: Iterable[Any]) -> Iterator[str]:
        for trozo in flujo:
            if trozo.prompt_feedback is not None and trozo.prompt_feedback.block_reason:
                self.bloqueo = trozo.prompt_feedback.block_reason
            if trozo.usage_metadata is not None:
                self.uso = trozo.usage_metadata
            self.modelo = trozo.model_version or self.modelo
            if trozo.candidates and trozo.candidates[0].finish_reason:
                self.fin = trozo.candidates[0].finish_reason
            texto = trozo.text
            if texto:
                self.texto.append(texto)
                yield texto


def _consumir_gemini(flujo: Iterable[Any]) -> _RespuestaGemini:
    respuesta = _RespuestaGemini()
    _vigilar(respuesta.leer(flujo))
    return respuesta


def _nombre(valor: Any) -> str:
    return getattr(valor, "value", None) or str(valor)


class GeminiClient:
    def __init__(self, client: Any = None):
        self._client = client

    def _cliente(self) -> Any:
        if self._client is None:
            from google import genai

            clave = os.environ.get("GEMINI_API_KEY", "").strip()
            if not clave:
                raise ErrorLLM("No hay credenciales para el proveedor (GEMINI_API_KEY): agregue la clave de Gemini en Inteligencia artificial.")
            if not clave_valida(clave):
                raise ErrorLLM(
                    "La clave de Gemini (GEMINI_API_KEY) tiene caracteres no válidos (solo ASCII visible, sin espacios ni saltos de línea): "
                    "vuelva a agregarla en Inteligencia artificial."
                )
            self._client = genai.Client(api_key=clave, vertexai=False)
        return self._client

    def estructurado(
        self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config
    ) -> tuple[BaseModel, dict]:
        from google.genai import errors, types

        modelo = cfg.modelo_para(nodo)
        nivel = cfg.effort_para(nodo)
        admitidos = niveles_admitidos("gemini", modelo) or ()
        if nivel not in admitidos:
            raise ErrorLLM(f"El nivel de razonamiento {nivel} no es válido para {modelo} (admite: {', '.join(admitidos)}).")
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=esquema_gemini(schema),
            max_output_tokens=cfg.llm.max_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[nivel.upper()]),
            store=False,
            http_options=types.HttpOptions(
                timeout=round(cfg.llm.timeout_s * 1000),
                retry_options=types.HttpRetryOptions(attempts=cfg.llm.max_retries + 1),
            ),
        )
        cliente = self._cliente()
        try:
            resp = _transmitir(
                lambda: contextlib.closing(cliente.models.generate_content_stream(model=modelo, contents=user, config=config)),
                _consumir_gemini,
            )
        except (errors.APIError, errors.UnknownApiResponseError, httpx.HTTPError) as e:
            raise ErrorLLM(f"Error del proveedor ({type(e).__name__}): {e}") from e
        if resp.bloqueo:
            raise ErrorLLM(f"Gemini bloqueó la solicitud (block_reason={_nombre(resp.bloqueo)}).")
        if resp.fin == types.FinishReason.MAX_TOKENS:
            raise ErrorLLM(
                f"La respuesta se cortó por el límite de tokens ({cfg.llm.max_tokens}); aumente llm.max_tokens."
            )
        if resp.fin != types.FinishReason.STOP:
            raise ErrorLLM(f"Gemini detuvo la respuesta (finish_reason={_nombre(resp.fin) if resp.fin else 'ausente'}).")
        texto = "".join(resp.texto)
        if not texto.strip():
            raise ErrorLLM(f"El modelo no devolvió una salida estructurada (stop_reason={_nombre(resp.fin)}).")
        try:
            salida = schema.model_validate_json(texto)
        except ValidationError as e:
            raise ErrorLLM(f"La respuesta del modelo no cumple el esquema: {_resumen_errores(e)}.") from e
        uso = resp.uso
        meta = {
            "modelo_efectivo": resp.modelo or modelo,
            "tokens_entrada": (uso and uso.prompt_token_count) or 0,
            "tokens_salida": ((uso and uso.candidates_token_count) or 0) + ((uso and uso.thoughts_token_count) or 0),
            "stop_reason": _nombre(resp.fin),
        }
        return salida, meta


def _tokens(resp: Any) -> tuple[int, int]:
    iteraciones = getattr(resp.usage, "iterations", None)
    if iteraciones:
        return (
            sum(getattr(i, "input_tokens", 0) or 0 for i in iteraciones),
            sum(getattr(i, "output_tokens", 0) or 0 for i in iteraciones),
        )
    return resp.usage.input_tokens, resp.usage.output_tokens


def _resumen_errores(e: ValidationError, maximo: int = 5) -> str:
    errores = e.errors()
    partes = [f"{'.'.join(str(p) for p in err['loc']) or 'raíz'}: {err['msg']}" for err in errores[:maximo]]
    resto = f" (+{len(errores) - maximo} más)" if len(errores) > maximo else ""
    return "; ".join(partes) + resto


class FakeClient:
    def __init__(self) -> None:
        self.llamadas: list[tuple[str, str]] = []

    def estructurado(
        self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config
    ) -> tuple[BaseModel, dict]:
        self.llamadas.append((nodo, user))
        secs = leer_secciones(user)
        if schema is AperturaLLM:
            salida = self._apertura(secs)
        elif schema is ConsideracionesLLM:
            salida = self._consideraciones(secs)
        elif schema is CasoConcretoLLM:
            salida = self._caso(secs)
        elif schema is ApoderadosLLM:
            salida = self._apoderados(secs)
        else:
            raise ErrorLLM(f"FakeClient no soporta el esquema {schema.__name__}.")
        meta = {
            "modelo_efectivo": "fake",
            "tokens_entrada": len(user) // 4,
            "tokens_salida": len(salida.model_dump_json()) // 4,
            "stop_reason": "end_turn",
        }
        return salida, meta

    def _apertura(self, secs: dict[str, str]) -> AperturaLLM:
        docs = _parsear_docs(secs.get("DOCUMENTOS", ""))
        meta = json.loads(secs.get("METADATOS", "{}") or "{}")
        por_rol: dict[str, list[dict]] = {}
        for d in docs:
            por_rol.setdefault(d["rol"], []).append(d)

        cronologia = []
        for rol, descripcion in _ROLES_EVENTO:
            for d in por_rol.get(rol, [])[:1]:
                cita = _ventanas(d["texto"], 14)
                if cita:
                    cronologia.append(
                        Evento(
                            fecha=None,
                            hecho=f"Obra en el expediente {descripcion}.",
                            doc_id=d["doc_id"],
                            cita_literal=cita[min(1, len(cita) - 1)],
                        )
                    )

        reparos = []
        for d in por_rol.get("impugnacion", [])[:1]:
            ventanas = _ventanas(d["texto"], 14)
            for i, v in enumerate(_repartidas(ventanas, 3), start=1):
                reparos.append(
                    Reparo(
                        id=f"R{i}",
                        sintesis=f"El impugnante señala que «{v}».",
                        doc_id=d["doc_id"],
                        cita_literal=v,
                    )
                )

        contestaciones = [
            Contestacion(
                entidad=re.sub(r"^[\d_ ]+|\.\w+$", "", d["nombre"]) or "Entidad",
                silencio=False,
                texto=_contestacion_fake(d["texto"]),
            )
            for d in por_rol.get("contestacion", [])
        ]

        fallo = " ".join(d["texto"] for d in por_rol.get("fallo_a_quo", [])).upper()
        escrito = " ".join(d["texto"] for d in por_rol.get("escrito_tutela", [])).lower()
        derechos = meta.get("derechos_invocados") or [x for x in _DERECHOS if x in escrito]

        metadatos = MetadatosLLM(
            juzgado_a_quo=meta.get("juzgado_a_quo"),
            accionante=meta.get("accionante"),
            accionadas=meta.get("accionadas") or [],
            vinculadas=meta.get("vinculadas") or [],
            impugnante=meta.get("impugnante"),
            impugnante_rol=meta.get("impugnante_rol"),
            derechos_invocados=derechos,
            decision_a_quo=meta.get("decision_a_quo") or _decision_a_quo(fallo),
            impugnantes=meta.get("impugnantes") or [meta.get("impugnante") or "la parte impugnante"],
            resultado_a_quo=meta.get("resultado_a_quo") or "resolvió la acción de tutela",
            resultado_a_quo_se=meta.get("resultado_a_quo_se") or "resolvió la acción de tutela",
            accionante_tratamiento=meta.get("accionante_tratamiento") or "el señor",
            accionante_identificacion=meta.get("accionante_identificacion") or "identificado con cédula de ciudadanía",
            juez_a_quo_nombres=meta.get("juez_a_quo_nombres") or "Juez",
            juez_a_quo_apellidos=meta.get("juez_a_quo_apellidos") or "De Primera",
            genero_accionadas=meta.get("genero_accionadas") or "f",
            genero_vinculadas=meta.get("genero_vinculadas") or "f",
        )
        impugnacion = [f"En relación con el reparo {r.id}, {_minuscula(r.sintesis)}" for r in reparos]
        impugnacion.append(
            "Con fundamento en lo anterior, el impugnante solicita al superior que revoque el fallo de primera instancia."
        )
        return AperturaLLM(
            metadatos=metadatos,
            cronologia=cronologia,
            antecedentes_hechos=(
                "El accionante acudió a la acción de tutela para solicitar la protección de sus derechos fundamentales, según consta en el escrito que dio inicio al trámite.\n\n"
                "El juez de primera instancia admitió la acción y dispuso la notificación de las entidades accionadas y vinculadas."
            ),
            contestaciones=contestaciones,
            sentencia_impugnada=(
                "El juez de primera instancia resolvió la acción de tutela y expuso las razones de su decisión frente a los requisitos de procedibilidad y al fondo del asunto."
            ),
            impugnacion="\n\n".join(impugnacion),
            reparos=reparos,
            pruebas_nuevas_2a=[],
        )

    def _consideraciones(self, secs: dict[str, str]) -> ConsideracionesLLM:
        reparos = json.loads(secs.get("REPAROS", "[]") or "[]")
        ids = [r["id"] for r in reparos]
        maximo = int(re.search(r"\d+", secs.get("LIMITES", "3")).group())
        citas = [CitaPropuesta(id=i, sentencia=s, texto_citado=t, reparo_ids=ids) for i, (s, t) in CITAS_FAKE.items()]
        bloque1 = BloqueLLM(
            titulo="La carencia actual de objeto por hecho superado",
            reparo_ids=ids,
            texto=(
                "La carencia actual de objeto por hecho superado se configura cuando desaparece la afectación que dio origen a la acción de tutela y la pretensión queda satisfecha. "
                "En la [[CITA:c1]], la Corte Constitucional explicó los presupuestos de esta figura y su alcance frente a la pretensión de la acción."
            ),
        )
        bloque2 = BloqueLLM(
            titulo="El término razonable de conservación del dato negativo",
            reparo_ids=ids,
            texto=(
                "La Corte Constitucional ha entendido que, a falta de regulación legal expresa, corresponde al juez fijar un término razonable para la conservación de los datos negativos. "
                "En la [[CITA:c2]], la corporación precisó el criterio que orienta esa determinación."
            ),
        )
        bloques = [bloque1, bloque2]
        if maximo < 2:
            bloques = [bloque1.model_copy(update={"texto": bloque1.texto + "\n\n" + bloque2.texto})]
        return ConsideracionesLLM(
            procedibilidad=(
                "La acción de tutela procede cuando el afectado no dispone de otro medio de defensa judicial idóneo y eficaz, o cuando, existiendo, se utiliza para evitar un perjuicio irremediable. "
                "Además, debe interponerse dentro de un plazo razonable contado desde la acción u omisión que se estima vulneradora."
            ),
            bloques=bloques,
            citas=citas,
        )

    def _caso(self, secs: dict[str, str]) -> CasoConcretoLLM:
        decision = json.loads(secs.get("DECISION", "{}") or "{}")
        reparos = json.loads(secs.get("REPAROS", "[]") or "[]")
        disponibles = json.loads(secs.get("CITAS", "[]") or "[]")
        citas = [c for c in disponibles if c.get("estado") == "ok"] or [c for c in disponibles if c.get("estado") == "alerta"]

        def apoyo(i: int) -> str:
            return f" Esto se apoya en la [[CITA:{citas[i % len(citas)]['id']}]]." if citas else ""

        parrafos = []
        for i, r in enumerate(reparos):
            valoracion = _VALORACION.get(
                r.get("disposicion"), "El Despacho lo resuelve conforme al eje de la decisión."
            )
            parrafos.append(
                ParrafoLLM(
                    reparo_ids=[r["id"]],
                    texto=f"Sobre el reparo {r['id']}, {_minuscula(r['sintesis'])} {valoracion}{apoyo(i)}",
                )
            )
        if not parrafos:
            parrafos.append(
                ParrafoLLM(
                    reparo_ids=[],
                    texto=(
                        "El Despacho revisó la decisión de primera instancia a la luz de lo expuesto en las "
                        f"consideraciones.{apoyo(0)}"
                    ),
                )
            )
        plazos = _plazos_de_ordenes(decision.get("ordenes") or [])
        if plazos:
            parrafos.append(
                ParrafoLLM(
                    reparo_ids=[],
                    texto=(
                        f"Frente a las órdenes que se impartirán, el Despacho considera que el plazo de {plazos} "
                        "resulta proporcional al alcance de la medida y a la urgencia que el caso exige."
                    ),
                )
            )
        resultado = _VERBO_RESULTADO.get(decision.get("resultado"), "resolver sobre")
        sustitutiva = _VERBO_SUSTITUTIVA.get(decision.get("sustitutiva"), "resolver lo pertinente")
        return CasoConcretoLLM(
            problema_juridico="Corresponde al Despacho determinar si la decisión de primera instancia se ajusta a la Constitución y a la ley a la luz de los reparos formulados por el impugnante.",
            parrafos=parrafos,
            conclusion=f"En consecuencia, el Despacho considera que debe {resultado} el fallo de primera instancia y {sustitutiva}.",
        )

    def _apoderados(self, secs: dict[str, str]) -> ApoderadosLLM:
        meta = json.loads(secs.get("METADATOS", "{}") or "{}")
        partes = [(meta.get("accionante") or "", "accionante")]
        partes += [(n, "accionada") for n in meta.get("accionadas") or []]
        partes += [(n, "vinculada") for n in meta.get("vinculadas") or []]
        partes = [(n, r) for n, r in partes if n]
        paginas = _paginas_fake(secs.get("DOCUMENTOS", ""))
        certificados = [(doc_id, n, plano) for doc_id, n, certificado, plano in paginas if certificado]
        abogados: dict[tuple[str, str], AbogadoLLM] = {}
        for doc_id, n, certificado, plano in paginas:
            if certificado:
                continue
            for m in _FAKE_ABOGADO.finditer(plano):
                tras = plano[m.end() : m.end() + 300]
                tp = _FAKE_TP.search(tras)
                if not tp:
                    continue
                nombre = " ".join(m.group("nombre").split())
                parte = _parte_cercana(plano, m.start(), [p for p, _ in partes])
                ab = abogados.setdefault((apoderados.clave(nombre), parte), AbogadoLLM(nombre=nombre, parte=parte))
                cc = _FAKE_CC.search(tras)
                ab.tarjeta_texto = ab.tarjeta_texto or tp.group(1)
                ab.cedula_texto = ab.cedula_texto or (cc.group(1) if cc else "")
                otorga = list(_FAKE_OTORGA.finditer(plano, max(0, m.start() - 600), m.start()))
                if not otorga:
                    ab.menciones.append(MencionLLM(doc_id=doc_id, pagina=n, cita=_ventana_fake(plano, m.start(), m.end())))
                    continue
                kw = otorga[-1]
                otorgante = next(
                    (r.group(1) for r in reversed(list(_FAKE_REPRESENTANTE.finditer(plano, 0, kw.start())))), ""
                )
                tokens = apoderados.tokens_nombre(otorgante)
                cert_doc, cert_n = next(
                    (
                        (d, k)
                        for d, k, t in certificados
                        if tokens and apoderados.ocurrencias(tokens, apoderados.plegar(t), apoderados.minimo_nombre(len(tokens)))
                    ),
                    ("", 0),
                )
                ab.poderes.append(
                    PoderLLM(
                        tipo="sustitucion" if kw.group().lower().startswith("sustitu") else "poder",
                        doc_id=doc_id,
                        pagina=n,
                        cita=_ventana_fake(plano, kw.start(), m.end(), antes=0),
                        otorgante=otorgante,
                        cargo_otorgante="representante legal" if otorgante else "",
                        certificado_doc_id=cert_doc,
                        certificado_pagina=cert_n,
                    )
                )
        representadas = {parte for _, parte in abogados}
        return ApoderadosLLM(
            partes=[ParteLLM(nombre=n, rol_parte=r, con_abogado=n in representadas) for n, r in partes],
            abogados=list(abogados.values()),
        )


_NOMBRE_FAKE = r"(?P<nombre>(?:[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü]+\s+){1,4}[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü]+)"
_FAKE_ABOGADO = re.compile(r"(?<!\w)(?P<titulo>(?i:doctora?|dra?\.|abogad[oa]))\s+" + _NOMBRE_FAKE)
_FAKE_TP = re.compile(r"(?i:\bt\.\s?p\.|tarjeta\s+profesional)\s?(?i:n[o°º]\.?\s?)?(\d{1,3}(?:\.\d{3})+|\d{3,7})")
_FAKE_CC = re.compile(r"(?i:\bc\.\s?c\.|c[ée]dula\s+de\s+ciudadan[íi]a)\s?(?i:n[o°º]\.?\s?)?(\d{1,3}(?:\.\d{3})+|\d{5,10})")
_FAKE_OTORGA = re.compile(r"(?i)\b(?:confiero|otorgo|sustituyo)\b")
_FAKE_REPRESENTANTE = re.compile(r"((?:[A-ZÁÉÍÓÚÑ]{2,} ){1,4}[A-ZÁÉÍÓÚÑ]{2,}),[\s\S]{0,200}?(?i:representante\s+legal)")
_PAGINA_FAKE = re.compile(rf"^\[p\. (\d+)\]( {re.escape(ETIQUETA_CERTIFICADO)})?[ \t]*$", re.M)


def _paginas_fake(documentos: str) -> list[tuple[str, int, bool, str]]:
    salida = []
    for d in _parsear_docs(documentos):
        partes = _PAGINA_FAKE.split(d["texto"])
        for i in range(1, len(partes) - 2, 3):
            lineas = (" ".join(linea.split()) for linea in partes[i + 2].splitlines())
            salida.append((d["doc_id"], int(partes[i]), bool(partes[i + 1]), "\n".join(filter(None, lineas))))
    return salida


def _ventana_fake(plano: str, ini: int, fin: int, antes: int = 6, despues: int = 14) -> str:
    palabras = list(re.finditer(r"\S+", plano))
    primera = next(i for i, w in enumerate(palabras) if w.end() > ini)
    ultima = max(i for i, w in enumerate(palabras) if w.start() < fin)
    a, b = max(0, primera - antes), min(len(palabras) - 1, ultima + despues)
    a = max(a, b - 59)
    return " ".join(plano[palabras[a].start() : palabras[b].end()].split())


def _parte_cercana(plano: str, pos: int, partes: list[str]) -> str:
    plegado = apoderados.plegar(plano)
    antes, despues = [], []
    for nombre in partes:
        tokens = apoderados.tokens_parte(nombre)
        for ini, _ in apoderados.ocurrencias(tokens, plegado, apoderados.minimo_parte(len(tokens))):
            (antes if ini < pos else despues).append((ini, nombre))
    if antes:
        return max(antes)[1]
    if despues:
        return min(despues)[1]
    return partes[0] if partes else ""


def _contestacion_fake(texto: str) -> str:
    plano = "\n".join(filter(None, (" ".join(linea.split()) for linea in texto.splitlines())))
    abogado = next((m for m in _FAKE_ABOGADO.finditer(plano) if _FAKE_TP.search(plano, m.end(), m.end() + 300)), None)
    if abogado is None:
        return "La entidad dio respuesta a la acción de tutela y solicitó que se negara el amparo por improcedente."
    nombre = " ".join(abogado.group("nombre").split()).title()
    femenino = abogado.group("titulo").lower() in ("doctora", "dra.", "abogada")
    quien = f"su apoderada judicial, la doctora {nombre}" if femenino else f"su apoderado judicial, el doctor {nombre}"
    return f"La entidad, mediante {quien}, dio respuesta a la acción de tutela y solicitó que se negara el amparo por improcedente."


_ROLES_EVENTO = (
    ("escrito_tutela", "el escrito de tutela"),
    ("auto_admisorio", "el auto que admitió la acción"),
    ("fallo_a_quo", "el fallo de primera instancia"),
    ("impugnacion", "el escrito de impugnación"),
    ("auto_concede_impugnacion", "el auto que concedió la impugnación"),
)

_DERECHOS = ("salud", "petición", "debido proceso", "mínimo vital", "vida", "habeas data", "educación", "igualdad")

_VALORACION = {
    "ACOGE": "El Despacho considera que este reparo prospera.",
    "DESESTIMA": "El Despacho considera que este reparo no prospera.",
    "ACOGE_PARCIAL": "El Despacho considera que este reparo prospera solo en parte.",
    "REFORMULA": "El Despacho replantea este reparo en los términos de la decisión.",
}

_VERBO_RESULTADO = {"CONFIRMAR": "confirmar", "REVOCAR": "revocar", "MODIFICAR": "modificar"}

_VERBO_SUSTITUTIVA = {
    "AMPARAR": "amparar los derechos fundamentales invocados",
    "NEGAR": "negar el amparo solicitado",
    "IMPROCEDENTE": "declarar improcedente la acción de tutela",
    "CARENCIA_HECHO_SUPERADO": "declarar la carencia actual de objeto por hecho superado",
    "CARENCIA_DANO_CONSUMADO": "declarar la carencia actual de objeto por daño consumado",
    "CARENCIA_SOBREVINIENTE": "declarar la carencia actual de objeto por situación sobreviniente",
}


_UNIDAD_PLAZO = {
    "horas_habiles": ("hora hábil", "horas hábiles"),
    "horas": ("hora", "horas"),
    "dias_habiles": ("día hábil", "días hábiles"),
    "dias": ("día", "días"),
}


def _plazos_de_ordenes(ordenes: list[dict]) -> str:
    plazos: list[str] = []
    for o in ordenes:
        if o.get("verbo", "ORDENAR") != "ORDENAR" or o.get("mismo_termino"):
            continue
        plazo = o.get("plazo") or {}
        n = plazo.get("n", 48)
        singular, plural = _UNIDAD_PLAZO[plazo.get("unidad", "horas_habiles")]
        texto = f"{n} {singular if n == 1 else plural}"
        if texto not in plazos:
            plazos.append(texto)
    return " y ".join(plazos)


def _decision_a_quo(fallo: str) -> str:
    if "IMPROCEDENT" in fallo:
        return "declaró improcedente la acción de tutela"
    if "NEG" in fallo or "NIEG" in fallo:
        return "negó el amparo solicitado"
    if "AMPAR" in fallo or "CONCED" in fallo or "TUTELAR" in fallo:
        return "amparó los derechos fundamentales invocados"
    return "resolvió la acción de tutela"


def _minuscula(texto: str) -> str:
    return texto[:1].lower() + texto[1:]


def _parsear_docs(texto: str) -> list[dict]:
    partes = re.split(r"^### DOC (\S+) \| (\S+) \| (.*)$", texto, flags=re.M)
    return [
        {"doc_id": partes[i], "rol": partes[i + 1], "nombre": partes[i + 2].strip(), "texto": partes[i + 3]}
        for i in range(1, len(partes) - 3, 4)
    ]


def _ventanas(texto: str, n: int) -> list[str]:
    ventanas: list[str] = []
    for pagina in re.split(r"\[p\. \d+\]", texto):
        pagina = " ".join(pagina.split())
        palabras = pagina.split(" ")
        i = 0
        pos = 0
        while i + n <= len(palabras):
            v = " ".join(palabras[i : i + n])
            inicio = pagina.find(v, pos)
            contexto = pagina[max(0, inicio - 200) : inicio + len(v) + 200]
            limpio = not re.search(r"[\[\]()…]", contexto) and sum(w.isalpha() for w in palabras[i : i + n]) >= n - 2
            if limpio:
                ventanas.append(v)
                pos = inicio + len(v)
                i += n
            else:
                i += 1
    return ventanas


def _repartidas(items: list[str], k: int) -> list[str]:
    if len(items) <= k:
        return items
    paso = len(items) / k
    return [items[int(j * paso)] for j in range(k)]


def _exigir_modelos_permitidos(cfg: Config) -> None:
    for nodo in NODOS_LLM:
        modelo = cfg.modelo_para(nodo)
        if not modelo_permitido(modelo, cfg.llm.proveedor):
            permitidos = ", ".join(modelos_permitidos(cfg.llm.proveedor)) or "ninguno"
            raise ErrorLLM(
                f"El modelo {modelo} (nodo {nodo}) no está permitido en este servidor "
                f"({VARIABLE_MODELOS_PERMITIDOS}); permitidos: {permitidos}."
            )


def cliente_para(cfg: Config) -> LLMClient:
    if cfg.llm.proveedor == "fake":
        return FakeClient()
    _exigir_modelos_permitidos(cfg)
    if cfg.llm.proveedor == "gemini":
        return GeminiClient()
    return AnthropicClient()
