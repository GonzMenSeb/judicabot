# Integración de Jev: segunda opinión de roles y verificación de metadatos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usar Jev (TypeSafe AI, modelo de decisión que no genera texto) como segunda opinión barata y medible en dos puntos donde hoy no hay verificación independiente: el rol de cada documento al ingerir y los metadatos que escribe el LLM en `apertura`.

**Architecture:** Un cliente HTTP delgado (`jev.py`) con un doble `FakeJev` para pruebas. Dos módulos de preguntas cerradas (`jev_roles.py`, `jev_metadatos.py`) que solo producen opiniones y alertas. Jev nunca bloquea, nunca toca la decisión del juez y arranca apagado. Un benchmark contra `referencia/analisis/ground_truth_1a.json` decide si el modo `relleno` merece activarse.

**Tech Stack:** Python 3.12, pydantic, `urllib.request` de la biblioteca estándar (sin dependencia nueva), pytest, LangGraph 1.2.

**Spec:** no hay spec propio. Contexto en `docs/superpowers/specs/2026-11-02-tutela2-primera-a-segunda-design.md`; las decisiones de este plan están en la sección "Decisiones" y en la API verificada de Jev.

## Global Constraints

- Comentarios al mínimo absoluto (CLAUDE.md del usuario). Nada de suposiciones sin fundamento: lo que no esté verificado se marca como valor inicial a calibrar.
- Jev **nunca** emite `BLOQUEA: `, nunca reintenta un nodo y nunca decide el sentido del fallo (Acuerdo PCSJA24-12243, arts. 3.6 y 8.3). Solo `lint.ALERTA` y, en modo `relleno`, asignar un rol que el código no pudo asignar.
- Valor por defecto `jev.modo = "apagado"`. Sin clave, o con la clave pero el modo apagado, no sale ninguna petición.
- La clave solo vive en la variable de entorno `JEV_API_KEY` (el archivo `.local.env` está en `.gitignore`; se carga con `uv run --env-file ../.local.env`). Nunca en `config.json`, en el repositorio ni en la bitácora.
- Las pruebas no usan red: todo con `FakeJev`. Las pruebas que sí la usan llevan el marcador `jev` y se omiten sin `JEV_API_KEY`.
- Datos reales (`referencia/`, `casos/`) nunca entran al repositorio. Los informes del benchmark se escriben fuera de él.
- Minimización de datos: a Jev solo se le envía el nombre del archivo y un fragmento (cabecera o cola) acotado por configuración, nunca el expediente completo.
- Cada petición a Jev queda en la bitácora como `LlamadaIA` con `proveedor="jev"` (alimenta la declaración del art. 10).
- Commits al final de cada tarea, con el pie `Claude-Session: https://claude.ai/code/session_01Xkg932FpsKAvXdQqGt2FYY`.

## API de Jev (verificada con la documentación oficial y una llamada real)

- `POST https://api.typesafe.ai/v1/systemone`, cabecera `Authorization: Bearer <clave>`, cuerpo `{"state": texto|objeto, "model": "jev-latest", "questions": {id: {"type": "choice"|"score"|"noul", "instructions": ..., "criteria": {opción: descripción}}}}`.
- Respuesta: `{"model": "jev-1.14.0", "answers": {id: {"type": "choice", "choice": str, "confidence": float, "probabilities": {opción: float}}}, "usage": {"input_tokens": int, "output_tokens": int}}`. Un `noul` responde `{"noul": float}`.
- Límites: cuerpo ≤ 32 MiB, `choice` ≤ 255 opciones. Estados: `400` (regla violada), `401` (clave), `422` (validación), `429` y `529` (reintentar con backoff exponencial).
- Debilidades documentadas que condicionan el diseño: no cuenta (por eso no se usa para contar reparos), lee las fechas como texto, tiende a la primera opción, se degrada con estado ruidoso o largo, no lleva bien varias preguntas escondidas en una.
- Primera llamada real: 10,3 s con 434 tokens de entrada. Latencia sin repetir, así que se usa concurrencia y un tiempo máximo de 60 s.

## Decisiones

- **Roles: Jev solo rellena huecos.** `clasificar.py` es determinista y tiene 390 líneas de pruebas contra 9 casos reales. Jev no puede anular una decisión suya ni un rol fijado por el usuario (`rol_origen == "usuario"`). En modo `relleno` solo asigna rol cuando `clasificar` devolvió `otro` por falta de rasgos (`"Sin texto legible."` o `"Sin rasgos de ningún rol."`), con confianza ≥ umbral. Ese es el fallo que cuesta caro: un escrito mal clasificado produce un correo de requerimiento para un expediente completo.
- **Metadatos: verificador independiente, no extractor.** `apertura` ya escribe `decision_a_quo` e `impugnante_rol` (texto libre y cerrado, respectivamente) y nadie los contrasta. Jev contesta preguntas cerradas sobre las mismas fuentes y se compara la etiqueta con la del LLM. Una discrepancia es una alerta.
- **Fuera de alcance, con razón:** contar reparos (Jev no cuenta, según su propia documentación); selección de bloques del banco (hay 5 semillas); detección de ruido (`_es_certificado` ya es determinista y barata); chequeos de coherencia sobre los borradores (los cubre `lint.py` con regex, y mezclan varios juicios en una pregunta).
- **Sin dependencia nueva.** Existe el paquete `typesafe-sdk`, pero el cliente necesario son unas 60 líneas con `urllib`. Si prefieres el SDK, cambia solo `HttpJev`.
- **El umbral de confianza es un valor inicial** (`0.9`) que la Tarea 3 calibra con datos; no tiene respaldo propio.

## Archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/tutela2/jev.py` (nuevo) | `JevClient`, `HttpJev`, `FakeJev`, `ErrorJev`, `cliente_jev`, `llamada_ia` |
| `backend/tutela2/jev_roles.py` (nuevo) | pregunta de rol, `segunda_opinion`, `aplicar` |
| `backend/tutela2/jev_metadatos.py` (nuevo) | `verificar_apertura` |
| `backend/tutela2/jev_bench.py` (nuevo) | benchmark contra la verdad de referencia |
| `backend/tutela2/config.py` | `JevConfig` y `Config.jev` |
| `backend/tutela2/models.py` | `Doc.rol_origen` acepta `"jev"`; `Ingesta.llamadas_jev` |
| `backend/tutela2/clasificar.py` | constantes `EVIDENCIA_SIN_TEXTO` y `EVIDENCIA_SIN_ROL` |
| `backend/tutela2/ingest.py` | `ingerir(..., jev=None)` llama a `jev_roles` |
| `backend/tutela2/graph.py` | `construir(..., jev=None)`, `nodo_validar_apertura`, `estado_inicial` |
| `backend/tutela2/cli.py`, `server.py`, `static/app.js` | comando `jev-bench`, clave y ajustes en la UI |
| `backend/tests/test_jev*.py` (nuevos) | pruebas con `FakeJev` |

## Review Focus

1. **Jev caído, lento o sin clave** (timeout, 401, 429 agotado, 529): la ingesta y `validar_apertura` terminan igual, con una sola alerta y sin excepción. Pruebas en las Tareas 1, 4 y 5.
2. **Documento sin texto** (escaneado sin OCR): no se hace ninguna petición, porque el estado sería solo el nombre del archivo. Prueba en la Tarea 2.
3. **Rol fijado por el usuario**: ni `relleno` ni `sombra` lo cambian, tampoco en una reingesta (`api.py:186` conserva `roles_usuario`). Prueba en la Tarea 4.
4. **Minimización**: la carga enviada contiene como máximo `max_chars_cabecera` caracteres del documento más el nombre del archivo. Prueba en la Tarea 2.
5. **Respuesta fuera del catálogo**: si Jev devuelve una etiqueta que no está entre las opciones declaradas, se ignora con una alerta y no se aplica. Prueba en la Tarea 2.

---

### Task 1: Cliente de Jev y configuración

**Files:**
- Create: `backend/tutela2/jev.py`
- Modify: `backend/tutela2/config.py` (añadir `JevConfig` y el campo `Config.jev`)
- Test: `backend/tests/test_jev.py`

**Interfaces:**
- Consumes: `Config` de `config.py`; `LlamadaIA` de `models.py`.
- Produces:
  - `class ErrorJev(Exception)`
  - `@dataclass class RespuestaJev: modelo: str; respuestas: dict[str, dict]; tokens_entrada: int; tokens_salida: int`
  - `class JevClient(Protocol): def preguntar(self, estado: str | dict, preguntas: dict[str, dict], modelo: str) -> RespuestaJev`
  - `class HttpJev: def __init__(self, clave: str, timeout_s: float, reintentos: int = 3, pausa_s: float = 1.0, base_url: str = "https://api.typesafe.ai")`; implementa `JevClient`. Las pruebas pasan `pausa_s=0` y `base_url` apuntando al servidor local.
  - `class FakeJev: def __init__(self, respuestas: dict[str, dict] | Callable[[str | dict, dict], dict]); .llamadas: list[tuple[str | dict, dict]]`; implementa `JevClient`
  - `def cliente_jev(cfg: Config) -> JevClient | None`: `None` si `cfg.jev.modo == "apagado"` o si falta `JEV_API_KEY`
  - `def llamada_ia(nodo: str, estado: str | dict, preguntas: dict[str, dict], resp: RespuestaJev) -> dict`: un `LlamadaIA` volcado a dict con `proveedor="jev"`, `prompt_id=f"jev-{nodo}-v1"` y los sha256 del estado, las preguntas y las respuestas
  - `JevConfig(modo: Literal["apagado","sombra","relleno"]="apagado", modelo: str="jev-latest", umbral_confianza: float=0.9, timeout_s: float=60.0, max_chars_cabecera: int=1500, max_chars_sentido: int=2500, concurrencia: int=6)`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_cliente_jev_apagado_o_sin_clave_devuelve_none(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente_jev(Config()) is None
    assert cliente_jev(Config(jev=JevConfig(modo="sombra"))) is None
    monkeypatch.setenv("JEV_API_KEY", "x")
    assert cliente_jev(Config()) is None
    assert isinstance(cliente_jev(Config(jev=JevConfig(modo="sombra"))), HttpJev)

def test_http_jev_arma_la_peticion_y_lee_la_respuesta(servidor_local):
    # servidor_local: http.server en un hilo que registra la petición y responde el JSON documentado
    r = HttpJev("clave", 5, pausa_s=0, base_url=servidor_local.url).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert servidor_local.recibida["headers"]["Authorization"] == "Bearer clave"
    assert servidor_local.recibida["json"]["model"] == "jev-latest"
    assert r.modelo == "jev-1.14.0" and r.tokens_entrada == 434

@pytest.mark.parametrize("estado", [401, 422])
def test_http_jev_no_reintenta_errores_de_cliente(servidor_local, estado): ...  # 1 petición y ErrorJev

def test_http_jev_reintenta_429_y_529_y_luego_falla(servidor_local): ...  # reintentos+1 peticiones y ErrorJev

def test_llamada_ia_no_contiene_la_clave_ni_el_texto():
    d = llamada_ia("roles", "texto secreto", PREGUNTA_EJEMPLO, RESP)
    assert d["proveedor"] == "jev" and "texto secreto" not in json.dumps(d)
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_jev.py -v`
Expected: FAIL (`ModuleNotFoundError: tutela2.jev`).

- [ ] **Step 3: Implementar `jev.py` y `JevConfig`**

`HttpJev.__init__` acepta además `base_url="https://api.typesafe.ai"` para poder apuntarlo al servidor local de las pruebas. Usar `urllib.request`; reintentar solo `429`, `529` y errores de conexión con espera `pausa_s * 2**i`; cualquier otro estado lanza `ErrorJev` con el cuerpo de error truncado. `FakeJev` con un callable recibe `(estado, preguntas)` y devuelve el dict de `answers`; con un dict, responde lo mismo a toda llamada. `Config.jev: JevConfig = JevConfig()`.

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd backend && uv run pytest tests/test_jev.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/jev.py backend/tutela2/config.py backend/tests/test_jev.py
git commit -m "feat: cliente de Jev con reintentos, doble para pruebas y configuración apagada por defecto"
```

---

### Task 2: Pregunta de rol y segunda opinión

**Files:**
- Create: `backend/tutela2/jev_roles.py`
- Modify: `backend/tutela2/clasificar.py:278,324` (reemplazar los dos textos por constantes)
- Test: `backend/tests/test_jev_roles.py`

**Interfaces:**
- Consumes: `Doc`, `Rol` de `models.py`; `texto_cabecera` de `clasificar.py`; `JevClient`, `llamada_ia` de la Tarea 1; `Config.jev`.
- Produces:
  - En `clasificar.py`: `EVIDENCIA_SIN_TEXTO = "Sin texto legible."` y `EVIDENCIA_SIN_ROL = "Sin rasgos de ningún rol."`
  - `ROLES_JEV: tuple[Rol, ...]`: todos los valores de `Rol` salvo `producto_despacho`, en orden fijo con `otro` al final
  - `@dataclass class OpinionRol: doc_id: str; rol: Rol; confianza: float; probabilidades: dict[str, float]; llamada: dict`
  - `def pregunta_rol(invertir: bool = False) -> dict[str, dict]`: una pregunta `choice` con id `"rol"` y una descripción en español por cada rol de `ROLES_JEV`; con `invertir=True` las opciones van en orden inverso
  - `def estado_rol(doc: Doc, max_chars: int) -> str | None`: `f"Nombre del archivo: {doc.nombre}\n\n{texto_cabecera(doc)[:max_chars]}"`, o `None` si el documento no tiene texto
  - `def segunda_opinion(docs: list[Doc], cliente: JevClient, cfg: Config, invertir: bool = False) -> tuple[list[OpinionRol], list[str]]`: concurrencia `cfg.jev.concurrencia`; devuelve las opiniones y las alertas (errores de Jev, etiquetas fuera del catálogo)

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_documento_sin_texto_no_genera_peticion():
    doc = doc_de(nombre="scan.pdf", paginas=[Pagina(n=1, texto="", sin_texto=True)])
    fake = FakeJev({"rol": CHOICE_OTRO})
    ops, alertas = segunda_opinion([doc], fake, Config(jev=JevConfig(modo="sombra")))
    assert fake.llamadas == [] and ops == []

def test_estado_enviado_esta_acotado_y_lleva_el_nombre():
    doc = doc_de(nombre="004Escrito.pdf", paginas=[Pagina(n=1, texto="x" * 9000)])
    estado = estado_rol(doc, 1500)
    assert estado.startswith("Nombre del archivo: 004Escrito.pdf")
    assert estado.count("x") <= 1500

def test_etiqueta_fuera_del_catalogo_se_ignora_con_alerta():
    fake = FakeJev({"rol": {"type": "choice", "choice": "inventado", "confidence": 0.99, "probabilidades": {}}})
    ops, alertas = segunda_opinion([doc_con_texto()], fake, Config(jev=JevConfig(modo="sombra")))
    assert ops == [] and any("inventado" in a for a in alertas)

def test_error_de_jev_produce_una_alerta_y_no_excepcion():
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(_lanza(ErrorJev("429"))), Config(jev=JevConfig(modo="sombra")))
    assert ops == [] and len(alertas) == 1

def test_roles_jev_excluye_producto_despacho_y_cubre_el_resto():
    assert "producto_despacho" not in ROLES_JEV
    assert set(ROLES_JEV) == set(get_args(Rol)) - {"producto_despacho"}
    assert ROLES_JEV[-1] == "otro"

def test_invertir_reordena_las_opciones():
    directo = list(pregunta_rol()["rol"]["criteria"])
    assert list(pregunta_rol(invertir=True)["rol"]["criteria"]) == directo[::-1]
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_jev_roles.py -v`
Expected: FAIL (`ModuleNotFoundError: tutela2.jev_roles`).

- [ ] **Step 3: Implementar**

Añadir las dos constantes a `clasificar.py` y usarlas en las líneas 278 y 324. En `jev_roles.py`, escribir una descripción corta por rol (qué es y cómo se reconoce, p. ej. `fallo_a_quo`: "Sentencia de primera instancia de la tutela, con un RESUELVE") y usar la `confidence` y las `probabilities` de la respuesta tal como vienen. Cada llamada exitosa agrega su `llamada_ia("roles", estado, preguntas, resp)` a `OpinionRol.llamada`.

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd backend && uv run pytest tests/test_jev_roles.py tests/test_clasificar.py -v`
Expected: PASS (las pruebas existentes de `clasificar` siguen pasando).

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/jev_roles.py backend/tutela2/clasificar.py backend/tests/test_jev_roles.py
git commit -m "feat: pregunta de rol para Jev con estado acotado y catálogo cerrado"
```

---

### Task 3: Benchmark contra la verdad de referencia

**Files:**
- Create: `backend/tutela2/jev_bench.py`
- Modify: `backend/tutela2/cli.py` (nuevo subcomando `jev-bench`)
- Test: `backend/tests/test_jev_bench.py`

**Interfaces:**
- Consumes: `ingerir` de `ingest.py` (con Jev apagado); `segunda_opinion`, `pregunta_rol` de la Tarea 2; `HttpJev`/`FakeJev` de la Tarea 1; formato de `referencia/analisis/ground_truth_1a.json`: lista de `{case, docs: [{file, role, confidence, evidence}], ...}`.
- Produces:
  - `def comparar(verdad: list[dict], ingestas: dict[str, Ingesta], opiniones: dict[str, list[OpinionRol]]) -> dict`: contiene `n_docs`, `exactitud_codigo`, `exactitud_jev`, `por_umbral: {umbral: {cobertura, exactitud}}`, `discrepancias: [{caso, archivo, verdad, codigo, jev, confianza}]`, `rescates` (el código dijo `otro`, la verdad no, y Jev acertó), `falsos_rellenos` (el código dijo `otro`, Jev propone otro rol distinto de la verdad), `sin_pareja: [archivo]`
  - `def correr(referencia: Path, cliente: JevClient, cfg: Config, invertir: bool = False) -> dict`
  - CLI: `uv run tutela2 jev-bench --referencia ../referencia [--invertir] [--salida RUTA]`; escribe el informe en `--salida` o en stdout y nunca dentro del repositorio

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_comparar_cuenta_rescates_y_falsos_rellenos():
    verdad = [{"case": "C", "docs": [
        {"file": "01PrimeraInstancia/C01Principal/a.pdf", "role": "escrito_tutela"},
        {"file": "01PrimeraInstancia/C01Principal/b.pdf", "role": "memorial"}]}]
    ing = {"C": ingesta_con([("a.pdf", "otro"), ("b.pdf", "otro")])}
    ops = {"C": [OpinionRol("1a-001", "escrito_tutela", 0.97, {}, {}), OpinionRol("1a-002", "contestacion", 0.95, {}, {})]}
    r = comparar(verdad, ing, ops)
    assert len(r["rescates"]) == 1 and len(r["falsos_rellenos"]) == 1

def test_documentos_sin_pareja_se_listan_no_se_descartan():
    r = comparar(VERDAD_CON_UN_ARCHIVO_DE_MAS, INGESTAS, OPINIONES)
    assert "archivo_de_mas.pdf" in r["sin_pareja"]

def test_por_umbral_baja_la_cobertura_al_subir_el_umbral():
    r = comparar(VERDAD, ING, OPS_CON_CONFIANZAS_VARIADAS)
    u = r["por_umbral"]
    assert u[0.99]["cobertura"] <= u[0.9]["cobertura"] <= u[0.5]["cobertura"]
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_jev_bench.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar `comparar`, `correr` y el subcomando**

La pareja entre verdad y documento es la ruta relativa a la carpeta del caso (`Doc.ruta` frente a `docs[].file`). Los umbrales evaluados son `0.5, 0.7, 0.8, 0.9, 0.95, 0.99`. Con `--invertir` se repite la corrida con las opciones en orden inverso y se informa cuántas etiquetas cambian (mide el sesgo hacia la primera opción). El informe incluye la latencia p50/p95 por petición y los tokens totales.

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd backend && uv run pytest tests/test_jev_bench.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/jev_bench.py backend/tutela2/cli.py backend/tests/test_jev_bench.py
git commit -m "feat: benchmark de roles de Jev contra la verdad de referencia"
```

- [ ] **Step 6: Compuerta de decisión (la ejecuta una persona, con la clave real)**

Run: `cd backend && uv run --env-file ../.local.env tutela2 jev-bench --referencia ../referencia --salida /tmp/jev-roles.md` y luego repetir con `--invertir`.

Regla para activar `relleno` por defecto, fijada antes de ver los resultados: en el umbral elegido, **cero** `falsos_rellenos` y al menos un `rescate` sobre los 9 casos. Si no se cumple, `relleno` sigue disponible pero la recomendación es `sombra`. El umbral por defecto de `JevConfig` se actualiza con el valor más bajo que cumpla la regla. Con solo 9 casos, el resultado se lee como indicio, no como garantía; si el código ya acierta todos los documentos, no hay nada que rescatar y se queda en `sombra`.

---

### Task 4: Integración en la ingesta (modos `sombra` y `relleno`)

**Files:**
- Modify: `backend/tutela2/jev_roles.py` (añadir `aplicar`), `backend/tutela2/models.py` (`Doc.rol_origen`, `Ingesta.llamadas_jev`), `backend/tutela2/ingest.py:821-824`, `backend/tutela2/graph.py:38-56` (`estado_inicial`)
- Test: `backend/tests/test_jev_ingesta.py`

**Interfaces:**
- Consumes: `segunda_opinion`, `OpinionRol` (Tarea 2); `cliente_jev` (Tarea 1); `EVIDENCIA_SIN_TEXTO`, `EVIDENCIA_SIN_ROL`.
- Produces:
  - `def aplicar(docs: list[Doc], opiniones: list[OpinionRol], cfg: Config) -> list[str]` en `jev_roles.py`: modo `sombra`, alerta por cada documento con `opinion.rol != doc.rol` y `confianza >= umbral`; modo `relleno`, además asigna `doc.rol = opinion.rol`, `doc.rol_origen = "jev"` y `doc.evidencia = f"Jev (confianza {c:.2f})"` solo si `doc.rol == "otro"`, la evidencia es una de las dos constantes, `doc.rol_origen == "contenido"` y `opinion.rol != "otro"`
  - `Doc.rol_origen: Literal["contenido", "usuario", "jev"]`
  - `Ingesta.llamadas_jev: list[dict] = []`
  - `ingerir(caso_dir: Path, cfg: Config, jev: JevClient | None = None) -> Ingesta`: si `jev` es `None` usa `cliente_jev(cfg)`; la llamada a `segunda_opinion` va entre el bucle `clasificar` y `resolver_caso`, y sus alertas se suman a `alertas_lectura`
  - `estado_inicial` inicializa `"bitacora": list(ing.llamadas_jev)`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_relleno_asigna_rol_solo_a_documentos_sin_rasgos(tmp_path):
    caso = carpeta_con(("escrito.pdf", TEXTO_SIN_RASGOS),)
    fake = FakeJev({"rol": choice("escrito_tutela", 0.97)})
    ing = ingerir(caso, Config(jev=JevConfig(modo="relleno")), jev=fake)
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen) == ("escrito_tutela", "jev")

def test_sombra_nunca_cambia_el_rol_y_alerta_la_discrepancia(tmp_path):
    caso = carpeta_con(("fallo.pdf", TEXTO_DE_FALLO),)
    fake = FakeJev({"rol": choice("impugnacion", 0.98)})
    ing = ingerir(caso, Config(jev=JevConfig(modo="sombra")), jev=fake)
    assert ing.documentos[0].rol == "fallo_a_quo"
    assert any("impugnacion" in a for a in ing.alertas_lectura)

def test_relleno_no_pisa_un_rol_decidido_por_el_codigo(tmp_path): ...  # fallo con rasgos + Jev dice otro rol: sigue fallo_a_quo

def test_relleno_respeta_el_umbral(tmp_path): ...  # confianza 0.5 con umbral 0.9: sigue "otro"

def test_rol_fijado_por_el_usuario_no_se_toca_aunque_jev_discrepe():
    doc = doc_de(rol="otro", rol_origen="usuario", evidencia=EVIDENCIA_SIN_ROL)
    aplicar([doc], [OpinionRol(doc.doc_id, "escrito_tutela", 0.99, {}, {})], Config(jev=JevConfig(modo="relleno")))
    assert (doc.rol, doc.rol_origen) == ("otro", "usuario")

def test_ingesta_termina_si_jev_falla(tmp_path):
    ing = ingerir(carpeta_con(("a.pdf", TEXTO_SIN_RASGOS),), Config(jev=JevConfig(modo="relleno")), jev=FakeJev(_lanza(ErrorJev("401"))))
    assert ing.documentos and any("Jev" in a for a in ing.alertas_lectura)

def test_modo_apagado_no_hace_peticiones(tmp_path):
    fake = FakeJev({"rol": choice("otro", 0.99)})
    ingerir(carpeta_con(("a.pdf", TEXTO_SIN_RASGOS),), Config(), jev=fake)
    assert fake.llamadas == []

def test_estado_inicial_copia_las_llamadas_de_jev_a_la_bitacora():
    ing = Ingesta(documentos=[], llamadas_jev=[{"nodo": "roles", "proveedor": "jev"}])
    assert estado_inicial(Path("."), Config(), ing)["bitacora"][0]["proveedor"] == "jev"
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_jev_ingesta.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**

`ingerir` pasa a `segunda_opinion` solo los documentos con texto y, si `jev` es `None`, no hace nada. Las `llamada` de cada `OpinionRol` van a `Ingesta.llamadas_jev`. Revisar `api.py:186` y `ingest.py:667,758`: la lógica de `roles_usuario` solo mira `"usuario"`, así que `"jev"` no se confunde con un rol fijado por la persona; confirmar con una prueba de reingesta.

- [ ] **Step 4: Ejecutar la suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS (toda la suite, sin los marcados `aceptacion` ni `jev`).

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/jev_roles.py backend/tutela2/models.py backend/tutela2/ingest.py backend/tutela2/graph.py backend/tests/test_jev_ingesta.py
git commit -m "feat: segunda opinión de Jev en la ingesta, en modo sombra o relleno"
```

---

### Task 5: Verificador de metadatos en `validar_apertura`

**Files:**
- Create: `backend/tutela2/jev_metadatos.py`
- Modify: `backend/tutela2/graph.py:240-260` (`nodo_validar_apertura`) y `:543` (`construir`)
- Test: `backend/tests/test_jev_metadatos.py`

**Interfaces:**
- Consumes: `Ingesta`, `AperturaLLM` de `models.py`; `JevClient`, `llamada_ia` (Tarea 1); `Config.jev`; `lint.ALERTA`.
- Produces:
  - `SENTIDOS: tuple[str, ...] = ("ampara", "niega", "improcedente", "carencia_actual_de_objeto", "otro")`
  - `ROLES_IMPUGNANTE: tuple[str, ...] = ("accionante", "accionada", "vinculada", "otro")`
  - `def verificar_apertura(ing: Ingesta, ap: AperturaLLM, cliente: JevClient, cfg: Config) -> tuple[list[str], list[dict]]`: una sola petición con `state` objeto y tres preguntas `choice`; devuelve las alertas (`lint.ALERTA` + texto) y la entrada de bitácora
  - `construir(cfg: Config, llm: LLMClient, checkpointer: Any, jev: JevClient | None = None)`; `nodo_validar_apertura(state, cfg, jev=None)` suma las alertas de `verificar_apertura` a `mensajes` y añade la llamada a `bitacora`
- Estado enviado: `{"fallo_resolutivo": <últimos cfg.jev.max_chars_sentido caracteres del documento fallo_a_quo>, "clausula": ap.metadatos.decision_a_quo, "escrito_impugnacion": <cabecera acotada del documento impugnacion>, "impugnante": ..., "accionante": ..., "accionadas": [...], "vinculadas": [...]}`
- Preguntas: `sentido_fallo` (sobre `fallo_resolutivo`), `sentido_clausula` (sobre `clausula`), ambas con el catálogo `SENTIDOS`; `rol_impugnante` con `ROLES_IMPUGNANTE`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_alerta_si_la_clausula_no_coincide_con_el_fallo():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    alertas, _ = verificar_apertura(ING, AP_CON_ROL("accionada"), fake, CFG_SOMBRA)
    assert any(a.startswith(lint.ALERTA) and "decision_a_quo" in a for a in alertas)

def test_sin_alertas_si_todo_coincide():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionada", 0.95)))
    assert verificar_apertura(ING, AP_CON_ROL("accionada"), fake, CFG_SOMBRA)[0] == []

def test_alerta_si_el_rol_del_impugnante_difiere():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionante", 0.95)))
    alertas, _ = verificar_apertura(ING, AP_CON_ROL("accionada"), fake, CFG_SOMBRA)
    assert any("impugnante_rol" in a for a in alertas)

def test_baja_confianza_no_genera_alerta():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.4), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    assert verificar_apertura(ING, AP_CON_ROL("accionada"), fake, CFG_SOMBRA)[0] == []

def test_la_peticion_lleva_solo_la_cola_del_fallo():
    fake = FakeJev(RESP_OK)
    verificar_apertura(ING_CON_FALLO_DE_20000_CARACTERES, AP, fake, CFG_SOMBRA)
    assert len(fake.llamadas[0][0]["fallo_resolutivo"]) <= CFG_SOMBRA.jev.max_chars_sentido

def test_jev_caido_deja_una_alerta_y_el_nodo_termina():
    r = nodo_validar_apertura(ESTADO_CON_APERTURA, CFG_SOMBRA, jev=FakeJev(_lanza(ErrorJev("529"))))
    assert "errores" in r and not any(e.startswith(lint.BLOQUEA) for e in r["errores"])

def test_modo_apagado_no_hace_peticiones():
    fake = FakeJev(RESP_OK)
    nodo_validar_apertura(ESTADO_CON_APERTURA, Config(), jev=fake)
    assert fake.llamadas == []
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_jev_metadatos.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**

`verificar_apertura` compara etiquetas solo cuando la confianza de ambas respuestas es ≥ `cfg.jev.umbral_confianza`. Para `rol_impugnante` compara contra `ap.metadatos.impugnante_rol` si no está vacío y, si no, contra `ing.metadatos.impugnante_rol`. Todo error de Jev se convierte en una única alerta; el modo `apagado` o la ausencia de cliente no hace nada. `construir` guarda `jev or cliente_jev(cfg)` y se lo pasa al nodo en el `lambda` ya existente (`graph.py:566`). La bitácora se devuelve con la misma clave `bitacora` que usa `nodo_apertura`.

- [ ] **Step 4: Ejecutar la suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/jev_metadatos.py backend/tutela2/graph.py backend/tests/test_jev_metadatos.py
git commit -m "feat: Jev verifica sentido del fallo e impugnante contra lo que escribe apertura"
```

---

### Task 6: Clave, ajustes en la UI y documentación

**Files:**
- Modify: `backend/tutela2/server.py:263,279-285` (estado y endpoint de la clave), `backend/tutela2/static/app.js:60` (etiquetas de la configuración) y `:593` (etiqueta del rol sugerido), `README.md`
- Test: `backend/tests/test_server.py` (ampliar)

**Interfaces:**
- Consumes: `JevConfig` (Tarea 1); `rol_origen == "jev"` (Tarea 4).
- Produces:
  - `POST /api/jev-key` con cuerpo `{"key": str}`: pone `os.environ["JEV_API_KEY"]` y responde `{"jev_key": True}`; la clave no se escribe en disco
  - `GET /api/estado-servidor` añade `"jev_key": bool(os.environ.get("JEV_API_KEY"))`
  - La pestaña Parámetros muestra `jev.modo` (apagado / sombra / relleno), `jev.umbral_confianza`, `jev.timeout_s`, `jev.max_chars_cabecera`, `jev.max_chars_sentido`, `jev.concurrencia`; las filas con `rol_origen == "jev"` muestran "Sugerido por Jev"

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_jev_key_se_guarda_solo_en_el_entorno(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    r = cliente.post("/api/jev-key", json={"key": "k-prueba"})
    assert r.json() == {"jev_key": True} and os.environ["JEV_API_KEY"] == "k-prueba"
    assert "k-prueba" not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))

def test_estado_servidor_informa_si_hay_clave_de_jev(cliente, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is False
    monkeypatch.setenv("JEV_API_KEY", "x")
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is True

def test_config_de_un_caso_acepta_y_devuelve_los_ajustes_de_jev(cliente, caso): ...  # PUT modo="sombra", GET devuelve "sombra"
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd backend && uv run pytest tests/test_server.py -k jev -v`
Expected: FAIL.

- [ ] **Step 3: Implementar el endpoint, el campo de estado, las etiquetas de la UI y el README**

Seguir el patrón de `guardar_api_key` (`server.py:279`). En `app.js`, revisar cómo se pintan los campos anidados de `llm.*` y repetirlo para `jev.*`. El README gana una sección "Jev" con: cómo arrancar con `uv run --env-file ../.local.env tutela2-ui`, el significado de los tres modos, el aviso de que el modo `relleno` envía fragmentos de documentos a un tercero (art. 8.6) y el comando `jev-bench`.

- [ ] **Step 4: Ejecutar la suite y verificar la UI**

Run: `cd backend && uv run pytest -q`
Expected: PASS.
Después: levantar `uv run --env-file ../.local.env tutela2-ui`, abrir Configuración y comprobar que los campos de Jev se ven, se guardan y sobreviven a recargar la página.

- [ ] **Step 5: Commit**

```bash
git add backend/tutela2/server.py backend/tutela2/static/app.js backend/tests/test_server.py README.md
git commit -m "feat: clave de Jev en memoria, ajustes en la UI y documentación"
```

---

## Enmienda (2026-11-03): puntuaciones de confianza visibles en la UI

Objetivo del usuario: en todos los pasos donde interviene una suposición de Jev, la UI muestra su puntuación de confianza. Esta enmienda prevalece sobre lo que contradiga a las Tareas 4 a 6.

- **Roles (Tarea 4).** `aplicar` guarda la opinión de Jev en cada `Doc` aunque no cambie el rol, y también en modo `sombra`: `Doc.jev_rol: Optional[str] = None`, `Doc.jev_confianza: Optional[float] = None`, `Doc.jev_probabilidades: dict[str, float] = {}`. Los tres quedan en `None`/vacío si Jev no opinó (apagado, sin texto, error o etiqueta fuera del catálogo).
- **Metadatos (Tarea 5).** `verificar_apertura` devuelve además un diccionario serializable `jev_metadatos` con la forma `{"modelo": str, "preguntas": {"sentido_fallo": {"choice": str, "confidence": float}, "sentido_clausula": {...}, "rol_impugnante": {...}}, "coincide": {"sentido": bool | None, "rol_impugnante": bool | None}}`; `None` significa que no se pudo comparar (confianza por debajo del umbral, o sin valor del LLM). Se guarda en el estado del grafo bajo la clave `jev_metadatos` (añadir `jev_metadatos: Optional[dict[str, Any]]` a `Estado` en `models.py` y a `estado_inicial` como `None`). Firma nueva: `verificar_apertura(...) -> tuple[list[str], list[dict], dict | None]`.
- **API (Tarea 6).** `_doc_resumen` (`api.py`) añade `jev_rol`, `jev_confianza`; `_resumen` añade `jev_metadatos`.
- **UI (Tarea 6).** (a) En la tabla de documentos, cada fila con `jev_rol` muestra una insignia "Jev: {rol} · {confianza en %}"; si `jev_rol` difiere del rol vigente se resalta como discrepancia, y si `rol_origen == "jev"` la fila dice "Sugerido por Jev · {%}". (b) En Revisión, una tarjeta "Verificación de Jev" con las tres respuestas, su porcentaje de confianza y una insignia "coincide" / "discrepa" / "sin comparar". (c) El porcentaje se pinta con tres tonos según el umbral configurado (`jev.umbral_confianza`) y uno neutro por debajo de él. (d) Sin datos de Jev no aparece nada: ni insignia ni tarjeta.
- **Pruebas añadidas.** Tarea 4: `test_opinion_de_jev_queda_en_el_documento_aunque_el_rol_no_cambie`; Tarea 5: `test_jev_metadatos_incluye_confianzas_y_coincidencias`; Tarea 6: `test_resumen_expone_jev_rol_y_confianza`, `test_resumen_expone_jev_metadatos` y una verificación en navegador con un caso sintético y `FakeJev`.

- **Ajuste posterior (2026-11-03).** (a) `HttpJev` reintenta **una sola vez** ante cualquier error de Jev (estado HTTP de error, conexión, tiempo agotado o respuesta mal formada); no reintenta los errores locales (clave con caracteres no válidos, tiempo máximo no válido) porque no llegan a salir. Esto sustituye a la política de la Tarea 1 (reintentar solo 429/529, tres veces). (b) La evidencia de un rol asignado por Jev ya no repite la confianza (`EVIDENCIA_JEV`), porque la UI la muestra una sola vez.

## Autorrevisión

- **Cobertura:** roles (Tareas 2 y 4), metadatos (Tarea 5), medición y decisión sobre `relleno` (Tarea 3), apagado por defecto y clave en memoria (Tareas 1 y 6), bitácora para el art. 10 (Tareas 1, 4 y 5). Los cuatro descartes están en "Fuera de alcance, con razón".
- **Consistencia de tipos:** `RespuestaJev`, `OpinionRol` y `llamada_ia` se definen en las Tareas 1 y 2 y se usan igual en las 3 a 5. `ROLES_IMPUGNANTE` coincide con los valores de `Metadatos.impugnante_rol` (`accionante`, `accionada`, `vinculada`, `otro`).
- **Proporción:** cada tarea se limita a firmas, pruebas y valores fijados; los cuerpos los escribe quien implemente.
- **Riesgo reconocido:** la integración de metadatos depende de la calidad de Jev sobre texto jurídico colombiano, que no está medida (la documentación no dice nada del idioma ni del ruido de OCR). Por eso la Tarea 5 solo alerta y la compuerta de la Tarea 3 mide los roles antes de activar nada. La verificación de metadatos no tiene benchmark propio: solo hay una compuerta sobre los roles. Si quieres medirla también, el siguiente paso sería añadir `sentido_fallo` al benchmark, comparando contra `fallo_a_quo_decision` de la verdad de referencia.
