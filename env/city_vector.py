"""ГОРОДА ИЗ ВЕКТОРА СЕЙВА: `c={...}` в разделе игрока (§13.376).

Замер (§13.376): ходовой сейв стенда разделов `[city]` не содержит вовсе, а города лежат вектором
`c={...}` внутри раздела `[playerN]` — заголовки колонок в первой строке, затем строки значений,
закрытие `}`. Колонок 81; проверено на живом сейве: `y, x, id, original, size, nspe0..2,
food_stock, shield_stock, …, name, currently_building_kind, currently_building_name,
last_turns_shield_surplus, …`.

Строка значений разбирается по запятым; имя города запятых не содержит (проверено на
`"Ciudad del Este"` и `"Montevideo"`).
"""

from __future__ import annotations

import re
from typing import Any


def _columns(head: str) -> list[str]:
    """Имена колонок из строки вида `c={"y","x","id",…`."""
    return re.findall(r'"([^"]*)"', head)


def _value(raw: str) -> Any:
    """Значение поля: кавычки снимаем, числа приводим к числам, прочее — как есть."""
    text = raw.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
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
    """Города из векторов `c={...}`. При `username` — только города этого игрока.

    Ничего не выдумываем: чего в сейве нет, того в записи нет.
    """
    out: dict[str, dict[str, Any]] = {}
    owner: str | None = None
    lines = str(text).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("["):
            owner = None
            i += 1
            continue
        if line.startswith("username="):
            owner = line.split("=", 1)[1].strip().strip('"')
            i += 1
            continue
        if line.startswith("c={") or line.startswith("c ={"):
            cols = _columns(line)
            i += 1
            while i < len(lines):
                row = lines[i]
                if row.startswith("}") or row.startswith("[") or "={" in row:
                    break
                parts = row.split(",")
                if cols and len(parts) == len(cols):
                    rec = {cols[n]: _value(parts[n]) for n in range(len(cols))}
                    if username is None or owner is None or owner == username:
                        out[str(rec.get("id", len(out)))] = rec
                i += 1
            continue
        i += 1
    return out


def for_production(text: str, username: str | None = None) -> dict[str, dict[str, Any]]:
    """Записи городов для выбора производства. Имена полей — КАК В СЕЙВЕ."""
    return parse_city_vectors(text, username=username)
