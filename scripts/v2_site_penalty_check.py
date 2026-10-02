"""Проверка штрафов §10.108 на синтетическом графе: перекрытие зон и плодородие."""
import sys
sys.path.insert(0, r"/home/hermes/projects/AI/DOF-MODEL-CIV")

from brain.v2.knowledge import KnowledgeGraph
from brain.v2.horizon import city_crowding_penalty, site_food_penalty


def make(r_sq=17, food_cost=2.0):
    g = KnowledgeGraph()
    g.world = {"xsize": 78, "ysize": 52}
    g.rules = {"border_city_radius_sq": r_sq, "food_cost": food_cost}
    return g


def add_city(g, cid, x, y, terrain=None, eda=None):
    g.ensure(f"city:{cid}", "city", owner=0, is_own=True, name=f"C{cid}")
    g.entity(f"city:{cid}").attrs.update({"x": x, "y": y, "prod_food": eda})
    if terrain is not None and eda is not None:
        g.note_observation("terrain_food", {"terrain": terrain, "еда": float(eda)})


def add_settler(g, uid, x, y, terrain):
    g.ensure(f"unit:{uid}", "unit", owner=0, is_own=True, name="Settlers")
    g.entity(f"unit:{uid}").attrs.update({"x": x, "y": y})
    g.ensure(f"tile:{x},{y}", "tile")
    g.entity(f"tile:{x},{y}").attrs.update({"x": x, "y": y, "terrain": terrain})


# 1) город в (10,10); поселенец прямо на нём (перекрытие полное ~100%)
g = make()
add_city(g, 1, 10, 10, terrain=0, eda=4)
add_settler(g, 5, 10, 10, terrain=0)
p, w = city_crowding_penalty(g, "5")
print(f"поселенец НА городе:  penalty={p:.3f} | {w[:80]}")

# 2) поселенец на дистанции 2 от города (как было раньше): должно быть заметное перекрытие
g = make()
add_city(g, 1, 10, 10, terrain=0, eda=4)
add_settler(g, 5, 12, 10, terrain=0)
p, w = city_crowding_penalty(g, "5")
print(f"дистанция 2:           penalty={p:.3f} | {w[:80]}")

# 3) поселенец далеко (30,30) от города (10,10): перекрытия нет
g = make()
add_city(g, 1, 10, 10, terrain=0, eda=4)
add_settler(g, 5, 30, 30, terrain=1)
p, w = city_crowding_penalty(g, "5")
print(f"дистанция ~28:          penalty={p:.3f} | {w[:60]}")

# 4) плодородие: участок terrain 1 не кормит (еда 1 ≤ 2), DoF города 15
g = make()
add_settler(g, 5, 10, 10, terrain=1)
add_city(g, 1, 40, 40, terrain=1, eda=1)   # замер: террейн 1 -> еда 1
p, w = site_food_penalty(g, "5", dof_city=15.0)
print(f"неплодородный участок:  penalty={p:.3f} | {w[:90]}")

# 5) плодородие: участок кормит (еда 4 > 2) — штрафа нет
g = make()
add_settler(g, 5, 10, 10, terrain=0)
add_city(g, 1, 40, 40, terrain=0, eda=4)
p, w = site_food_penalty(g, "5", dof_city=15.0)
print(f"плодородный участок:    penalty={p:.3f} | {w[:80]}")
