"""Действия, о которые стенд заклинивает: это знание, а не догадка.

Почему отдельный файл, а не константа в коде. Клинч зависит от пары
действие×местность (`irrigation` на речной равнине, `build_road` на уже
орошённой) — предсказать его из имени действия нельзя, а обнаружить можно
только исполнением. Значит, это **измеренный** факт, и он должен пережить
матч: модель мира живёт один матч, а клинч убивает именно тот матч, в котором
случился.

Что здесь есть:
* `record_wedged()` — записать измеренный клинч (атомарно, с контекстом);
* `is_wedged()` — спросить, известно ли уже, что действие заклинивает;
* файл переживает прогоны, поэтому длинный турнир не наступает на грабли
  заново через каждые двадцать ходов.

Контекст клетки записывается, когда он доступен. Контекстные вызовы
`is_wedged()` проверяют повторы на той же позиции; вызовы без координат сохраняют
старое семейное поведение. Исторические записи без позиции остаются в файле,
но успешный возврат `env.step` разрешает действие только в наблюдённой позиции:
там шаг отработал без клинча. Это не удаляет счётчики отказов; старый семейный
запрет остаётся для других позиций, а позиционные записи не сбрасываются.

ПРАВИЛО ОТСЕЧЕНИЯ: один timeout — подозрение; нужны два неразрешённых timeout
в одной позиции. `reason == "refused"` подтверждает отказ сразу, но только в
соответствующем контексте. Для старых вызовов без позиции порог остаётся
семейным. Возврат шага снимает текущий порог для наблюдённого действия, не
стирая `seen` и оставляя запись аудируемой.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from .action_family import family_of

#: Куда пишем. Переопределяется переменной окружения (нужно тестам и прогонам
#: в отдельной песочнице).
WEDGED_FILE = Path(
    os.environ.get("DOF_WEDGED_FILE",
                   Path(__file__).resolve().parents[1] / "wedged_actions.json")
)

_cache: Optional[dict[str, dict[str, Any]]] = None


def key_of(ctrl_type: str, action_name: str) -> str:
    """Ключ записи: контроллер + семейство действия (не имя с параметрами)."""
    return f"{ctrl_type}/{family_of(action_name)}"


def load_wedged() -> dict[str, dict[str, Any]]:
    """Прочитать реестр клинчей (одна копия на процесс, диск — источник правды)."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(WEDGED_FILE) as fh:
            data = json.load(fh)
        _cache = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # Нет файла — нет измеренных клинчей. Это не ошибка, это начало работы.
        _cache = {}
    return _cache


def reset_cache() -> None:
    """Сбросить кэш (тесты и внешняя правка файла)."""
    global _cache
    _cache = None


def _position(context: Optional[dict[str, Any]]) -> tuple[int, int] | None:
    if not isinstance(context, dict):
        return None
    value = context.get("position")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _scope_key(position: tuple[int, int]) -> str:
    return f"position:{position[0]},{position[1]}"


def _unscoped_seen(entry: dict[str, Any]) -> int:
    if "unscoped_seen" in entry:
        return int(entry["unscoped_seen"])
    return int(entry.get("seen", 0)) if not entry.get("scopes") else 0


def _active_failures(reason: str, seen: int, resolved: int = 0) -> bool:
    pending = max(0, int(seen) - int(resolved))
    return (reason == "refused" and pending > 0) or pending >= 2


def _record_scoped_failure(entry: dict[str, Any], position: tuple[int, int],
                           turn: int, reason: str) -> None:
    key = _scope_key(position)
    scopes = entry.setdefault("scopes", {})
    scope = scopes.setdefault(key, {
        "position": list(position), "seen": 0, "resolved_seen": 0,
        "successes": 0, "reason": "timeout", "first_turn": int(turn),
    })
    scope["seen"] = int(scope.get("seen", 0)) + 1
    scope["last_turn"] = int(turn)
    if reason == "refused":
        scope["reason"] = "refused"


def _context_is_wedged(entry: dict[str, Any],
                       position: tuple[int, int]) -> bool:
    key = _scope_key(position)
    success = entry.get("successes_by_context", {}).get(key, {})
    global_active = _active_failures(
        str(entry.get("unscoped_reason", entry.get("reason", "timeout"))),
        _unscoped_seen(entry), int(success.get("resolved_unscoped_seen", 0)))
    scope = entry.get("scopes", {}).get(key, {})
    local_active = _active_failures(
        str(scope.get("reason", "timeout")), int(scope.get("seen", 0)),
        int(scope.get("resolved_seen", 0)))
    return global_active or local_active


def is_wedged(ctrl_type: str, action_name: str, *,
              context: Optional[dict[str, Any]] = None) -> bool:
    """Check the family globally or against failures at this exact position."""
    if not ctrl_type or not action_name:
        return False
    entry = load_wedged().get(key_of(ctrl_type, action_name))
    if not entry:
        return False
    position = _position(context)
    if position is not None:
        return _context_is_wedged(entry, position)
    return _active_failures(str(entry.get("reason", "timeout")),
                            int(entry.get("seen", 1)),
                            int(entry.get("resolved_seen", 0)))


def _new_wedge_entry(ctrl_type, action_name, turn, context):
    return {
        "ctrl_type": str(ctrl_type), "action_name": str(action_name),
        "family": family_of(action_name), "first_turn": int(turn), "seen": 0,
        "reason": "timeout", "context": dict(context or {}),
        "unscoped_seen": 0, "unscoped_reason": "timeout",
    }


def _record_unscoped_failure(entry, reason):
    entry["unscoped_seen"] = int(entry.get("unscoped_seen", 0)) + 1
    if reason == "refused":
        entry["unscoped_reason"] = "refused"


def record_wedged(ctrl_type: str, action_name: str, *, turn: int = 0,
                  context: Optional[dict[str, Any]] = None,
                  reason: str = "timeout") -> bool:
    """Record a timeout/refusal, retaining aggregate and position-scoped history."""
    if not ctrl_type or not action_name:
        return False
    registry = load_wedged()
    key = key_of(ctrl_type, action_name)
    position = _position(context)
    entry = registry.setdefault(
        key, _new_wedge_entry(ctrl_type, action_name, turn, context))
    entry["unscoped_seen"] = _unscoped_seen(entry)
    entry.setdefault("unscoped_reason", str(entry.get("reason", "timeout")))
    entry["seen"] = int(entry.get("seen", 0)) + 1
    entry["last_turn"] = int(turn)
    if reason == "refused":
        entry["reason"] = "refused"
    else:
        entry.setdefault("reason", "timeout")
    if position is None:
        _record_unscoped_failure(entry, reason)
    else:
        _record_scoped_failure(entry, position, turn, reason)
    _write(registry)
    return int(entry["seen"]) == 1


def _record_position_success(entry, position, turn):
    entry["unscoped_seen"] = _unscoped_seen(entry)
    key = _scope_key(position)
    successes = entry.setdefault("successes_by_context", {})
    success = successes.setdefault(key, {"successes": 0,
                                           "resolved_unscoped_seen": 0})
    success["successes"] = int(success.get("successes", 0)) + 1
    success["resolved_unscoped_seen"] = _unscoped_seen(entry)
    scope = entry.get("scopes", {}).get(key)
    if scope is not None:
        scope["resolved_reason"] = str(scope.get("reason", "timeout"))
        scope["reason"] = "timeout"
        scope["successes"] = int(scope.get("successes", 0)) + 1
        scope["resolved_seen"] = int(scope.get("seen", 0))
        scope["last_success_turn"] = int(turn)


def record_success(ctrl_type: str, action_name: str, *, turn: int = 0,
                   context: Optional[dict[str, Any]] = None) -> bool:
    """Resolve legacy and scoped failures only at the observed position."""
    if not ctrl_type or not action_name:
        return False
    registry = load_wedged()
    entry = registry.get(key_of(ctrl_type, action_name))
    if entry is None:
        return False
    entry["successes"] = int(entry.get("successes", 0)) + 1
    entry["last_success_turn"] = int(turn)
    entry["last_success_context"] = dict(context or {})
    position = _position(context)
    if position is None:
        entry["resolved_seen"] = int(entry.get("seen", 0))
    else:
        _record_position_success(entry, position, turn)
    _write(registry)
    return True


def _write(registry: dict[str, dict[str, Any]]) -> None:
    WEDGED_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(WEDGED_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(registry, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, WEDGED_FILE)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
