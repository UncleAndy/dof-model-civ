"""СИЛЫ ЮНИТОВ ИЗ ПРАВИЛ МИРА (`units.ruleset`) — для его же формул (§13.387).

Его ИИ считает желание войска из сил юнита: `defense_desirability = hp*fp*defense + …`
(`ai/default/daimilitary.c`, перенесён в `brain/ai_default/military_want.py`). Силы — это
характеристика мира, а не наша выдумка: решение владельца 2026-10-12 разрешает брать
характеристики мира из кода и хранить их.

Имена полей в правилах: `hitpoints`, `firepower`, `attack`, `defense`, `build_cost`,
`move_rate`; в его формулах они называются `hp`, `fp`, `attack`, `defense`, `cost`,
`move_rate` — переименование здесь и только здесь.

Ничего не досчитываем: чего в правилах нет, того в записи нет.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_RULESET = "drafts/reference/freeciv-src/data/classic/units.ruleset"

_RENAME = {
    "hitpoints": "hp",
    "firepower": "fp",
    "attack": "attack",
    "defense": "defense",
    "build_cost": "cost",
    "move_rate": "move_rate",
    "pop_cost": "pop_cost",
}


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:
        return None


def _plain_name(value: str) -> str:
    """`_("Warriors")` → `Warriors`."""
    return value.replace("_(", "").replace(")", "").strip().strip('"')


def parse_units(text: str) -> dict[str, dict[str, Any]]:
    """`{имя: {hp, fp, attack, defense, cost, move_rate, flags}}` по разделам `[unit_*]`."""
    out: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    for raw in str(text).splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = {} if line.startswith("[unit_") else None
            continue
        if cur is None or not line or line.startswith(";") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "name":
            name = _plain_name(value)
            out[name] = cur
            continue
        if key in _RENAME:
            num = _number(value)
            cur[_RENAME[key]] = num if num is not None else value
            continue
        if key == "flags":
            cur["flags"] = [f.strip().strip('"') for f in value.split(",") if f.strip()]
    return out


def load_units(path: str | Path = DEFAULT_RULESET) -> dict[str, dict[str, Any]]:
    """Силы юнитов из файла правил; при отсутствии файла — пустой словарь."""
    try:
        return parse_units(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}
