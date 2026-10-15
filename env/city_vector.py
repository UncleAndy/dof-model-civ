"""ГОРОДА ИЗ ВЕКТОРА СЕЙВА: `c={...}` в разделе игрока (§13.376).

Замер (§13.376): ходовой сейв стенда разделов `[city]` не содержит вовсе, а города лежат вектором
`c={...}` внутри раздела `[playerN]` — заголовки колонок в первой строке, затем строки значений,
закрытие `}`. Колонок 81, имена и порядок проверены на живом сейве:
`y, x, id, original, size, nspe0, nspe1, nspe2, food_stock, shield_stock, history, airlift,
was_happy, had_famine, turn_plague, anarchy, …, name, kind(производство), value(производство), …`.

Строка значений — 81 поле, простой разбор по запятым корректен (в именах городов запятых нет:
проверено на `"Ciudad del Este"`, `"Montevideo"`).
"""

from __future__ import annotations

import re
from typing import Any


def _columns(head: str) -> list[str]:
    """Имена колонок из строки `c={"y","x",…`."""
    out = [m for m in re.findall(r'"([^"]*)"', head)]
    return out


def _value(raw: str) -> Any:
    text = raw.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_city_vectors(text: str, *, username: str | None = None) -> dict[str, dict[str, Any]]:
    """Все города из векторов `c={...}`; при `username` — только города этого игрока.

    Возвращает `{id: {поле: значение}}`; поля берутся из заголовков вектора, ничего не
    выдумывается: чего в сейве нет — того в записи нет.
    """
    out: dict[str, dict[str, Any]] = {}
    section_owner: str | None = None
    lines = str(text).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r")
        if line.startswith("["):
            section_owner = None
            i += 1
            continue
        if line.startswith("username="):
            section_owner = line.split("=", 1)[1].strip().strip('"')
            i += 1
            continue
        if line.startswith("c={") or line.startswith("c ={"):
            cols = _columns(line)
            i += 1
            while i < len(lines) and not lines[i].startswith("}"):
                row = lines[i].rstrip("\r")
                parts = row.split(",")
                if cols and parts and len(parts) >= 2:
                    rec = {cols[n]: _value(parts[n]) for n in range(min(len(cols), len(parts)))}
                    if username is None or section_owner is None or section_owner == username:
                        key = str(rec.get("id", len(out)))
                        out[key] = rec
                i += 1
            continue
        i += 1
    return out


def for_production(text: str, username: str | None = None) -> dict[str, dict[str, Any]]:
    """Записи городов в виде, пригодном для выбора производства.

    Имена полей оставляем КАК В СЕЙВЕ; перевод в наш словарь — дело вызывающего
    (чтобы не подменять факты мира нашими названиями).
    """
    return parse_city_vectors(text, username=username)
