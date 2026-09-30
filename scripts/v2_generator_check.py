"""Проверка генератора на живом наблюдении (без нового прогона на стенде).

Берёт уже снятую пару «наблюдение + меню» (/tmp/v2_capture_seed9000.json), строит граф и
порождает пути. Печатает: цели, пути, цели без пути (открытые), DoF в двух видах, эффект
фильтра клинов стенда.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from baselines import wedges  # noqa: E402
from brain.v2 import knowledge, sensors  # noqa: E402
from brain.v2.families import family_of_options  # noqa: E402
from brain.v2.generator import derive_goals, generate  # noqa: E402

CAP = Path("/tmp/v2_capture_seed9000.json")


def main() -> int:
    if not CAP.exists():
        print(f"нет съёмки {CAP} — сначала запусти scripts/v2_capture.py")
        return 2
    d = json.loads(CAP.read_text())
    obs, available, own_id = d["observation"], d["available_actions"], d.get("my_id") or 0
    g = knowledge.build_graph(obs, available, own_id=own_id)
    menu = sensors.read_menu(available)

    print("== DoF в двух видах (механическое / семейное) ==")
    for e in sorted(g.by_kind("unit_type"), key=lambda x: x.eid):
        a = e.attrs
        if a.get("capabilities"):
            print(f"  {e.name}: механическое {a['dof_mechanical']}, семейное {a['dof_families']}"
                  f" — {', '.join(a['families'])}")
    for e in sorted(g.by_kind("controller"), key=lambda x: x.eid):
        a = e.attrs
        if a.get("capabilities"):
            print(f"  {e.name}: механическое {a['dof_mechanical']}, семейное {a['dof_families']}")

    print("\n== цели, выведенные из графа ==")
    goals = derive_goals(g, menu)
    kinds: dict[str, int] = {}
    for gl in goals:
        kinds[gl["goal"]] = kinds.get(gl["goal"], 0) + 1
    print("  всего:", len(goals), kinds)
    for gl in goals[:6]:
        print(f"    · {gl['goal']}: {gl['why']}")

    print("\n== пути БЕЗ фильтра клинов ==")
    paths_raw, _ = generate(g, menu, own_id=own_id)
    for p in paths_raw:
        print("  ", p.summary())

    print("\n== пути С фильтром клинов стенда (реестр) ==")
    paths, open_goals = generate(g, menu, own_id=own_id, avoid=wedges.is_wedged)
    if not paths:
        print("   путей нет")
    for i, p in enumerate(paths, 1):
        print(f"  {i}. {p.summary()}")
        print(f"     источник: {p.source}")
    print(f"\n  путей: {len(paths)} (объявленный коридор 3–5)")
    print(f"  цели без пути (открытые, не выдуманы): {len(open_goals)}")
    for gl in open_goals[:5]:
        print(f"    · {gl['goal']}: {gl['why']}")

    print("\n== проверка правила D1 на семействах ==")
    for name, opts in (("Settlers", ["build_city", "build_road", "cultivate", "goto_0", "goto_7",
                                     "hut_enter_6", "irrigation", "keep_activity", "plant"]),
                       ("канал tech", ["research_tech_Code of Laws_13", "set_tech_goal_Banking_7"]),
                       ("канал gov", ["set_sci_lux_tax_0_40_60", "change_gov_Anarchy"])):
        fams = family_of_options(opts)
        print(f"  {name}: {len(opts)} вариантов -> {len(fams)} семейств: {sorted(fams)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())