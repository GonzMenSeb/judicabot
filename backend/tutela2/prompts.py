from __future__ import annotations

import hashlib
from pathlib import Path

from tutela2.config import NODOS_LLM, Config

DIRECTORIO = Path(__file__).with_name("prompts")


def prompt_default(nodo: str) -> str:
    return (DIRECTORIO / f"{nodo}.md").read_text(encoding="utf-8").strip()


def version_default(nodo: str) -> str:
    return hashlib.sha256(prompt_default(nodo).encode("utf-8")).hexdigest()[:12]


def prompts_default() -> dict[str, str]:
    return {nodo: prompt_default(nodo) for nodo in NODOS_LLM}


def prompt_para(nodo: str, cfg: Config) -> tuple[str, str]:
    texto = cfg.prompts_override.get(nodo, "").strip()
    if texto:
        return texto, f"{nodo}@override"
    return prompt_default(nodo), f"{nodo}@{version_default(nodo)}"
