"""ВСЯ КАРТА ИЗ СЕЙВА СЕРВЕРА — источник тот же, что у встроенного ИИ (§13.363).

Зачем. Встроенный ИИ планирует по ВСЕЙ карте: `parameter.omniscience = !has_handicap(pplayer,
H_MAP)` (`server/unittools.c:531`, `advisors/autoworkers.c:464,842,1090`, `advbuilding.c:94`).
Наш агент живёт на наблюдении клиента, а клиент стенда отдаёт только обзор: замер §13.361/13.362 —
`вне обзора 4035, известно-невидимо 0, видно 21` из 4056 клеток. Настройками стенда это не
лечится (пять способов, §13.362): клетки создаются раньше, чем любая настройка успевает
подействовать (`server/maphand.c:1348`: `seen_count[V_MAIN] = !fogofwar_old` при создании клетки),
а редакторский путь «снять туман игроку» (`server/edithand.c:1312`) требует уровня `ALLOW_HACK`,
которого у веб-клиента нет.

Что здесь. Тот же мир, что читает его `omniscience`, лежит в сохранённой игре сервера: в разделе
`[map]` построчно, по одному символу на клетку (`t0000="..."`). Символ — `identifier` террейна из
правил (`data/classic/terrain.ruleset`). Читаем этот раздел и наполняем им память о карте
(`env/world_memory.py`) — тогда поиск площадок и пути видят всю карту, как он.

Это данные мира, а не догадка: по решению владельца характеристики мира берутся из источника и
один раз сохраняются в картину мира.
"""

from __future__ import annotations

import subprocess
from typing import Any

#: Символ клетки → имя террейна. Взято из правил стенда: `data/classic/terrain.ruleset`,
#: поля `identifier` (проверено для всех 14 террейнов; лишние символы здесь — `extras`, их
#: в строке карты не бывает).
TERRAIN_BY_IDENTIFIER: dict[str, str] = {
    "i": "Inaccessible",
    "+": "Lake",
    " ": "Ocean",
    ":": "Deep Ocean",
    "a": "Glacier",
    "d": "Desert",
    "f": "Forest",
    "g": "Grassland",
    "h": "Hills",
    "j": "Jungle",
    "m": "Mountains",
    "p": "Plains",
    "s": "Swamp",
    "t": "Tundra",
}


def parse_map_rows(text: str) -> dict[tuple[int, int], str]:
    """Раздел `[map]` сейва → `{(x, y): террейн}`.

    Строка сейва: `t0017="d f ph ms ..."` — `t0017` это НОМЕР СТРОКИ (y), символы в кавычках —
    клетки по x. Неизвестный символ не выдумываем: клетка пропускается (её террейн останется
    «не знаем», как и было).
    """
    out: dict[tuple[int, int], str] = {}
    in_map = False
    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith("["):
            in_map = line.strip().lower() == "[map]"
            continue
        if not in_map:
            continue
        if not line.startswith("t"):
            continue
        head, _, rest = line.partition("=")
        digits = head[1:].strip()
        if not digits.isdigit():
            continue
        if not rest.startswith('"'):
            continue
        body = rest[1:]
        end = body.rfind('"')
        if end >= 0:
            body = body[:end]
        y = int(digits)
        for x, ch in enumerate(body):
            name = TERRAIN_BY_IDENTIFIER.get(ch)
            if name is not None:
                out[(x, y)] = name
    return out


def fetch_newest_save(username: str, container: str = "freeciv-web") -> str | None:
    """Самый свежий сейв ЭТОГО игрока из стенда — уже распакованным текстом.

    Сейвы лежат внутри контейнера стенда (`/var/lib/tomcat10/webapps/data/savegames/<имя>/`),
    наружу не смонтированы, поэтому читаем через `docker exec`; распаковка — `xzcat` там же.
    """
    try:
        listing = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             f"ls -t /var/lib/tomcat10/webapps/data/savegames/{username}/*.sav* 2>/dev/null | head -1"],
            capture_output=True, text=True, timeout=60)
        path = (listing.stdout or "").strip()
        if not path:
            return None
        got = subprocess.run(
            ["docker", "exec", container, "sh", "-c", f"xzcat '{path}' 2>/dev/null || cat '{path}'"],
            capture_output=True, text=True, timeout=120)
        return got.stdout or None
    except Exception:  # noqa: BLE001
        return None


def learn_full_map(terrain_by_xy: dict[tuple[int, int], str]) -> int:
    """Наполнить память о карте (`env/world_memory.py`) всей картой из сейва.

    Возвращает число известных клеток ПОСЛЕ наполнения.
    """
    from env import world_memory
    return int(world_memory.learn_full_map(terrain_by_xy))


def load_from_save(username: str, container: str = "freeciv-web") -> int:
    """Сейв → память. Возвращает число запомненных клеток (0 — сейва нет или он пуст)."""
    text = fetch_newest_save(username, container=container)
    if not text:
        return 0
    tiles = parse_map_rows(text)
    if not tiles:
        return 0
    return learn_full_map(tiles)


def summary() -> dict[str, Any]:
    """Что видит модуль — для следа."""
    out: dict[str, Any] = {}
    try:
        from env import world_memory
        out["known"] = len(world_memory.known())
        out["full"] = int(world_memory.CALLS.get("full") or 0)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out

def fetch_named_save(name: str, container: str = "freeciv-web") -> str | None:
    """Сейв, который мы сами попросили у сервера командой `/save <имя>` — по имени, а не по времени.
    Ищем файл по всему контейнеру: сервер пишет его в свой рабочий каталог, а не в каталог
    стенда."""
    try:
        find = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
              f"find / -name '{name}*' -newermt '-10 minutes' 2>/dev/null | head -3"],
            capture_output=True, text=True, timeout=90)
        path = (find.stdout or "").strip().splitlines()
        if not path:
            return None
        got = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
              f"xzcat '{path[0]}' 2>/dev/null || cat '{path[0]}'"],
            capture_output=True, text=True, timeout=150)
        return got.stdout or None
    except Exception:  # noqa: BLE001
        return None
