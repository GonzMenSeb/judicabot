from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Any, Literal, Optional, TypedDict

import re

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

Rol = Literal[
    "acta_reparto_1a",
    "acta_reparto_2a",
    "escrito_tutela",
    "auto_admisorio",
    "auto_vinculacion",
    "contestacion",
    "fallo_a_quo",
    "impugnacion",
    "auto_concede_impugnacion",
    "notificacion",
    "correo",
    "memorial",
    "indice",
    "anexo",
    "producto_despacho",
    "otro",
]


class Pagina(BaseModel):
    n: int
    texto: str
    ocr: bool = False
    sin_texto: bool = False
    ruido: bool = False


class Doc(BaseModel):
    doc_id: str
    ruta: str
    nombre: str
    instancia: Literal["1a", "2a"]
    rol: Rol
    sha256: str
    paginas: list[Pagina]
    ruido: bool = False
    motivo_ruido: str = ""
    cuis: list[str] = []
    evidencia: str = ""
    rol_origen: Literal["contenido", "usuario"] = "contenido"

    def texto(self) -> str:
        return "\n".join(p.texto for p in self.paginas)


class Fechas(BaseModel):
    admision: Optional[str] = None
    fallo_a_quo: Optional[str] = None
    notificacion_fallo: Optional[str] = None
    impugnacion: Optional[str] = None
    concesion_impugnacion: Optional[str] = None
    reparto_2a: Optional[str] = None


class Metadatos(BaseModel):
    cui_1a: Optional[str] = None
    cui_2a: Optional[str] = None
    juzgado_a_quo: Optional[str] = None
    accionante: Optional[str] = None
    accionadas: list[str] = []
    vinculadas: list[str] = []
    impugnante: Optional[str] = None
    impugnante_rol: Optional[Literal["accionante", "accionada", "vinculada", "otro"]] = None
    derechos_invocados: list[str] = []
    decision_a_quo: Optional[str] = None
    fechas: Fechas = Fechas()
    impugnantes: list[str] = []
    resultado_a_quo: Optional[str] = None
    resultado_a_quo_se: Optional[str] = None
    accionante_tratamiento: Optional[str] = None
    accionante_identificacion: Optional[str] = None
    juez_a_quo_nombres: Optional[str] = None
    juez_a_quo_apellidos: Optional[str] = None
    genero_accionadas: Optional[Literal["m", "f"]] = None
    genero_vinculadas: Optional[Literal["m", "f"]] = None
    juzgado_a_quo_numero: Optional[int] = None
    juzgado_a_quo_funcion: Optional[Literal["conocimiento", "control_garantias"]] = None
    juzgado_a_quo_letras: Optional[str] = None
    juzgado_a_quo_plural: bool = False
    juzgado_a_quo_derivado: bool = False

    @field_validator("*", mode="before")
    @classmethod
    def _vacio_es_none(cls, v: Any, info: ValidationInfo) -> Any:
        if v == "" and cls.model_fields[info.field_name].default is None:
            return None
        return v


class Ingesta(BaseModel):
    documentos: list[Doc]
    docs_ajenos: list[str] = []
    faltantes: list[str] = []
    alertas: list[str] = []
    esperados_faltantes: list[str] = []
    alertas_lectura: list[str] = []
    ignorados: list[str] = []
    metadatos: Metadatos = Metadatos()

    @property
    def completo(self) -> bool:
        return not self.faltantes

    def textos_visibles(self) -> list[str]:
        return [
            p.texto
            for d in self.documentos
            if not (d.ruido or d.doc_id in self.docs_ajenos or d.rol == "producto_despacho")
            for p in d.paginas
            if not p.ruido
        ]


class Evento(BaseModel):
    fecha: Optional[str] = Field(None, description="Fecha ISO AAAA-MM-DD si consta")
    hecho: str
    doc_id: str
    cita_literal: str = Field(description="Fragmento literal copiado del documento fuente que respalda el hecho")


class Reparo(BaseModel):
    id: str = Field(description="Identificador corto: R1, R2, ...")
    sintesis: str
    doc_id: str
    cita_literal: str = Field(description="Fragmento literal del escrito de impugnación")


class Contestacion(BaseModel):
    entidad: str
    silencio: bool = False
    texto: str = Field(description="Párrafo en prosa corrida, tercera persona; cierra con la pretensión defensiva o con 'guardó absoluto silencio'")


def _todos_requeridos(schema: dict[str, Any]) -> None:
    schema["required"] = list(schema.get("properties", {}))


class MetadatosLLM(BaseModel):
    model_config = ConfigDict(json_schema_extra=_todos_requeridos)

    juzgado_a_quo: str = Field("", description="Nombre del juzgado de primera instancia; vacío si no consta")
    accionante: str = Field("", description="Nombre completo del accionante; vacío si no consta")
    accionadas: list[str] = Field([], description="Entidades o personas accionadas")
    vinculadas: list[str] = Field([], description="Entidades o personas vinculadas")
    impugnante: str = Field("", description="Quien interpuso la impugnación; vacío si no consta")
    impugnante_rol: Literal["accionante", "accionada", "vinculada", "otro", ""] = Field(
        "", description="Calidad del impugnante en el trámite; vacío si no consta"
    )
    derechos_invocados: list[str] = Field(
        [], description="Derechos fundamentales que invoca el escrito de tutela, nombres cortos en minúscula"
    )
    decision_a_quo: str = Field(
        "",
        description="Cláusula de máximo veinte palabras, en pasado, que completa 'mediante el cual ...' y empieza con "
        "el verbo de la decisión: 'amparó ...', 'negó el amparo ...', 'declaró improcedente ...'",
    )
    impugnantes: list[str] = Field(
        [],
        description="Una frase por impugnante con su calidad y documento de identificación tal como constan, p. ej. "
        "'la ciudadana Nombre Apellido identificada con C.C. 1.234.567'",
    )
    resultado_a_quo: str = Field(
        "",
        description="Decisión principal de primera instancia en voz activa, pasado y tercera persona del singular, "
        "para ir tras 'que' ('declaró improcedente la acción de tutela', 'amparó los derechos fundamentales al "
        "mínimo vital y a la salud'); sin órdenes; máximo treinta palabras",
    )
    resultado_a_quo_se: str = Field(
        "",
        description="La misma decisión como cláusula para ir tras 'se', en pasiva refleja que concuerda en número "
        "con su objeto ('ampararon los derechos fundamentales al mínimo vital y a la salud invocados por la "
        "accionante', 'declaró improcedente el amparo constitucional'); sin órdenes; máximo treinta palabras",
    )
    accionante_tratamiento: str = Field(
        "", description="Tratamiento del accionante con artículo, en minúscula: 'la señora', 'el señor', 'la sociedad'"
    )
    accionante_identificacion: str = Field(
        "",
        description="Identificación del accionante como consta, p. ej. 'identificada con cédula de ciudadanía "
        "1.000.000.000', concordando en género con el tratamiento; vacío si no consta",
    )
    juez_a_quo_nombres: str = Field("", description="Nombres de quien firma el fallo de primera instancia; vacío si no consta")
    juez_a_quo_apellidos: str = Field("", description="Apellidos de quien firma el fallo de primera instancia; vacío si no consta")
    genero_accionadas: Literal["m", "f", ""] = Field(
        "", description="Género gramatical con que el fallo se refiere a las accionadas; vacío si no se puede determinar"
    )
    genero_vinculadas: Literal["m", "f", ""] = Field(
        "", description="Género gramatical con que el fallo se refiere a las vinculadas; vacío si no se puede determinar"
    )

    @field_validator("*", mode="before")
    @classmethod
    def _normalizar(cls, v: Any, info: ValidationInfo) -> Any:
        if v is None:
            return [] if isinstance(cls.model_fields[info.field_name].default, list) else ""
        if info.field_name in ("impugnante_rol", "genero_accionadas", "genero_vinculadas") and isinstance(v, str):
            return v.strip().lower()
        return v


class AperturaLLM(BaseModel):
    metadatos: MetadatosLLM
    cronologia: list[Evento]
    antecedentes_hechos: str = Field(description="Hechos y pretensiones en prosa corrida, tercera persona; párrafos separados por línea en blanco")
    contestaciones: list[Contestacion]
    sentencia_impugnada: str = Field(description="Decisión del a quo y su ratio, requisito por requisito, en prosa")
    impugnacion: str = Field(description="Un párrafo por reparo y cierre con la petición concreta")
    reparos: list[Reparo]
    pruebas_nuevas_2a: list[str] = []


class CitaPropuesta(BaseModel):
    id: str = Field(description="Identificador del marcador: c1, c2, ...")
    sentencia: str = Field(description="Identificador de la sentencia de la Corte Constitucional, p. ej. 'T-200 de 2022' o 'SU-082/95'")
    texto_citado: str = Field(description="Fragmento literal de la sentencia, copiado tal cual")
    reparo_ids: list[str] = []


class BloqueLLM(BaseModel):
    titulo: str
    reparo_ids: list[str] = []
    texto: str = Field(description="Prosa doctrinal con marcadores [[CITA:id]] donde se invoca cada sentencia")
    banco_id: Optional[str] = None


class ConsideracionesLLM(BaseModel):
    procedibilidad: str = Field(description="Marco doctrinal de procedibilidad elegido según los reparos, sin aplicarlo al caso")
    bloques: list[BloqueLLM]
    citas: list[CitaPropuesta]


class CitaVerificada(BaseModel):
    id: str
    sentencia_original: str
    sentencia_norm: Optional[str] = None
    tipo: Optional[str] = None
    numero: Optional[int] = None
    anio: Optional[int] = None
    texto_citado: str
    reparo_ids: list[str] = []
    en_dataset: bool = False
    mp_dataset: Optional[str] = None
    fecha_dataset: Optional[str] = None
    url: Optional[str] = None
    pagina_ok: bool = False
    cobertura: Optional[float] = None
    estado: Literal["ok", "alerta", "rechazada"] = "rechazada"
    motivos: list[str] = []


class ParrafoLLM(BaseModel):
    reparo_ids: list[str] = []
    texto: str = Field(description="Prosa argumentativa; solo puede citar con marcadores [[CITA:id]] de citas ya verificadas")


class CasoConcretoLLM(BaseModel):
    problema_juridico: str
    parrafos: list[ParrafoLLM]
    conclusion: str


class DisposicionReparo(BaseModel):
    reparo_id: str
    disposicion: Literal["ACOGE", "DESESTIMA", "ACOGE_PARCIAL", "REFORMULA", "ABSORBIDO"] = "ACOGE"
    nota: str = ""


class DisposicionDerecho(BaseModel):
    derecho: str
    disposicion: Literal["AMPARA", "NIEGA", "SIN_PRONUNCIAMIENTO"] = "AMPARA"


class Plazo(BaseModel):
    n: int = 48
    unidad: Literal["horas_habiles", "dias_habiles", "horas", "dias"] = "horas_habiles"


class Orden(BaseModel):
    verbo: Literal["ORDENAR", "PREVENIR", "ADVERTIR"] = "ORDENAR"
    destinatario: str
    via_representante: bool = True
    conducta: str
    plazo: Plazo = Plazo()
    condicion: str = ""
    literales: list[str] = []
    mismo_termino: bool = False


class Compulsa(BaseModel):
    organo: str = "Comisión Seccional de Disciplina Judicial de Antioquia"
    respecto_de: str
    hechos_ref: str = ""


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def limpiar_control(v: Any) -> Any:
    if isinstance(v, str):
        return _CONTROL.sub("", v)
    if isinstance(v, dict):
        return {k: limpiar_control(x) for k, x in v.items()}
    if isinstance(v, list):
        return [limpiar_control(x) for x in v]
    return v


class _SinControl(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _sin_control(cls, v: Any) -> Any:
        return limpiar_control(v) if isinstance(v, dict) else v


class DatosAuto(_SinControl):
    fecha: Optional[str] = None
    accionante: Optional[str] = None
    accionada: Optional[str] = None


CLAVES_NUMERAL = ("resultado", "sustitutiva", "prevenir", "desvincular", "compulsa", "notificar", "remitir")


def _iso_valida(v: str) -> bool:
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


class NumeralesEstandar(BaseModel):
    notificar: bool = True
    remitir_corte: bool = True


class Decision(_SinControl):
    accion: Literal["decidir", "rehacer_apertura", "rehacer_consideraciones"]
    instruccion: str = ""
    resultado: Optional[Literal["CONFIRMAR", "REVOCAR", "MODIFICAR"]] = None
    sustitutiva: Optional[
        Literal[
            "AMPARAR",
            "NEGAR",
            "IMPROCEDENTE",
            "CARENCIA_HECHO_SUPERADO",
            "CARENCIA_DANO_CONSUMADO",
            "CARENCIA_SOBREVINIENTE",
        ]
    ] = None
    eje: str = ""
    por_reparo: list[DisposicionReparo] = []
    derechos: list[DisposicionDerecho] = []
    ordenes: list[Orden] = []
    desvincular: list[str] = []
    prevenir: list[str] = []
    compulsa: Optional[Compulsa] = None
    numerales: NumeralesEstandar = NumeralesEstandar()
    decidido_por: str = ""
    previo_sha256: str = ""
    numerales_libres: list[str] = []
    orden_numerales: list[str] = []
    generar_formato: bool = False
    fecha_fallo: Optional[str] = None
    fecha_oficio: Optional[str] = None
    etiqueta_encabezado: str = ""

    def _clave_valida(self, k: str) -> bool:
        if k in CLAVES_NUMERAL:
            return True
        pref, _, i = k.partition(":")
        if not i.isdigit():
            return False
        n = {"orden": len(self.ordenes), "libre": len(self.numerales_libres)}.get(pref)
        return n is not None and int(i) < n

    def errores(self) -> list[str]:
        e: list[str] = []
        if self.accion.startswith("rehacer") and not self.instruccion.strip():
            e.append("Para rehacer hay que escribir una instrucción.")
        if self.accion == "decidir":
            if not self.resultado:
                e.append("Falta el resultado (CONFIRMAR, REVOCAR o MODIFICAR).")
            if not self.sustitutiva and self.resultado != "CONFIRMAR":
                e.append("Falta la decisión sustitutiva (AMPARAR, NEGAR, ...).")
            if not self.eje.strip():
                e.append("Falta el eje: 2 a 5 líneas con el porqué de la decisión.")
            if self.sustitutiva == "AMPARAR" and not self.ordenes:
                e.append("Si se ampara, hay que indicar al menos una orden.")
        for k in self.orden_numerales:
            if not self._clave_valida(k):
                e.append(f"Clave de numeral inválida en el orden: {k!r}.")
        if any(not t.strip() for t in self.numerales_libres):
            e.append("Hay un numeral libre vacío.")
        for campo in ("fecha_fallo", "fecha_oficio"):
            v = getattr(self, campo)
            if v is not None and not _iso_valida(v):
                e.append(f"{campo} no es una fecha ISO válida: {v!r}.")
        return e


class LlamadaIA(BaseModel):
    nodo: str
    intento: int
    proveedor: str
    modelo_pedido: str
    modelo_efectivo: Optional[str] = None
    prompt_id: str
    sha256_instrucciones: str
    sha256_entrada: str
    sha256_salida: str
    instrucciones: Optional[str] = None
    fecha: str
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    error: Optional[str] = None


class Estado(TypedDict, total=False):
    caso_dir: str
    config: dict[str, Any]
    ingesta: dict[str, Any]
    metadatos: dict[str, Any]
    apertura: Optional[dict[str, Any]]
    consideraciones: Optional[dict[str, Any]]
    citas: list[dict[str, Any]]
    decisiones: Annotated[list[dict[str, Any]], operator.add]
    caso: Optional[dict[str, Any]]
    errores: list[str]
    alertas: dict[str, list[str]]
    intentos: dict[str, int]
    bitacora: Annotated[list[dict[str, Any]], operator.add]
    salidas: dict[str, str]
