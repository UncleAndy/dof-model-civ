"""Сторож таблицы мира: молчаливый отбор родов построек — это потеря картины мира.

Зачем отдельный файл. Здесь ловится ошибка, которая НЕ проявляется ни падением, ни
предупреждением: белый список родов построек отбрасывал всё, чего в нём не было. Мир говорит
`GreatWonder` и `SmallWonder`, а список знал только `Wonder` — и из 68 построек в таблицу
попадали 38, то есть молча пропадали все 28 великих чудес и малое. Заметить это можно было
только глазами, а глазами такое не видно.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import read_rules_costs as reader                                    # noqa: E402


SYNTHETIC = '''
[building_library]
name        = _("Library")
genus       = "Improvement"
build_cost  = 60

[building_colossus]
name        = _("Colossus")
genus       = "GreatWonder"
build_cost  = 100

[building_apollo]
name        = _("Apollo Program")
genus       = "SmallWonder"
build_cost  = 300

[building_airport]
name        = _("Airport")
genus       = "Special"
build_cost  = 120
'''


def test_no_building_genus_is_dropped_silently():
    """Ни один род, названный миром, не выбрасывается: фильтра родов больше нет."""
    table = reader.parse_buildings(SYNTHETIC)
    assert set(table) == {"Library", "Colossus", "Apollo Program", "Airport"}
    assert table["Colossus"]["genus"] == "GreatWonder"
    assert table["Apollo Program"]["genus"] == "SmallWonder"
    assert table["Colossus"]["build_cost"] == 100


def test_world_table_keeps_wonders():
    """В собранной картине мира чудеса ЕСТЬ — иначе правило «город чудес» не с чем сверять."""
    from env.rules_costs import BUILDING_COST

    genus = [str((row or {}).get("genus") or "") for row in BUILDING_COST.values()]
    assert "GreatWonder" in genus, "великие чудеса пропали из картины мира"
    assert "SmallWonder" in genus, "малые чудеса пропали из картины мира"
    assert (BUILDING_COST.get("Colossus") or {}).get("build_cost") == 100


def test_great_wonder_is_recognisable_by_name():
    """Род доступен по имени типа — по нему и решается, чудо ли это."""
    from env.rules_costs import BUILDING_COST

    genre = {name: str((row or {}).get("genus") or "")
             for name, row in BUILDING_COST.items()}
    assert genre.get("Colossus") == "GreatWonder"
    assert genre.get("Library") == "Improvement"