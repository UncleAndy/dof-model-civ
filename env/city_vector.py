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


def _split_row(row: str) -> list[str]:
    """Разбор строки вектора по запятым, но запятые внутри кавычек — часть значения."""
    out: list[str] = []
    cur: list[str] = []
    inq = False
    esc = False
    for ch in row:
        if esc:  # в сейвах кавычка внутри строки экранируется: \"
            cur.append(ch)
            esc = False
            continue
        if ch == "\\":
            cur.append(ch)
            esc = True
            continue
        if ch == '"':
            inq = not inq
            cur.append(ch)
            continue
        if ch == "," and not inq:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur))
    return out


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

    В сейве вектор `c={...}` идёт РАНЬШЕ строк `username=`/`name=` своего раздела, поэтому
    сначала определяем владельца раздела, и лишь потом читаем его города: иначе города
    чужих игроков попадают в выборку (измерено §13.379: приходили имена чужих городов).
    """
    out: dict[str, dict[str, Any]] = {}
    lines = str(text).splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("["):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("["):
                j += 1
            owner = None
            for k in range(i + 1, j):
                if lines[k].startswith("username="):
                    owner = lines[k].split("=", 1)[1].strip().strip('"')
                    break
                if owner is None and lines[k].startswith('name="'):
                    owner = lines[k].split("=", 1)[1].strip().strip('"')
            if username is None or owner is None or owner == username:
                _read_vectors(lines[i + 1:j], out)
            i = j
            continue
        i += 1
    return out


def _read_vectors(block: list[str], out: dict[str, dict[str, Any]]) -> None:
    """Векторы `c={...}` внутри одного раздела."""
    i = 0
    while i < len(block):
        line = block[i]
        if line.startswith("c={") or line.startswith("c ={"):
            cols = _columns(line)
            i += 1
            while i < len(block):
                row = block[i]
                if row.startswith("}") or "={" in row:
                    break
                parts = _split_row(row)
                if cols and len(parts) == len(cols):
                    rec = {cols[n]: _value(parts[n]) for n in range(len(cols))}
                    out[str(rec.get("id", len(out)))] = rec
                i += 1
            continue
        i += 1


def for_production(text: str, username: str | None = None) -> dict[str, dict[str, Any]]:
    """Записи городов для выбора производства. Имена полей — КАК В СЕЙВЕ."""
    return parse_city_vectors(text, username=username)

def parse_player_section(text: str, index: int) -> dict[str, dict[str, Any]]:
    """Города игрока по НОМЕРУ его раздела `[playerN]` (§13.383).

    Искать по `username=` нельзя: у нашего игрока в сейве он бывает `Unassigned`
    (игрока ведёт встроенный ИИ), и тогда фильтр по имени выкидывает наши же города.
    Номер раздела совпадает с `my_player_id` клиента — это и есть надёжный ключ.
    """
    lines = str(text).splitlines()
    head = f"[player{int(index)}]"
    start = None
    for n, line in enumerate(lines):
        if line.startswith(head):
            start = n + 1
            break
    if start is None:
        return {}
    end = len(lines)
    for n in range(start, len(lines)):
        if lines[n].startswith("["):
            end = n
            break
    out: dict[str, dict[str, Any]] = {}
    _read_vectors(lines[start:end], out)
    return out
