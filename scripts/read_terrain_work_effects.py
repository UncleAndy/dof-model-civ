"""ЭФФЕКТ РАБОТЫ ПО КЛЕТКЕ — прочитан из правил мира, не выдуман.

Повод (§13.256): цена работы по клетке у нас ровно ноль, потому что таблица эффектов пуста:
мы не знаем, что ирригация или шахта дают клетке. У мира это записано по каждому террейну
(`terrain.ruleset`): `irrigation_food_incr`, `mining_shield_incr` и проценты дорог.

Указание владельца (2026-10-12): «Код встроенного ИИ — это тоже наблюдение, можно использовать
значения из него и сохранить их в картину мира»; цена/эффект — характеристика мира, её достаточно
узнать один раз. Здесь только чтение правил: ни одного выведенного числа.

Запуск:

    .venv/bin/python scripts/read_terrain_work_effects.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "env" / "terrain_work_effects.py"
CONTAINER = "freeciv-web"
RULESET = "/home/docker/freeciv/share/freeciv/classic/terrain.ruleset"

#: Поля террейна, которые несут эффект работы (`terrain.ruleset`).
TERRAIN_FIELDS = ("irrigation_food_incr", "irrigation_shield_incr", "irrigation_trade_incr",
                  "mining_food_incr", "mining_shield_incr", "mining_trade_incr",
                  "road_food_incr_pct", "road_shield_incr_pct", "road_trade_incr_pct")


def read_ruleset() -> str:
    with tempfile.TemporaryDirectory(prefix="dof_rules_") as directory:
        destination = pathlib.Path(directory) / "terrain.ruleset"
        subprocess.run(["docker", "cp", f"{CONTAINER}:{RULESET}", str(destination)],
                       capture_output=True, text=True, check=True)
        return destination.read_text(encoding="utf-8")


def sections(text: str, prefix: str) -> dict[str, dict[str, str]]:
    """Разобрать секции `[имя]` с парами `ключ = значение`, отбросив комментарии."""
    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            name = m.group(1)
            current = name if name.startswith(prefix) else None
            if current:
                out[current] = {}
            continue
        if current and "=" in line:
            key, _, value = line.partition("=")
            out[current][key.strip()] = value.strip().strip('"')
    return out


def main() -> None:
    text = read_ruleset()
    terrains = sections(text, "terrain_")
    road_types = sections(text, "road_")

    table: dict[str, dict[str, float]] = {}
    for name, fields in sorted(terrains.items()):
        row = {k: float(fields[k]) for k in TERRAIN_FIELDS
               if k in fields and float(fields[k]) != 0.0}
        if row:
            table[name[len("terrain_"):]] = row

    # Дороги: у самой экстры свои приросты, у террейна — проценты их применения.
    roads: dict[str, dict[str, float]] = {}
    for name, fields in sorted(road_types.items()):
        effect_fields = tuple(f"{output}_{suffix}" for output in ("food", "shield", "trade")
                              for suffix in ("incr", "incr_const", "bonus"))
        row = {k: float(fields[k]) for k in effect_fields
               if k in fields and float(fields[k]) != 0.0}
        roads[name[len("road_"):]] = row

    lines = [
        '"""ЭФФЕКТ РАБОТЫ ПО КЛЕТКЕ — прочитан из правил мира, не выдуман.\n',
        f"Источник: `{RULESET}` в контейнере `{CONTAINER}`. "
        "Сгенерировано: `scripts/read_terrain_work_effects.py`.\n",
        "Указание владельца: эффект — характеристика мира, её достаточно узнать один раз.\n"
        '"""\n',
        "from __future__ import annotations\n",
        "#: террейн → приросты, которые даёт работа (только ненулевые поля правил).",
        "TERRAIN_WORK_EFFECTS: dict[str, dict[str, float]] = {",
    ]
    for name, row in table.items():
        lines.append(f'    "{name}": {row!r},')
    lines += ["}\n", "#: дорога/железная дорога → собственные приросты экстры.",
              "ROAD_EFFECTS: dict[str, dict[str, float]] = {"]
    for name, row in roads.items():
        lines.append(f'    "{name}": {row!r},')
    lines += ["}\n", "#: террейн → процент применения приростов дороги.",
              "ROAD_PCT_FIELDS = (", ]
    for field in ("road_food_incr_pct", "road_shield_incr_pct", "road_trade_incr_pct"):
        lines.append(f'    "{field}",')
    lines += [")", ""]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано {OUT}: террейнов {len(table)}, дорог {len(roads)}")
    for name, row in table.items():
        print(f"  {name:<12} {row}")
    for name, row in roads.items():
        print(f"  {name:<12} {row}  (проценты по террейну: см. ROAD_PCT_FIELDS)")


if __name__ == "__main__":
    main()
