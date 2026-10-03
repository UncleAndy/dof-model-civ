"""Сквозная проверка обороны: генератор+калькулюс на осаждённом городе (без мира).

Сценарий: наш город осаждён чужим юнитом ВПЛОТНУЮ, наш гарнизон рядом.
Ожидание (задача Andy): гарнизон НЕ убегает, а бьёт (отпор) или прикрывает город.
"""
import sys
sys.path.insert(0, '/home/hermes/projects/AI/DOF-MODEL-CIV')
from brain.v2.knowledge import KnowledgeGraph, Entity
from brain.v2 import generator, calculus
from brain.v2 import threat


def threat_exposure(g):
    return threat.exposure(g, threat.STRIKE_TURNS).keys()

DIRS = {0: (-1, -1), 1: (0, -1), 2: (1, -1), 3: (-1, 0), 4: (1, 0),
        5: (-1, 1), 6: (0, 1), 7: (1, 1)}


def build(besieged=True):
    g = KnowledgeGraph()
    g.world = {"xsize": 80, "ysize": 50, "ход": 30, "games": 1}
    g.add_entity(Entity(eid="unit_type:Phalanx", kind="unit_type", owner=None, is_own=False,
                        name="Phalanx",
                        attrs={"dof_families": 12, "type_attack_strength": 3,
                               "type_move_rate": 1, "type_defense_strength": 4}))
    g.add_entity(Entity(eid="city:1", kind="city", owner=0, is_own=True, name="Cap",
                        attrs={"x": 10, "y": 10, "size": 4, "city_radius_sq": 17,
                               "dof_families": 22, "владелец": 0}))
    g.add_entity(Entity(eid="unit:5", kind="unit", owner=0, is_own=True, name="Phalanx",
                        attrs={"x": 10, "y": 9, "type_attack_strength": 3,
                               "type_defense_strength": 4, "type_move_rate": 1}))
    g.add_entity(Entity(eid="unit:9", kind="unit", owner=1, is_own=False, name=None,
                        attrs={"x": 11, "y": 10, "type_attack_strength": 2,
                               "type_move_rate": 1, "владелец": 1}))
    if besieged:
        g.collapse["unit:9"] = {"до_хода": 60, "с_хода": 28, "владелец": 1, "почему": "наблюдено"}
    menu = {"unit": {"5": {**{f"goto_{i}": True for i in DIRS},
                           **{f"attack_{i}": True for i in DIRS},
                           "fortify": True, "sleep": True}}}
    return g, menu


def run(label, besieged):
    g, menu = build(besieged)
    print(f"[диагностика] hold_set={generator.hold_set(g)} "
          f"под_ударом={sorted(threat_exposure(g))}")
    paths, open_goals = generator.generate(g, menu, 0)
    rows = []
    for p in paths:
        d = calculus.evaluate(g, [p], 0)
        if d.chosen is not None:
            rows.append((d.chosen.steps[0].action, p.goal))
    rows.sort(key=lambda r: -_net(g, paths, r[1]))
    dec = calculus.evaluate(g, paths, 0)
    print(f"--- {label} ---")
    print(f"цели: {sorted({p.goal for p in paths})}")
    print(f"ВЫБРАНО: {dec.chosen.steps[0].action if dec.chosen else None}"
          f" (цель {dec.chosen.goal if dec.chosen else None})")
    print(f"причина: {dec.trace['reason'][:400]}")
    print()


def _net(g, paths, goal):
    for p in paths:
        if p.goal == goal:
            return calculus.evaluate(g, [p], 0).trace.get("net_delta") or 0.0
    return 0.0


run("ОСАДА: чужой вплотную к городу, нападение наблюдено", True)
run("НАРУШИТЕЛЬ: чужой вплотную к городу, нападения НЕ было", False)


def run_intercept():
    """Сближение: источник коллапса ВИДЕН, наш военный в 3 шагах, города рядом нет."""
    g = KnowledgeGraph()
    g.world = {"xsize": 80, "ysize": 50, "ход": 30, "games": 1}
    g.add_entity(Entity(eid="unit_type:Phalanx", kind="unit_type", owner=None, is_own=False,
                        name="Phalanx",
                        attrs={"dof_families": 12, "type_attack_strength": 3,
                               "type_move_rate": 1, "type_defense_strength": 4}))
    g.add_entity(Entity(eid="city:1", kind="city", owner=0, is_own=True, name="Cap",
                        attrs={"x": 11, "y": 11, "size": 4, "city_radius_sq": 17,
                               "dof_families": 22, "владелец": 0}))
    g.add_entity(Entity(eid="unit:5", kind="unit", owner=0, is_own=True, name="Phalanx",
                        attrs={"x": 8, "y": 10, "type_attack_strength": 3,
                               "type_defense_strength": 4, "type_move_rate": 1}))
    g.add_entity(Entity(eid="unit:9", kind="unit", owner=1, is_own=False, name=None,
                        attrs={"x": 11, "y": 10, "type_attack_strength": 2,
                               "type_move_rate": 1, "владелец": 1}))
    g.collapse["unit:9"] = {"до_хода": 60, "с_хода": 28, "владелец": 1, "почему": "наблюдено"}
    menu = {"unit": {"5": {**{f"goto_{i}": True for i in DIRS},
                           **{f"attack_{i}": True for i in DIRS},
                           "fortify": True, "sleep": True}}}
    paths, _ = generator.generate(g, menu, 0)
    dec = calculus.evaluate(g, paths, 0)
    print("--- СБЛИЖЕНИЕ: источник в 3 шагах, города рядом нет ---")
    print(f"цели: {sorted({p.goal for p in paths})}")
    print(f"ВЫБРАНО: {dec.chosen.steps[0].action if dec.chosen else None} "
          f"(цель {dec.chosen.goal if dec.chosen else None})")
    print(f"причина: {dec.trace['reason'][:300]}")


run_intercept()


def run_intercept_only():
    """Сближение БЕЗ города рядом: источник угрожает нашему юниту (source_price > 0)."""
    g = KnowledgeGraph()
    g.world = {"xsize": 80, "ysize": 50, "ход": 30, "games": 1}
    g.add_entity(Entity(eid="unit_type:Phalanx", kind="unit_type", owner=None, is_own=False,
                        name="Phalanx",
                        attrs={"dof_families": 12, "type_attack_strength": 3,
                               "type_move_rate": 1, "type_defense_strength": 4}))
    g.add_entity(Entity(eid="unit:5", kind="unit", owner=0, is_own=True, name="Phalanx",
                        attrs={"x": 8, "y": 10, "type_attack_strength": 3,
                               "type_defense_strength": 4, "type_move_rate": 1}))
    g.add_entity(Entity(eid="unit:6", kind="unit", owner=0, is_own=True, name="Settlers",
                        attrs={"x": 12, "y": 10, "dof_families": 13, "type_move_rate": 1}))
    g.add_entity(Entity(eid="unit:9", kind="unit", owner=1, is_own=False, name=None,
                        attrs={"x": 11, "y": 10, "type_attack_strength": 2,
                               "type_move_rate": 1, "владелец": 1}))
    g.collapse["unit:9"] = {"до_хода": 60, "с_хода": 28, "владелец": 1, "почему": "наблюдено"}
    menu = {"unit": {"5": {**{f"goto_{i}": True for i in DIRS},
                           **{f"attack_{i}": True for i in DIRS},
                           "fortify": True, "sleep": True},
                     "6": {**{f"goto_{i}": True for i in DIRS}, "fortify": True}}}
    paths, _ = generator.generate(g, menu, 0)
    dec = calculus.evaluate(g, paths, 0)
    print("--- СБЛИЖЕНИЕ БЕЗ ГОРОДА: источник угрожает нашему юниту ---")
    print(f"цели: {sorted({p.goal for p in paths})}")
    print(f"ВЫБРАНО: {dec.chosen.steps[0].action if dec.chosen else None} "
          f"(цель {dec.chosen.goal if dec.chosen else None}, "
          f"актор {dec.chosen.steps[0].actor if dec.chosen else None})")
    print(f"причина: {dec.trace['reason'][:300]}")


run_intercept_only()