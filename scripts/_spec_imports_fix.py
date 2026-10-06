"""Разовая утилита: делает импорты эталонного ядра DOF-Core пакетными (brain.spec).

Эталон (`DOF-CORE/patterns/python`) импортирует свои модули по «плоским» именам
(`from measurement import ...`). В проекте ядро живёт пакетом `brain/spec`, поэтому
импорты делаются относительными. Ничего, кроме строк импорта, не меняется.

Запуск:  .venv/bin/python scripts/_spec_imports_fix.py
"""
from __future__ import annotations

import pathlib
import re

MODULES = [
    "measurement", "calculus_core", "world_graph", "hypothesis", "orchestrator",
    "generator", "graph_mapper", "fixture_v07", "fixture_v011", "options_v07",
]
ALT = "|".join(MODULES)

TARGET = pathlib.Path(__file__).resolve().parent.parent / "brain" / "spec"


def main() -> int:
    changed = 0
    for path in sorted(TARGET.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        orig = text
        # from MOD import ...  ->  from .MOD import ...   (с любым отступом — импорты бывают
        # и внутри функций, напр. в fixture_v011.observed_only)
        text = re.sub(rf"^(\s*)from ({ALT})\b", r"\1from .\2", text, flags=re.M)
        # import MOD           ->  from . import MOD
        text = re.sub(rf"^(\s*)import ({ALT})\b", r"\1from . import \2", text, flags=re.M)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            changed += 1
            print("patched:", path.name)
    print("файлов изменено:", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())