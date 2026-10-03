"""Синтетическая проверка §10.114 (отпор) и §10.113 (прикрытие) без ожидания живого боя."""
import sys
sys.path.insert(0, '/home/hermes/projects/AI/DOF-MODEL-CIV')
from brain.v2.knowledge import KnowledgeGraph, Entity
from brain.v2 import threat

g = KnowledgeGraph()
g.world = {"xsize": 80, "ysize": 50, "ход": 30, "games": 1,
           "наша_территория": [[10, 10], [11, 10], [12, 10], [10, 11], [11, 11]]}
g.add_entity(Entity(eid="city:1", kind="city", owner=0, is_own=True, name="Cap",
                    attrs={"x": 10, "y": 10, "size": 4, "city_radius_sq": 17}))
g.add_entity(Entity(eid="unit:5", kind="unit", owner=0, is_own=True, name="Phalanx",
                    attrs={"x": 11, "y": 10, "type_attack_strength": 3,
                           "type_defense_strength": 4}))
g.add_entity(Entity(eid="unit:9", kind="unit", owner=1, is_own=False, name=None,
                    attrs={"x": 12, "y": 10, "type_attack_strength": 2,
                           "type_move_rate": 1}))

def dof_of(gr, e):
    if e.attrs.get("kind_dof") is not None:
        return e.attrs["kind_dof"], ""
    if e.kind == "city":
        return 22.125, ""
    return 10.0, ""

# --- 1) отпор по ИСТОЧНИКУ КОЛЛАПСА (нападение наблюдено) ---
g.collapse["unit:9"] = {"до_хода": 40, "с_хода": 28, "владелец": 1, "почему": "наблюдено"}
gain, why = threat.defense_gain(g, "unit", "attack_4", "5", dof_of)   # attack_4 = E
print(f"[отпор/источник] gain={gain:.3f}  {why}")

# --- 2) отпор по НАРУШИТЕЛЮ территории (нападения не было) ---
g.collapse = {}
gain2, why2 = threat.defense_gain(g, "unit", "attack_4", "5", dof_of)
print(f"[отпор/нарушитель] gain={gain2:.3f}  {why2}")

# --- 3) прикрытие: наш военный встаёт к городу, рядом чужой ---
g.collapse = {}
g.entity("unit:5").attrs["x"], g.entity("unit:5").attrs["y"] = 9, 10   # в стороне
gain3, why3 = threat.cover_gain(g, "goto_4", "5", dof_of)              # шаг E -> (10,10) = город
print(f"[прикрытие] gain={gain3:.3f}  {why3}")

# --- 4) прикрытие НЕ нужно: чужих рядом нет ---
g.entity("unit:9").attrs["x"], g.entity("unit:9").attrs["y"] = 40, 40
gain4, why4 = threat.cover_gain(g, "goto_4", "5", dof_of)
print(f"[прикрытие/нет чужого] gain={gain4:.3f}  {why4!r}")

# --- 5) выключатель арма A ---
threat._POTENTIAL_ENABLED = False
g.collapse["unit:9"] = {"до_хода": 40, "с_хода": 28, "владелец": 1, "почему": "наблюдено"}
gain5, why5 = threat.defense_gain(g, "unit", "attack_4", "5", dof_of)
print(f"[выключено] gain={gain5:.3f}  {why5!r}")