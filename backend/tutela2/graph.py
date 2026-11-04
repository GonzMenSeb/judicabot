from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from tutela2 import citas, eventos, expediente, fallos, ingest, lint, prompts
from tutela2.config import Config
from tutela2.jev import JevClient, cliente_jev
from tutela2.jev_metadatos import verificar_apertura
from tutela2.llm import LLMClient, leer_secciones, seccion
from tutela2.models import (
    AperturaLLM,
    CasoConcretoLLM,
    CitaVerificada,
    ConsideracionesLLM,
    Decision,
    Doc,
    Estado,
    Ingesta,
    LlamadaIA,
    Metadatos,
    MetadatosLLM,
    Pagina,
)

log = logging.getLogger("tutela2")

REGLA_DE_ORO = "Regla de oro: cambia la cita, nunca la tesis."


def estado_inicial(caso_dir: Path, cfg: Config, ing: Ingesta) -> Estado:
    return {
        "caso_dir": str(caso_dir),
        "config": cfg.model_dump(mode="json"),
        "ingesta": ing.model_dump(mode="json"),
        "metadatos": ing.metadatos.model_dump(mode="json"),
        "apertura": None,
        "consideraciones": None,
        "citas": [],
        "decisiones": [],
        "caso": None,
        "errores": [],
        "alertas": {},
        "intentos": {},
        "bitacora": list(ing.llamadas_jev),
        "salidas": {},
        "jev_metadatos": None,
    }


def _json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unicos(mensajes: list[str]) -> list[str]:
    return list(dict.fromkeys(mensajes))


def _bloqueantes(mensajes: list[str]) -> list[str]:
    return [m for m in mensajes if m.startswith("BLOQUEA:")]


_ETIQUETA_EXTENSION = {
    "antecedentes": "antecedentes (hechos y contestaciones sumados)",
    "consideraciones": "consideraciones (solo tu parte; el sistema antepone otras piezas)",
}
_SECCIONES_INSTRUCCION = ("EXTENSION", "LIMITES", "LISTAS", "ERRORES", "INSTRUCCION")


def _extension(cfg: Config, campos: tuple[str, ...]) -> str:
    return "\n".join(
        f"{_ETIQUETA_EXTENSION.get(c, c)}: entre {cfg.rango_palabras[c][0]} y {cfg.rango_palabras[c][1]} palabras"
        for c in campos
    )


def _instrucciones(user: str) -> str:
    secs = leer_secciones(user)
    return "\n\n".join(f"=== {t} ===\n{secs[t]}" for t in _SECCIONES_INSTRUCCION if t in secs)


def _ultima_decision(state: Estado) -> dict | None:
    decisiones = state.get("decisiones") or []
    return decisiones[-1] if decisiones else None


def _correcciones(state: Estado, nodo: str, rehacer: str | None, previa: str | None = None) -> list[str]:
    partes = []
    if state.get("intentos", {}).get(nodo, 0) > 0 and state.get("errores"):
        if state.get(previa or ""):
            partes.append(seccion("SALIDA ANTERIOR", _json(state[previa])))
        partes.append(seccion("ERRORES", "\n".join(f"- {e}" for e in state["errores"])))
    d = _ultima_decision(state)
    if rehacer and d and d["accion"] == rehacer and d.get("instruccion"):
        partes.append(seccion("INSTRUCCION", d["instruccion"]))
    return partes


def _llamar(
    cliente: LLMClient, cfg: Config, state: Estado, nodo: str, user: str, schema: type[BaseModel]
) -> tuple[Any, dict, dict]:
    system, prompt_id = prompts.prompt_para(nodo, cfg)
    intentos = dict(state.get("intentos") or {})
    intento = intentos.get(nodo, 0) + 1
    log.info("%s: llamada al modelo, intento %d", nodo, intento)
    modelo = cfg.modelo_para(nodo)
    eventos.emitir(
        nodo,
        "lee",
        f"Llamada al modelo {modelo}{'' if cfg.llm.proveedor == 'anthropic' else f' (proveedor {cfg.llm.proveedor})'}, "
        f"intento {intento}: {len(user)} caracteres de entrada.",
        {"nodo": nodo, "intento": intento, "modelo": modelo, "proveedor": cfg.llm.proveedor, "caracteres_entrada": len(user)},
    )
    try:
        salida, meta = cliente.estructurado(nodo, system, user, schema, cfg)
    except Exception as e:
        eventos.emitir(
            nodo,
            "error",
            f"La llamada al modelo falló en el intento {intento}: {type(e).__name__}: {e}",
            {"nodo": nodo, "intento": intento, "tipo_error": type(e).__name__},
        )
        try:
            fallos.registrar(
                Path(state["caso_dir"]),
                {
                    "nodo": nodo,
                    "fecha": _ahora(),
                    "exitos": sum(1 for b in state.get("bitacora") or [] if b.get("nodo") == nodo),
                    "proveedor": cfg.llm.proveedor,
                    "modelo_pedido": cfg.modelo_para(nodo),
                    "prompt_id": prompt_id,
                    "sha256_entrada": _sha(user),
                    "tipo_error": type(e).__name__,
                    "error": str(e),
                },
            )
        except OSError:
            log.exception("%s: no se pudo registrar la llamada fallida", nodo)
        raise
    log.info("%s: respuesta recibida (%s tokens de salida)", nodo, meta.get("tokens_salida") or "?")
    eventos.emitir(
        nodo,
        "escribe",
        f"Respuesta del modelo recibida: {meta.get('tokens_salida') or '?'} tokens de salida.",
        {
            "nodo": nodo,
            "intento": intento,
            "modelo_efectivo": meta.get("modelo_efectivo"),
            "tokens_entrada": meta.get("tokens_entrada"),
            "tokens_salida": meta.get("tokens_salida"),
        },
    )
    llamada = LlamadaIA(
        nodo=nodo,
        intento=intento,
        proveedor=cfg.llm.proveedor,
        modelo_pedido=cfg.modelo_para(nodo),
        modelo_efectivo=meta.get("modelo_efectivo"),
        prompt_id=prompt_id,
        sha256_instrucciones=_sha(system),
        sha256_entrada=_sha(user),
        instrucciones=_instrucciones(user),
        sha256_salida=_sha(salida.model_dump_json()),
        fecha=_ahora(),
        tokens_entrada=meta.get("tokens_entrada"),
        tokens_salida=meta.get("tokens_salida"),
    )
    intentos[nodo] = intento
    return salida, llamada.model_dump(mode="json"), intentos


def _fusionar_metadatos(codigo: Metadatos, modelo: MetadatosLLM) -> Metadatos:
    datos = codigo.model_dump()
    for campo, valor in modelo.model_dump().items():
        if valor != "" and not datos.get(campo):
            datos[campo] = valor
    return Metadatos.model_validate(datos)


_ETAPA_VALIDACION = {"consideraciones": "verificacion"}


def _cierre_validacion(state: Estado, cfg: Config, nodo: str, mensajes: list[str]) -> dict:
    mensajes = _unicos(mensajes)
    bloqueantes = _bloqueantes(mensajes)
    agotados = bloqueantes and state.get("intentos", {}).get(nodo, 0) >= cfg.max_intentos
    if bloqueantes:
        log.warning(
            "%s: %d errores bloqueantes%s", nodo, len(bloqueantes), "" if agotados else "; se repite la llamada"
        )
        for e in bloqueantes[:3]:
            log.warning("  %s", e[:240])
    if agotados:
        mensajes.append(
            f"ALERTA: Se agotaron los {cfg.max_intentos} intentos de {nodo} sin resolver los errores bloqueantes; revise manualmente."
        )
    intento = state.get("intentos", {}).get(nodo, 0)
    n_alertas = sum(1 for m in mensajes if m.startswith("ALERTA:"))
    if not bloqueantes:
        texto = f"Validación sin errores bloqueantes: {n_alertas} alerta{'' if n_alertas == 1 else 's'} para revisar."
    elif agotados:
        texto = f"Se agotaron los {cfg.max_intentos} intentos con {len(bloqueantes)} errores bloqueantes sin resolver; queda para revisión manual."
    else:
        texto = f"{len(bloqueantes)} errores bloqueantes; se repite la llamada (intento {intento + 1} de {cfg.max_intentos})."
    eventos.emitir(
        _ETAPA_VALIDACION.get(nodo, nodo),
        "verifica",
        texto,
        {"nodo": nodo, "intento": intento, "bloqueantes": [e[:240] for e in bloqueantes[:3]], "n_bloqueantes": len(bloqueantes), "n_alertas": n_alertas},
    )
    return {"errores": bloqueantes, "alertas": {**(state.get("alertas") or {}), nodo: mensajes}}


def nodo_apertura(state: Estado, cfg: Config, cliente: LLMClient) -> dict:
    ing = Ingesta.model_validate(state["ingesta"])
    texto = ingest.texto_para_llm(ing, max_chars=cfg.max_chars_documento)
    user = "\n".join(
        [
            seccion("DOCUMENTOS", texto),
            seccion("METADATOS", _json(ing.metadatos.model_dump(mode="json"))),
            seccion("EXTENSION", _extension(cfg, ("antecedentes", "sentencia_impugnada", "impugnacion"))),
            *_correcciones(state, "apertura", "rehacer_apertura", "apertura"),
        ]
    )
    ap, llamada, intentos = _llamar(cliente, cfg, state, "apertura", user, AperturaLLM)
    metadatos = _fusionar_metadatos(ing.metadatos, ap.metadatos)
    return {
        "apertura": ap.model_dump(mode="json"),
        "metadatos": metadatos.model_dump(mode="json"),
        "intentos": intentos,
        "bitacora": [llamada],
        "alertas": {**(state.get("alertas") or {}), "ingesta": list(ing.alertas)},
    }


_CAMPOS_COMPARABLES = ("juzgado_a_quo", "accionante", "accionadas", "vinculadas", "impugnante", "impugnante_rol")


def _clave_comparable(valor: Any) -> Any:
    def uno(v: str) -> str:
        return unicodedata.normalize("NFC", " ".join(v.split())).casefold()

    if isinstance(valor, list):
        return sorted(uno(v) for v in valor)
    return uno(valor) if isinstance(valor, str) else valor


def _verificar_metadatos(ap: AperturaLLM, ing: Ingesta) -> list[str]:
    mensajes: list[str] = []
    modelo = ap.metadatos.model_dump()
    for campo, valor in modelo.items():
        textos = [valor] if isinstance(valor, str) else valor
        for texto in filter(None, textos):
            mensajes += [
                f"{m.rstrip('.')} (metadatos, campo {campo})." for m in lint.datos_ajenos(texto, ing)
            ]
    codigo = ing.metadatos.model_dump()
    for campo in _CAMPOS_COMPARABLES:
        a, b = codigo.get(campo), modelo.get(campo)
        if a and b and _clave_comparable(a) != _clave_comparable(b):
            mensajes.append(
                f"{lint.ALERTA}En metadatos, campo {campo}, la ingesta extrajo {a!r} y el modelo leyó {b!r}; "
                "se conserva el de la ingesta, verifique cuál es correcto."
            )
    return mensajes


def nodo_validar_apertura(state: Estado, cfg: Config, jev: JevClient | None = None) -> dict:
    ap = AperturaLLM.model_validate(state["apertura"])
    ing = Ingesta.model_validate(state["ingesta"])
    mensajes = list(lint.anclas_literales(ap, ing))

    secciones = {
        "antecedentes": ap.antecedentes_hechos,
        "sentencia_impugnada": ap.sentencia_impugnada,
        "impugnacion": ap.impugnacion,
    }
    prosa = {**secciones, **{f"contestacion de {c.entidad}": c.texto for c in ap.contestaciones}}
    for campo, texto in prosa.items():
        mensajes += lint.lint_prosa(texto, campo)
        mensajes += lint.datos_ajenos(texto, ing)
        mensajes += lint.residuos(texto)
    antecedentes = "\n\n".join([ap.antecedentes_hechos, *(c.texto for c in ap.contestaciones)])
    medidas = {**secciones, "antecedentes": antecedentes}
    for campo, texto in medidas.items():
        mensajes += lint.extension(texto, cfg.rango_palabras[campo], campo)
    mensajes += _verificar_metadatos(ap, ing)
    alertas_jev, llamadas_jev, metadatos_jev = verificar_apertura(ing, ap, jev, cfg)
    mensajes += alertas_jev
    mensajes += lint.duplicados(
        [p for texto in prosa.values() for p in texto.split("\n\n") if p.strip()], cfg.jaccard_duplicados
    )

    ids = [r.id for r in ap.reparos]
    if not ids:
        mensajes.append("ALERTA: No se identificó ningún reparo en el escrito de impugnación; revíselo.")
    if len(set(ids)) != len(ids):
        mensajes.append("BLOQUEA: Los identificadores de reparo (R1, R2, ...) deben ser únicos.")
    parrafos_impugnacion = [p for p in ap.impugnacion.split("\n\n") if p.strip()]
    if len(parrafos_impugnacion) < len(ids):
        mensajes.append("ALERTA: La sección de impugnación tiene menos párrafos que reparos; puede faltar alguno.")
    return {
        **_cierre_validacion(state, cfg, "apertura", mensajes),
        "bitacora": llamadas_jev,
        "jev_metadatos": metadatos_jev,
    }


def nodo_consideraciones(state: Estado, cfg: Config, cliente: LLMClient) -> dict:
    ap = AperturaLLM.model_validate(state["apertura"])
    md = Metadatos.model_validate(state["metadatos"])
    user = "\n".join(
        [
            seccion("REPAROS", _json([{"id": r.id, "sintesis": r.sintesis} for r in ap.reparos])),
            seccion("DERECHOS", _json(md.derechos_invocados)),
            seccion("SENTENCIA IMPUGNADA", ap.sentencia_impugnada),
            seccion("IMPUGNACION", ap.impugnacion),
            seccion("LIMITES", f"Máximo de bloques temáticos: {cfg.max_bloques_tematicos}"),
            seccion("EXTENSION", _extension(cfg, ("consideraciones",))),
            *_correcciones(state, "consideraciones", "rehacer_consideraciones", "consideraciones"),
        ]
    )
    cons, llamada, intentos = _llamar(cliente, cfg, state, "consideraciones", user, ConsideracionesLLM)
    return {"consideraciones": cons.model_dump(mode="json"), "intentos": intentos, "bitacora": [llamada]}


def nodo_verificar_consideraciones(state: Estado, cfg: Config) -> dict:
    cons = ConsideracionesLLM.model_validate(state["consideraciones"])
    ap = AperturaLLM.model_validate(state["apertura"])
    md = Metadatos.model_validate(state["metadatos"])

    verificadas = citas.verificar_citas(cons.citas, cfg, citas.cargar_dataset(cfg))
    por_estado = {e: sum(1 for cv in verificadas if cv.estado == e) for e in ("ok", "alerta", "rechazada")}
    eventos.emitir(
        "verificacion",
        "verifica",
        f"Informe de citas: {por_estado['ok']} verificadas, {por_estado['alerta']} para revisar, {por_estado['rechazada']} rechazadas.",
        por_estado,
    )
    mensajes: list[str] = []
    for cv in verificadas:
        detalle = "; ".join(cv.motivos) or "sin detalle"
        if cv.estado == "rechazada":
            mensajes.append(
                f"BLOQUEA: La cita {cv.id} ({cv.sentencia_original}) fue rechazada: {detalle}. {REGLA_DE_ORO}"
            )
        elif cv.estado == "alerta":
            mensajes.append(f"ALERTA: La cita {cv.id} ({cv.sentencia_original}) requiere revisión: {detalle}.")

    mensajes += lint.marcadores_consideraciones(cons)
    mensajes += lint.guardia_p3(cons, md)
    textos = {"procedibilidad": cons.procedibilidad, **{f"bloque {i}": b.texto for i, b in enumerate(cons.bloques, 1)}}
    for campo, texto in textos.items():
        mensajes += lint.lint_prosa(texto, f"consideraciones, {campo}")
        mensajes += lint.residuos(texto)
    mensajes += lint.extension("\n\n".join(textos.values()), cfg.rango_palabras["consideraciones"], "consideraciones")
    mensajes += lint.duplicados(
        [p for texto in textos.values() for p in texto.split("\n\n") if p.strip()], cfg.jaccard_duplicados
    )
    mensajes += lint.cobertura_reparos([b.reparo_ids for b in cons.bloques], ap.reparos)
    if len(cons.bloques) > cfg.max_bloques_tematicos:
        mensajes.append(
            f"ALERTA: Hay {len(cons.bloques)} bloques temáticos y el máximo configurado es {cfg.max_bloques_tematicos}."
        )

    return {
        "citas": [cv.model_dump(mode="json") for cv in verificadas],
        **_cierre_validacion(state, cfg, "consideraciones", mensajes),
    }


def _payload_decision(state: Estado) -> dict:
    ap = state["apertura"]
    md = state["metadatos"]
    return {
        "reparos": ap["reparos"],
        "decision_a_quo": md.get("decision_a_quo"),
        "impugnante": md.get("impugnante"),
        "impugnante_rol": md.get("impugnante_rol"),
        "derechos_invocados": md.get("derechos_invocados", []),
        "impugnantes": md.get("impugnantes", []),
        "resultado_a_quo": md.get("resultado_a_quo"),
        "accionante_tratamiento": md.get("accionante_tratamiento"),
        "accionante_identificacion": md.get("accionante_identificacion"),
        "pruebas_nuevas_2a": ap.get("pruebas_nuevas_2a", []),
        "citas": [
            {
                k: c.get(k)
                for k in (
                    "id",
                    "sentencia_original",
                    "estado",
                    "cobertura",
                    "mp_dataset",
                    "fecha_dataset",
                    "url",
                    "motivos",
                )
            }
            for c in state.get("citas") or []
        ],
        "alertas": state.get("alertas") or {},
        "accionadas": md.get("accionadas", []),
        "vinculadas": md.get("vinculadas", []),
        "fecha_hoy": date.today().isoformat(),
    }


def _errores_validacion(e: ValidationError) -> list[str]:
    return [
        f"Campo '{'.'.join(str(p) for p in err['loc']) or 'decision'}' inválido: {err['msg']}." for err in e.errors()
    ]


def nodo_decision(state: Estado) -> dict:
    payload = _payload_decision(state)
    errores: list[str] = []
    while True:
        valor = interrupt({**payload, "errores": errores})
        try:
            decision = Decision.model_validate(valor)
        except ValidationError as e:
            errores = _errores_validacion(e)
            continue
        errores = decision.errores()
        if not errores:
            break

    intentos = dict(state.get("intentos") or {})
    if decision.accion == "rehacer_apertura":
        intentos.update(apertura=0, consideraciones=0)
    elif decision.accion == "rehacer_consideraciones":
        intentos["consideraciones"] = 0
    else:
        intentos["caso_concreto"] = 0
    registro = {**decision.model_dump(mode="json"), "fecha": _ahora()}
    return {"decisiones": [registro], "intentos": intentos, "errores": []}


def _reparos_con_disposicion(ap: AperturaLLM, decision: Decision) -> list[dict]:
    disposiciones = {d.reparo_id: d for d in decision.por_reparo}
    salida = []
    for r in ap.reparos:
        d = disposiciones.get(r.id)
        salida.append(
            {
                "id": r.id,
                "sintesis": r.sintesis,
                "disposicion": d.disposicion if d else "SIN_DISPOSICION_EXPRESA",
                "nota": d.nota if d else "",
            }
        )
    return salida


ROLES_EXCLUIDOS = {
    "acta_reparto_1a",
    "acta_reparto_2a",
    "auto_admisorio",
    "auto_vinculacion",
    "notificacion",
    "auto_concede_impugnacion",
    "indice",
}
PRIORIDAD_ROLES = ["fallo_a_quo", "impugnacion", "escrito_tutela", "contestacion", "memorial", "anexo"]


def _prioridad(rol: str) -> int:
    return PRIORIDAD_ROLES.index(rol) if rol in PRIORIDAD_ROLES else len(PRIORIDAD_ROLES)


def _documentos_caso(ing: Ingesta, cfg: Config) -> tuple[str, list[str]]:
    docs = [d for d in ing.documentos if d.rol not in ROLES_EXCLUIDOS]
    docs = sorted(docs, key=lambda d: _prioridad(d.rol))
    bloques, alertas = [], []
    restante = cfg.max_chars_documentos_caso
    for d in docs:
        texto = ingest.texto_para_llm(
            ing.model_copy(update={"documentos": [d], "alertas": []}), max_chars=cfg.max_chars_documento
        )
        if not texto:
            continue
        if restante <= 0:
            alertas.append(f"{d.doc_id} {d.nombre}: omitido de DOCUMENTOS por el tope de {cfg.max_chars_documentos_caso} caracteres.")
            continue
        if len(texto) > restante:
            texto = texto[:restante] + "\n[... TRUNCADO ...]"
            alertas.append(f"{d.doc_id} {d.nombre}: truncado en DOCUMENTOS por el tope de {cfg.max_chars_documentos_caso} caracteres.")
        restante -= len(texto)
        bloques.append(texto)
    return "\n\n".join(bloques), alertas


def nodo_caso_concreto(state: Estado, cfg: Config, cliente: LLMClient) -> dict:
    ap = AperturaLLM.model_validate(state["apertura"])
    cons = ConsideracionesLLM.model_validate(state["consideraciones"])
    md = Metadatos.model_validate(state["metadatos"])
    ing = Ingesta.model_validate(state["ingesta"])
    decision = Decision.model_validate(_ultima_decision(state))
    documentos, alertas_docs = _documentos_caso(ing, cfg)
    verificadas = [CitaVerificada.model_validate(c) for c in state.get("citas") or []]
    disponibles = [
        {
            "id": cv.id,
            "marcador": f"[[CITA:{cv.id}]]",
            "referencia": citas.formatear_referencia(cv),
            "estado": cv.estado,
            "texto_citado": cv.texto_citado,
            "reparo_ids": cv.reparo_ids,
        }
        for cv in verificadas
        if cv.estado in ("ok", "alerta")
    ]
    contestaciones = "\n\n".join(f"{c.entidad}: {c.texto}" for c in ap.contestaciones)
    cronologia = "\n".join(f"{e.fecha or 's. f.'} | {e.hecho} ({e.doc_id}) «{e.cita_literal}»" for e in ap.cronologia)
    bloques = "\n\n".join(f"{b.titulo}\n{b.texto}" for b in cons.bloques)
    excluidos = {"accion", "instruccion", "decidido_por", "previo_sha256"}
    if decision.sustitutiva not in ("AMPARAR", "NEGAR"):
        excluidos.add("derechos")
    user = "\n".join(
        [
            seccion("DECISION", _json(decision.model_dump(mode="json", exclude=excluidos))),
            seccion("REPAROS", _json(_reparos_con_disposicion(ap, decision))),
            seccion("METADATOS", _json(md.model_dump(mode="json"))),
            seccion("ANTECEDENTES", ap.antecedentes_hechos + "\n\n" + contestaciones),
            seccion("CRONOLOGIA", cronologia),
            seccion("DOCUMENTOS", documentos),
            seccion("SENTENCIA IMPUGNADA", ap.sentencia_impugnada),
            seccion("IMPUGNACION", ap.impugnacion),
            seccion("PRUEBAS NUEVAS", _json(ap.pruebas_nuevas_2a)),
            seccion("CONSIDERACIONES", cons.procedibilidad + "\n\n" + bloques),
            seccion("CITAS", _json(disponibles)),
            seccion("EXTENSION", _extension(cfg, ("caso_concreto",))),
            seccion("LISTAS", "permitidas" if cfg.permitir_listas_caso else "no permitidas"),
            *_correcciones(state, "caso_concreto", None, "caso"),
        ]
    )
    caso, llamada, intentos = _llamar(cliente, cfg, state, "caso_concreto", user, CasoConcretoLLM)
    alertas = {k: v for k, v in (state.get("alertas") or {}).items()}
    alertas["documentos_caso"] = alertas_docs
    return {"caso": caso.model_dump(mode="json"), "intentos": intentos, "bitacora": [llamada], "alertas": alertas}


def _ingesta_con_decision(ing: Ingesta, decision: Decision) -> Ingesta:
    texto = json.dumps(decision.model_dump(mode="json", exclude={"previo_sha256"}), ensure_ascii=False)
    fuente = Doc(
        doc_id="decision",
        ruta="decision",
        nombre="decision",
        instancia="2a",
        rol="otro",
        sha256=_sha(texto),
        paginas=[Pagina(n=1, texto=texto)],
    )
    return ing.model_copy(update={"documentos": [*ing.documentos, fuente]})


def nodo_validar_caso(state: Estado, cfg: Config) -> dict:
    caso = CasoConcretoLLM.model_validate(state["caso"])
    ap = AperturaLLM.model_validate(state["apertura"])
    decision = Decision.model_validate(_ultima_decision(state))
    ing = _ingesta_con_decision(Ingesta.model_validate(state["ingesta"]), decision)
    verificadas = [CitaVerificada.model_validate(c) for c in state.get("citas") or []]

    textos = {"problema jurídico": caso.problema_juridico, "conclusión": caso.conclusion}
    textos.update({f"párrafo {i}": p.texto for i, p in enumerate(caso.parrafos, 1)})
    mensajes: list[str] = []
    for campo, texto in textos.items():
        mensajes += lint.lint_prosa(texto, f"caso concreto, {campo}", permitir_listas=cfg.permitir_listas_caso)
        mensajes += lint.datos_ajenos(texto, ing)
        mensajes += lint.residuos(texto)
    mensajes += lint.subconjunto_citas(caso, verificadas)
    mensajes += lint.coherencia_decision(caso, decision)
    mensajes += lint.cobertura_reparos([p.reparo_ids for p in caso.parrafos], ap.reparos, decision)
    mensajes += lint.extension("\n\n".join(textos.values()), cfg.rango_palabras["caso_concreto"], "caso concreto")
    mensajes += lint.duplicados([p.texto for p in caso.parrafos], cfg.jaccard_duplicados)
    return _cierre_validacion(state, cfg, "caso_concreto", mensajes)


def nodo_ensamblar(state: Estado, cfg: Config) -> dict:
    eventos.emitir(
        "documentos",
        "escribe",
        f"Generación del fallo con la plantilla {cfg.plantilla_gen} y de los documentos del expediente.",
        {"plantilla_gen": cfg.plantilla_gen},
    )
    salidas = expediente.generar_final(Path(state["caso_dir"]), dict(state), cfg)
    for archivo, sha in salidas.items():
        eventos.emitir("documentos", "escribe", f"Documento generado: {archivo}.", {"archivo": archivo, "sha256": sha})
    return {"salidas": salidas}


def construir(cfg: Config, llm: LLMClient, checkpointer: Any, jev: JevClient | None = None):
    verificador_jev = jev if jev is not None else cliente_jev(cfg)

    def tras_validar_apertura(state: Estado) -> Literal["apertura", "consideraciones"]:
        reintentar = state.get("errores") and state.get("intentos", {}).get("apertura", 0) < cfg.max_intentos
        return "apertura" if reintentar else "consideraciones"

    def tras_verificar(state: Estado) -> Literal["consideraciones", "decision"]:
        reintentar = state.get("errores") and state.get("intentos", {}).get("consideraciones", 0) < cfg.max_intentos
        return "consideraciones" if reintentar else "decision"

    def tras_decision(state: Estado) -> Literal["apertura", "consideraciones", "caso_concreto"]:
        accion = _ultima_decision(state)["accion"]
        if accion == "rehacer_apertura":
            return "apertura"
        if accion == "rehacer_consideraciones":
            return "consideraciones"
        return "caso_concreto"

    def tras_validar_caso(state: Estado) -> Literal["caso_concreto", "ensamblar"]:
        reintentar = state.get("errores") and state.get("intentos", {}).get("caso_concreto", 0) < cfg.max_intentos
        return "caso_concreto" if reintentar else "ensamblar"

    g = StateGraph(Estado)
    g.add_node("apertura", lambda s: nodo_apertura(s, cfg, llm))
    g.add_node("validar_apertura", lambda s: nodo_validar_apertura(s, cfg, verificador_jev))
    g.add_node("consideraciones", lambda s: nodo_consideraciones(s, cfg, llm))
    g.add_node("verificar_consideraciones", lambda s: nodo_verificar_consideraciones(s, cfg))
    g.add_node("decision", nodo_decision)
    g.add_node("caso_concreto", lambda s: nodo_caso_concreto(s, cfg, llm))
    g.add_node("validar_caso", lambda s: nodo_validar_caso(s, cfg))
    g.add_node("ensamblar", lambda s: nodo_ensamblar(s, cfg))

    g.add_edge(START, "apertura")
    g.add_edge("apertura", "validar_apertura")
    g.add_conditional_edges("validar_apertura", tras_validar_apertura)
    g.add_edge("consideraciones", "verificar_consideraciones")
    g.add_conditional_edges("verificar_consideraciones", tras_verificar)
    g.add_conditional_edges("decision", tras_decision)
    g.add_edge("caso_concreto", "validar_caso")
    g.add_conditional_edges("validar_caso", tras_validar_caso)
    g.add_edge("ensamblar", END)
    return g.compile(checkpointer=checkpointer)
