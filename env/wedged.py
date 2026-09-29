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

Честная оговорка: клинч измерен на конкретной клетке, а исключается семейство
целиком. Это осознанная грубость — цена ложного исключения меньше цены
матча, который не заканчивается; контекст (местность, ход) сохраняется рядом,
чтобы решение можно было пересмотреть, когда клинчей наберётся достаточно.
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


def is_wedged(ctrl_type: str, action_name: str) -> bool:
    """Известно ли, что это действие заклинивает стенд."""
    if not ctrl_type or not action_name:
        return False
    return key_of(ctrl_type, action_name) in load_wedged()


def record_wedged(ctrl_type: str, action_name: str, *, turn: int = 0,
                  context: Optional[dict[str, Any]] = None) -> bool:
    """Записать измеренный клинч. True — запись новая, False — уже знали.

    Пишем атомарно: матч обрывается по этому событию, и полузаписанный файл
    был бы источником тихо неверных данных в следующем прогоне.
    """
    if not ctrl_type or not action_name:
        return False
    registry = load_wedged()
    key = key_of(ctrl_type, action_name)
    if key in registry:
        return False
    registry[key] = {
        "ctrl_type": str(ctrl_type),
        "action_name": str(action_name),
        "family": family_of(action_name),
        "first_turn": int(turn),
        "seen": 1,
        "context": dict(context or {}),
    }
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
