# Spike B7: razonamiento del modelo en el proceso en vivo

Estado: el script está listo y probado sin red; **no se ha ejecutado contra el modelo real** (en este entorno no hay clave). Lo corre el usuario con su clave. No bloquea el resto: si el spike falla, el proceso en vivo queda con los eventos del sistema.

## Qué se quiere saber

| | Pregunta | Cómo la responde el spike |
|---|---|---|
| a | ¿Se pueden transmitir resúmenes de razonamiento junto con la salida estructurada (`output_config.format`), con el `effort` de hoy y por el mismo camino que usa producción (`beta.messages.stream` con `fallbacks="default"`)? | Variante `resumen` frente a `base`: `ok`, `error`, `esquema_valido`, `stop_reason` |
| b | ¿Qué eventos llegan y cuánta latencia añaden? | Tabla de eventos con tiempos; `tiempos_s` y `s_por_1000_tokens_salida` por variante |
| c | ¿Cómo exponerlos desde `AnthropicClient` sin cambiar su contrato? | Propuesta de cambio más abajo (validada contra las pruebas existentes) |
| d | ¿Cuánto texto llega y conviene mostrarlo ("Razona")? | `razonamiento.chars`, `bloques[].parrafos`, `huecos_mediana_s`, `razonamiento.idioma`, y el texto mismo (caso sintético) |

Lo que ya dice la documentación de la API (skill `claude-api`, tabla cacheada el 2026-10-06; el spike lo confirma o lo desmiente):

- `claude-sonnet-5-5` sin parámetro `thinking` ya corre con pensamiento adaptativo. Hoy `llm.py` no envía `thinking`, así que el modelo piensa y se factura, pero con `display` en `omitted` (valor por defecto): los bloques `thinking` llegan **vacíos**. Por eso hoy no hay nada que mostrar.
- `thinking: {"type": "adaptive", "display": "summarized"}` devuelve un resumen legible del razonamiento. `display` solo cambia la visibilidad: el pensamiento ocurre y se factura igual con cualquier valor.
- `budget_tokens` y `thinking: {"type": "disabled"}` dan 400 en este modelo; no se usan.
- `display: "updates"` (beta `thinking-display-updates-2026-08-18`) entrega las notas de progreso que el modelo escribe entre llamadas a herramientas. La apertura no usa herramientas, así que se espera vacío; queda como variante opcional.

Lo que **no** se sabe y mide el spike: si `summarized` convive con `output_config.format` + `effort: high` + `fallbacks` en el endpoint beta; cuántos eventos y de qué tamaño; si el resumen llega en español; cuánto tarda en aparecer el primer texto.

## Cómo correrlo

```bash
cd backend
export ANTHROPIC_API_KEY=sk-ant-...
uv run python scripts/spike_razonamiento.py --solo-entrada        # sin clave: muestra el prompt y los parámetros que se enviarían
uv run python scripts/spike_razonamiento.py --modelo claude-sonnet-5-5
```

- Usa el caso sintético (ficticio; necesita LibreOffice `soffice`, como `caso_sintetico.py`). Con `--caso <carpeta>` usa un caso ya creado (lee su `caso.json`); en ese caso el texto del razonamiento **no** se guarda salvo con `--guardar-texto`, porque puede citar datos del expediente.
- Construye la entrada de la etapa `apertura` con el mismo código de producción (`graph.nodo_apertura` con un cliente espía): mismo prompt de sistema, mismas secciones, mismo esquema `AperturaLLM`, mismo `effort`, `max_tokens`, `timeout` y reintentos de la configuración. Con el caso sintético son unos 34 000 caracteres (~8 600 tokens estimados).
- Variantes (`--variantes`, por defecto `base,resumen`): `base` = la petición de hoy; `resumen` = `thinking` adaptativo con `display: "summarized"`; `updates` = `display: "updates"` con su cabecera beta.
- `--repeticiones N` repite cada variante; una sola llamada solo es indicativa de latencia porque la longitud de la salida varía entre corridas (compare con `s_por_1000_tokens_salida` y el tiempo hasta el primer texto).
- Pide confirmación antes de llamar (`--si` la omite). Costo: cada llamada tiene tope de 64 000 tokens de salida; con la tarifa de Sonnet 5.5 de la skill (2 USD de entrada y 10 USD de salida por millón de tokens) el peor caso es unos 0,66 USD por llamada y lo habitual, bastante menos. Confirme la tarifa vigente en la página de precios.
- Sin clave sale con código 2 e imprime estas instrucciones. Si una variante da 400, se registra el error y se sigue con las demás (un 400 también es una respuesta a la pregunta a).
- Escribe `backend/scripts/salida/spike_razonamiento.json` (se reescribe después de cada llamada, así que una interrupción conserva lo hecho).

## Qué pegar de vuelta

El contenido de `backend/scripts/salida/spike_razonamiento.json` (con el caso sintético solo contiene texto ficticio) y la tabla "Resumen" que imprime el script. Campos clave por variante:

- `ok`, `error` (tipo, HTTP, mensaje), `stop_reason`, `esquema_valido`, `modelo_efectivo`, `request_id`.
- `tiempos_s`: `conexion`, `message_start`, `primer_thinking_con_texto`, `primer_text_delta`, `total`, `s_por_1000_tokens_salida`.
- `razonamiento`: `bloques`, `chars`, `visible`, `idioma` (`probable`: es/en/mixto, conteo de marcas).
- `bloques[]`: por bloque `tipo`, `t_inicio`, `t_primer_delta_con_texto`, `t_fin`, `n_deltas`, `delta_chars_mediana`, `huecos_mediana_s`, `huecos_max_s`, `parrafos`, `texto`.
- `eventos_por_tipo` y `lineas_de_tiempo`: la tabla de eventos completa (cualquier tipo de evento o bloque desconocido, como un bloque `fallback`, aparece tal cual llega).

## Cómo decidir con los resultados

| Resultado | Decisión |
|---|---|
| `resumen` da 400 o `esquema_valido` es falso donde `base` es válido | No aplicar el cambio. El proceso queda con eventos del sistema. Pegar el mensaje de error |
| `resumen` válido, `razonamiento.visible` verdadero, `idioma.probable` = `es` | Aplicar el cambio de abajo y emitir `razona` |
| `visible` verdadero pero `idioma` = `en` o `mixto` | Decidir si se acepta mostrar inglés o se descarta; controlar el idioma desde el prompt no se probó en este spike |
| `bloques[].parrafos` alto o `huecos_mediana_s` muy pequeño | Agrupar más antes de emitir (por tiempo, además de por párrafo) para no saturar el buffer de 2 000 eventos por job |
| `primer_thinking_con_texto` mucho menor que `primer_text_delta` | El "Razona" llena la espera real de la apertura; es el caso de uso |
| `total` y `s_por_1000_tokens_salida` de `resumen` similares a `base` | El resumen no añade latencia apreciable |
| `updates` vacío | Esperado (sin herramientas); descartarlo |

Nota: no pedir al modelo en el prompt que "escriba su razonamiento"; la skill advierte que eso invita a rechazos por `reasoning_extraction`. Los prompts actuales no lo piden.

Sobre mostrarlo: es un **resumen** generado por el modelo, no el razonamiento crudo; la UI debe rotularlo así ("Razona" con el resumen) y no tratarlo como fundamento jurídico. Se recomienda no guardarlo en la bitácora de llamadas (`LlamadaIA`), en los `.docx` ni en `fallos_ia.jsonl`; solo viaja por el flujo de eventos del job.

## Cambio propuesto en `llm.py`

No se aplicó (este paquete no modifica `llm.py`). El diff se verificó sobre una copia del árbol en `HEAD`: las 38 pruebas de `tests/test_llm.py` pasan sin cambios y 4 pruebas nuevas también (apéndice; el resto de la base solo llama a `llm.cliente_para(cfg)` desde `api.py` y usa `FakeClient`, y no toca `_llamar`/`_una`; la petición no cambia sin callback; con callback lleva `thinking` y el callback recibe `(nodo, párrafo)` en orden; un callback que falla no rompe la llamada; `cliente_para` pasa el callback y `FakeClient` lo ignora).

Decisiones de diseño:

- El contrato `LLMClient.estructurado(nodo, system, user, schema, cfg)` y `FakeClient` no cambian. El callback se inyecta al construir el cliente (`cliente_para(cfg, on_razonamiento=...)`), y recibe `(nodo, texto)`: `nodo` coincide con los valores `etapa` del contrato (`apertura`, `consideraciones`, `caso_concreto`).
- Sin callback la petición es idéntica a la de hoy (no se envía `thinking`; la prueba existente que lo exige sigue en pie) y se sigue usando `get_final_message()`.
- Con callback se envía `thinking={"type": "adaptive", "display": "summarized"}` (los tipos del SDK 2.4.0 lo aceptan en el endpoint estándar y en el beta; que la API lo acepte junto con `output_config` y `fallbacks` es justo lo que mide el spike) y se itera el stream en vez de esperar al mensaje final; luego se llama a `get_final_message()` como siempre.
- Se emite un texto por **párrafo** completo (separador `\n\n`) y el resto al cerrar el bloque, para no inundar el buffer de eventos. Si el spike muestra párrafos muy largos o muy escasos, añadir un vaciado por tiempo (cada ~1,5 s) en `_final`.
- Un callback que lanza excepción se registra y no interrumpe la llamada al modelo.
- Efectos laterales: cada reintento del validador (`max_intentos`), la repetición por `refusal` y la repetición sin fallbacks tras un 400 generan otro flujo de razonamiento; la UI verá varios bloques "Razona" por etapa.

```diff
--- a/backend/tutela2/llm.py
+++ b/backend/tutela2/llm.py
@@ -3,7 +3,7 @@
 import json
 import logging
 import re
-from typing import Any, Protocol
+from typing import Any, Callable, Protocol
 
 from pydantic import BaseModel, ValidationError
 
@@ -63,12 +63,16 @@
     return {partes[i]: partes[i + 1].strip() for i in range(1, len(partes) - 1, 2)}
 
 
+RazonamientoFn = Callable[[str, str], None]
+
+
 class AnthropicClient:
-    def __init__(self, client: Any = None):
+    def __init__(self, client: Any = None, on_razonamiento: RazonamientoFn | None = None):
         import anthropic
 
         self._anthropic = anthropic
         self._client = client or anthropic.Anthropic()
+        self._on_razonamiento = on_razonamiento
 
     def estructurado(
         self, nodo: str, system: str, user: str, schema: type[BaseModel], cfg: Config
@@ -85,15 +89,17 @@
             output_config={"effort": cfg.effort_para(nodo), "format": to_json_output_format(schema)},
             timeout=cfg.llm.timeout_s,
         )
+        if self._on_razonamiento:
+            args["thinking"] = {"type": "adaptive", "display": "summarized"}
         cliente = self._client.with_options(max_retries=cfg.llm.max_retries)
         previos: list[Any] = []
         try:
             respaldo = RESPALDO_CLIENTE.get(modelo) if cfg.llm.fallbacks_default else None
-            resp = self._llamar(cliente, args, cfg.llm.fallbacks_default and modelo not in RESPALDO_CLIENTE)
+            resp = self._llamar(cliente, args, cfg.llm.fallbacks_default and modelo not in RESPALDO_CLIENTE, nodo)
             if resp.stop_reason == "refusal" and respaldo:
                 log.warning("%s rechazó la solicitud; se repite con %s.", modelo, respaldo)
                 previos.append(resp)
-                resp = self._llamar(cliente, {**args, "model": respaldo}, True)
+                resp = self._llamar(cliente, {**args, "model": respaldo}, True, nodo)
                 if resp.stop_reason == "refusal":
                     raise ErrorLLM(f"Los modelos {modelo} y {respaldo} rechazaron la solicitud (stop_reason=refusal).")
         except TypeError as e:
@@ -128,22 +134,43 @@
         }
         return salida, meta
 
-    def _llamar(self, cliente: Any, args: dict, fallbacks: bool):
+    def _llamar(self, cliente: Any, args: dict, fallbacks: bool, nodo: str):
         if not fallbacks:
-            return self._una(cliente, args)
+            return self._una(cliente, args, nodo)
         try:
             with cliente.beta.messages.stream(**args, betas=[BETA_FALLBACK], fallbacks="default") as flujo:
-                return flujo.get_final_message()
+                return self._final(flujo, nodo)
         except self._anthropic.BadRequestError as e:
             if "fallback" not in str(e).lower():
                 raise
             log.warning("La API rechazó los fallbacks del servidor; se reintenta sin ellos: %s", e)
-            return self._una(cliente, args)
+            return self._una(cliente, args, nodo)
 
-    @staticmethod
-    def _una(cliente: Any, args: dict):
+    def _una(self, cliente: Any, args: dict, nodo: str):
         with cliente.messages.stream(**args) as flujo:
+            return self._final(flujo, nodo)
+
+    def _final(self, flujo: Any, nodo: str):
+        if self._on_razonamiento is None:
             return flujo.get_final_message()
+        pendiente = ""
+        for ev in flujo:
+            if ev.type == "content_block_delta" and ev.delta.type == "thinking_delta":
+                *completos, pendiente = (pendiente + ev.delta.thinking).split("\n\n")
+                for parrafo in completos:
+                    self._razona(nodo, parrafo)
+            elif ev.type == "content_block_stop":
+                self._razona(nodo, pendiente)
+                pendiente = ""
+        return flujo.get_final_message()
+
+    def _razona(self, nodo: str, texto: str) -> None:
+        if not texto.strip():
+            return
+        try:
+            self._on_razonamiento(nodo, texto.strip())
+        except Exception:
+            log.exception("%s: falló el callback de razonamiento", nodo)
 
 
 def _tokens(resp: Any) -> tuple[int, int]:
@@ -418,7 +445,7 @@
     return [items[int(j * paso)] for j in range(k)]
 
 
-def cliente_para(cfg: Config) -> LLMClient:
+def cliente_para(cfg: Config, on_razonamiento: RazonamientoFn | None = None) -> LLMClient:
     if cfg.llm.proveedor == "fake":
         return FakeClient()
-    return AnthropicClient()
+    return AnthropicClient(on_razonamiento=on_razonamiento)
```

## Evento `razona` y cableado con B3

El contrato (B3) ya reserva `tipo: "razona"` en `Evento {n, t, etapa, tipo, texto, datos}`. `eventos.py` aún no existe en el árbol al escribir esto, así que lo siguiente **no está verificado contra el módulo real** y se basa en la firma `emitir(etapa, tipo, texto, datos)` del plan y en el contrato:

```python
def razonamiento(nodo: str, texto: str) -> None:
    emitir(nodo, "razona", texto, None)
```

`api.py`, en los tres sitios donde hoy se hace `llm.cliente_para(cfg)` (`iniciar`, `decidir` y `continuar`):

```python
with _grafo(caso_dir, cfg, llm.cliente_para(cfg, on_razonamiento=eventos.razonamiento)) as (g, hilo):
```

- `emitir` debe ser un no-op cuando no hay job en el contextvar (CLI y pruebas), igual que el manejador de logs que ya filtra con `_JOB_ACTUAL` (`server.py`). El grafo se ejecuta de forma síncrona en el hilo del job, por lo que el contextvar es visible en el callback de la misma forma que lo es para `_JobHandler`.
- Si se quiere un interruptor, puede colgarse de las preferencias de IA (B6): pasar `on_razonamiento` solo si el usuario activó "mostrar razonamiento". Sin callback el comportamiento es el de hoy.
- Aumento de eventos: un `razona` por párrafo y por etapa e intento. Con el campo `bloques[].parrafos` del JSON del spike se puede comprobar que queda muy por debajo del tope de 2 000 eventos por job.
- Pendiente de F4: mostrar el evento como "Razona" con el texto del resumen, y el número de intento si se decide pasarlo en `datos` (el callback actual no lo conoce; `graph._llamar` sí).

## Apéndice: pruebas que acompañan el cambio

Archivo nuevo `backend/tests/test_llm_razonamiento.py` (escrito y pasando sobre la copia de `HEAD` con el diff aplicado, junto con `tests/test_llm.py`: 42 pruebas). Reutiliza los ayudantes de `test_llm.py` (`CASO`, `sdk_real`, `httpx`) y el SDK real contra un transporte simulado, no mocks del stream.

```python
from __future__ import annotations

import json

from test_llm import CASO, httpx, sdk_real
from tutela2.config import Config
from tutela2.llm import AnthropicClient, FakeClient, cliente_para
from tutela2.models import CasoConcretoLLM


def ev(tipo: str, datos: dict) -> str:
    return f"event: {tipo}\ndata: {json.dumps({'type': tipo, **datos})}\n\n"


def sse_con_razonamiento(partes: list[str]) -> httpx.Response:
    mensaje = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-efectivo", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 0},
    }
    cuerpo = [
        ev("message_start", {"message": mensaje}),
        ev("content_block_start", {"index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
        *[ev("content_block_delta", {"index": 0, "delta": {"type": "thinking_delta", "thinking": p}}) for p in partes],
        ev("content_block_delta", {"index": 0, "delta": {"type": "signature_delta", "signature": "firma"}}),
        ev("content_block_stop", {"index": 0}),
        ev("content_block_start", {"index": 1, "content_block": {"type": "text", "text": ""}}),
        ev("content_block_delta", {"index": 1, "delta": {"type": "text_delta", "text": CASO.model_dump_json()}}),
        ev("content_block_stop", {"index": 1}),
        ev("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}}),
        ev("message_stop", {}),
    ]
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(cuerpo).encode())


PARTES = ["Leo la impugn", "ación.\n", "\nIdentifico dos reparos", " y el sentido del fallo.\n\nEstructuro la salida"]


def correr(callback, partes=PARTES):
    cuerpos: list[dict] = []

    def manejador(peticion):
        cuerpos.append(json.loads(peticion.content))
        return sse_con_razonamiento(partes)

    cliente = AnthropicClient(sdk_real(manejador), on_razonamiento=callback)
    salida, meta = cliente.estructurado("apertura", "s", "u", CasoConcretoLLM, Config())
    return salida, meta, cuerpos[0]


def test_el_callback_recibe_el_razonamiento_por_parrafos_y_pide_el_resumen():
    recibido: list[tuple[str, str]] = []
    salida, meta, cuerpo = correr(lambda nodo, texto: recibido.append((nodo, texto)))
    assert salida == CASO and meta["tokens_salida"] == 2
    assert cuerpo["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert recibido == [
        ("apertura", "Leo la impugnación."),
        ("apertura", "Identifico dos reparos y el sentido del fallo."),
        ("apertura", "Estructuro la salida"),
    ]


def test_sin_callback_la_peticion_no_cambia():
    salida, _, cuerpo = correr(None)
    assert salida == CASO and "thinking" not in cuerpo
    assert cuerpo["fallbacks"] == "default"


def test_un_callback_que_falla_no_rompe_la_llamada(caplog):
    def malo(nodo, texto):
        raise RuntimeError("boom")

    salida, _, _ = correr(malo)
    assert salida == CASO
    assert "falló el callback de razonamiento" in caplog.text


def test_cliente_para_pasa_el_callback_y_fake_lo_ignora(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: object())
    f = lambda nodo, texto: None
    assert cliente_para(Config(), on_razonamiento=f)._on_razonamiento is f
    from tutela2.config import LLMConfig

    assert isinstance(cliente_para(Config(llm=LLMConfig(proveedor="fake")), on_razonamiento=f), FakeClient)
```
