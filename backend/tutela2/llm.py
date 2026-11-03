from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from tutela2.config import RESPALDO_CLIENTE, Config
from tutela2.models import (
    AperturaLLM,
    BloqueLLM,
    CasoConcretoLLM,
    CitaPropuesta,
    ConsideracionesLLM,
    Contestacion,
    Evento,
    MetadatosLLM,
    ParrafoLLM,
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
            with cliente.beta.messages.stream(**args, betas=[BETA_FALLBACK], fallbacks="default") as flujo:
                return flujo.get_final_message()
        except self._anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            log.warning("La API rechazó los fallbacks del servidor; se reintenta sin ellos: %s", e)
            return self._una(cliente, args)

    @staticmethod
    def _una(cliente: Any, args: dict):
        with cliente.messages.stream(**args) as flujo:
            return flujo.get_final_message()


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
                texto="La entidad dio respuesta a la acción de tutela y solicitó que se negara el amparo por improcedente.",
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
        citas = [c for c in json.loads(secs.get("CITAS", "[]") or "[]") if c.get("estado") in ("ok", "alerta")]
        parrafos = []
        for i, r in enumerate(reparos):
            apoyo = f" Esto se apoya en la [[CITA:{citas[i % len(citas)]['id']}]]." if citas else ""
            valoracion = _VALORACION.get(
                r.get("disposicion"), "El Despacho lo resuelve conforme al eje de la decisión."
            )
            parrafos.append(
                ParrafoLLM(
                    reparo_ids=[r["id"]],
                    texto=f"Sobre el reparo {r['id']}, {_minuscula(r['sintesis'])} {valoracion}{apoyo}",
                )
            )
        if not parrafos:
            parrafos.append(
                ParrafoLLM(
                    reparo_ids=[],
                    texto="El Despacho revisó la decisión de primera instancia a la luz de lo expuesto en las consideraciones.",
                )
            )
        resultado = _VERBO_RESULTADO.get(decision.get("resultado"), "resolver sobre")
        sustitutiva = _VERBO_SUSTITUTIVA.get(decision.get("sustitutiva"), "resolver lo pertinente")
        return CasoConcretoLLM(
            problema_juridico="Corresponde al Despacho determinar si la decisión de primera instancia se ajusta a la Constitución y a la ley a la luz de los reparos formulados por el impugnante.",
            parrafos=parrafos,
            conclusion=f"En consecuencia, el Despacho considera que debe {resultado} el fallo de primera instancia y {sustitutiva}.",
        )


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


def cliente_para(cfg: Config) -> LLMClient:
    if cfg.llm.proveedor == "fake":
        return FakeClient()
    return AnthropicClient()
