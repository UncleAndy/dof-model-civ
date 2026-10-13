"""ОСНОВА ВЫХОДОВ И ВРЕМЕНА РАБОТ ПО ТЕРРЕЙНУ — прочитаны из правил мира, не выдуманы.

Зачем. Перенесённый выбор работы встроенного ИИ (13.285) требует того же входа, что и его
исходник: ценность клетки ДО и ПОСЛЕ работы и срок работы.

* ПОСЛЕ — приросты из `mining_shield_incr` / `irrigation_food_incr` (уже в
  `env/terrain_work_effects.py`);
* ДО — основа выходов клетки: в правилах рельефа она лежит явно (`food = 2`, `shield = 0`,
  `trade = 0`). Брать её из наблюдения нельзя: город сообщает выходы только своих клеток, а
  юнит часто стоит ВНЕ радиуса (измерено: 6 обращений подряд к клетке вне радиуса), и
  подставлять ноль запрещено — нули `map.output` отозваны как слепые;
* СРОК — времена работ; без них две работы с равной выгодой неразличимы, а перенесённое
  правило дисконтирует выгоду по сроку (`amortize(total, delay)`,
  `server/advisors/autoworkers.c:375`).

Откуда. Установленные правила набора `classic` в контейнере стенда —
`/home/docker/freeciv/share/freeciv/classic/terrain.ruleset`. Поля — из его же движка:
`common/terrain.h:215-227` (`road_time`, `cultivate_time`, `plant_time`, `irrigation_time`,
`mining_time`, `transform_time`) и раздел выходов рельефа.

Ноль означает «эту работу на этом террейне делать НЕЛЬЗЯ» — такие поля не пишем, чтобы
«нельзя» не выглядело как «мгновенно».

Запуск:

    .venv/bin/python scripts/read_terrain_work_times.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "env" / "terrain_work_times.py"
CONTAINER = "freeciv-web"
RULESET = "/home/docker/freeciv/share/freeciv/classic/terrain.ruleset"

#: Поля времени из `common/terrain.h:215-227` — ключ в правилах → наше имя работы.
TIME_FIELDS = {
    "road_time": "road",
    "cultivate_time": "cultivate",
    "plant_time": "plant",
    "irrigation_time": "irrigation",
    "mining_time": "mine",
    "transform_time": "transform",
}

#: Поля основы выходов клетки — в правилах рельефа это `food`, `shield`, `trade`.
BASE_FIELDS = {"food": 0, "shield": 1, "trade": 2}

SECTION = re.compile(r"^\[terrain_([a-z_]+)\]\s*$")
FIELD = re.compile(r"^\s*([a-z_]+)\s*=\s*(\d+)\s*$")


def read_ruleset() -> str:
    """Прочитать файл правил из контейнера стенда (единственный источник мира)."""
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", RULESET],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"правила не прочитаны: {proc.stderr.strip()}")
    return proc.stdout


def parse(text: str) -> tuple[dict[str, dict[str, int]], dict[str, list[int]]]:
    """Вернуть `(времена работ, основа выходов)` — только то, что правила реально задают.

    Времена: `{террейн: {работа: ходов}}`, нулевые работы пропущены («нельзя», а не «мгновенно»).
    Основа: `{террейн: [еда, щиты, торговля]}`.
    """
    times: dict[str, dict[str, int]] = {}
    base: dict[str, list[int]] = {}
    terrain: str | None = None
    for line in text.splitlines():
        sec = SECTION.match(line)
        if sec:
            terrain = sec.group(1)
            continue
        if terrain is None:
            continue
        field = FIELD.match(line)
        if not field:
            continue
        key, value = field.group(1), int(field.group(2))
        index = BASE_FIELDS.get(key)
        if index is not None:
            base.setdefault(terrain, [0, 0, 0])[index] = value
            continue
        work = TIME_FIELDS.get(key)
        if work is None or value <= 0:
            continue
        times.setdefault(terrain, {})[work] = value
    return times, base


HEADER = '''"""Основа выходов и времена работ по террейну — ПРАВИЛА МИРА, а не наши догадки.

Источник: установленные правила набора `classic` в контейнере стенда
({ruleset});
поля — из исходника его же движка (`common/terrain.h:215-227` закреплённого коммита).

* `TERRAIN_WORK_TIMES` — сколько ходов идёт работа. Ноль в правилах означает «работу здесь
  делать нельзя», поэтому нулевые поля не выписаны: иначе «нельзя» выглядело бы как
  «мгновенно» и портило бы дисконт по срокам
  (`amortize(total, delay)`, `server/advisors/autoworkers.c:375`).
* `TERRAIN_BASE_OUTPUTS` — основа выходов клетки `(еда, щиты, торговля)`. Нужна, когда
  город не сообщает выход клетки: юнит стоит вне его радиуса, а подставлять ноль нельзя
  (нули `map.output` отозваны как слепые).

Перечитать: `.venv/bin/python scripts/read_terrain_work_times.py`
"""

from __future__ import annotations

#: террейн → работа → число ходов.
TERRAIN_WORK_TIMES: dict[str, dict[str, int]] = {{
'''


def render(times: dict[str, dict[str, int]], base: dict[str, list[int]]) -> str:
    lines = [HEADER.format(ruleset=RULESET)]
    for terrain in sorted(times):
        works = ", ".join(f'"{w}": {t}' for w, t in sorted(times[terrain].items()))
        lines.append(f'    "{terrain}": {{{works}}},\n')
    lines.append("}\n\n")
    lines.append("#: террейн → основа выходов клетки `(еда, щиты, торговля)`.\n")
    lines.append("TERRAIN_BASE_OUTPUTS: dict[str, tuple[float, float, float]] = {\n")
    for terrain in sorted(base):
        food, shield, trade = base[terrain]
        lines.append(f'    "{terrain}": ({food}, {shield}, {trade}),\n')
    lines.append("}\n")
    return "".join(lines)


def main() -> None:
    times, base = parse(read_ruleset())
    if not times:
        raise SystemExit("таблица времён пуста — правила прочитаны, но поля не найдены")
    if not base:
        raise SystemExit("основа выходов пуста — правила прочитаны, но `food/shield/trade` не найдены")
    OUT.write_text(render(times, base), encoding="utf-8")
    print(f"записано террейнов: {len(times)} времён, {len(base)} основ → {OUT}")
    for terrain in sorted(times):
        print(f"  {terrain}: времена {times[terrain]}, основа {tuple(base.get(terrain, [0, 0, 0]))}")


if __name__ == "__main__":
    main()
