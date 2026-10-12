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
целиком. Контекст (местность, ход) сохраняется рядом, чтобы решение можно было
пересмотреть, когда клинчей наберётся достаточно.

ПРАВИЛО ОТСЕЧЕНИЯ (исправлено по замеру). Сначала резали по одному наблюдению.
Замер показал, что это сечёт исправное: реестр записал `unit/build_city` по
одному случаю, а основание города у нас работает постоянно — и из-за этой
записи основание молча выпало из оценки действий (`estimate_dof_delta`
возвращал пусто, агент переставал его рассматривать). Цена ошибок
несимметрична: ложное исключение стоит возможности и не видно, а лишний клин
стоит одного матча и виден сразу. Поэтому режем только подтверждённое:
* `seen >= 2` — клин повторился;
* `reason == "refused"` — стенд прямо сказал `Action produce_X of N is not valid`
  (это утверждение о невозможности, а не о неудаче), хватает одного.
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
    """Известно ли, что это действие заклинивает стенд (по правилу отсечения)."""
    if not ctrl_type or not action_name:
        return False
    entry = load_wedged().get(key_of(ctrl_type, action_name))
    if not entry:
        return False
    if str(entry.get("reason", "timeout")) == "refused":
        return True          # стенд прямо отказал: это утверждение о невозможности
    return int(entry.get("seen", 1)) >= 2    # одиночное наблюдение — лишь подозрение


def record_wedged(ctrl_type: str, action_name: str, *, turn: int = 0,
                  context: Optional[dict[str, Any]] = None,
                  reason: str = "timeout") -> bool:
    """Записать измеренный клинч. True — запись новая, False — уже знали.

    `reason`: "timeout" — матч не докончился, и мы знаем только, какое действие
    было в полёте (причина не установлена: так записалось `unit/build_city`);
    "refused" — стенд прямо отказал в действии (`Action ... is not valid`).

    Пишем атомарно: матч обрывается по этому событию, и полузаписанный файл
    был бы источником тихо неверных данных в следующем прогоне.
    """
    if not ctrl_type or not action_name:
        return False
    registry = load_wedged()
    key = key_of(ctrl_type, action_name)
    if key in registry:
        entry = registry[key]
        entry["seen"] = int(entry.get("seen", 1)) + 1
        entry["last_turn"] = int(turn)
        if reason == "refused":
            entry["reason"] = "refused"
        elif "reason" not in entry:
            entry["reason"] = "timeout"
        _write(registry)
        return False
    registry[key] = {
        "ctrl_type": str(ctrl_type),
        "action_name": str(action_name),
        "family": family_of(action_name),
        "first_turn": int(turn),
        "seen": 1,
        "reason": "refused" if reason == "refused" else "timeout",
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
