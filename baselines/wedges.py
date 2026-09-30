"""Реестр клинов стенда: какие действия подвешивают сервер.

ЗНАНИЕ О СТЕНДЕ, а не часть модели. Перенесено из v1 (`env/wedged.py` + `wedged_actions.json`),
потому что это измеренный факт мира: на некоторых действиях сервер не отвечает, и партия
теряется целиком. Реестр **накапливается**: каждый клин — измерение, и следующий матч за него
уже не платит.

Измерено в v1 (реестр из git): `city/city_buy_production`, `city/city_change_specialist_0`.
Измерено в v2 (живой прогон, 30.09.2026): `unit/plant` — шаг не вернулся за 60 с.

Файл реестра лежит в корне проекта (`wedged_actions.json`), форма совместима с v1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "wedged_actions.json"


def _load() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def known() -> dict[str, dict[str, Any]]:
    """Весь реестр: `{«контроллер/действие»: запись}`."""
    return _load()


def is_wedged(ctrl_type: str, action_name: str) -> bool:
    """Известно ли, что на этом действии сервер подвешивало.

    Сравнение по точному имени и по семейству (имя до первого `_`), потому что сервер
    различает варианты (`city_change_specialist_0`, `city_change_specialist_3`), а клинит
    на всём семействе.
    """
    registry = _load()
    key = f"{ctrl_type}/{action_name}"
    if key in registry:
        return True
    family = str(action_name).split("_")[0]
    return any(f"{ctrl_type}/{family}" == k or
               str(v.get("family")) == family and str(v.get("ctrl_type")) == ctrl_type
               for k, v in registry.items())


def record_wedge(ctrl_type: str, action_name: str, *, turn: int,
                 agent: str = "", context: Optional[dict] = None) -> dict:
    """Записать клин. Партия потеряна, знание остаётся."""
    registry = _load()
    key = f"{ctrl_type}/{action_name}"
    entry = registry.get(key) or {
        "ctrl_type": ctrl_type,
        "action_name": action_name,
        "family": str(action_name).split("_")[0],
        "first_turn": turn,
        "seen": 0,
        "context": {},
    }
    entry["seen"] = int(entry.get("seen", 0)) + 1
    entry["last_turn"] = turn
    ctx = dict(entry.get("context") or {})
    if agent:
        ctx["agent"] = agent
    if context:
        ctx.update(context)
    entry["context"] = ctx
    registry[key] = entry
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry