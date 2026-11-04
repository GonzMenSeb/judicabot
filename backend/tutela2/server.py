from __future__ import annotations

import functools
import importlib
import json
import logging
import os
import re
import shutil
import threading
import unicodedata
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Receive, Scope, Send

from tutela2 import acceso
from tutela2 import config as cfgmod
from tutela2.config import Config
from tutela2.estaticos import SIN_GZIP, CabecerasEstaticas
from tutela2.jev import clave_valida

log = logging.getLogger("tutela2.server")

STATIC = Path(__file__).parent / "static"
REPO = Path(__file__).resolve().parents[2]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_JOB_ACTUAL: ContextVar[str | None] = ContextVar("job_actual", default=None)

def _calentar_resumenes() -> None:
    from tutela2 import resumen_caso

    try:
        resumen_caso.calentar(casos_dir())
    except Exception:
        log.warning("No se pudo calentar la caché de resúmenes", exc_info=True)


@asynccontextmanager
async def _ciclo_de_vida(aplicacion: FastAPI) -> AsyncIterator[None]:
    aplicacion.state.calentamiento = threading.Thread(target=_calentar_resumenes, name="calentar-resumenes", daemon=True)
    aplicacion.state.calentamiento.start()
    yield


app = FastAPI(title="Tutela 2ª instancia", lifespan=_ciclo_de_vida)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(GZipMiddleware, minimum_size=500, exclude_content_types=SIN_GZIP)
app.middleware("http")(acceso.compuerta)
app.add_middleware(CabecerasEstaticas)


class RunBody(BaseModel):
    cmd: Literal["nuevo", "iniciar", "decidir", "continuar"]
    decision: dict[str, Any] | None = None
    forzar: bool = False


class RevisionBody(BaseModel):
    roles: dict[str, str] | None = None
    auto: dict[str, Any] | None = None


class ApiKeyBody(BaseModel):
    key: str


class ModeloBody(BaseModel):
    modelo: str


class EstadoServidor(BaseModel):
    api_key: bool
    jev_key: bool
    modelo: str
    modelos: list[str]


class JobInicio(BaseModel):
    job_id: str


def casos_dir() -> Path:
    return Path(os.environ.get("CASOS_DIR") or REPO / "casos").expanduser()


def _api():
    return importlib.import_module("tutela2.api")


def _salidas():
    return importlib.import_module("tutela2.salidas")


def _slug(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")


def sanear_ruta(nombre: str | None) -> tuple[str, ...]:
    if not nombre or "\x00" in nombre:
        raise ValueError("Nombre de archivo inválido.")
    texto = nombre.replace("\\", "/")
    if texto.startswith("/") or re.match(r"[A-Za-z]:", texto):
        raise ValueError(f"No se admiten rutas absolutas: {nombre}")
    partes = [unicodedata.normalize("NFC", p) for p in texto.split("/") if p not in ("", ".")]
    if not partes or ".." in partes:
        raise ValueError(f"Ruta no permitida: {nombre}")
    return tuple(partes)


def quitar_carpeta_raiz(rutas: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    if rutas and all(len(r) > 1 for r in rutas) and len({r[0] for r in rutas}) == 1:
        return [r[1:] for r in rutas]
    return rutas


def _dir_caso(caso_id: str) -> Path:
    raiz = casos_dir().resolve()
    d = (raiz / caso_id).resolve()
    if caso_id.startswith(".") or d.parent != raiz or not d.is_dir():
        raise HTTPException(404, "Caso no encontrado.")
    return d


def _ruta_salida(caso_id: str, archivo: str) -> Path:
    caso_dir = _dir_caso(caso_id)
    try:
        ruta = _salidas().resolver(caso_dir, archivo).resolve()
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(404, "Archivo no encontrado.") from exc
    if not ruta.is_file() or not ruta.is_relative_to((caso_dir / "salidas").resolve()):
        raise HTTPException(404, "Archivo no encontrado.")
    return ruta


def _crear_dir_caso(nombre: str) -> tuple[str, Path]:
    base = _slug(nombre) or "caso"
    raiz = casos_dir()
    raiz.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        caso_id = base if n == 1 else f"{base}-{n}"
        try:
            (raiz / caso_id).mkdir()
            return caso_id, raiz / caso_id
        except FileExistsError:
            n += 1


def _contar_insumos(caso_dir: Path) -> int:
    insumos = caso_dir / "insumos"
    return sum(1 for f in insumos.rglob("*") if f.is_file()) if insumos.is_dir() else 0


def _job_activo(caso_id: str) -> str | None:
    with _LOCK:
        return next((j["id"] for j in JOBS.values() if j["caso"] == caso_id and j["estado"] == "corriendo"), None)


def _estado_api(caso_dir: Path) -> dict[str, Any]:
    try:
        return dict(_api().estado(caso_dir))
    except Exception as exc:
        log.exception("No se pudo leer el estado de %s", caso_dir.name)
        raise HTTPException(500, f"No se pudo leer el estado del caso: {exc}") from exc


class _JobHandler(logging.Handler):
    def __init__(self, job: dict[str, Any]):
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        if _JOB_ACTUAL.get() == self.job["id"]:
            if record.exc_info or record.exc_text:
                record = logging.makeLogRecord({**record.__dict__, "exc_info": None, "exc_text": None})
            self.job["log"].append(self.format(record))


def _ejecutar(job: dict[str, Any], fn: Callable[[], dict[str, Any]]) -> None:
    from tutela2 import eventos

    buffer = eventos.buffer(job["id"]) or eventos.crear(job["id"])
    logger = logging.getLogger("tutela2")
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    handler = _JobHandler(job)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    token = _JOB_ACTUAL.set(job["id"])
    token_eventos = eventos.activar(buffer)
    estado, error, resultado = "terminado", None, None
    try:
        eventos.emitir("sistema", "sistema", f"Inicio de «{job['cmd']}» en el caso {job['caso']}.", {"cmd": job["cmd"], "caso": job["caso"]})
        log.info("Inicio de %s", job["cmd"])
        resultado = fn()
        if isinstance(resultado, dict) and resultado.get("ok") is False:
            estado, error = "error", resultado.get("error") or "La operación falló."
        log.info("Fin de %s: %s", job["cmd"], estado)
    except Exception as exc:
        log.exception("Falló %s: %s", job["cmd"], exc)
        estado, error = "error", str(exc) or type(exc).__name__
    finally:
        eventos.desactivar(token_eventos)
        _JOB_ACTUAL.reset(token)
        logger.removeHandler(handler)
    job["resultado"], job["error"] = resultado, error
    job["estado"] = estado
    eventos.finalizar(buffer, job["cmd"], estado, error)


def _comando(cmd: str, caso_dir: Path, decision: dict[str, Any] | None, forzar: bool = False) -> dict[str, Any]:
    from tutela2 import preferencias

    api = _api()
    preferencias.aplicar_entorno(preferencias.leer(_preferencias()))
    if cmd == "nuevo":
        return api.nuevo(caso_dir)
    if cmd == "iniciar":
        return api.iniciar(caso_dir)
    if cmd == "continuar":
        return api.continuar(caso_dir, forzar)
    return api.decidir(caso_dir, decision)


_MENSAJES_CONFIG = {
    "int_parsing": "debe ser un número entero.",
    "int_from_float": "debe ser un número entero, sin decimales.",
    "float_parsing": "debe ser un número.",
    "bool_parsing": "debe ser Sí o No.",
    "missing": "es obligatorio.",
    "string_type": "debe ser texto.",
    "list_type": "debe ser una lista.",
    "dict_type": "debe ser un objeto.",
    "extra_forbidden": "no es un campo reconocido.",
    "literal_error": "no es una de las opciones permitidas.",
    "enum": "no es una de las opciones permitidas.",
}


def _mensaje_config(e: Any) -> str:
    tipo = e["type"]
    if tipo in _MENSAJES_CONFIG:
        return _MENSAJES_CONFIG[tipo]
    ctx = e.get("ctx") or {}
    if tipo in ("greater_than", "greater_than_equal") and ctx.get("gt", ctx.get("ge")) is not None:
        return f"debe ser {'mayor que' if tipo == 'greater_than' else 'al menos'} {ctx.get('gt', ctx.get('ge'))}."
    if tipo in ("string_too_long", "too_long") and ctx.get("max_length") is not None:
        return f"debe tener como máximo {ctx['max_length']} {'caracteres' if tipo == 'string_too_long' else 'elementos'}."
    if tipo in ("less_than", "less_than_equal") and ctx.get("lt", ctx.get("le")) is not None:
        return f"debe ser {'menor que' if tipo == 'less_than' else 'como máximo'} {ctx.get('lt', ctx.get('le'))}."
    return "tiene un valor no válido."


def _errores_config(exc: ValidationError) -> dict[str, Any]:
    return {"errores": [{"campo": ".".join(str(p) for p in e["loc"]), "mensaje": _mensaje_config(e)} for e in exc.errors()]}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _dist() -> Path:
    return STATIC / "dist"


def _shell() -> Path | None:
    indice_dist = _dist() / "index.html"
    return indice_dist if indice_dist.is_file() else None


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def indice() -> Response:
    shell = _shell()
    if shell is None:
        return PlainTextResponse("Falta compilar el frontend (pnpm build).", status_code=503)
    return FileResponse(shell)


@app.get("/api/config-default")
def config_default() -> Any:
    return _api().config_default()


@app.get("/api/prompts-default")
def prompts_default() -> Any:
    return _api().prompts_default()


def _preferencias() -> Path:
    return casos_dir() / ".preferencias.json"


def modelo_actual() -> str:
    from tutela2 import preferencias

    return preferencias.leer(_preferencias()).modelo or cfgmod.LLMConfig().modelo


@app.get("/api/estado-servidor", response_model=EstadoServidor)
def estado_servidor() -> dict[str, Any]:
    return {
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "jev_key": bool(os.environ.get("JEV_API_KEY", "").strip()),
        "modelo": modelo_actual(),
        "modelos": list(cfgmod.MODELOS),
    }


@app.post("/api/modelo")
def elegir_modelo(body: ModeloBody) -> dict[str, str]:
    if body.modelo not in cfgmod.MODELOS:
        raise HTTPException(422, f"Modelo no permitido: {body.modelo}.")
    from tutela2 import preferencias

    preferencias.actualizar(_preferencias(), preferencias.Preferencias(modelo=body.modelo))
    return {"modelo": body.modelo}


@app.post("/api/api-key")
def guardar_api_key(body: ApiKeyBody) -> dict[str, bool]:
    key = body.key.strip()
    if not key:
        raise HTTPException(422, "La API key no puede estar vacía.")
    os.environ["ANTHROPIC_API_KEY"] = key
    return {"api_key": True}


@app.post("/api/jev-key")
def guardar_jev_key(body: ApiKeyBody) -> dict[str, bool]:
    key = body.key.strip()
    if not key:
        raise HTTPException(422, "La clave de Jev no puede estar vacía.")
    if not clave_valida(key):
        raise HTTPException(422, "La clave de Jev solo admite caracteres ASCII visibles, sin espacios ni saltos de línea.")
    os.environ["JEV_API_KEY"] = key
    return {"jev_key": True}


@app.get("/api/casos/{caso_id}/config")
def leer_config(caso_id: str) -> dict[str, Any]:
    try:
        return cfgmod.cargar(_dir_caso(caso_id), entorno=False).model_dump()
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"config.json no es válido: {exc}") from exc


@app.put("/api/casos/{caso_id}/config")
def escribir_config(caso_id: str, body: dict[str, Any]) -> dict[str, Any]:
    caso_dir = _dir_caso(caso_id)
    try:
        cfg = Config.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, _errores_config(exc)) from exc
    cfgmod.guardar(caso_dir, cfg)
    return cfg.model_dump()


@app.get("/api/casos/{caso_id}/estado")
def estado_caso(caso_id: str) -> dict[str, Any]:
    caso_dir = _dir_caso(caso_id)
    resultado = _estado_api(caso_dir)
    if (caso_dir / "hilo.sqlite").exists() and (caso_dir / "caso.json").exists():
        try:
            api = _api()
            resultado["ingesta"] = api._resumen_ingesta(caso_dir, api._cargar_ingesta(caso_dir))
        except Exception:
            log.exception("No se pudo leer la ingesta de %s", caso_id)
    resultado["job_activo"] = _job_activo(caso_id)
    return resultado


@app.post("/api/casos/{caso_id}/run", response_model=JobInicio)
def ejecutar(caso_id: str, body: RunBody) -> dict[str, str]:
    caso_dir = _dir_caso(caso_id)
    if body.cmd == "decidir" and not body.decision:
        raise HTTPException(422, "Falta la decisión.")
    from collections import deque

    from tutela2 import eventos

    job = {"id": uuid.uuid4().hex, "caso": caso_id, "cmd": body.cmd, "estado": "corriendo", "log": deque(maxlen=200), "resultado": None, "error": None}
    with _LOCK:
        if any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in JOBS.values()):
            raise HTTPException(409, "Ya hay una ejecución en curso para este caso.")
        JOBS[job["id"]] = job
        eventos.crear(job["id"])
        for viejo in [i for i, j in JOBS.items() if j["estado"] != "corriendo"][:-50]:
            del JOBS[viejo]
            eventos.olvidar(viejo)
    threading.Thread(
        target=_ejecutar, args=(job, lambda: _comando(body.cmd, caso_dir, body.decision, body.forzar)), daemon=True
    ).start()
    return {"job_id": job["id"]}


@app.get("/api/jobs/{job_id}")
def leer_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado.")
    return {**job, "log": list(job["log"])[-200:]}


@app.put("/api/casos/{caso_id}/revision")
def revisar(caso_id: str, body: RevisionBody) -> dict[str, Any]:
    caso_dir = _dir_caso(caso_id)
    with _LOCK:
        if any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in JOBS.values()):
            raise HTTPException(409, "Ya hay una ejecución en curso para este caso.")
        try:
            resultado = dict(_api().revisar(caso_dir, body.roles, body.auto))
        except Exception as exc:
            log.exception("No se pudo guardar la revisión de %s", caso_id)
            raise HTTPException(500, f"No se pudo guardar la revisión: {exc}") from exc
    if resultado.get("ok") is False:
        con_hilo = resultado.get("estado") in ("esperando_decision", "error", "terminado")
        raise HTTPException(409 if con_hilo else 422, resultado.get("error") or "No se pudo guardar la revisión.")
    return resultado


@app.get("/api/casos/{caso_id}/salidas")
def listar_salidas(caso_id: str) -> dict[str, list[str]]:
    return {"archivos": _salidas().listar(_dir_caso(caso_id))}


@app.get("/api/casos/{caso_id}/salidas/{archivo:path}")
def descargar_salida(caso_id: str, archivo: str) -> FileResponse:
    ruta = _ruta_salida(caso_id, archivo)
    return FileResponse(ruta, filename=ruta.name, media_type=DOCX if ruta.suffix == ".docx" else None)


@app.get("/api/casos/{caso_id}/zip")
def descargar_zip(caso_id: str) -> Response:
    caso_dir = _dir_caso(caso_id)
    contenido = _salidas().zip_bytes(caso_dir)
    return Response(
        contenido,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{caso_id}.zip"'},
    )


@functools.cache
def _servidor_assets(directorio: Path) -> StaticFiles:
    return StaticFiles(directory=directorio)


class _Assets:
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        directorio = _dist() / "assets"
        if not directorio.is_dir():
            raise HTTPException(404, "Not Found")
        await _servidor_assets(directorio)(scope, receive, send)


for _modulo in ("rutas_casos", "rutas_formato", "rutas_eventos", "rutas_vista", "rutas_decision", "rutas_ia"):
    try:
        _m = importlib.import_module(f"tutela2.{_modulo}")
    except ModuleNotFoundError as exc:
        if exc.name != f"tutela2.{_modulo}":
            raise
    else:
        app.include_router(_m.router)

app.mount("/assets", _Assets(), name="assets")


def _respuesta_spa(ruta: str) -> FileResponse | None:
    shell = _shell()
    if shell is None or any(ruta == p or ruta.startswith(p + "/") for p in ("/api", "/assets")):
        return None
    dist = _dist().resolve()
    try:
        archivo = (dist / ruta.lstrip("/")).resolve()
        existe = archivo.is_file() and archivo.is_relative_to(dist)
    except (ValueError, OSError):
        existe = False
    if existe:
        return FileResponse(archivo)
    return None if Path(ruta).suffix else FileResponse(shell)


@app.exception_handler(StarletteHTTPException)
async def http_o_spa(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404 and request.method in ("GET", "HEAD"):
        respuesta = _respuesta_spa(request.url.path)
        if respuesta is not None:
            return respuesta
    return await http_exception_handler(request, exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and not acceso.password():
        raise SystemExit("JUDICABOT_PASSWORD es obligatoria cuando HOST no es local")
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
