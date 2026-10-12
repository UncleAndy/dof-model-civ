"""ЦЕНА И ХАРАКТЕРИСТИКИ ТИПОВ — прочитаны из правил мира, не выдуманы.

Указание владельца (2026-10-12): «Цена — это характеристика мира. Её достаточно узнать
один раз, например, из кода и сохранить в картину мира»; и «Код встроенного ИИ — это тоже
наблюдение, можно использовать значения из него».

Что делает скрипт: читает файлы правил из контейнера стенда и пишет таблицу в
`env/rules_costs.py` с указанием источника по каждому разделу. Ничего не выводит из
наблюдений в бою: цена типа — свойство мира, а не результат наших проб.

Запуск:

    .venv/bin/python scripts/read_rules_costs.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "env" / "rules_costs.py"
CONTAINER = "freeciv-web"
RULES_DIR = "/home/docker/freeciv/share/freeciv/classic"

UNIT_KEYS = ("name", "rule_name", "build_cost", "pop_cost", "attack", "defense",
             "hitpoints", "firepower", "move_rate")
BUILDING_KEYS = ("name", "rule_name", "genus", "build_cost", "upkeep")


def read_rules(name: str) -> str:
    """Прочитать файл правил из контейнера стенда."""
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", f"{RULES_DIR}/{name}"],
        capture_output=True, text=True, check=True)
    return proc.stdout


def _unquote(value: str) -> str:
    """`_("Granary")` → `Granary` — берём имя, как его называет мир."""
    value = value.strip()
    match = re.search(r'_\(\s*"([^"]*)"\s*\)', value)
    if match:
        plain = match.group(1)
    else:
        match = re.search(r'"([^"]*)"', value)
        plain = match.group(1) if match else value.strip('"')
    # Безымянные разделы мир отдаёт как `?unit:Workers` / `?building:Barracks` —
    # имя после двоеточия и есть имя типа (так его называет и стенд).
    if plain.startswith("?unit:") or plain.startswith("?building:"):
        return plain.split(":", 1)[1]
    return plain


def sections(text: str) -> list[tuple[str, str]]:
    """Разделы файла правил: [(имя раздела, тело)]."""
    found: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current is not None:
                found.append((current, "\n".join(body)))
            current = stripped[1:-1]
            body = []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        found.append((current, "\n".join(body)))
    return found


def scalar(body: str, key: str) -> str | None:
    """Значение ключа верхнего уровня (`key = ...`), если оно в одну строку."""
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", body, re.MULTILINE)
    if not match:
        return None
    return match.group(1).split(";")[0].strip()


def reqs_targets(body: str) -> list[tuple[str, str, str]]:
    """Из `reqs` — требования вида ("Building", "Granary", "City")."""
    pairs = re.findall(r'"([A-Za-z]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"', body)
    return [(kind, name, rng) for kind, name, rng in pairs]


def parse_units(text: str) -> dict[str, dict[str, object]]:
    table: dict[str, dict[str, object]] = {}
    for name, body in sections(text):
        if not name.startswith("unit_"):
            continue
        row: dict[str, object] = {}
        for key in UNIT_KEYS:
            raw = scalar(body, key)
            if raw is None:
                continue
            if key in ("name", "rule_name"):
                row[key] = _unquote(raw)
            else:
                try:
                    row[key] = int(float(raw))
                except ValueError:
                    row[key] = raw
        key_name = str(row.get("rule_name") or row.get("name") or name)
        table[key_name] = row
    return table


def parse_buildings(text: str) -> dict[str, dict[str, object]]:
    table: dict[str, dict[str, object]] = {}
    for name, body in sections(text):
        if not name.startswith("building_"):
            continue
        genus = scalar(body, "genus")
        if genus and _unquote(genus) not in ("Improvement", "Special", "Wonder"):
            continue
        row: dict[str, object] = {}
        for key in BUILDING_KEYS:
            raw = scalar(body, key)
            if raw is None:
                continue
            if key in ("name", "rule_name", "genus"):
                row[key] = _unquote(raw)
            else:
                try:
                    row[key] = int(float(raw))
                except ValueError:
                    row[key] = raw
        key_name = str(row.get("rule_name") or row.get("name") or name)
        table[key_name] = row
    return table


def parse_effects(text: str) -> list[tuple[str, int, str, str, str]]:
    """Эффекты мира: (эффект, величина, род цели, имя цели, охват)."""
    out: list[tuple[str, int, str, str, str]] = []
    for name, body in sections(text):
        if not name.startswith("effect_"):
            continue
        kind = scalar(body, "type")
        value = scalar(body, "value")
        if kind is None or value is None:
            continue
        try:
            amount = int(float(value))
        except ValueError:
            continue
        for req_kind, req_name, req_range in reqs_targets(body):
            if req_kind in ("Building", "Unit", "Extra", "Tech"):
                out.append((_unquote(kind), amount, req_kind, req_name, req_range))
    return out


def main() -> None:
    units = parse_units(read_rules("units.ruleset"))
    buildings = parse_buildings(read_rules("buildings.ruleset"))
    effects = parse_effects(read_rules("effects.ruleset"))

    lines = [
        '"""ЦЕНА И ХАРАКТЕРИСТИКИ ТИПОВ — прочитаны из правил мира, не выдуманы.',
        "",
        f"Источник: `{RULES_DIR}/units.ruleset`, `buildings.ruleset`, `effects.ruleset` в контейнере",
        f"`{CONTAINER}`. Сгенерировано: `scripts/read_rules_costs.py`.",
        "",
        "Указание владельца: цена — характеристика мира, её достаточно узнать один раз (из кода)",
        "и сохранить в картине мира. Здесь только чтение правил: ни одного выведенного числа.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "#: имя типа → цена постройки и характеристики (как их называет мир)",
        "UNIT_STATS: dict[str, dict[str, object]] = {",
    ]
    for name in sorted(units):
        lines.append(f"    {name!r}: {units[name]!r},")
    lines += ["}", "", "#: имя постройки → цена и содержание",
              "BUILDING_COST: dict[str, dict[str, object]] = {"]
    for name in sorted(buildings):
        lines.append(f"    {name!r}: {buildings[name]!r},")
    lines += ["}", "", "#: эффекты мира: (эффект, величина, род цели, имя цели, охват)",
              "EFFECTS: list[tuple[str, int, str, str, str]] = ["]
    for row in sorted(set(effects)):
        lines.append(f"    {row!r},")
    lines += ["]", "", "",
              "def build_cost_of(name: str) -> float | None:",
              '    """Цена типа по имени — из правил мира, без проб и без догадок."""',
              "    row = UNIT_STATS.get(name) or BUILDING_COST.get(name)",
              "    if not row:",
              "        return None",
              "    cost = row.get('build_cost')",
              "    try:",
              "        value = float(cost)  # type: ignore[arg-type]",
              "    except (TypeError, ValueError):",
              "        return None",
              "    return value if value > 0.0 else None",
              ""]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"записано: {OUT}")
    print(f"  юнитов: {len(units)}, построек: {len(buildings)}, эффектов: {len(set(effects))}")
    sample = sorted(units)[:4]
    for name in sample:
        print(f"  {name}: {units[name]}")


if __name__ == "__main__":
    main()