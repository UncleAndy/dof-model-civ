"""Канал наблюдений смены производства — порт `produce_switch` из ветки `v2` (§10.102).

В `v2` канал писал агент (`brain/v2/agent.py:492`: `note_observation("produce_switch", …)`),
а цену отказа считал `brain/v2/horizon.py:321 switch_penalty`: по строкам с `сменил is True`
бралась медиана положительных потерь. Здесь тот же канал, но под `v0.11`.

**Кто что знает — разделено честно:**

* **Факт смены** знает раннер: он выбрал вариант постройки. Из наблюдения имя текущей
  постройки не восстанавливается (`production_value` — числовой id, которого нет среди
  опубликованных спек, замер 2026-10-06), поэтому смену НЕ угадывают по данным.
* **Величина потери** берётся у мира: падение `shield_stock` города между срезами. Это
  измерение, а не мнение агента.

**Падение щитов без смены — не потеря.** Щиты тратятся и на саму постройку; потеря
приписывается смене только если смена заявлена раннером. Иначе любое производство читалось
бы как «отказ от постройки».

Корпус — JSONL, как у `env/site_outcomes.py`: строки разных прогонов различимы по
`DOF_RUN_TAG`, запись не критична для матча (ошибка ввода-вывода матч не роняет).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Optional

#: Имя канала — как в `v2`, чтобы корпуса разных линий были сравнимы по имени.
CHANNEL = "produce_switch"

DEFAULT_PATH = Path(
    os.environ.get("DOF_SWITCH_CHANNEL",
                   Path(__file__).resolve().parents[1] / "switch_losses.jsonl")
)


def loss_from_stock(stock_before: Any, stock_after: Any) -> tuple[Optional[float], str]:
    """Потеря щитов по падению `shield_stock`: `(щиты, причина)`.

    Оба числа должны быть числами: не наблюдали запас — нечего вычитать, и это
    `None` **с причиной**, а не ноль (ноль был бы утверждением «не потерял»).
    """
    if not isinstance(stock_before, (int, float)) or not isinstance(stock_after, (int, float)):
        return None, "запас щитов не наблюдён до или после смены — потеря не измерена"
    drop = float(stock_before) - float(stock_after)
    if drop <= 0.0:
        return 0.0, f"запас не упал ({float(stock_before):g} → {float(stock_after):g}) — потери нет"
    return drop, f"запас упал {float(stock_before):g} → {float(stock_after):g} на {drop:g} щитов"


def make_row(*, turn: Any, city: Any, switched: bool, lost: Optional[float],
             stock_before: Any = None, stock_after: Any = None,
             current: Optional[str] = None, chosen: Optional[str] = None,
             source: str = "runner") -> dict[str, Any]:
    """Строка канала. Ключи — как у `v2` (`switched`/`lost`), чтобы корпуса сравнивались."""

    def _num(x: Any) -> Any:
        return float(x) if isinstance(x, (int, float)) else x

    return {"channel": CHANNEL, "turn": turn, "city": city, "switched": bool(switched),
            "lost": _num(lost), "stock_before": _num(stock_before),
            "stock_after": _num(stock_after), "current": current, "chosen": chosen,
            "source": source}


def observe(*, turn: Any, city: Any, stock_before: Any, stock_after: Any,
            current: Optional[str], chosen: Optional[str]) -> tuple[Optional[dict[str, Any]], str]:
    """Строка канала, если смена ЗАЯВЛЕНА и её потеря измерена: `(строка|None, причина)`.

    Смена заявлена — значит вариант назван и отличается от текущего. Ничего не заявлено
    или вариант тот же — строки нет, и причина названа (канал не заполняется догадками).
    """
    if current is None or chosen is None:
        return None, "текущий или выбранный вариант не назван — смена не определяется"
    if str(current) == str(chosen):
        return None, "вариант тот же — потери при смене не бывает"
    lost, why = loss_from_stock(stock_before, stock_after)
    if lost is None:
        return None, why
    return (make_row(turn=turn, city=city, switched=True, lost=lost,
                     stock_before=stock_before, stock_after=stock_after,
                     current=current, chosen=chosen), why)


def measured_loss(rows: Iterable[dict[str, Any]]) -> tuple[Optional[float], int, str]:
    """Медиана положительных потерь по корпусу: `(щиты|None, сколько строк, причина)`.

    Только объявленные смены (`switched is True`) с положительной потерей: нули и
    необъявленные строки медиану не двигают. Нечего усреднять — `None` **с причиной**,
    и вызывающий обязан показать, что цена взята не из воздуха (правило №31: проверка,
    довольная нулём, доказывает ноль, а не механизм).
    """
    losses: list[float] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("switched"):
            continue
        value = row.get("lost")
        if isinstance(value, (int, float)) and float(value) > 0.0:
            losses.append(float(value))
    if not losses:
        return None, 0, ("потеря щитов при смене производства ещё не измерена — "
                         "цена отказа берётся нулём С ПРИЧИНОЙ, а не по догадке")
    losses.sort()
    mid = len(losses) // 2
    median = losses[mid] if len(losses) % 2 else 0.5 * (losses[mid - 1] + losses[mid])
    return median, len(losses), (f"медиана по {len(losses)} объявленным сменам; "
                                 f"медиана {median:g} щитов (замер `v2`: 3 при медиане "
                                 f"накопленных 6 — та же валюта, другая линия)")


def record(rows: Iterable[dict[str, Any]], path: Optional[Path] = None) -> int:
    """Дописать строки в корпус. Возвращает число записанных (0 — не записали, и это не беда)."""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    target = Path(path or DEFAULT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    tag = os.environ.get("DOF_RUN_TAG", "")
    if tag:
        rows = [dict(r, tag=tag) for r in rows]
    try:
        with open(target, "a") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return 0
    return len(rows)


def load(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Корпус целиком: битая строка не портит остальные."""
    target = Path(path or DEFAULT_PATH)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def clear(path: Optional[Path] = None) -> None:
    """Очистить корпус (§«rm только по явной команде» — вызывать осознанно)."""
    target = Path(path or DEFAULT_PATH)
    if target.exists():
        target.unlink()
