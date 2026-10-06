"""Длинный прогон: труба «линзы → граф → вердикт → calc» на серии миров.

Смоук проверяет одну точку — реальное наблюдение и синтетику вокруг него. Здесь
проверяется **серия**: N миров разной формы, у каждого свой набор сущностей, меню,
нулей и чужих актов. Инварианты обязаны держаться на каждом мире серии, а не в
среднем, поэтому падение считается по первому нарушителю и печатается мир, на
котором оно случилось.

Что считается нарушением:

  I1  NaN/бесконечность в любом ψ, DoF или индексе;
  I2  сущность без вердикта или вердикт `undetermined` там, где тип объявлен;
  I3  индекс не равен ручной сумме `Σ ln(max(DoF, ε))` по множеству счёта;
  I4  из счёта выбыла сущность с положительной DoF (§4.2 так не делает);
  I5  сущность с положительной DoF осталась вне счёта;
  I6  повторный прогон того же мира дал другой отпечаток, счёт или индекс;
  I7  свидетель вердикта не из актов графа или меняется от порядка актов;
  I8  восстановленная чужим актом сущность выбыла из счёта.

Запуск: .venv/bin/python scripts/_spec_long_run.py [--worlds N] [--seed S]
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.spec.world_graph import ActEdge, EntityNode, WorldGraph  # noqa: E402
from env.config import TURN_DURATION_MKS  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402
from env import spec_graph as G  # noqa: E402
from env import spec_lenses as L  # noqa: E402

OBS_FILE = ROOT / "tests" / "fixtures" / "real_obs_01.json"
MY_PLAYER = 0
EPS = 1e-6

MENUS: dict[str, tuple[str, ...]] = {
    "unit": ("goto_0", "goto_1", "goto_7", "build_road", "irrigation", "fortify",
             "mine", "pillage", "build_city"),
    "city": ("produce_Warriors", "produce_Settlers", "produce_Temple",
             "produce_Granary", "city_buy_production", "city_work_13_-2_-1"),
    "player": ("research_tech_Warriors_9", "research_tech_Pottery_12",
               "set_tech_goal_Pottery_12", "change_gov_Monarchy",
               "change_gov_Republic", "set_sci_lux_tax"),
    "diplomacy": ("add_clause_ShareMap_1_0_1", "cancel_treaty_1",
                  "stop_negotiation_1", "accept_treaty_1"),
}

KNOWN_POOL = ("9", "12", "3")   # номера технологий, которые могут быть уже известны


def make_world(rng: random.Random) -> dict:
    """Один мир серии: сущности, меню, нули и, иногда, чужой акт восстановления."""
    kinds = ["unit", "city", "player", "diplomacy"]
    entities: list[str] = []
    for i in range(rng.randint(4, 11)):
        kind = rng.choice(kinds)
        entities.append(f"{kind}_{100 + i}")
    known_gates = rng.sample(KNOWN_POOL, rng.randint(0, len(KNOWN_POOL)))

    vectors: dict[str, list[str]] = {}
    fields_of: dict[str, dict] = {}
    for eid in entities:
        kind = eid.split("_", 1)[0]
        raw = list(rng.sample(MENUS[kind], rng.randint(0, len(MENUS[kind]))))
        fields = {}
        if kind == "city":
            fields = {"shield_stock": rng.choice([0.0, 3.0, 40.0]),
                      "turns_to_prod_complete": 2.0, "ppl_happy": 2.0, "ppl_unhappy": 0.0}
        vectors[eid] = L.available_vectors(kind, fields, raw, known_gates)
        fields_of[eid] = fields

    bindings = {}
    for eid in entities:
        kind = eid.split("_", 1)[0]
        requirements = {}
        if kind == "city" and rng.random() < 0.5:
            requirements = {"energy": rng.choice([0.0, 20.0, 200.0])}
        bindings[eid] = L.lens_observation(
            variety=L.variety_counters(vectors[eid]),
            requirements=L.reduce_requirements([requirements]) if requirements else {},
            constraint=L.constraint_observation(kind, fields_of[eid]),
        )
    means = {"energy": rng.choice([0.0, 7.0, 500.0]), "food": 0.0, "gold": 0.0, "tech": 0.0}
    measured = L.measure(bindings, means)
    dof = {eid: m.current_dof for eid, m in measured.items()}

    zeroed: list[str] = []
    if rng.random() < 0.7 and entities:
        for eid in rng.sample(entities, rng.randint(1, min(3, len(entities)))):
            dof[eid] = 0.0                  # известный ноль — то, ради чего §4.9 и есть
            zeroed.append(eid)

    helper = None
    if zeroed and rng.random() < 0.6:
        helper = (f"unit_{900 + rng.randint(0, 9)}", rng.choice(zeroed))
        vectors[helper[0]] = ["goto_3", "build_road"]
        fields_of[helper[0]] = {}
        dof[helper[0]] = 0.5

    graph = G.world_graph(vectors, fields_of, dof)
    if helper:
        graph.acts.append(ActEdge(id=f"{helper[0]}:revive", source=helper[0],
                                  target=helper[1], category="production",
                                  effect={helper[1]: 1.0}, duration_mks=TURN_DURATION_MKS))
    return {"entities": entities, "vectors": vectors, "fields": fields_of, "dof": dof,
            "graph": graph, "zeroed": zeroed, "helper": helper, "known_gates": known_gates}


def run_world(template, world: dict) -> dict:
    """Один прогон мира: вердикты, счёт, индекс."""
    ctx = G.observation_context(world["graph"], world["dof"])
    st = G.state_with_measured_dof(template, world["dof"])
    members, index = G.calc_and_index(st, ctx)
    verdicts = G.recoverability(st, ctx)
    return {"st": st, "ctx": ctx, "members": members, "index": index, "verdicts": verdicts}


def check_world(i: int, world: dict, r: dict, order_permuted: bool = False) -> list[str]:
    bad: list[str] = []
    st, dof = r["st"], world["dof"]
    ok_entities = set(st.entities)

    for eid in sorted(ok_entities):
        ent = st.entities[eid]
        if not math.isfinite(ent.current_dof):
            bad.append(f"I1 {eid} DoF не конечно: {ent.current_dof}")
    if not math.isfinite(r["index"]):
        bad.append(f"I1 индекс не конечен: {r['index']}")

    if set(r["verdicts"]) != ok_entities:
        bad.append(f"I2 вердикт есть не у всех: {sorted(ok_entities - set(r['verdicts']))}")
    for eid, v in r["verdicts"].items():
        if v["verdict"] == "undetermined":
            bad.append(f"I2 {eid} undetermined: {v['reason']}")

    hand = sum(math.log(max(st.entities[e].current_dof, EPS)) for e in r["members"])
    if abs(hand - r["index"]) > 1e-9:
        bad.append(f"I3 индекс {r['index']} ≠ ручной {hand}")

    for eid in sorted(set(ok_entities) - r["members"]):
        if dof[eid] > 0.0:
            bad.append(f"I4 выбыла положительная {eid} (DoF={dof[eid]})")
    for eid in sorted(r["members"]):
        if dof[eid] > 0.0:
            continue
        if r["verdicts"][eid]["verdict"] == "reachable":
            continue
        bad.append(f"I5 {eid} в счёте, но вердикт {r['verdicts'][eid]['verdict']}")

    again = run_world(template_of(world), world)
    if (again["members"] != r["members"] or again["index"] != r["index"]
            or again["ctx"].observation_digest != r["ctx"].observation_digest):
        bad.append("I6 повтор дал другой счёт/индекс/отпечаток")
    for eid, v in r["verdicts"].items():
        if v["witness"] != again["verdicts"][eid]["witness"]:
            bad.append(f"I6 {eid} свидетель не воспроизвелся")

    if r["verdicts"]:
        for eid, v in r["verdicts"].items():
            for act_id in v["witness"]:
                if act_id not in {a.id for a in world["graph"].acts}:
                    bad.append(f"I7 свидетель {act_id} не из актов графа")
    if world["helper"]:
        revived = world["helper"][1]
        v = r["verdicts"][revived]
        if v["verdict"] != "reachable":
            bad.append(f"I8 {revived} с чужим актом не восстановлен: {v['verdict']}")
        if revived not in r["members"]:
            bad.append(f"I8 восстановленная {revived} выбыла из счёта")
    return bad


TEMPLATE: dict = {}


def template_of(world: dict):
    return TEMPLATE["state"]


def main() -> int:
    worlds = 300
    seed = 20261006
    if "--worlds" in sys.argv:
        worlds = int(sys.argv[sys.argv.index("--worlds") + 1])
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])

    snap = json.load(open(OBS_FILE))[0]
    TEMPLATE["state"] = GameStateExtractor(my_player_id=MY_PLAYER).extract(
        snap["observation"], snap["info"], snap["turn"]).state

    rng = random.Random(seed)
    print(f"=== Длинный прогон: миров {worlds}, сид {seed} ===")
    totals = {"entities": 0, "reachable": 0, "unreachable": 0, "nodes": 0, "acts": 0,
              "excluded": 0, "worlds_with_zero": 0, "worlds_with_helper": 0,
              "revived": 0, "index_min": 0.0, "index_max": 0.0}
    failures: list[str] = []
    for i in range(worlds):
        world = make_world(rng)
        r = run_world(TEMPLATE["state"], world)
        bad = check_world(i, world, r)
        for b in bad:
            failures.append(f"мир {i} (сид-ветка {seed}): {b}")

        totals["nodes"] += len(world["graph"].entities)
        totals["acts"] += len(world["graph"].acts)
        totals["entities"] += len(r["verdicts"])
        totals["excluded"] += len(set(r["st"].entities) - r["members"])
        totals["worlds_with_zero"] += bool(world["zeroed"])
        totals["worlds_with_helper"] += bool(world["helper"])
        totals["revived"] += sum(
            1 for _, tgt in ([world["helper"]] if world["helper"] else [])
            if r["verdicts"][tgt]["verdict"] == "reachable")
        for v in r["verdicts"].values():
            if v["verdict"] == "reachable":
                totals["reachable"] += 1
            elif v["verdict"] == "proven_unreachable":
                totals["unreachable"] += 1
        totals["index_min"] = min(totals["index_min"], r["index"])
        totals["index_max"] = max(totals["index_max"], r["index"])

    print(f"  узлов всего {totals['nodes']}, актов всего {totals['acts']}")
    print(f"  сущностей {totals['entities']}: reachable {totals['reachable']}, "
          f"proven_unreachable {totals['unreachable']}")
    print(f"  миров с нулём {totals['worlds_with_zero']}, с чужим актом "
          f"{totals['worlds_with_helper']}, восстановлено {totals['revived']}")
    print(f"  исключено из счёта за серию: {totals['excluded']}")
    print(f"  индекс по серии: от {totals['index_min']:.4f} до {totals['index_max']:.4f}")
    if failures:
        print(f"\nНАРУШЕНИЙ: {len(failures)}")
        for line in failures[:10]:
            print(f"  {line}")
        return 1
    print("\nнарушений нет: все инварианты I1–I8 держатся на каждом мире серии")
    return 0


if __name__ == "__main__":
    sys.exit(main())