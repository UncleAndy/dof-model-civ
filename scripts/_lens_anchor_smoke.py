"""Смоук отображения «игра → линзы v0.11»: реальное наблюдение + проверка якорей.

Что проверяется (до данных объявлено):

  A. Реальные счётчики. На наблюдении `tests/fixtures/real_obs_01.json`:
     V — из настоящего меню мира, V_env — из настоящих врагов в радиусе,
     c_g/C_g — из настоящих стоимостей построек, F/F_env — из наблюдаемых заморозок.
  B. Якоря §4.6: `V = V_env ⇒ 0.5`; `c_g/C_g = 0.5 ⇒ 0.5`; `F = F_env ⇒ 0.5`.
  C. Вырожденные случаи ⇒ ровно 0, и ни одного `NaN`:
     `V = 0`; `c_g > 0 ∧ C_g = 0`; `F = 0 ∧ F_env = 0`; `c_g = 0 ∧ C_g = 0`.
  D. Линза не выдумывает требования: у сущности без требования `ψ_opt = 1`.
  E. Индекс конечен и **отрицателен** по построению (§4.1).

Запуск: .venv/bin/python scripts/_lens_anchor_smoke.py [--steps N]
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.spec.measurement import measure_entity  # noqa: E402
from brain.spec.world_graph import ActEdge, EntityNode, WorldGraph  # noqa: E402
from env.config import (  # noqa: E402
    SPEC_MEANS_CLASS,
    SPEC_MEANS_HORIZON_TURNS,
    TURN_DURATION_MKS,
)
from env.entity_extractor import GameStateExtractor  # noqa: E402
from env import spec_graph as G  # noqa: E402
from env import spec_lenses as L  # noqa: E402
from env import spec_options as O  # noqa: E402
from brain.spec.calculus_core import ActionOption, DOFCalculusCore  # noqa: E402

OBS_FILE = ROOT / "tests" / "fixtures" / "real_obs_01.json"
MY_PLAYER = 0

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK   {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        print(f"  ФЕЙЛ {name}  [{detail}]")


# ── настоящие данные: стоимости построек из правил ───────────────────────────

def build_cost_index(obs: dict) -> dict[str, float]:
    """Имя → стоимость в щитах, из спек, которые мир публикует у технологий.

    Единственный наблюдённый источник цен: у технологий лежат `sup_units` и
    `sup_improvements` — полные спецификации того, что они открывают, вместе с
    `build_cost`. Ничего не выдумываем: чего нет в спеках — того нет и в ценах.
    """
    index: dict[str, float] = {}
    for tech in (obs.get("tech") or {}).values():
        if not isinstance(tech, dict):
            continue
        for key in ("sup_units", "sup_improvements"):
            specs = tech.get(key)
            if not isinstance(specs, list):
                continue
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                name = spec.get("name") or spec.get("rule_name")
                cost = spec.get("build_cost")
                if name and cost is not None:
                    index[str(name)] = float(cost)
    return index


def city_requirements(city_obs: dict, costs: dict[str, float],
                      menu: list[str], production: float | None = None,
                      horizon: float = SPEC_MEANS_HORIZON_TURNS) -> dict[str, float]:
    """Требования города: **платёж за горизонт** по тому, что мир предлагает строить.

    База времени одна и та же у требования и у средств: средства — запас плюс доход
    за горизонт, требование — то, что придётся оплатить за горизонт. Полная цена
    против однодневного дохода — не свойство города, а разные базы времени: `20/7`
    вместо `7/7`.
    """
    per_transition: list[dict[str, float]] = []
    for name in menu:
        if not name.startswith("produce_"):
            continue
        due = O.payment_due(costs.get(name[len("produce_"):]), production, horizon)
        if due is not None:
            per_transition.append({"energy": float(due)})
    return L.reduce_requirements(per_transition)


def empire_stocks(obs: dict) -> dict[str, float]:
    """Запасы агента — наблюдаемые остатки по объявленным ресурсам."""
    shield = food = tech = 0.0
    for city in (obs.get("city") or {}).values():
        if not isinstance(city, dict):
            continue
        shield += float(city.get("shield_stock") or 0.0)
        food += float(city.get("food_stock") or 0.0)
        tech += float(city.get("bulbs") or 0.0)
    gold = 0.0
    for rec in (obs.get("player") or {}).values():
        if isinstance(rec, dict) and "gold" in rec:
            gold = float(rec.get("gold") or 0.0)
            break
    return {"energy": shield, "food": food, "tech": tech, "gold": gold}


def empire_incomes(obs: dict) -> dict[str, float]:
    """Доход агента за ход — сумма по городам, по объявленным полям дохода."""
    from env.config import SPEC_INCOME_FIELDS

    incomes: dict[str, float] = {}
    for res, fields in SPEC_INCOME_FIELDS.items():
        total = 0.0
        for city in (obs.get("city") or {}).values():
            if not isinstance(city, dict):
                continue
            for field in fields:
                if field in city:
                    total += float(city.get(field) or 0.0)
                    break
        incomes[res] = total
    return incomes


def disturbances(obs: dict, entity_id: str, kind: str) -> list[str]:
    """Способ подсчёта возмущений объявлен в модуле (там же и объявление линейки)."""
    return L.active_disturbances(obs, entity_id, kind, my_player_id=MY_PLAYER)


# ── прогон на реальном наблюдении ───────────────────────────────────────────

def run_real(steps: int) -> None:
    snaps = json.load(open(OBS_FILE))
    extractor = GameStateExtractor(my_player_id=MY_PLAYER)
    print(f"\n=== A. Реальные счётчики (шагов: {min(steps, len(snaps))}) ===")
    rows = []
    index_negative = True
    gates = 0
    tech_skipped = 0
    open_gate_dropped = 0
    cat_kept = 0
    cat_total = 0
    last: dict = {}
    for snap in snaps[:steps]:
        obs, info = snap["observation"], snap["info"]
        state = extractor.extract(obs, info, snap["turn"]).state
        tech_skipped += len([e for e in state.entities if e.startswith("tech_")])
        menu = L.menu_by_entity(info.get("available_actions") or {})
        costs = build_cost_index(obs)
        means = L.means_with_income(empire_stocks(obs), empire_incomes(obs))

        bindings = {}
        vectors: dict[str, list[str]] = {}
        fields_of: dict[str, dict] = {}
        raw_menus: dict[str, list[str]] = {}
        known_gates = {tid for tid, rec in (obs.get("tech") or {}).items()
                       if isinstance(rec, dict) and L.gate_is_open(rec)}
        catalogue = L.catalogue_index(obs.get("tech") or {})
        for eid in sorted(menu):
            kind = L.entity_type_of(eid)
            if kind == "tech":
                tech_skipped += 1            # технология — предмет действия, не сущность
                continue
            raw_names = menu.get(eid, [])
            if not raw_names:
                continue                     # сущности без меню не о чем мерить
            raw_menus[eid] = raw_names
            cat_total += sum(1 for n in raw_names if n.startswith("produce_"))
            raw = obs.get("dipl" if kind == "diplomacy" else kind, {}) or {}
            fields = raw.get(eid.split("_", 1)[1], {}) or {}
            names = L.available_vectors(kind, fields, raw_names, known_gates,
                                        catalogue=catalogue, known_techs=known_gates)
            cat_kept += sum(1 for n in raw_names
                            if n.startswith("produce_") and n in names)
            open_gate_dropped += sum(1 for n in raw_names
                                     if L.action_targets_open_gate(n, known_gates))
            if not names:
                gates += 1                   # живых векторов не осталось
            vectors[eid] = names
            fields_of[eid] = fields
            variety = L.variety_counters(names, disturbances(obs, eid, kind))
            if kind == "city":
                requirements = city_requirements(fields, costs, names,
                                                 fields.get("prod_shield"))
            else:
                requirements = {}            # мир не публикует цену переходов — не выдумываем
            bindings[eid] = L.lens_observation(
                variety=variety,
                requirements=requirements,
                constraint=L.constraint_observation(kind, fields),
            )

        measured = L.measure(bindings, means)
        for eid, m in measured.items():
            rows.append((snap["turn"], eid, m))
        if L.total_index(measured) > 0:
            index_negative = False
        last = {"turn": snap["turn"], "state": state, "vectors": vectors,
                "fields": fields_of, "measured": measured, "raw_menus": raw_menus,
                "catalogue": catalogue, "known_techs": known_gates, "obs": obs,
                "dof": {eid: m.current_dof for eid, m in measured.items()}}

    for turn, eid, m in rows:
        psi = m.psi
        blocks = ", ".join(f"c={c:.0f}/C={C:.0f}" for c, C in m.blocks) or "—"
        print(f"  ход {turn:<3} {eid:<16} V={m.variety_counters['V']:>4.0f} "
              f"V_env={m.variety_counters['V_env']:>2.0f}  {blocks:<28} "
              f"ψ=({psi['variety']:.4f}, {psi['options']:.4f}, {psi['constraint']:.4f}) "
              f"DoF={m.current_dof:.6f}  ln={m.contribution:+.3f}  узкое место: {m.binding_lens}")

    check("A1 все ψ в [0,1] и конечны, и найдена хотя бы одна сущность",
          bool(rows) and all(0.0 <= v <= 1.0 and math.isfinite(v)
                             for _, _, m in rows for v in m.psi.values() if v is not None),
          f"сущностей измерено: {len(rows)}")
    check("A2 ни одного NaN в DoF",
          all(math.isfinite(m.current_dof) for _, _, m in rows))
    check("A3 индекс отрицателен (§4.1: величина читается порядком)",
          index_negative and bool(rows))
    real_options = [m for _, _, m in rows if m.psi["options"] is not None]
    check("D у сущности без требования ψ_opt = 1",
          all(m.psi["options"] == 1.0 for m in real_options
              if not any(c > 0 for c, _ in m.blocks)),
          f"с требованием: {sum(1 for m in real_options if any(c > 0 for c, _ in m.blocks))}")
    player_id = f"player_{MY_PLAYER}"
    player_vectors = last.get("vectors", {}).get(player_id, [])
    check("A4 технология не сущность: среди измеренных её нет, а исследование — вектор игрока",
          not [eid for _, eid, _ in rows if eid.startswith("tech_")]
          and tech_skipped > 0 and open_gate_dropped > 0 and bool(player_vectors),
          f"тех-сущностей отброшено {tech_skipped}, действий к открытым дверям снято "
          f"{open_gate_dropped}, векторов у игрока {len(player_vectors)}")
    check("A5 каталог города отсечён требованиями: доступно меньше, чем перечислено",
          cat_total > cat_kept > 0,
          f"перечислено построек {cat_total}, доступно {cat_kept}, "
          f"неоценённых требований {last['catalogue']['unevaluated']}")

    # ── G. §3.5/§4.9/§4.2: граф мира, вердикты, множество счёта ─────────────
    print(f"\n=== G. Граф мира, вердикты и calc(S) (ход {last['turn']}) ===")
    graph = G.world_graph(last["vectors"], last["fields"], last["dof"],
                          catalogue=last["catalogue"], known_techs=last["known_techs"],
                          raw_menus=last["raw_menus"])
    ctx = G.observation_context(graph, last["dof"])
    st = G.state_with_measured_dof(last["state"], last["dof"])
    members, index = G.calc_and_index(st, ctx)
    verdicts = G.recoverability(st, ctx)
    counts = collections.Counter(v["verdict"] for v in verdicts.values())
    reasons = collections.Counter(v["reason"] for v in verdicts.values())
    print(f"  узлов {len(graph.entities)}, актов {len(graph.acts)}, "
          f"средств {len(graph.means)}, гор. счёта {ctx.counting_horizon_mks / 1e6:.0f} с, "
          f"T_rec(unit) {ctx.horizon('unit_113') / 1e6 if ctx.horizon('unit_113') else 0:.0f} с")
    print(f"  отпечаток наблюдения: {ctx.observation_digest[:16]}…")
    print(f"  вердикты: {dict(counts)}")
    for reason, n in reasons.most_common():
        print(f"    ×{n:<4} {reason}")
    excluded = sorted(set(st.entities) - members)
    print(f"  вне счёта ({len(excluded)}): {excluded[:6]}")
    missing = sorted(set(last["dof"]) - set(st.entities))
    print(f"  измерено, но не в состоянии: {len(missing)} {missing[:4]}")
    print(f"  индекс по calc(S): {index:.4f}  (в счёте сущностей: {len(members)})")
    check("G1 вердикт получен по каждой сущности и ни один не 'undetermined'",
          bool(verdicts) and all(v["verdict"] != "undetermined" for v in verdicts.values()),
          f"различных причин: {len(reasons)}")
    check("G2 на реальных данных известных нулей нет — и потому из счёта никто не выбывает",
          not excluded and all(v["verdict"] == "reachable" for v in verdicts.values()),
          f"в счёте {len(members)} из {len(st.entities)}, исключено {len(excluded)}")
    check("G3 у каждой исключённой сущности свидетель пуст, а наблюдение полное",
          all(not verdicts[e]["witness"] and verdicts[e]["observation"] == "complete"
              for e in excluded))
    check("G4 в счёте не остаётся сущности с известным нулём",
          all(st.entities[e].current_dof > 0.0 for e in members),
          f"нулей в счёте: {sum(1 for e in members if st.entities[e].current_dof <= 0.0)}")
    check("G5 индекс по calc(S) конечен и отрицателен (§4.1)",
          math.isfinite(index) and index < 0, f"{index:.4f}")
    bridges = [a for a in graph.acts if "->" in a.id]
    print(f"  рёбер-мостов «технология → город»: {len(bridges)}"
          + (f", пример {bridges[0].id}" if bridges else ""))
    check("G6 мост построен: исследование — ребро от игрока к городу, а не петля на себя",
          bool(bridges)
          and all(a.source.startswith("player_") and a.target.startswith("city_")
                  for a in bridges)
          and all(a.effect and min(a.effect.values()) > 0 for a in bridges),
          f"мостов {len(bridges)}")

    # ── I. §4.3–4.5: кандидаты, гейты применимости/оплаты, выбор ядра ───────
    print(f"\n=== I. Ход: кандидаты, гейты §4.8b/§4.8 и выбор §4.5 (ход {last['turn']}) ===")
    obs_last = last["obs"]
    fields_last = last["fields"]
    costs_last = build_cost_index(obs_last)
    stocks_last = empire_stocks(obs_last)
    incomes_last = empire_incomes(obs_last)
    means_last = L.means_with_income(stocks_last, incomes_last)

    def make_remeasure(cost_index):
        """Пересчёт линз на спроецированном меню **и** спроецированных средствах."""
        def remeasure(vecs, means=None):
            fresh = {}
            for eid, names in vecs.items():
                kind = L.entity_type_of(eid)
                names = list(names)
                fresh[eid] = L.lens_observation(
                    variety=L.variety_counters(names, disturbances(obs_last, eid, kind)),
                    requirements=(city_requirements(fields_last[eid], cost_index, names,
                                                    fields_last[eid].get("prod_shield"))
                                  if kind == "city" else {}),
                    constraint=L.constraint_observation(kind, fields_last[eid]),
                )
            return {eid: m.current_dof
                    for eid, m in L.measure(fresh, means_last if means is None
                                            else means).items()}
        return remeasure

    remeasure = make_remeasure(costs_last)

    deciders = [player_id] + sorted(e for e in last["vectors"] if e.startswith("city_"))
    city_id = next(e for e in deciders if e.startswith("city_"))
    production = {e: float(fields_last[e].get("prod_shield") or 0.0)
                  for e in deciders if e.startswith("city_")}
    standing = {e: float(fields_last[e]["turns_to_prod_complete"])
                for e in deciders if e.startswith("city_")
                and fields_last[e].get("turns_to_prod_complete") is not None}
    options = O.build_options(last["vectors"], last["raw_menus"], last["catalogue"],
                              last["known_techs"], graph, remeasure,
                              only=deciders, costs=costs_last,
                              means=means_last, production=production,
                              standing=standing)
    with_delta = [o for o in options if o.flat_delta()]
    priced = [o for o in options if o.projected_resource_delta]
    unpriced = [o for o in options if o.requires and not o.projected_resource_delta]
    st.deadlines = O.budget_deadlines(deciders)
    st.resources = O.resource_observations(means_last)
    tau = min(st.deadlines.values()) if st.deadlines else None
    core = DOFCalculusCore()
    winner, rows, barred = O.decide(core, st, options, ctx)
    by_bar = collections.Counter(str(r["barred_by"]) for r in rows)
    print(f"  кандидатов {len(options)} — решающие: {', '.join(deciders)}")
    print(f"  с приростом от пересчёта: {len(with_delta)}; "
          f"с наблюдённой ценой: {len(priced)}; цена неизвестна: {len(unpriced)}")
    print(f"  средства: energy={means_last.get('energy', 0.0):.0f} "
          f"(запас {stocks_last.get('energy', 0.0):.0f} + доход "
          f"{incomes_last.get('energy', 0.0):.0f}×1 ход), τ={tau / 1e6:.0f} с")
    print(f"  гейты: {dict(by_bar)} (нет ключа None — барьеров не было)")
    print(f"  решение: {winner.option_id if winner else 'стоять'}")
    if winner is not None:
        print(f"    {winner.description}")
    for r in sorted(rows, key=lambda x: -float(x["net_delta"]))[:3]:
        print(f"    {str(r['option_id'])[:56]:<56} Δ={float(r['net_delta']):+.6f} "
              f"барьер: {r['barred_by']}")
    check("I1 кандидатов ровно столько, сколько векторов у решающих сущностей",
          len(options) == sum(len(last["vectors"].get(e, [])) for e in deciders),
          f"{len(options)} опций на {len(deciders)} сущностях")
    cheap_index = dict(costs_last)
    cheap_index["__probe__"] = 1.0               # предмет дешевле любого в каталоге
    probe_remeasure = make_remeasure(cheap_index)
    base_dof = remeasure({city_id: list(last["vectors"][city_id])})[city_id]
    probe_dof = probe_remeasure(
        {city_id: list(last["vectors"][city_id]) + ["produce___probe__"]})[city_id]
    check("I2 прирост добыт пересчётом линз, а не объявлен: дешёвый предмет его даёт",
          probe_dof > base_dof + 1e-9,
          f"без него DoF города {base_dof:.6f}, с ним {probe_dof:.6f}")
    builds = [o for o in options if ":produce_" in str(o.option_id)]
    paid = [o for o in options if o.flat_delta()]
    prod_city = production.get(city_id, 0.0)
    stand_due = prod_city * SPEC_MEANS_HORIZON_TURNS
    due_of = {o.option_id: O.payment_due(
                  costs_last.get(str(o.option_id).split("produce_", 1)[1]), prod_city)
              for o in builds}
    expect_shift = {k for k, v in due_of.items()
                    if v is not None and abs(float(v) - stand_due) > 1e-9}
    check("I2б прирост построек есть ровно там, где платёж отличается от платежа стоящего обязательства",
          bool(builds) and {o.option_id for o in paid} == expect_shift,
          f"построек {len(builds)}, платежей, отличных от стоящего ({stand_due:.0f}): "
          f"{len(expect_shift)}, опций с приростом {len(paid)}")
    c_energy, C_energy = last["measured"][city_id].blocks[0]
    cheap_prices = [float(costs_last[str(a)[len("produce_"):]])
                    for a in last["vectors"][city_id]
                    if str(a).startswith("produce_")
                    and str(a)[len("produce_"):] in costs_last]
    cheap = min(cheap_prices) if cheap_prices else 0.0
    check("I10 требование города — платёж за горизонт, а не полная цена предмета",
          abs(c_energy - min(cheap, prod_city)) < 1e-9
          and abs(C_energy - means_last.get("energy", 0.0)) < 1e-9
          and cheap > prod_city,
          f"c={c_energy:.0f} = min(дешёвый предмет {cheap:.0f}, производительность {prod_city:.0f}); "
          f"C={C_energy:.0f}, ψ_opt={last['measured'][city_id].psi['options']:.4f}")
    check("I11 предмет, завершающийся в горизонт, стоит свою цену; не завершающийся — только поток",
          abs(float(O.payment_due(5.0, prod_city)) - 5.0) < 1e-9
          and abs(float(O.payment_due(cheap, prod_city)) - prod_city) < 1e-9
          and float(O.payment_due(None, prod_city)) == prod_city
          and float(O.payment_due(cheap, None)) == cheap,
          f"цена 5 при производительности {prod_city:.0f} → "
          f"{float(O.payment_due(5.0, prod_city)):.0f}; цена {cheap:.0f} → "
          f"{float(O.payment_due(cheap, prod_city)):.0f}; цена неизвестна → "
          f"{float(O.payment_due(None, prod_city)):.0f}")
    # Контроль платежа: платёж ниже стоящего обязан дать плюс, равный — не дать прироста.
    probe_standing = {city_id: 3.0}      # проба: обязательство, не завершающееся в горизонт
    cheap_costs = {name: 1.0 for name in costs_last}
    cheap_opts = O.build_options(last["vectors"], last["raw_menus"], last["catalogue"],
                                 last["known_techs"], graph, make_remeasure(cheap_costs),
                                 only=[city_id], costs=cheap_costs, means=means_last,
                                 production=production, standing=probe_standing)
    due_now_probe = prod_city * SPEC_MEANS_HORIZON_TURNS
    exp_sign: dict[str, int] = {}
    for o in cheap_opts:
        if ":produce_" not in str(o.option_id):
            continue
        due_new = O.payment_due(cheap_costs.get(str(o.option_id).split("produce_", 1)[1]),
                                prod_city)
        if due_new is None or prod_city <= 0.0:
            continue
        exp_sign[o.option_id] = (1 if float(due_new) < due_now_probe
                                 else (-1 if float(due_new) > due_now_probe else 0))
    got = {o.option_id: (min(o.flat_delta().values()) if o.flat_delta() else 0.0)
           for o in cheap_opts if ":produce_" in str(o.option_id)}
    gain = {k for k, v in exp_sign.items() if v > 0}
    same = {k for k, v in exp_sign.items() if v == 0}
    loss = {k for k, v in exp_sign.items() if v < 0}
    check("I14 контроль платежа: платёж ниже стоящего даёт плюс, выше — минус, равный — ничего",
          bool(gain) and all(got.get(k, 0.0) > 1e-12 for k in gain)
          and all(abs(got.get(k, 0.0)) < 1e-12 for k in same)
          and all(got.get(k, 0.0) < -1e-12 for k in loss),
          f"построек с платежом ниже стоящего {len(gain)}, равным {len(same)}, выше {len(loss)}; "
          f"пример Δ={min([got[k] for k in gain], default=0.0):+.4f}")
    # База времени одна — и проверяется с обеих сторон: запас двигает линзу,
    # один доход нет, потому что требование следует за производительностью.
    base_city = remeasure({city_id: list(last["vectors"][city_id])})[city_id]
    dof_more_stock = remeasure({city_id: list(last["vectors"][city_id])},
                               {**means_last,
                                "energy": float(means_last.get("energy", 0.0)) + prod_city})[city_id]
    kept_prod = fields_last[city_id].get("prod_shield")
    try:
        fields_last[city_id]["prod_shield"] = 2.0 * prod_city
        dof_more_income = remeasure(
            {city_id: list(last["vectors"][city_id])},
            {**means_last, "energy": 2.0 * float(means_last.get("energy", 0.0))})[city_id]
    finally:
        fields_last[city_id]["prod_shield"] = kept_prod
    check("I15 проверено: линза средств отзывчива к запасу, но не к одному доходу — требование идёт за производительностью",
          (dof_more_stock > base_city + 1e-9 or base_city >= 1.0 - 1e-9)
          and abs(dof_more_income - base_city) < 1e-9,
          f"DoF {base_city:.4f} → при запасе +{prod_city:.0f}: {dof_more_stock:.4f}, "
          f"при удвоенном доходе с удвоенной производительностью: {dof_more_income:.4f}")
    v_env_zero = all(float(m.variety_counters.get("V_env", 0.0)) == 0.0
                     for m in last["measured"].values())
    research_opts = [o for o in options if ":research_tech_" in o.option_id]
    check("I2в у исследования прироста нет, и это объяснено: V_env = 0 делает ψ_var слепой к V",
          bool(research_opts) and not [o for o in research_opts if o.flat_delta()] and v_env_zero,
          f"исследований {len(research_opts)}, с приростом "
          f"{len([o for o in research_opts if o.flat_delta()])}, V_env = 0 у всех: {v_env_zero}")
    check("I3 §4.8b: τ' >= 0 у каждого кандидата (τ — самый срочный срок сущности)",
          all(bool(r["viable"]) for r in rows),
          f"неприменимых {sum(1 for r in rows if not r['viable'])}, τ={tau / 1e6:.0f} с")
    req = {o.option_id: core.requirement(o) for o in options}
    blocked = {o.option_id for o in options
               if any(req[o.option_id].get(res, 0.0) > means_last.get(res, 0.0)
                      for res in req[o.option_id])}
    barred_rs = {str(r["option_id"]) for r in rows if r["barred_by"] == "resources_ok"}
    check("I4 §4.8 отсёк ровно те опции, чей расход больше средств",
          barred_rs == blocked,
          f"отсечено {len(barred_rs)}, дороже средств {len(blocked)}, "
          f"из них без цены {len([o for o in options if not o.projected_resource_delta])}")
    check("I5 решение допустимо: у победителя нет барьера",
          winner is None or all(r["barred_by"] is None for r in rows
                                if r["option_id"] == winner.option_id))
    again = O.decide(core, st, options, ctx)[0]
    check("I6 выбор детерминирован: повтор даёт того же победителя",
          (again is None) == (winner is None)
          and (winner is None or again.option_id == winner.option_id),
          f"{again.option_id if again else 'стоять'}")
    positive = [r for r in rows
                if float(r["net_delta"]) > 0.0 and r["barred_by"] is None]
    check("I7 победитель поднимает индекс строго, иначе решает 'стоять' (§4.5)",
          (winner is None) == (not positive),
          f"допустимых кандидатов с ростом: {len(positive)}")
    h3 = L.means_with_income(stocks_last, incomes_last, horizon=3.0)
    st3 = G.state_with_measured_dof(last["state"], last["dof"])
    st3.deadlines = dict(st.deadlines)
    st3.resources = O.resource_observations(h3)
    payable3, _ = DOFCalculusCore().apply_resource_gate(st3, options)
    print(f"  сверка (горизонт средств 3 хода, НЕ объявленный): "
          f"energy={h3.get('energy', 0.0):.0f}, платёжеспособных {len(payable3)} "
          f"из {len(options)}")
    declared = [o for o in options
                if not O.is_reversible_action(o.option_id.split(":", 1)[1])]
    check("I9 объявленная необратимой опция назвала потерю и не свой путь (§4.4)",
          all(bool(o.closed) and all(str(c.get("id")) != o.act_id for c in o.closed)
              for o in declared),
          f"объявлено необратимыми {len(declared)}, названо потерь всего "
          f"{sum(len(o.closed) for o in declared)}")
    # Приобретение: почему вклад «нового юнита» невыразим — проверяем, а не утверждаем.
    probe_id = "unit_probe"
    probe_option = ActionOption(
        option_id=f"{city_id}:produce_probe",
        description="проба: прирост приписан сущности, которой в состоянии нет",
        projected_dof_delta={probe_id: 0.9},
        act_id=f"{city_id}:produce_probe",
        estimated_duration_mks=TURN_DURATION_MKS,
    )
    sim, sim_members = core.simulate(st, probe_option, ctx)
    check("I12 опция не может завести сущность: прирост несуществующей не применяется ни к кому",
          probe_id not in sim.entities and probe_id not in sim_members
          and set(sim.entities) == set(st.entities),
          f"сущностей в S' {len(sim.entities)} против {len(st.entities)} в S; "
          f"прирост к {probe_id} пропал")
    probe_lo = G.state_with_measured_dof(last["state"], {**last["dof"], probe_id: 0.9},
                                         measurements=last["measured"])
    probe_hi = G.state_with_measured_dof(last["state"], {**last["dof"], probe_id: 1.0},
                                         measurements=last["measured"])
    i_lo = core.calculate_system_dof(probe_lo, set(members) | {probe_id}, ctx)
    i_hi = core.calculate_system_dof(probe_hi, set(members) | {probe_id}, ctx)
    check("I13 прибавленная сущность индекс не поднимает: ln DoF ≤ 0, потолок — ровно ноль",
          i_lo < index and abs(i_hi - index) < 1e-9,
          f"без неё {index:.6f}; с ней при DoF 0.9 → {i_lo:.6f} (Δ {i_lo - index:+.6f}), "
          f"при DoF 1.0 → {i_hi:.6f} (Δ {i_hi - index:+.6f})")
    over_draw = ActionOption(
        option_id=f"{city_id}:produce___overdraw__",
        description="проба: объявленный расход больше средств агента",
        projected_resource_delta={city_id: {
            "energy": -(float(means_last.get("energy", 0.0)) + 1.0)}},
        requires=["energy"],
        act_id=f"{city_id}:produce___overdraw__",
        estimated_duration_mks=TURN_DURATION_MKS,
    )
    _, over_rows, _ = O.decide(core, st, [over_draw], ctx)
    barred_over = over_rows[0]["barred_by"] if over_rows else None
    check("I8 при объявленном горизонте §4.8 не отсекает ни одной постройки (платёж не больше "
          "средств), но пробу с расходом больше средств отсекает",
          not barred_rs and barred_over == "resources_ok",
          f"отсечено построек {len(barred_rs)} из {len(builds)}; барьер пробы: {barred_over}; "
          f"сверка на 3 ходах: платёжеспособных {len(payable3)}")


# ── якоря и вырожденные случаи (§4.6) ───────────────────────────────────────

def run_anchors() -> None:
    print("\n=== B/C. Якоря и вырожденные случаи (§4.6) ===")
    u = 0.5

    def psi_of(variety=None, requirements=None, constraint=None, means=None):
        obs = L.lens_observation(variety, requirements, constraint)
        return measure_entity("probe", obs, u, means or {})

    m = psi_of(variety={"V": 3, "V_env": 3})
    check("B1 V = V_env ⇒ ψ_var = 0.5", abs(m.psi["variety"] - 0.5) < 1e-12,
          f"{m.psi['variety']:.6f}")

    m = psi_of(requirements={"energy": 5.0}, means={"energy": 10.0})
    check("B2 c/C = 0.5 ⇒ ψ_opt = 0.5", abs(m.psi["options"] - 0.5) < 1e-9,
          f"{m.psi['options']:.6f} (4^-0.5)")

    m = psi_of(constraint={"F": 2, "F_env": 2})
    check("B3 F = F_env ⇒ ψ_con = 0.5", abs(m.psi["constraint"] - 0.5) < 1e-12,
          f"{m.psi['constraint']:.6f}")

    m = psi_of(variety={"V": 0, "V_env": 0})
    check("C1 V = 0 ⇒ ψ_var = 0 (а не NaN)", m.psi["variety"] == 0.0)

    m = psi_of(requirements={"energy": 5.0}, means={"energy": 0.0})
    check("C2 c_g > 0 ∧ C_g = 0 ⇒ ψ_opt = 0 (а не clamp)", m.psi["options"] == 0.0,
          "нет средств на то, что группа требует")

    m = psi_of(requirements={"energy": 0.0}, means={"energy": 0.0})
    check("C3 c_g = 0 ∧ C_g = 0 ⇒ ψ_opt = 1 (группа не ограничивает)",
          m.psi["options"] == 1.0)

    m = psi_of(constraint={"F": 0, "F_env": 0})
    check("C4 F = 0 ∧ F_env = 0 ⇒ ψ_con = 0", m.psi["constraint"] == 0.0)

    m = psi_of(variety={"V": 5, "V_env": 1}, requirements={"energy": 10.0},
               means={"energy": 10.0}, constraint={"F": 3, "F_env": 1})
    check("B4 все три линзы вместе дают произведение",
          abs(m.current_dof - m.psi["variety"] * m.psi["options"] * m.psi["constraint"]) < 1e-12,
          f"DoF={m.current_dof:.6f}")

    check("C5 ни одного NaN во всех пробах",
          all(math.isfinite(v) for v in (m.psi["variety"], m.psi["options"],
                                         m.psi["constraint"], m.current_dof)))


def run_rules() -> None:
    print("\n=== D. Объявленные правила (свёртка требований) ===")
    got = L.reduce_requirements([{"energy": 40.0}, {"energy": 10.0}])
    check("свёртка 'min' берёт требование самого дешёвого перехода",
          got["energy"] == 10.0, f"{got}")
    try:
        L.constraint_counters(("a", "b"), ("c",))
        ok = False
    except ValueError:
        ok = True
    check("заморозка вне объявленного набора — ошибка входа, а не ноль", ok)

    war = {"dipl": {"1": {"diplomatic_state": 3}}, "unit": {}}
    peace = {"dipl": {"1": {"diplomatic_state": 5}}, "unit": {}}
    check("война видна без контакта (hostile_diplo из diplomatic_state)",
          L.active_disturbances(war, "unit_113", "unit") == ["hostile_diplo"],
          "врага в поле зрения нет, а возмущение есть")
    check("союз возмущением не считается (diplomatic_state = 5)",
          L.active_disturbances(peace, "unit_113", "unit") == [])


def run_declaration() -> None:
    print("\n=== E. Объявление линейки (§3.4.1) ===")
    layer = L.spec_layer()
    print(f"  ресурсы: {[(r['id'], r['unit']) for r in layer['resources']]}")
    print(f"  группы:  {layer['groups']}   нумэрайр: {layer['numeraire']}")
    print(f"  процедуры: {layer['procedures']}")
    snaps = json.load(open(OBS_FILE))[0]
    extractor = GameStateExtractor(my_player_id=MY_PLAYER)
    state = extractor.extract(snaps["observation"], snaps["info"], snaps["turn"]).state
    menu = L.menu_by_entity(snaps["info"].get("available_actions") or {})
    bindings = {
        eid: L.lens_observation(variety=L.variety_counters(menu[eid]),
                                requirements={}, constraint=L.constraint_observation(
                                    L.entity_type_of(eid), {}))
        for eid in list(menu)[:5]
    }
    decl = L.declaration(bindings, {}, state.global_time_to_collapse_mks)
    r = decl.ruler_digest()
    d = decl.digest()
    print(f"  ruler_digest: {r}")
    print(f"  digest:       {d}")
    check("E1 два дайджеста различаются (§3.4.3)", r != d and len(r) == 64)
    decl2 = L.declaration(bindings, {}, state.global_time_to_collapse_mks)
    check("E2 дайджест воспроизводим на том же входе", decl2.ruler_digest() == r)


def run_horizon() -> None:
    """Что решает окно платёжеспособности `H` — числа, а не мнение (§4.6, `C_g`)."""
    print("\n=== F. Окно средств: что даёт город под разными H ===")
    snap = json.load(open(OBS_FILE))[0]
    obs = snap["observation"]
    costs = build_cost_index(obs)
    city = obs["city"]["121"]
    stocks = empire_stocks(obs)
    incomes = empire_incomes(obs)
    city_menu = L.menu_by_entity(snap["info"]["available_actions"]).get("city_121", [])
    reqs = city_requirements(city, costs, city_menu)
    print(f"  город: запас {stocks['energy']:.0f} щитов, доход {incomes['energy']:.0f}/ход, "
          f"требование (min по постройкам) {reqs.get('energy', 0):.0f} щитов; "
          f"стройка {city.get('production_value')} за {city.get('turns_to_prod_complete')} ход(а)")
    values: list[float] = []
    for h in (0.0, 1.0, 2.0, 3.0):
        means = L.means_with_income(stocks, incomes, horizon=h)
        obs_l = L.lens_observation(
            variety=L.variety_counters(city_menu),
            requirements=reqs,
            constraint=L.constraint_observation("city", city),
        )
        m = measure_entity("city_121", obs_l, 0.5, means)
        values.append(m.psi["options"])
        print(f"  H={h:>3.1f}  средства={means['energy']:>5.1f}  "
              f"ψ_opt={m.psi['options']:.4f}  DoF={m.current_dof:.4f}  ln={m.contribution:+.3f}")
    check("F1 ψ_opt не убывает с ростом окна средств и остаётся в [0,1]",
          all(b >= a - 1e-12 for a, b in zip(values, values[1:]))
          and all(0.0 <= v <= 1.0 for v in values),
          " → ".join(f"{v:.4f}" for v in values))


def run_recovery() -> None:
    """§4.9 в работе: город поднимается мостом, юнит — нет.

    На реальном наблюдении известных нулей не остаётся, поэтому поиск пути сам
    собой не упражняется. Здесь он упражняется **синтетикой**: та же труба, что и
    на живых данных, но DoF обнулён у города и у юнита.

    Город восстановим **чужой** дверью: исследование ведёт игрок, и оно открывает
    городу постройку, которой у него не было, — ребро идёт от игрока к городу,
    путь простой, и вердикт обязан назвать свидетеля. Собственные акты города тут
    не помогают: правило простоты пути запрещает акт на самого себя. Юнит на нуле
    не восстановим ничем — дверей, ведущих к нему, нет вовсе.
    """
    print("\n=== H. §4.9 в работе: живой ноль против мёртвого (синтетика) ===")
    snap = json.load(open(OBS_FILE))[0]
    obs, info = snap["observation"], snap["info"]
    state = GameStateExtractor(my_player_id=MY_PLAYER).extract(obs, info, snap["turn"]).state
    menu = L.menu_by_entity(info["available_actions"])
    known_gates = {tid for tid, rec in (obs.get("tech") or {}).items()
                   if isinstance(rec, dict) and L.gate_is_open(rec)}
    catalogue = L.catalogue_index(obs.get("tech") or {})
    vectors: dict[str, list[str]] = {}
    fields_of: dict[str, dict] = {}
    raw_menus: dict[str, list[str]] = {}
    for eid in sorted(menu):
        kind = L.entity_type_of(eid)
        if not menu.get(eid):
            continue
        raw = obs.get("dipl" if kind == "diplomacy" else kind, {}) or {}
        fields = raw.get(eid.split("_", 1)[1], {}) or {}
        raw_menus[eid] = menu[eid]
        vectors[eid] = L.available_vectors(kind, fields, menu[eid], known_gates,
                                           catalogue=catalogue, known_techs=known_gates)
        fields_of[eid] = fields

    city_id = next(e for e in sorted(vectors) if e.startswith("city_"))
    unit_id = next(e for e in sorted(vectors) if e.startswith("unit_"))
    player_id = f"player_{MY_PLAYER}"
    keep = (player_id, city_id, unit_id)
    dof = {player_id: 0.5, city_id: 0.0, unit_id: 0.0}
    graph = G.world_graph({k: vectors[k] for k in keep},
                          {k: fields_of[k] for k in keep}, dof,
                          catalogue=catalogue, known_techs=known_gates,
                          raw_menus={k: raw_menus[k] for k in keep})
    ctx = G.observation_context(graph, dof)
    st = G.state_with_measured_dof(state, dof)
    verdicts = G.recoverability(st, ctx)
    members, index = G.calc_and_index(st, ctx)
    city_v, unit_v = verdicts[city_id], verdicts[unit_id]
    print(f"  {city_id}: {city_v['verdict']}, свидетель {city_v['witness'][:1]}, "
          f"своих актов {len(vectors[city_id])}, допустимых увидено "
          f"{city_v['admissible_seen']}")
    print(f"  {unit_id}: {unit_v['verdict']}, своих актов {len(vectors[unit_id])}, "
          f"допустимых увидено {unit_v['admissible_seen']}")
    print(f"  в счёте: {sorted(members)}   индекс: {index:.4f}")

    # Крошечный граф, где чужой акт есть: та же машинерия, но восстановление
    # приходит от другого узла — как и требует правило простоты пути.
    helper = WorldGraph(
        entities={"a": EntityNode(id="a", current_dof=0.0),
                  "b": EntityNode(id="b", current_dof=1.0)},
        means=["energy"],
        acts=[ActEdge(id="b:revive", source="b", target="a", category="production",
                      effect={"a": 1.0}, duration_mks=TURN_DURATION_MKS)],
    )
    hv = helper.verdict("a", list(SPEC_MEANS_CLASS), 5 * TURN_DURATION_MKS, 0.0)
    print(f"  граф с чужим актом: a — {hv.verdict}, свидетель {hv.witness}")
    check("H1 город на известном нуле восстановлен чужой дверью, и свидетель назван",
          city_v["verdict"] == "reachable" and bool(city_v["witness"])
          and "->" in city_v["witness"][0],
          f"{city_v['verdict']}, свидетель {city_v['witness'][:1]}")
    check("H2 восстановленный город остался в счёте, а юнит без дверей выбыл",
          city_id in members and unit_id not in members, f"calc = {sorted(members)}")
    check("H3 к юниту не ведёт ни одна дверь — proven_unreachable без свидетеля",
          unit_v["verdict"] == "proven_unreachable" and not unit_v["witness"])
    check("H4 контроль в изоляции: чужой акт восстанавливает ноль (правило простоты пути)",
          hv.verdict == "reachable" and hv.witness == ["b:revive"],
          f"{hv.verdict}, свидетель {hv.witness}")


def main() -> int:
    steps = 1
    if "--steps" in sys.argv:
        steps = int(sys.argv[sys.argv.index("--steps") + 1])
    run_real(steps)
    run_recovery()
    run_anchors()
    run_rules()
    run_horizon()
    run_declaration()
    print(f"\nпроверок: {PASS + FAIL}, падений: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
