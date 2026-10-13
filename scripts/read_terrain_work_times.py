"""ВРЕМЕНА РАБОТ ПО ТЕРРЕЙНУ — прочитаны из правил мира, не выдуманы.

Зачем. Перенесённый выбор работы встроенного ИИ дисконтирует выигрыш по числу ходов:
`amortize(total_value, delay)` (`server/advisors/autoworkers.c:375`), а `delay` берётся из
времени работы на клетке (`get_turns_for_activity_at`). Без времён перенос неполон: две
работы с равной выгодой нельзя различить по сроку.

Откуда. Тот же источник, что и приросты (`env/terrain_work_effects.py`): установленные
правила набора `classic` в контейнере стенда —
`/home/docker/freeciv/share/freeciv/classic/terrain.ruleset`. Поля — из его же исходника:
`common/terrain.h:215-227` закреплённого коммита
(`road_time`, `cultivate_time`, `plant_time`, `irrigation_time`, `mining_time`,
`transform_time`).

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


def parse(text: str) -> dict[str, dict[str, int]]:
    """`{террейн: {работа: ходов}}` — только ненулевые (ноль означает «нельзя»)."""
    out: dict[str, dict[str, int]] = {}
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
        work = TIME_FIELDS.get(key)
        if work is None or value <= 0:
            continue
        out.setdefault(terrain, {})[work] = value
    return out


HEADER = '''"""Времена работ по террейну — ПРАВИЛА МИРА, а не наши догадки.

Источник: установленные правила набора `classic` в контейнере стенда
(`{ruleset}`);
поля — из исходника его же движка (`common/terrain.h:215-227` закреплённого коммита).

Ноль в правилах означает «работу здесь делать нельзя», поэтому нулевые поля не выписаны:
иначе «нельзя» выглядело бы как «мгновенно» и портило бы дисконт по срокам
(`amortize(total, delay)`, `server/advisors/autoworkers.c:375`).

Перечитать: `.venv/bin/python scripts/read_terrain_work_times.py`
"""

from __future__ import annotations

#: террейн → работа → число ходов.
TERRAIN_WORK_TIMES: dict[str, dict[str, int]] = {{
'''


def render(table: dict[str, dict[str, int]]) -> str:
    lines = [HEADER.format(ruleset=RULESET)]
    for terrain in sorted(table):
        works = ", ".join(f'"{w}": {t}' for w, t in sorted(table[terrain].items()))
        lines.append(f'    "{terrain}": {{{works}}},\n')
    lines.append("}\n")
    return "".join(lines)


def main() -> None:
    table = parse(read_ruleset())
    if not table:
        raise SystemExit("таблица времён пуста — правила прочитаны, но поля не найдены")
    OUT.write_text(render(table), encoding="utf-8")
    print(f"записано террейнов: {len(table)} → {OUT}")
    for terrain in sorted(table):
        print(f"  {terrain}: {table[terrain]}")


if __name__ == "__main__":
    main()
