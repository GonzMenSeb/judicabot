from __future__ import annotations

import json
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def generar() -> str:
    from tutela2.server import app

    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(generar(), encoding="utf-8")


if __name__ == "__main__":
    main()
