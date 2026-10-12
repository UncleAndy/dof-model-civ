"""Выгружает из правил мира связи «технология → что она открывает».

Зачем. Встроенный ИИ оценивает технологию по приросту того, что могут его города
(`ai/default/daitech.c`, `dai_tech_base_want`): он мысленно даёт технологию и смотрит,
насколько выросла оценка города. Чтобы применить то же правило у нас, нужна связь
«технология → постройки и юниты», а её даёт сам мир: раздел `reqs` в
`classic/buildings.ruleset` и `classic/units.ruleset`.

Числа не выдумываются: скрипт читает файлы правил и пишет таблицу в `env/rules_ai_prereqs.py`
с указанием источника. Запуск (пути правил видны из контейнера стенда):

    .venv/bin/python scripts/read_ruleset_requirements.py
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "env" / "rules_ai_prereqs.py"
CONTAINER = "freeciv-web"
RULES_DIR = "/home/docker/freeciv/share/freeciv/classic"


def read_rules(name: str) -> str:
    """Прочитать файл правил из контейнера стенда."""
    res = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", f"cat {RULES_DIR}/{name}"],
        capture_output=True, text=True, timeout=120,
    )
    if res.returncode != 0:
        raise SystemExit(f"не удалось прочитать {name}: {res.stderr.strip()[:200]}")
    return res.stdout


def parse_requirements(text: str, *, skip: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """Собрать для каждой секции имя и список требуемых технологий.

    В правилах freeciv требования записаны блоком `reqs = ...`; строка вида
    `{ "type", "name", "range", "Tech", "Pottery", "Player" }` означает «нужна
    технология Pottery». Разбираем именно такие строки: первые три элемента — шапка,
    дальше пары «вид, значение».
    """
    out: dict[str, list[str]] = {}
    section = None
    in_reqs = False
    buffer: list[str] = []

    def flush(section_name: str, chunk: list[str]) -> None:
        text_chunk = " ".join(chunk)
        # Строка вида: { "type", "name", "range" "Tech", "Pottery", "Player" }
        pairs = re.findall(r'"(Tech|Building|Unit|Improvement|Government|Terrain|Extra|DiplRel|Nation|None)"'
                           r'\s*,\s*"([^"]*)"', text_chunk)
        for kind, value in pairs:
            if kind.lower() in ("tech", "none"):
                continue
            out.setdefault(section_name, []).append(f"{kind}:{value}")

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            in_reqs = False
            buffer = []
            continue
        if section is None or section in skip:
            continue
        if in_reqs:
            if line.startswith("}"):
                in_reqs = False
                # сначала технологии — они и нужны как «что открывает»
                techs = re.findall(r'"Tech"\s*,\s*"([^"]+)"', " ".join(buffer))
                if techs and section not in skip:
                    out.setdefault(section, [])
                    for t in techs:
                        if t not in out[section]:
                            out[section].append(t)
                continue
            buffer.append(line)
            continue
        if re.match(r"reqs\s*=", line):
            in_reqs = True
            buffer = []
    return out


def main() -> None:
    buildings = parse_requirements(read_rules("buildings.ruleset"))
    units = parse_requirements(read_rules("units.ruleset"))
    if not buildings and not units:
        raise SystemExit("ничего не разобрано — проверь формат правил")

    tech_to_buildings: dict[str, list[str]] = {}
    for building, techs in sorted(buildings.items()):
        for tech in techs:
            tech_to_buildings.setdefault(tech, []).append(building)
    tech_to_units: dict[str, list[str]] = {}
    for unit, techs in sorted(units.items()):
        for tech in techs:
            tech_to_units.setdefault(tech, []).append(unit)

    body = [
        '"""ЧТО ОТКРЫВАЕТ ТЕХНОЛОГИЯ — прочитано из правил мира, не выдумано.',
        "",
        f"Источник: `{RULES_DIR}/buildings.ruleset` и `units.ruleset`, разделы `reqs`",
                '(требование вида `{ "type", "name", "range", "Tech", "Pottery", ... }`).',
        "Сгенерировано: `scripts/read_ruleset_requirements.py`.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "#: технология → постройки, которые она открывает",
        "TECH_BUILDINGS: dict[str, tuple[str, ...]] = {",
    ]
    for tech, names in sorted(tech_to_buildings.items()):
        body.append(f"    {tech!r}: {tuple(sorted(names))!r},")
    body += [
        "}",
        "",
        "#: технология → юниты, которые она открывает",
        "TECH_UNITS: dict[str, tuple[str, ...]] = {",
    ]
    for tech, names in sorted(tech_to_units.items()):
        body.append(f"    {tech!r}: {tuple(sorted(names))!r},")
    body += ["}", ""]
    OUT.write_text("\n".join(body), encoding="utf-8")
    print(f"записано: {OUT}")
    print(f"технологий с постройками: {len(tech_to_buildings)}, "
          f"с юнитами: {len(tech_to_units)}")
    key = ("Pottery", "Bronze Working", "Alphabet", "Ceremonial Burial")
    for t in key:
        print(f"  {t}: постройки {tech_to_buildings.get(t, ())} юниты {tech_to_units.get(t, ())}")


if __name__ == "__main__":
    sys.exit(main())