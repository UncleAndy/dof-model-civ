"""ГОРОДА ИЗ СЕЙВА СЕРВЕРА — тот же источник, что карта (§13.363, §13.370).

Зачем. Прибор §13.369 показал: на момент решения ОБА канала по городам пусты
(`наблюдение 0 []`, `контроллер 0 []`, `действия города {}`, `маски []`), хотя сервер считает нам
2 города. Пока записей городов нет, ни одно правило производства (ни наше, ни перенесённые его
§13.365/13.366) не может ничего заказать.

Что здесь. Разбор разделов городов сохранённой игры: раздел `[city <номер>]`, внутри строки
`ключ=значение`. Поля не выдумываем: `dump_city_block` печатает раздел КАК ЕСТЬ, чтобы имена
полей брать из самого сейва (прибор `DOF_CITY_FROM_SAVE=1`).
"""

from __future__ import annotations

import re
from typing import Any


def _blocks(text: str) -> list[list[str]]:
    """Разделы сейва: список блоков, каждый — строки без заголовка `[...]`."""
    out: list[list[str]] = []
    cur: list[str] | None = None
    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith("["):
            if cur is not None:
                out.append(cur)
            cur = []
            continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        out.append(cur)
    return out


def city_sections(text: str) -> list[dict[str, str]]:
    """Все разделы городов: список словарей «поле → значение» плюс `_section` (заголовок)."""
    out: list[dict[str, str]] = []
    head: str | None = None
    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith("["):
            head = line
            continue
        if head is None or not head.lower().startswith("[city"):
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name or not value:
            continue
        if len(out) == 0 or out[-1].get("_section") != head:
            out.append({"_section": head})
        out[-1][name] = value.strip().strip('"')
    return out


def dump_city_block(text: str, limit: int = 34) -> str:
    """Первый раздел города КАК ЕСТЬ — чтобы имена полей брать из сейва, а не из головы."""
    lines = str(text).splitlines()
    for i, raw in enumerate(lines):
        if raw.strip().lower().startswith("[city"):
            return "\n".join(lines[i:i + limit])
    return ""


def cities_for_production(text: str) -> dict[str, dict[str, Any]]:
    """Записи городов в виде, пригодном для выбора производства.

    Берём только те поля, что есть в сейве; отсутствующие не подставляем нулём — возвращаем
    лишь то, что реально прочитано (незнание ≠ отсутствие возможностей).
    """
    out: dict[str, dict[str, Any]] = {}
    for sec in city_sections(text):
        head = str(sec.get("_section") or "")
        m = re.search(r"(\d+)", head)
        cid = m.group(1) if m else str(len(out))
        rec: dict[str, Any] = {}
        for key, value in sec.items():
            if key == "_section":
                continue
            rec[key] = value
        if rec:
            out[cid] = rec
    return out

def dump_structure(text: str, city_lines: int = 14) -> str:
    """Оглавление сейва: заголовки разделов + первые строки со словом `city`."""
    heads: list[str] = []
    cityish: list[str] = []
    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith("[") and len(heads) < 200:
            heads.append(line)
        elif (str(line).startswith("c=") or line.lower().startswith("city")) and len(cityish) < city_lines:
            cityish.append(line[:120])
    return ("разделы: " + ", ".join(heads) + "\n"
            + "\n".join(cityish))

def dump_player_section(text: str, limit: int = 42) -> str:
    """Первый раздел игрока КАК ЕСТЬ — там лежат векторы городов и юнитов."""
    lines = str(text).splitlines()
    start = None
    for i, raw in enumerate(lines):
        head = raw.strip().lower()
        if head.startswith("[player") and "score" not in head:
            start = i
            break
    if start is None:
        return ""
    return "\n".join(x[:150] for x in lines[start:start + limit])

def dump_players_summary(text: str) -> str:
    """Кто есть кто в сейве: для каждого раздела игрока — имя, логин, `ai_type`, векторы."""
    rows: list[str] = []
    cur: str | None = None
    info: dict[str, str] = {}
    def _flush() -> None:
        if cur:
            rows.append(cur + ": " + ", ".join(f"{k}={v}" for k, v in info.items()))
    for raw in str(text).splitlines():
        line = raw.rstrip()
        if line.startswith("["):
            _flush()
            cur = line if line.lower().startswith("[player") and "score" not in line.lower() else None
            info = {}
            continue
        if not cur:
            continue
        for key in ("name=", "username=", "ai_type=", "ai_controlled=", "ai_fuzzy=", "is_alive="):
            if line.startswith(key):
                info[key.rstrip("=")] = line.split("=", 1)[1].strip()
        if line.startswith(("u=", "c=", "w=")) or "_size=" in line and "unit" in line.lower():
            info.setdefault("vectors", "")
            info["vectors"] = (info["vectors"] + " | " + line[:60]).strip(" |")
    _flush()
    return "\n".join(rows) if rows else "(разделов игроков не найдено)"
