from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError

from tutela2 import formulas
from tutela2.models import (
    Decision,
    DisposicionDerecho,
    DisposicionReparo,
    Fechas,
    Metadatos,
    Orden,
    Plazo,
    limpiar_control,
)

log = logging.getLogger("tutela2.decision_vista")

MAX_TEXTO = 5_000
MAX_FECHA = 64
MAX_CLAVE = 64
MAX_LISTA = 50
MAX_REPAROS = 100
MAX_ORDEN_NUMERALES = 200
MAX_LITERALES = 26
PLAZO_MAXIMO = 999_999
ESPERA_SQLITE_S = 0.5
CACHE_MAX = 128

ERROR_INTERNO = "No se pudo armar la vista previa del RESUELVE."

MSG_ORDEN_INCOMPLETA = "Cada orden necesita destinatario y conducta."
MSG_PLAZO = "El plazo de cada orden debe ser mayor que cero."
MSG_COMPULSA = "La compulsa de copias necesita indicar respecto de quién."
MSG_LIBRE_VACIO = "Hay un numeral libre vacío."


def _opciones(modelo: type[BaseModel], campo: str) -> tuple[str, ...]:
    anotacion = modelo.model_fields[campo].annotation
    for candidata in (anotacion, *get_args(anotacion)):
        if get_origin(candidata) is Literal:
            return tuple(get_args(candidata))
    raise TypeError(f"{modelo.__name__}.{campo} no es un Literal")


ACCIONES = _opciones(Decision, "accion")
RESULTADOS = _opciones(Decision, "resultado")
SUSTITUTIVAS = _opciones(Decision, "sustitutiva")
DISPOSICIONES_REPARO = _opciones(DisposicionReparo, "disposicion")
DISPOSICIONES_DERECHO = _opciones(DisposicionDerecho, "disposicion")
VERBOS = _opciones(Orden, "verbo")
UNIDADES = _opciones(Plazo, "unidad")

_TEXTOS = {
    "instruccion": "La instrucción",
    "eje": "El eje",
    "decidido_por": "El nombre de quien decide",
    "previo_sha256": "El identificador del borrador previo",
    "etiqueta_encabezado": "La etiqueta del encabezado",
}
_ORDEN_CAMPOS = {nombre: i for i, nombre in enumerate(Decision.model_fields)}
_ENTERO = TypeAdapter(int)
_Hallazgos = list[tuple[str, str]]


def _limpio(texto: str) -> str:
    return limpiar_control(texto).encode("utf-8", "replace").decode("utf-8")


def _lista_o(opciones: tuple[str, ...]) -> str:
    return ", ".join(opciones[:-1]) + " o " + opciones[-1]


def _texto(v: Any, campo: str, etiqueta: str, h: _Hallazgos, maximo: int = MAX_TEXTO) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        h.append((campo, f"{etiqueta} debe ser texto."))
        return None
    v = _limpio(v)
    if len(v) > maximo:
        h.append((campo, f"{etiqueta} supera los {maximo:,} caracteres permitidos.".replace(",", ".")))
        v = v[:maximo]
    return v


def _obligatorio(v: Any, campo: str, etiqueta: str, falta: str, h: _Hallazgos) -> str | None:
    texto = _texto(v, campo, etiqueta, h)
    if (texto is None and v is None) or (texto is not None and not texto.strip()):
        h.append((campo, falta))
        return None
    return texto


def _booleano(v: Any, campo: str, etiqueta: str, h: _Hallazgos) -> bool | None:
    if v is None or isinstance(v, bool):
        return v
    h.append((campo, f"{etiqueta} debe ser Sí o No."))
    return None


def _opcion(v: Any, campo: str, etiqueta: str, opciones: tuple[str, ...], h: _Hallazgos) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, str) and v in opciones:
        return v
    h.append((campo, f"{etiqueta} no tiene un valor permitido: use {_lista_o(opciones)}."))
    return None


def _lista(v: Any, campo: str, etiqueta: str, h: _Hallazgos, maximo: int = MAX_LISTA) -> list[Any]:
    if v is None:
        return []
    if not isinstance(v, list):
        h.append((campo, f"{etiqueta} debe ser una lista."))
        return []
    if len(v) > maximo:
        h.append((campo, f"{etiqueta} admite como máximo {maximo} elementos."))
        return v[:maximo]
    return v


def _nombres(v: Any, campo: str, etiqueta: str, h: _Hallazgos, maximo: int = MAX_LISTA) -> list[str]:
    salida = []
    for i, x in enumerate(_lista(v, campo, etiqueta, h, maximo)):
        texto = _texto(x, f"{campo}.{i}", f"El elemento {i + 1} de la lista", h)
        if texto is not None and texto.strip():
            salida.append(texto)
    return salida


def _reparos(v: Any, h: _Hallazgos) -> list[dict[str, Any]]:
    salida = []
    for i, x in enumerate(_lista(v, "por_reparo", "Las disposiciones por reparo", h, MAX_REPAROS)):
        base, n = f"por_reparo.{i}", i + 1
        if not isinstance(x, dict):
            h.append((base, f"La disposición del reparo {n} no es válida."))
            continue
        reparo_id = _obligatorio(
            x.get("reparo_id"), f"{base}.reparo_id", f"El identificador del reparo {n}",
            f"Falta indicar a qué reparo corresponde la disposición {n}.", h,
        )
        if reparo_id is None:
            continue
        item: dict[str, Any] = {"reparo_id": reparo_id}
        disposicion = _opcion(
            x.get("disposicion"), f"{base}.disposicion", f"La disposición del reparo {n}", DISPOSICIONES_REPARO, h
        )
        if disposicion:
            item["disposicion"] = disposicion
        nota = _texto(x.get("nota"), f"{base}.nota", f"La nota del reparo {n}", h)
        if nota is not None:
            item["nota"] = nota
        salida.append(item)
    return salida


def _derechos(v: Any, h: _Hallazgos) -> list[dict[str, Any]]:
    salida = []
    for i, x in enumerate(_lista(v, "derechos", "Los derechos", h)):
        base, n = f"derechos.{i}", i + 1
        if not isinstance(x, dict):
            h.append((base, f"El derecho {n} no es válido."))
            continue
        derecho = _obligatorio(
            x.get("derecho"), f"{base}.derecho", f"El nombre del derecho {n}", f"Falta el nombre del derecho {n}.", h
        )
        if derecho is None:
            continue
        item: dict[str, Any] = {"derecho": derecho}
        disposicion = _opcion(
            x.get("disposicion"), f"{base}.disposicion", f"La disposición del derecho {n}", DISPOSICIONES_DERECHO, h
        )
        if disposicion:
            item["disposicion"] = disposicion
        salida.append(item)
    return salida


def _plazo(v: Any, campo: str, n: int, h: _Hallazgos) -> dict[str, Any] | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        h.append((campo, f"El plazo de la orden {n} no es válido."))
        return None
    plazo: dict[str, Any] = {}
    unidad = _opcion(v.get("unidad"), f"{campo}.unidad", f"La unidad del plazo de la orden {n}", UNIDADES, h)
    if unidad:
        plazo["unidad"] = unidad
    bruto = v.get("n")
    if bruto is None or bruto == "":
        return plazo
    try:
        if isinstance(bruto, bool):
            raise ValueError
        cantidad = _ENTERO.validate_python(bruto)
    except (ValidationError, ValueError, TypeError):
        h.append((f"{campo}.n", "El plazo de cada orden debe ser un número entero."))
        return plazo
    if cantidad <= 0:
        h.append((f"{campo}.n", MSG_PLAZO))
    elif cantidad > PLAZO_MAXIMO:
        h.append((f"{campo}.n", f"El plazo de la orden {n} no puede superar {PLAZO_MAXIMO:,}.".replace(",", ".")))
    else:
        plazo["n"] = cantidad
    return plazo


def _ordenes(v: Any, h: _Hallazgos) -> list[dict[str, Any]]:
    salida = []
    falta_destinatario = formulas._falta("destinatario")
    falta_conducta = formulas._falta("conducta")
    for i, x in enumerate(_lista(v, "ordenes", "Las órdenes", h)):
        base, n = f"ordenes.{i}", i + 1
        if not isinstance(x, dict):
            h.append((base, f"La orden {n} no es válida."))
            salida.append({"destinatario": falta_destinatario, "conducta": falta_conducta})
            continue
        orden: dict[str, Any] = {}
        verbo = _opcion(x.get("verbo"), f"{base}.verbo", f"El verbo de la orden {n}", VERBOS, h)
        if verbo:
            orden["verbo"] = verbo
        orden["destinatario"] = _obligatorio(
            x.get("destinatario"), f"{base}.destinatario", f"El destinatario de la orden {n}", MSG_ORDEN_INCOMPLETA, h
        ) or falta_destinatario
        orden["conducta"] = _obligatorio(
            x.get("conducta"), f"{base}.conducta", f"La conducta de la orden {n}", MSG_ORDEN_INCOMPLETA, h
        ) or falta_conducta
        for clave, etiqueta in (("via_representante", "La vía del representante"), ("mismo_termino", "El mismo término")):
            valor = _booleano(x.get(clave), f"{base}.{clave}", f"{etiqueta} de la orden {n}", h)
            if valor is not None:
                orden[clave] = valor
        condicion = _texto(x.get("condicion"), f"{base}.condicion", f"La condición de la orden {n}", h)
        if condicion is not None:
            orden["condicion"] = condicion
        orden["literales"] = _nombres(
            x.get("literales"), f"{base}.literales", f"Los literales de la orden {n}", h, MAX_LITERALES
        )
        plazo = _plazo(x.get("plazo"), f"{base}.plazo", n, h)
        if plazo is not None:
            orden["plazo"] = plazo
        salida.append(orden)
    return salida


def _compulsa(v: Any, h: _Hallazgos) -> dict[str, Any] | None:
    if v is None or v is False:
        return None
    if not isinstance(v, dict):
        h.append(("compulsa", "La compulsa de copias no es válida."))
        return None
    compulsa: dict[str, Any] = {}
    organo = _texto(v.get("organo"), "compulsa.organo", "El órgano de la compulsa", h)
    if organo is not None and organo.strip():
        compulsa["organo"] = organo
    hechos = _texto(v.get("hechos_ref"), "compulsa.hechos_ref", "La referencia a los hechos de la compulsa", h)
    if hechos is not None:
        compulsa["hechos_ref"] = hechos
    compulsa["respecto_de"] = _obligatorio(
        v.get("respecto_de"), "compulsa.respecto_de", "La persona de la compulsa", MSG_COMPULSA, h
    ) or formulas._falta("respecto de quién")
    return compulsa


def _estandar(v: Any, h: _Hallazgos) -> dict[str, Any]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        h.append(("numerales", "Los numerales estándar no son válidos."))
        return {}
    salida = {}
    for clave, etiqueta in (("notificar", "Notificar"), ("remitir_corte", "Remitir a la Corte")):
        valor = _booleano(v.get(clave), f"numerales.{clave}", etiqueta, h)
        if valor is not None:
            salida[clave] = valor
    return salida


def _libres(v: Any, h: _Hallazgos) -> list[str]:
    salida = []
    for i, x in enumerate(_lista(v, "numerales_libres", "Los numerales libres", h)):
        campo = f"numerales_libres.{i}"
        texto = _texto(x, campo, f"El numeral libre {i + 1}", h)
        salida.append(texto if texto is not None else "")
    return salida


def _claves(v: Any, h: _Hallazgos) -> list[str]:
    salida = []
    for i, x in enumerate(_lista(v, "orden_numerales", "El orden de los numerales", h, MAX_ORDEN_NUMERALES)):
        texto = _texto(x, f"orden_numerales.{i}", f"La clave {i + 1} del orden", h, MAX_CLAVE)
        if texto is not None:
            salida.append(texto)
    return salida


def _limpiar(parcial: dict[str, Any], h: _Hallazgos) -> dict[str, Any]:
    d: dict[str, Any] = {}
    d["accion"] = _opcion(parcial.get("accion"), "accion", "La acción", ACCIONES, h) or "decidir"
    for campo, etiqueta in _TEXTOS.items():
        texto = _texto(parcial.get(campo), campo, etiqueta, h)
        if texto is not None:
            d[campo] = texto
    for campo, etiqueta, opciones in (
        ("resultado", "El resultado", RESULTADOS),
        ("sustitutiva", "La decisión sustitutiva", SUSTITUTIVAS),
    ):
        valor = _opcion(parcial.get(campo), campo, etiqueta, opciones, h)
        if valor:
            d[campo] = valor
    formato = _booleano(parcial.get("generar_formato"), "generar_formato", "Generar el formato", h)
    if formato is not None:
        d["generar_formato"] = formato
    for campo, etiqueta in (("fecha_fallo", "La fecha del fallo"), ("fecha_oficio", "La fecha del oficio")):
        texto = _texto(parcial.get(campo), campo, etiqueta, h, MAX_FECHA)
        if texto is not None and texto.strip():
            d[campo] = texto.strip()
    d["por_reparo"] = _reparos(parcial.get("por_reparo"), h)
    d["derechos"] = _derechos(parcial.get("derechos"), h)
    d["ordenes"] = _ordenes(parcial.get("ordenes"), h)
    d["desvincular"] = _nombres(parcial.get("desvincular"), "desvincular", "La lista de partes a desvincular", h)
    d["prevenir"] = _nombres(parcial.get("prevenir"), "prevenir", "La lista de partes a prevenir", h)
    compulsa = _compulsa(parcial.get("compulsa"), h)
    if compulsa is not None:
        d["compulsa"] = compulsa
    d["numerales"] = _estandar(parcial.get("numerales"), h)
    d["numerales_libres"] = _libres(parcial.get("numerales_libres"), h)
    d["orden_numerales"] = _claves(parcial.get("orden_numerales"), h)
    return d


_CAMPO_POR_ERROR = (
    ("Para rehacer", "instruccion"),
    ("Falta el resultado", "resultado"),
    ("Falta la decisión sustitutiva", "sustitutiva"),
    ("Falta el eje", "eje"),
    ("Si se ampara", "ordenes"),
    ("Clave de numeral inválida", "orden_numerales"),
    ("fecha_fallo", "fecha_fallo"),
    ("fecha_oficio", "fecha_oficio"),
)


def _campos_del_error(mensaje: str, dec: Decision) -> list[str]:
    if mensaje == MSG_LIBRE_VACIO:
        return [f"numerales_libres.{i}" for i, t in enumerate(dec.numerales_libres) if not t.strip()]
    for prefijo, campo in _CAMPO_POR_ERROR:
        if mensaje.startswith(prefijo):
            return [campo]
    return ["decision"]


def _faltantes(dec: Decision, hallazgos: _Hallazgos) -> list[tuple[str, str]]:
    faltantes = list(hallazgos)
    campos = {c for c, _ in hallazgos}
    for mensaje in dec.errores():
        for campo in _campos_del_error(mensaje, dec):
            if campo not in campos:
                faltantes.append((campo, mensaje))
    unicos = dict.fromkeys(faltantes)
    return sorted(unicos, key=lambda f: _ORDEN_CAMPOS.get(f[0].split(".")[0], len(_ORDEN_CAMPOS)))


def decision_vista(parcial: Any, md: Metadatos) -> dict[str, Any]:
    if not isinstance(parcial, dict):
        return {"numerales": [], "faltantes": [], "errores": ["La decisión debe ser un objeto."]}
    hallazgos: _Hallazgos = []
    dec = Decision.model_validate(_limpiar(parcial, hallazgos))
    faltantes = _faltantes(dec, hallazgos)
    return {
        "numerales": [
            {"clave": n.clave, "texto": n.texto, "negritas": list(n.negritas)} for n in formulas.numerales(dec, md)
        ],
        "faltantes": [{"campo": c, "mensaje": m} for c, m in faltantes],
        "errores": list(dict.fromkeys(m for _, m in faltantes)),
    }


def _vacio(valor: Any) -> bool:
    return valor in (None, "", []) or valor == Fechas()


def _rellenar(md: Metadatos, otro: Metadatos) -> Metadatos:
    faltan = {
        campo: getattr(otro, campo)
        for campo in Metadatos.model_fields
        if _vacio(getattr(md, campo)) and not _vacio(getattr(otro, campo))
    }
    return md.model_copy(update=faltan)


def _validar_md(crudo: Any) -> Metadatos | None:
    if not isinstance(crudo, dict):
        return None
    try:
        return Metadatos.model_validate(crudo)
    except ValidationError:
        return None


def _dic(valor: Any) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _md_de_valores(valores: dict[str, Any]) -> Metadatos | None:
    md: Metadatos | None = None
    for crudo in (
        valores.get("metadatos"),
        _dic(valores.get("ingesta")).get("metadatos"),
        _dic(valores.get("apertura")).get("metadatos"),
    ):
        otro = _validar_md(crudo)
        if otro is not None:
            md = otro if md is None else _rellenar(md, otro)
    return md


def _desde_hilo(caso_dir: Path) -> Metadatos | None:
    ruta = caso_dir / "hilo.sqlite"
    if not ruta.is_file():
        return None
    from langgraph.checkpoint.sqlite import SqliteSaver

    conexion = sqlite3.connect(ruta, timeout=ESPERA_SQLITE_S, check_same_thread=False)
    try:
        punto = SqliteSaver(conexion).get_tuple({"configurable": {"thread_id": caso_dir.name}})
    finally:
        conexion.close()
    if punto is None:
        return None
    return _md_de_valores(_dic(punto.checkpoint.get("channel_values")))


def _desde_caso_json(caso_dir: Path) -> Metadatos | None:
    try:
        crudo = json.loads((caso_dir / "caso.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _validar_md(_dic(crudo).get("metadatos"))


_CACHE: OrderedDict[str, tuple[tuple, Metadatos]] = OrderedDict()
_CERROJO = threading.Lock()


def _firma(caso_dir: Path) -> tuple:
    firma = []
    for nombre in ("caso.json", "hilo.sqlite", "hilo.sqlite-wal"):
        try:
            info = (caso_dir / nombre).stat()
        except OSError:
            firma.append(None)
        else:
            firma.append((info.st_mtime_ns, info.st_size))
    return tuple(firma)


def metadatos_del_caso(caso_dir: str | Path) -> Metadatos:
    caso_dir = Path(caso_dir).resolve()
    clave = str(caso_dir)
    firma = _firma(caso_dir)
    with _CERROJO:
        acierto = _CACHE.get(clave)
        if acierto is not None and acierto[0] == firma:
            _CACHE.move_to_end(clave)
            return acierto[1]
    estable = True
    md: Metadatos | None = None
    try:
        md = _desde_hilo(caso_dir)
    except (sqlite3.Error, OSError):
        log.warning("No se pudo leer el hilo de %s; se usan los metadatos de la ingesta.", caso_dir.name, exc_info=True)
        estable = False
    except Exception:
        log.exception("El hilo de %s no se pudo interpretar; se usan los metadatos de la ingesta.", caso_dir.name)
    if md is None:
        md = _desde_caso_json(caso_dir)
    if md is None:
        md = Metadatos()
    if estable:
        with _CERROJO:
            _CACHE[clave] = (firma, md)
            _CACHE.move_to_end(clave)
            while len(_CACHE) > CACHE_MAX:
                _CACHE.popitem(last=False)
    return md
