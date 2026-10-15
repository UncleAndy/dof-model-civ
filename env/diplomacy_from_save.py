"""Кто для нас ОПАСЕН по правилам встроенного ИИ — из сейва (§13.418).

Зачем: ЕГО правило опасности (`ai/default/daimilitary.c:812`) перебирает чужих игроков и
СНАЧАЛА отбрасывает тех, кого его `adv_is_player_dangerous` (`server/advisors/advdata.c:1103`)
не считает опасными. Возвращает `TRUE` только если:

  * состояние отношений — война (`DS_WAR`) или перемирие (`DS_CEASEFIRE`);
  * либо у него есть повод расторгнуть договор (`has_reason_to_cancel > 0`);
  * либо он союзник нашего врага;
  * либо наша «любовь» к нему ниже десятой части максимума (`MAX_AI_LOVE / 10`).

Без этой проверки мы считали опасными всех подряд: замер r980 — «Never met» у всех сторон,
а у нас 10 `Warriors` против НУЛЯ военных у каждой стороны-ИИ. Состояния и
`has_reason_to_cancel` есть в сейве (`diplstate=`), поэтому берём их оттуда — мир первичен.

Незнание — не отсутствие: если сейва нет, функция возвращает `None`, и вызывающий обязан
трактовать это как «сведений нет», а не как «никто не опасен» (правило владельца).

Формат блока в сейве (проверено на живом сейве):

    diplstate={"current","closest","first_contact_turn","turns_left",
               "has_reason_to_cancel","contact_turns_left","embassy",...
    "Never met","Never met",0,0,0,0,FALSE,FALSE,FALSE
    "Never met","Never met",0,0,0,0,FALSE,FALSE,FALSE
    }

То есть: первая строка — имена полей (без закрывающей скобки), дальше по строке на КАЖДОГО
ДРУГОГО игрока (строка про себя не пишется), закрывает блок отдельная `}`.
"""

from __future__ import annotations

import re
from typing import Any

# Состояния отношений из правил freeciv (`common/diplomacy.h`, `DS_*`) — в сейве записаны
# строками. Опасными его правило считает только войну и перемирие.
DANGEROUS_STATES = frozenset({"War", "Cease-fire"})

_DIPLSTATE_BLOCK = re.compile(r"^diplstate=\{(?P<body>.*?)^\}$", re.M | re.S)


def _split_quoted(line: str) -> list[str]:
    """Разобрать строку сейва: значения через запятую, строки в кавычках."""
    out: list[str] = []
    buf = ""
    inside = False
    for ch in line:
        if ch == '"':
            inside = not inside
            continue
        if ch == "," and not inside:
            out.append(buf)
            buf = ""
            continue
        buf += ch
    out.append(buf)
    return [v.strip() for v in out]


def dangerous_players(text: str | None, my_index: int) -> set[int] | None:
    """Множество индексов игроков, опасных для нас, — по его правилу.

    ``None`` означает «сведений нет» (сейва нет либо блок не разобран): вызывающий не должен
    превращать это в «никто не опасен».
    """
    if not text:
        return None
    block = _DIPLSTATE_BLOCK.search(text)
    if block is None:
        return None
    lines = [ln for ln in block.group("body").splitlines() if ln.strip()]
    if not lines:
        return None
    fields = [f.strip().strip('"') for f in _split_quoted(lines[0])]
    try:
        i_state = fields.index("current")
        i_reason = fields.index("has_reason_to_cancel")
    except ValueError:
        return None
    rows = [ln for ln in lines[1:] if ln.lstrip().startswith('"')]
    if not rows:
        return None
    # Строки идут по игрокам БЕЗ строки про себя: индексы — все, кроме нашего.
    others = [i for i in range(len(rows) + 1) if i != int(my_index)]
    dangerous: set[int] = set()
    for row, other in zip(rows, others):
        vals = _split_quoted(row)
        if len(vals) <= max(i_state, i_reason):
            continue
        state = vals[i_state]
        try:
            reason = int(float(vals[i_reason] or 0))
        except (TypeError, ValueError):
            reason = 0
        if state in DANGEROUS_STATES or reason > 0:
            dangerous.add(other)
    return dangerous


_PROVIDER: Any = None


def set_provider(fn: Any) -> None:
    """Задать источник текста сейва (вызывает раннер). `None` — сведений нет."""
    global _PROVIDER
    _PROVIDER = fn


def current_provider() -> Any:
    return _PROVIDER


def dangerous_now(my_index: int) -> set[int] | None:
    """Опасные игроки по свежему сейву (через установленный источник)."""
    if _PROVIDER is None:
        return None
    try:
        return dangerous_players(_PROVIDER(), my_index)
    except Exception:  # noqa: BLE001
        return None
