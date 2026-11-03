from __future__ import annotations

import importlib
import json
import logging
import os
import re
import shutil
import threading
import unicodedata
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tutela2 import config as cfgmod
from tutela2.config import Config

log = logging.getLogger("tutela2.server")

STATIC = Path(__file__).parent / "static"
REPO = Path(__file__).resolve().parents[2]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_JOB_ACTUAL: ContextVar[str | None] = ContextVar("job_actual", default=None)

app = FastAPI(title="Tutela 2ª instancia")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


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
    logger = logging.getLogger("tutela2")
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    handler = _JobHandler(job)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    token = _JOB_ACTUAL.set(job["id"])
    estado, error, resultado = "terminado", None, None
    try:
        log.info("Inicio de %s", job["cmd"])
        resultado = fn()
        if isinstance(resultado, dict) and resultado.get("ok") is False:
            estado, error = "error", resultado.get("error") or "La operación falló."
        log.info("Fin de %s: %s", job["cmd"], estado)
    except Exception as exc:
        log.exception("Falló %s: %s", job["cmd"], exc)
        estado, error = "error", str(exc) or type(exc).__name__
    finally:
        _JOB_ACTUAL.reset(token)
        logger.removeHandler(handler)
    job["resultado"], job["error"] = resultado, error
    job["estado"] = estado


def _comando(cmd: str, caso_dir: Path, decision: dict[str, Any] | None, forzar: bool = False) -> dict[str, Any]:
    api = _api()
    os.environ["TUTELA2_MODELO"] = modelo_actual()
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
    if tipo in ("less_than", "less_than_equal") and ctx.get("lt", ctx.get("le")) is not None:
        return f"debe ser {'menor que' if tipo == 'less_than' else 'como máximo'} {ctx.get('lt', ctx.get('le'))}."
    return "tiene un valor no válido."


def _errores_config(exc: ValidationError) -> dict[str, Any]:
    return {"errores": [{"campo": ".".join(str(p) for p in e["loc"]), "mensaje": _mensaje_config(e)} for e in exc.errors()]}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def indice() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config-default")
def config_default() -> Any:
    return _api().config_default()


@app.get("/api/prompts-default")
def prompts_default() -> Any:
    return _api().prompts_default()


def _preferencias() -> Path:
    return casos_dir() / ".preferencias.json"


def modelo_actual() -> str:
    try:
        modelo = json.loads(_preferencias().read_text(encoding="utf-8")).get("modelo")
    except (OSError, ValueError, AttributeError):
        modelo = None
    return modelo if modelo in cfgmod.MODELOS else cfgmod.LLMConfig().modelo


@app.get("/api/estado-servidor")
def estado_servidor() -> dict[str, Any]:
    return {
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "modelo": modelo_actual(),
        "modelos": list(cfgmod.MODELOS),
    }


@app.post("/api/modelo")
def elegir_modelo(body: ModeloBody) -> dict[str, str]:
    if body.modelo not in cfgmod.MODELOS:
        raise HTTPException(422, f"Modelo no permitido: {body.modelo}.")
    _preferencias().parent.mkdir(parents=True, exist_ok=True)
    _preferencias().write_text(json.dumps({"modelo": body.modelo}), encoding="utf-8")
    os.environ["TUTELA2_MODELO"] = body.modelo
    return {"modelo": body.modelo}


@app.post("/api/api-key")
def guardar_api_key(body: ApiKeyBody) -> dict[str, bool]:
    key = body.key.strip()
    if not key:
        raise HTTPException(422, "La API key no puede estar vacía.")
    os.environ["ANTHROPIC_API_KEY"] = key
    return {"api_key": True}


@app.get("/api/casos")
def listar_casos() -> list[dict[str, Any]]:
    raiz = casos_dir()
    if not raiz.is_dir():
        return []
    casos = []
    for d in sorted(p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if _job_activo(d.name):
            estado = "corriendo"
        else:
            try:
                estado = _api().estado(d).get("estado", "error")
            except Exception:
                log.exception("No se pudo leer el estado de %s", d.name)
                estado = "error"
        casos.append({"id": d.name, "estado": estado, "n_insumos": _contar_insumos(d)})
    return casos


@app.post("/api/casos")
def crear_caso(nombre: str = Form(...), files: list[UploadFile] = File(...)) -> dict[str, Any]:
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(422, "Falta el nombre del caso.")
    try:
        rutas = [sanear_ruta(f.filename) for f in files]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    pares = [(f, r) for f, r in zip(files, rutas) if not any(p.startswith(".") for p in r)]
    if not pares:
        raise HTTPException(400, "No se recibió ningún archivo.")
    rutas_finales = quitar_carpeta_raiz([r for _, r in pares])

    caso_id, caso_dir = _crear_dir_caso(nombre)
    insumos = (caso_dir / "insumos").resolve()
    try:
        for (f, _), ruta in zip(pares, rutas_finales):
            destino = insumos.joinpath(*ruta)
            if not destino.resolve().is_relative_to(insumos):
                raise HTTPException(400, f"Ruta no permitida: {'/'.join(ruta)}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            with destino.open("wb") as out:
                shutil.copyfileobj(f.file, out)
    except BaseException:
        shutil.rmtree(caso_dir, ignore_errors=True)
        raise
    log.info("Caso %s creado con %d archivos", caso_id, len(pares))
    return {"id": caso_id, "n_insumos": len(pares)}


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


@app.post("/api/casos/{caso_id}/run")
def ejecutar(caso_id: str, body: RunBody) -> dict[str, str]:
    caso_dir = _dir_caso(caso_id)
    if body.cmd == "decidir" and not body.decision:
        raise HTTPException(422, "Falta la decisión.")
    job = {"id": uuid.uuid4().hex, "caso": caso_id, "cmd": body.cmd, "estado": "corriendo", "log": [], "resultado": None, "error": None}
    with _LOCK:
        if any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in JOBS.values()):
            raise HTTPException(409, "Ya hay una ejecución en curso para este caso.")
        JOBS[job["id"]] = job
    threading.Thread(
        target=_ejecutar, args=(job, lambda: _comando(body.cmd, caso_dir, body.decision, body.forzar)), daemon=True
    ).start()
    return {"job_id": job["id"]}


@app.get("/api/jobs/{job_id}")
def leer_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado.")
    return {**job, "log": list(job["log"])}


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


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
