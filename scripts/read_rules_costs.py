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
             "hitpoints", "firepower", "move_rate", "class")
BUILDING_KEYS = ("name", "rule_name", "genus", "build_cost", "upkeep")
#: ключи, которые надо снять с кавычек (`class = "Land"` приходит как `"Land"`)
UNQUOTE_KEYS = ("name", "rule_name", "genus", "class")


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


def reqs_targets(body: str) -> list[tuple]:
    """Из `reqs` — требования вида ("Building", "Granary", "City").

    Четвёртое поле (`present`: TRUE/FALSE) тоже читаем: через него устроен `Barracks` —
    у него НЕТ собственных эффектов, он только включает чужие
    (`"BuildingFlag", "Barracks", "City", TRUE` в `effects.ruleset`) — и без этого поля
    постройка выглядела «неоценённой», хотя на деле её ценность просто не прочитана.
    """
    out: list[tuple] = []
    pattern = (r'"([A-Za-z]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"'
               r'(?:\s*,\s*(TRUE|FALSE))?')
    for kind, name, rng, present in re.findall(pattern, body):
        out.append((kind, name, rng, present))
    return out


def flags_of(body: str) -> tuple:
    """Флаги раздела правил.

    Измерено: флаги пишут и в скобках (`flags = { "NonMil" }`), и БЕЗ них
    (`flags = "Settlers", "Cant_Fortify"` — так у поселенца). Прежнее чтение знало
    только скобочную форму и молча возвращало пусто, а `NonMil` — ровно тот флаг, по
    которому `Barracks` на поселенцев НЕ действует.
    """
    match = re.search(r'^\s*flags\s*=\s*(.*?)(?=\n\s*[a-z_]+\s*=|$)', body, re.M | re.S)
    if not match:
        return ()
    return tuple(sorted(set(re.findall(r'"([^"]+)"', match.group(1)))))


def parse_unit_classes(text: str) -> dict[str, dict[str, object]]:
    """Классы юнитов: имя → флаги. Требования эффектов ссылаются на классы и их флаги."""
    table: dict[str, dict[str, object]] = {}
    for name, body in sections(text):
        if not name.startswith("unitclass_"):
            continue
        rule = scalar(body, "rule_name")
        shown = scalar(body, "name")
        key = _unquote(rule or shown or name)
        table[key] = {"name": _unquote(shown or key), "flags": flags_of(body)}
    return table


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
            if key in UNQUOTE_KEYS:
                row[key] = _unquote(raw)
            else:
                try:
                    row[key] = int(float(raw))
                except ValueError:
                    row[key] = raw
        row["flags"] = flags_of(body)
        key_name = str(row.get("rule_name") or row.get("name") or name)
        table[key_name] = row
    return table


def parse_buildings(text: str) -> dict[str, dict[str, object]]:
    table: dict[str, dict[str, object]] = {}
    for name, body in sections(text):
        if not name.startswith("building_"):
            continue
        # Фильтра по роду НЕТ, и это исправление, а не послабление: здесь стоял белый
        # список ("Improvement", "Special", "Wonder"), составленный мной по догадке, а
        # правила мира говорят `GreatWonder` и `SmallWonder`. Из-за догадки из 68 построек
        # в таблицу попадали 38 — молча пропадали все 28 великих чудес и малое чудо
        # (`Colossus` с ценой 100 среди них). Молчаливый отбор мира — это потеря картины
        # мира; род теперь ПИШЕТСЯ, а решает по нему тот, кто оценивает.
        row: dict[str, object] = {}
        for key in BUILDING_KEYS:
            raw = scalar(body, key)
            if raw is None:
                continue
            if key in UNQUOTE_KEYS:
                row[key] = _unquote(raw)
            else:
                try:
                    row[key] = int(float(raw))
                except ValueError:
                    row[key] = raw
        row["flags"] = flags_of(body)
        key_name = str(row.get("rule_name") or row.get("name") or name)
        table[key_name] = row
    return table


def parse_effects(text: str) -> list[tuple]:
    """Эффекты мира: (эффект, величина, род цели, имя цели, охват, ВИД ВЫХОДА, раздел).

    Вид выхода (`OutputType`: Food/Shield/Trade/Gold/Luxury) нужен, чтобы приложить к эффекту
    прироста вес его кода: `dai_city_want` (`daicity.c:1496`) считает хотение города как
    `еда×30 + щиты×17 − загрязнение×20 + роскошь×1 + наука×18 + золото×18`. Без вида выхода
    неизвестно, к какому слагаемому относится эффект.
    """
    out: list[tuple[str, int, str, str, str, str, str, tuple]] = []
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
        targets = reqs_targets(body)
        output_kind = ""
        for req_kind, req_name, _req_range, _present in targets:
            if req_kind == "OutputType":
                output_kind = req_name
        # Адресат эффекта. Если здания/юнита/науки в требованиях нет, адресатом может быть
        # ФЛАГ постройки: именно так устроен `Barracks` — своих эффектов у него нет, он
        # включает чужие (`"BuildingFlag", "Barracks", "City", TRUE` в `effects.ruleset`).
        # Без этого измеренный факт «Barracks нужен городу» не читался вовсе.
        addresses = [(k, _unquote(n), r)
                     for k, n, r, _p in targets
                     if k in ("Building", "Unit", "Extra", "Tech")]
        if not addresses:
            # Своих адресатов нет — значит адресат флаговый (измерено на `Barracks`).
            addresses = [(k, _unquote(n), r)
                         for k, n, r, pr in targets
                         if k == "BuildingFlag" and str(pr).upper() == "TRUE"][:1]
        if not addresses:
            continue
        for a_kind, a_name, a_range in addresses:
        # Требования К ГОРОДУ (что должно быть у города), кроме самого адресата: у
        # `[effect_oracle]` это ещё и `Building Oracle`, и без него эффект НЕ действует —
        # измерено: у Храма 3 раздела Make_Content, третий про Оракула.
            requires = tuple(sorted(
                (_unquote(n), k, str(p).upper())
                for k, n, _r, p in targets
                if k in ("Building", "Unit", "Extra", "Tech", "BuildingFlag")
                and not (k == a_kind and _unquote(n) == a_name)))
            # Требования К ЮНИТАМ: на кого эффект действует — это считает его
            # `num_affected_units` (`daieffects.c:120`), и без них военные семьи не оценить.
            unit_reqs = tuple(sorted(
                (_unquote(n), k, str(p).upper())
                for k, n, _r, p in targets
                if k in ("UnitClass", "UnitFlag")))
            out.append((_unquote(kind), amount, a_kind, a_name, a_range,
                        output_kind, name, requires, unit_reqs))
    return out


def main() -> None:
    units = parse_units(read_rules("units.ruleset"))
    # Классы юнитов определены ВНУТРИ units.ruleset (отдельного файла в classic нет):
    # измерено — `unitclasses.ruleset` в каталоге правил отсутствует, есть только
    # units/buildings/effects/terrain/techs/game/cities/governments/actions/styles.
    unit_classes = parse_unit_classes(read_rules("units.ruleset"))
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
    lines += ["}", "", "#: имя класса юнитов → его флаги (мир нумерует юнитов классами)",
              "UNIT_CLASSES: dict[str, dict[str, object]] = {"]
    for name in sorted(unit_classes):
        lines.append(f"    {name!r}: {unit_classes[name]!r},")
    lines += ["}", "",
              "#: эффекты мира: (эффект, величина, род цели, имя цели, охват, вид выхода,",
              "#:                 раздел, требования — кроме самого адресата)",
              "EFFECTS: list[tuple] = ["]
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
