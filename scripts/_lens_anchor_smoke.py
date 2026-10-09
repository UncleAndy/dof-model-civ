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
    SPEC_UNKNOWN_INPUTS,
    TURN_DURATION_MKS,
)
from env.entity_extractor import GameStateExtractor  # noqa: E402
from env import spec_graph as G  # noqa: E402
from env import spec_lenses as L  # noqa: E402
from env import spec_options as O  # noqa: E402
from env import spec_unknowns as U  # noqa: E402
from env import spec_eta as E  # noqa: E402
from env import spec_threat as T  # noqa: E402
from env import spec_work as W  # noqa: E402
from env import spec_attack as A  # noqa: E402
from env import switch_channel as SC  # noqa: E402
from env import spec_settler as ST  # noqa: E402
from env import spec_risk as SK  # noqa: E402
from env import video as V  # noqa: E402
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


# ── настоящие данные: замер идёт ОДНИМ кодом для фикстуры и живого прогона ───
# Помощники замера переехали в `env/spec_obs.py`: живой прогон обязан мерить тем же кодом,
# что и прогон на записанных наблюдениях, иначе числа расходятся не по существу, а по копии.
from env.spec_obs import (  # noqa: E402
    build_cost_index,
    city_requirements,
    disturbances,
    empire_incomes,
    empire_stocks,
    powers_of,
)


def city_tiles(city_obs: dict, layers: dict) -> dict:
    """Клетки, которые город может обрабатывать, и их выход по слою карты.

    Область — `dx² + dy² ≤ city_radius_sq` (радиус² 5 → 21 клетка). Слой `output`
    осмыслен только на раскрытых клетках (§4.2), поэтому «раскрыта» = выход ≠ 0.
    """
    out, ter, extras = layers["output"], layers["terrain"], layers["extras"]
    x, y = int(city_obs["x"]), int(city_obs["y"])
    r_sq = float(city_obs.get("city_radius_sq") or 0.0)
    cells: list[dict] = []
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx * dx + dy * dy > r_sq:
                continue
            cx, cy = x + dx, y + dy
            if not (0 <= cx < len(out) and 0 <= cy < len(out[0])):
                continue
            f, s, t = (float(out[cx][cy][k] or 0.0) for k in range(3))
            if f + s + t <= 0.0 and (dx, dy) != (0, 0):
                continue                      # не раскрыта — слоя нет
            cells.append({"at": (dx, dy), "terrain": int(ter[cx][cy]),
                          "extras": [i for i, v in enumerate(extras[cx][cy] or []) if v],
                          "food": f, "shield": s, "trade": t,
                          "revealed": (f + s + t) > 0.0})
    return {"cells": cells, "radius_sq": r_sq}


def best_cell_set(cells: list[dict], channel: str, need: int,
                  centre_min: float = 1.0) -> tuple[float, list[tuple[int, int]]]:
    """Лучший набор из `need` клеток по каналу; центр — не меньше `centre_min` (§10.7.5)."""
    pool = []
    for c in cells:
        v = float(c[channel])
        if c["at"] == (0, 0):
            v = max(v, centre_min)
        pool.append((v, c["at"]))
    pool.sort(key=lambda p: (-p[0], p[1]))
    chosen = pool[:need]
    return sum(v for v, _ in chosen), [at for _, at in chosen]


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
    prev_obs_loop = None
    for snap in snaps[:steps]:
        obs, info = snap["observation"], snap["info"]
        state = extractor.extract(obs, info, snap["turn"]).state
        tech_skipped += len([e for e in state.entities if e.startswith("tech_")])
        menu = L.menu_by_entity(info.get("available_actions") or {})
        costs = build_cost_index(obs)
        # Темп науки — ИЗМЕРЕННЫЙ (§13.11): Δ накопленного (`bulbs_researched`)
        # между двумя наблюдениями. Первый ход измерить нечем — тогда дохода нет
        # (названно, а не нулём вместо неизвестного).
        means = L.means_with_income(
            empire_stocks(obs), empire_incomes(obs),
            measured_tech_rate=L.measured_science_rate(prev_obs_loop, obs, MY_PLAYER))

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
            variety = L.variety_counters(names, disturbances(obs, eid, kind), powers_of(obs))
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
        prev_obs_loop = obs

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
    # Темп науки (§13.11) — ИЗМЕРЕННЫЙ по двум последним наблюдениям прогона;
    # цена цели — из опубликованного поля записи игрока.
    prev_obs_last = snaps[steps - 2]["observation"] if steps >= 2 else None
    tech_rate = L.measured_science_rate(prev_obs_last, obs_last, MY_PLAYER)
    _players_last = obs_last.get("player") or {}
    tech_rec = (_players_last.get(str(MY_PLAYER))
                or _players_last.get(MY_PLAYER) or {})
    means_last = L.means_with_income(stocks_last, incomes_last,
                                     measured_tech_rate=tech_rate)

    def make_remeasure(cost_index):
        """Пересчёт линз на спроецированном меню **и** спроецированных средствах."""
        def remeasure(vecs, means=None):
            fresh = {}
            for eid, names in vecs.items():
                kind = L.entity_type_of(eid)
                names = list(names)
                fresh[eid] = L.lens_observation(
                    variety=L.variety_counters(names, disturbances(obs_last, eid, kind),
                                               powers_of(obs_last)),
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
                              standing=standing,
                              tech_price=tech_rec.get("researching_cost"),
                              tech_progress=tech_rec.get("bulbs_researched"),
                              tech_rate=tech_rate,
                              tech_target=tech_rec.get("researching"))
    with_delta = [o for o in options if o.flat_delta()]
    priced = [o for o in options if o.projected_resource_delta]
    unpriced = [o for o in options if o.requires and not o.projected_resource_delta]
    st.deadlines = O.budget_deadlines(deciders)
    st.resources = O.resource_observations(means_last)
    tau = min(st.deadlines.values()) if st.deadlines else None
    core = DOFCalculusCore()
    winner, rows, barred = O.decide(core, st, options, ctx)
    completeness_now = U.completeness(options)
    by_bar = collections.Counter(str(r["barred_by"]) for r in rows)
    print(f"  кандидатов {len(options)} — решающие: {', '.join(deciders)}")
    print(f"  с приростом от пересчёта: {len(with_delta)}; "
          f"с наблюдённой ценой: {len(priced)}; цена неизвестна: {len(unpriced)}")
    print(f"  средства: energy={means_last.get('energy', 0.0):.0f} "
          f"(запас {stocks_last.get('energy', 0.0):.0f} + доход "
          f"{incomes_last.get('energy', 0.0):.0f}×1 ход), τ={tau / 1e6:.0f} с")
    print(f"  гейты: {dict(by_bar)} (нет ключа None — барьеров не было)")
    print(f"  решение: {winner.option_id if winner else 'стоять'}")
    print(f"  неполнота решения (§4.7/§6.2): incomplete={completeness_now['incomplete']}; "
          + "; ".join(str(r) for r in completeness_now["reasons"]))
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
          {o.option_id for o in paid if ":produce_" in str(o.option_id)} == expect_shift and bool(builds),
          f"построек {len(builds)}, платежей, отличных от стоящего ({stand_due:.0f}): "
          f"{len(expect_shift)}, построек с приростом "
          f"{len([o for o in paid if ':produce_' in str(o.option_id)])}, "
          f"прочих с приростом {len([o for o in paid if ':produce_' not in str(o.option_id)])} (двери)")
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
    # I16: вклад клеток не объявлен — и причина измерена, а не заявлена словами.
    tiles = city_tiles(fields_last[city_id], obs_last["map"])
    need = int(fields_last[city_id].get("size") or 1) + 1
    best_f = best_cell_set(tiles["cells"], "food", need)
    best_s = best_cell_set(tiles["cells"], "shield", need)
    best_t = best_cell_set(tiles["cells"], "trade", need)
    fact = (float(fields_last[city_id].get("prod_food") or 0.0),
            float(fields_last[city_id].get("prod_shield") or 0.0),
            float(fields_last[city_id].get("prod_trade") or 0.0))
    tile_opts = [o for o in options
                 if str(o.option_id).split(":", 1)[-1].startswith(("city_work_", "city_unwork_"))]
    revealed_all = sum(1 for row in obs_last["map"]["output"] for cell in row
                       if sum(float(v or 0.0) for v in cell[:3]) > 0.0)
    check("I16 вклад клеток не объявлен, и причина измерена: слой карты не воспроизводит "
          "опубликованный выход города, обработанных клеток мир не публикует",
          bool(tile_opts) and not [o for o in tile_opts if o.flat_delta()]
          and (best_s[0] < fact[1] or best_t[0] > fact[2]),
          f"клеточных действий {len(tile_opts)}, с приростом "
          f"{len([o for o in tile_opts if o.flat_delta()])}; лучшие {need} клетки "
          f"еда {best_f[0]:.0f}{best_f[1]}/щиты {best_s[0]:.0f}{best_s[1]}/торг {best_t[0]:.0f} "
          f"против факта {fact[0]:.0f}/{fact[1]:.0f}/{fact[2]:.0f}; "
          f"клеток в области {len(tiles['cells'])}, раскрыто во всём мире {revealed_all}")
    # I17–I19: линза разнообразия получает масштаб от числа чужих держав (§4.6, объявление
    # владельца модели), поэтому открытая дверь ВХОДИТ в число, а не остаётся невидимой.
    city_names = list(last["vectors"][city_id])
    req_city = city_requirements(fields_last[city_id], costs_last, city_names,
                                 fields_last[city_id].get("prod_shield"))
    v_now = float(last["measured"][city_id].variety_counters["V"])
    v_env_now = float(last["measured"][city_id].variety_counters["V_env"])
    powers = powers_of(obs_last)

    def dof_at_v(v_names):
        binding = L.lens_observation(
            variety=L.variety_counters(v_names, disturbances(obs_last, city_id, "city"), powers),
            requirements=req_city,
            constraint=L.constraint_observation("city", fields_last[city_id]))
        return L.measure({city_id: binding}, means_last)[city_id]

    arms = {"V=1": dof_at_v(city_names[:1]),
            f"V={v_now:.0f}": dof_at_v(city_names),
            f"V={v_now + 100:.0f}": dof_at_v(city_names + [f"city_work_9_9_{i}" for i in range(100)])}
    check("I17 число векторов реакции ВХОДИТ в число: V_env = число чужих держав даёт линзе масштаб, "
          "ψ_var растёт с V",
          v_env_now > 0.0 and v_env_now == float(len(powers))
          and abs(float(arms[f"V={v_now:.0f}"].psi["variety"]) - v_now / (v_now + v_env_now)) < 1e-12
          and (float(arms["V=1"].current_dof) < float(arms[f"V={v_now:.0f}"].current_dof)
               < float(arms[f"V={v_now + 100:.0f}"].current_dof)),
          f"V_env={v_env_now:.0f} (чужих держав {len(powers)}); " + ", ".join(
              f"{k} → ψ_var {float(d.psi['variety']):.6f}, DoF {d.current_dof:.6f}"
              for k, d in arms.items()))
    check("I18 V_env берётся из мира, а не из константы: чужих держав |obs['player']| − 1",
          len(powers) == len(obs_last.get("player") or {}) - 1,
          f"держав в наблюдении {len(obs_last.get('player') or {})}, не мы: {powers} → "
          f"V_env = {v_env_now:.0f}")
    research_opts = [o for o in options if ":research_tech_" in o.option_id]
    research_paid = [o for o in research_opts if o.flat_delta()]
    check("I2в у исследования прирост есть, и он из линзы разнообразия (дверь), а не из средств",
          bool(research_opts) and bool(research_paid),
          f"исследований {len(research_opts)}, с приростом {len(research_paid)}, "
          f"пример {research_paid[0].option_id if research_paid else '—'}")
    # I19: цена двери — сверка проекции опции с формулой линзы разнообразия.
    v_city = float(len(set(city_names)))
    opened = []
    for tid in (obs_last.get("tech") or {}):
        if tid in last["known_techs"]:
            continue
        more = L.available_vectors("city", fields_last[city_id], last["raw_menus"][city_id],
                                   last["known_techs"], catalogue=last["catalogue"],
                                   known_techs=last["known_techs"] | {tid})
        k = len(set(more) - set(city_names))
        if k:
            opened.append((k, tid))
    k_best, t_best = max(opened, default=(0, None))
    opt_best = next((o for o in research_opts if str(o.option_id).endswith(f"_{t_best}")), None)
    city_gain = float(opt_best.flat_delta().get(city_id, 0.0)) if opt_best else 0.0
    dof_before = float(last["measured"][city_id].current_dof)
    ratio = (((v_city + k_best) * (v_city + v_env_now))
             / (v_city * (v_city + k_best + v_env_now))) if k_best else 1.0
    expect = dof_before * (ratio - 1.0)
    ln_gain = (math.log1p(k_best / v_city) - math.log1p(k_best / (v_city + v_env_now))) if k_best else 0.0
    check("I19 цена открытой двери равна изменению DoF города — проекция совпадает с формулой линзы",
          k_best > 0 and opt_best is not None and abs(city_gain - expect) < 1e-12,
          (f"технология {t_best} открывает {k_best} дверей → город {city_gain:+.6f} против "
           f"формулы {expect:+.6f}; в логарифмах (это и читает ядро) {ln_gain:+.6f}; "
           f"прирост опции целиком {min(opt_best.flat_delta().values()):+.6f}"
           if opt_best is not None and opt_best.flat_delta()
           else f"опции с технологией {t_best} нет"))
    # I20 (§4.7/§6.2): решение объявлено неполным, и это поле отчёта, а не вход в счёт.
    # Список неразрешённых входов сравнивается с ОБЪЯВЛЕННЫМ набором (`env.config.SPEC_UNKNOWN_INPUTS`),
    # а не с одним именем: добавление объявленного входа — не поломка проверки, а её вход.
    check("I20 решение объявлено неполным, и это не двигает числа: ни один объявленный неизвестный вход "
          "не разрешён кандидатами (§6.2), `t_m` не объявлен (§4.7)",
          bool(completeness_now["incomplete"])
          and completeness_now["binding"] == [str(i["id"]) for i in SPEC_UNKNOWN_INPUTS]
          and not any(bool(r["used_estimated"]) for r in completeness_now["unknown_resources"])
          and not any(str(i["id"]) in str(row) for i in SPEC_UNKNOWN_INPUTS for row in rows),
          f"incomplete={completeness_now['incomplete']}, не разрешено: "
          f"{completeness_now['binding']}, причин {len(completeness_now['reasons'])}; "
          f"опций, называющих вход в `discovers`: "
          f"{sum(1 for o in options if (o.discovers or []))}; "
          f"в строках кандидатов флаг не встречается")
    # I21 (§13.11): платёж исследования объявлен по опубликованной цене цели и
    # ИЗМЕРЕННОМУ темпу, а не оставлен молчанием; при неизмеримом темпе — молчит
    # названно (это незнание, а не «бесплатно»).
    tech_opts = [o for o in options if ":research_tech_" in str(o.option_id)]
    drawn = [o for o in tech_opts if o.projected_resource_delta]
    price = tech_rec.get("researching_cost")
    progress = tech_rec.get("bulbs_researched") or 0.0
    if tech_rate is None:
        ok21 = not drawn
        detail21 = ("темп не измерен (наблюдений меньше двух) — платёж не объявлен у "
                    f"{len(tech_opts)} опций исследования")
    else:
        if price is not None:
            expected = min(max(float(price) - float(progress), 0.0),
                           float(tech_rate) * SPEC_MEANS_HORIZON_TURNS)
        else:
            expected = float(tech_rate) * SPEC_MEANS_HORIZON_TURNS
        if expected <= 0.0:
            # Темп 0 (наблюдения не растут — свойство этого фикстура, а не мира):
            # в горизонт платить нечего, и это объявлено нулём, а не умолчанием.
            ok21 = not drawn
            detail21 = (f"цена цели {price}, накоплено {progress:g}, темп "
                        f"{tech_rate:g} → платёж в горизонт 0; опций с платежом "
                        f"{len(drawn)} (ожидается 0)")
        else:
            ok21 = bool(drawn) and all(
                any(abs(float(-(v or {}).get("tech", 0.0)) - expected) < 1e-9
                    for v in (o.projected_resource_delta or {}).values())
                for o in drawn)
            detail21 = (f"цена цели из поля {price}, накоплено {progress:g}, темп "
                        f"{tech_rate:g} → платёж {expected:g}; с платежом {len(drawn)} "
                        f"из {len(tech_opts)} опций исследования")
    check("I21 §13.11: платёж исследования — из опубликованной цены цели и "
          "ИЗМЕРЕННОГО темпа (Δ накопленного)", ok21, detail21)
    # I22: положительный контроль на числах ЖИВОГО замера (стенд 2026-10-06) —
    # иначе «платёж не объявлен» неотличимо от «платёж посчитан по нулевому темпу».
    live_due = O.resource_draw("player_0", "research_tech_Monarchy_2", None,
                               None, 1.0, tech_price=28.0, tech_progress=0.0,
                               tech_rate=1.0, tech_target="2")
    live_due_done = O.resource_draw("player_0", "research_tech_Monarchy_2", None,
                                    None, 1.0, tech_price=28.0, tech_progress=27.0,
                                    tech_rate=1.0, tech_target="2")
    live_due_other = O.resource_draw("player_0", "research_tech_Rocketry_70", None,
                                     None, 1.0, tech_price=28.0, tech_progress=0.0,
                                     tech_rate=1.0, tech_target="2")
    due_of = lambda d: float(-(d.get("player_0") or {}).get("tech", 0.0))  # noqa: E731
    check("I22 положительный контроль: на живом замере (цена 28, темп 1, H=1) платёж "
          "цели равен 1 колбе, у почти готовой — тоже 1, у чужой технологии — темп",
          due_of(live_due) == 1.0 and due_of(live_due_done) == 1.0
          and due_of(live_due_other) == 1.0,
          f"цель с нуля {due_of(live_due)}, почти готовая {due_of(live_due_done)}, "
          f"не-цель {due_of(live_due_other)}")
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
    # Срок постройки — из измеренного, в объявленном порядке источников
    # (§10.76–10.78 ветки v2). Текущее производство мир публикует; для НОВОГО
    # варианта публикации нет, и срок выводится из измеренных цены и щитов.
    eta_here, eta_src = E.build_eta(
        stock=city.get("shield_stock"),
        shields_per_turn=city.get("prod_shield"),
        published=city.get("turns_to_prod_complete"))
    new_variant = next((name[len("produce_"):] for name in city_menu
                        if name.startswith("produce_")
                        and costs.get(name[len("produce_"):]) is not None), None)
    if new_variant is not None:
        eta_new, src_new = E.build_eta(price=costs.get(new_variant),
                                       stock=city.get("shield_stock"),
                                       shields_per_turn=city.get("prod_shield"))
    else:
        eta_new, src_new = None, "unknown"
    print(f"  срок постройки: текущая {eta_here} ({eta_src}); новый вариант "
          f"{new_variant}: цена {costs.get(new_variant)} при "
          f"{city.get('prod_shield')} щитов/ход → {eta_new} ({src_new})")
    live_eta = E.build_eta(price=20.0, stock=0.0, shields_per_turn=7.0)
    pub_eta = E.build_eta(price=20.0, stock=0.0, shields_per_turn=7.0, published=2.0)
    mean_eta = E.build_eta(price=None, shields_per_turn=7.0, known_etas=[2.0, 4.0])
    none_eta = E.build_eta(price=None, shields_per_turn=0.0)
    check("I23 срок постройки: текущее производство — по публикации мира, новый вариант — "
          "выводом из цены и щитов (§10.76–10.78 из v2)",
          (eta_here is None or eta_src in E.ETA_SOURCES)
          and (new_variant is None or (eta_new is not None
                                       and src_new == "derived_price_shields")),
          f"текущая {eta_here} ({eta_src}), новый {new_variant}: {eta_new} ({src_new})")
    check("I24 положительный контроль (живые числа: цена 20, 7 щитов/ход): выведенный срок 3 хода; "
          "публикация 2 берёт верх; без цены — среднее 3; измерять нечем — None, а не ноль",
          live_eta == (3.0, "derived_price_shields") and pub_eta == (2.0, "published_current")
          and mean_eta == (3.0, "estimated_mean") and none_eta == (None, "unknown"),
          f"выведенный {live_eta}, публикация {pub_eta}, среднее {mean_eta}, нечем {none_eta}")
    # ── угроза и источник коллапса (§10.70–10.75 из v2) ──────────────────────
    vendor_dx = [-1, 0, 1, -1, 1, -1, 0, 1]
    vendor_dy = [-1, -1, -1, 0, 0, 1, 1, 1]
    check("I25 геометрия шага: `goto_N`/`attack_N` — ОДИН шаг dir8, таблица совпадает с "
          "вендорскими DIR_DX/DIR_DY (map_const.py:60-61) и с замером v2",
          [d[0] for d in T.DIR8_OFFSETS] == vendor_dx
          and [d[1] for d in T.DIR8_OFFSETS] == vendor_dy
          and T.step(25, 43, 0) == (24, 42) and T.step(25, 43, 7) == (26, 44)
          and T.adjacent((25, 43), (26, 44)) and not T.adjacent((25, 43), (27, 45)),
          f"dir0 {T.step(25, 43, 0)}, dir7 {T.step(25, 43, 7)}")
    foes_real = T.foreign_units_from_map(obs, MY_PLAYER)
    fake_map = {"map": {"unit_owner": [[255] * 4, [255, 1, 255, 255], [255, 255, 0, 255]]}}
    foes_fake = T.foreign_units_from_map(fake_map, MY_PLAYER)
    check("I26 канал видимости: на реальном срезе чужих на карте нет; положительный контроль "
          "на синтетической карте ловит чужого с координатами",
          foes_real == [] and foes_fake == [(1, 1, 1)],
          f"реальных чужих {len(foes_real)}, на синтетической карте {foes_fake}")
    mean_atk, n_atk = T.mean_attack(obs, MY_PLAYER)
    check("I27 чужой без паспорта: сила — средним по ПУБЛИКУЕМОМУ каталогу типов, а не по одним "
          "своим юнитам и не нулём; усреднять нечего — None, а не ноль",
          mean_atk is not None and mean_atk > 5.0 and n_atk >= 48
          and T.mean_attack({"unit": {}}, MY_PLAYER) == (None, 0)
          and T.mean_attack({"unit": {"1": {"type_attack_strength": 0}}}, MY_PLAYER) == (0.0, 1),
          f"средняя атака {mean_atk:.2f} по {n_atk} известным типам (каталог спек: 48 записей, "
          f"средняя 7.02, боевых 38; по одним своим юнитам было бы 0.0 на 4)")

    def _grid(size: int = 50) -> list:
        return [[255] * size for _ in range(size)]

    prev_slice = {"unit": {"1": {"owner": 0, "health": 20, "x": 25, "y": 43}},
                  "city": {"121": {"owner": 0, "x": 25, "y": 43}}}
    lost_map = _grid(); lost_map[26][43] = 1          # чужой вплотную, юнит исчез
    blind_map = _grid()                                # юнит исчез, соседа не видно
    wound_map = _grid(); wound_map[24][43] = 2         # чужой с другой стороны, ранение
    cur_lost = {"unit": {}, "city": {"121": {"owner": 0, "x": 25, "y": 43}},
                "map": {"unit_owner": lost_map}}
    cur_blind = {"unit": {}, "city": {"121": {"owner": 0, "x": 25, "y": 43}},
                 "map": {"unit_owner": blind_map}}
    cur_wound = {"unit": {"1": {"owner": 0, "health": 4, "x": 25, "y": 43}},
                 "city": {"121": {"owner": 0, "x": 25, "y": 43}},
                 "map": {"unit_owner": wound_map}}
    atk_vis = T.observed_attack(prev_slice, cur_lost, MY_PLAYER)
    atk_blind = T.observed_attack(prev_slice, cur_blind, MY_PLAYER)
    atk_self = T.observed_attack(prev_slice, cur_lost, MY_PLAYER, consumed_by_us=["1"])
    atk_wound = T.observed_attack(prev_slice, cur_wound, MY_PLAYER)
    kept, dropped = T.counted(["player_0", "unit_1", "player_1"], ["unit_1"])
    check("I28 нападение — только по наблюдённому (синтетика, названа так и есть): потеря рядом "
          "с видимым чужим = нападение с нападавшим; без видимого соседа = «не наблюдён»; "
          "наша постройка города = не нападение; падение здоровья = нападение",
          atk_vis["attacked"] and atk_vis["attackers"] == [(1, 26, 43)]
          and atk_blind["attacked"] and atk_blind["attackers"] == []
          and not atk_self["attacked"]
          and atk_wound["attacked"] and atk_wound["attackers"] == [(2, 24, 43)]
          and kept == ["player_0", "player_1"]
          and dropped == [("unit_1", "его возможности не наши")],
          f"видимый {atk_vis['attackers']}, слепой {atk_blind['attackers']}, "
          f"своё действие {atk_self['attacked']}, ранение {atk_wound['attackers']}, "
          f"счёт {len(kept)} оставлено / {len(dropped)} исключено")
    check("I29 признак источника держится весь срок прогноза (20 ходов), а не один ход",
          T.COLLAPSE_HORIZON == 20 and atk_vis["hold_turns"] == 20,
          f"COLLAPSE_HORIZON={T.COLLAPSE_HORIZON}, в событии {atk_vis['hold_turns']}")
    # ── §10.88/§10.102: цена отказа от постройки и пустое окно меню ───────────
    real_gain = float(city.get("prod_shield") or 0.0)
    real_eta = eta_here if eta_here is not None else 2.0
    sw_ref = E.switch_cost_shields(net_shield_gain=real_gain, current_eta=real_eta)
    sw_meas = E.switch_cost_shields(lost_shields=5.0, net_shield_gain=real_gain,
                                    current_eta=real_eta)
    sw_same = E.switch_cost_shields(same_variant=True)
    sw_none = E.switch_cost_shields(lost_shields=None, loss_median=None)
    check("I30 цена отказа от начатой постройки (§10.102): величина — ИЗМЕРЕННЫЕ щиты (ссылка v2: "
          "медиана 3); доля срока — из прироста щитов и срока; тот же вариант — 0; мерить нечем — "
          "None С ПРИЧИНОЙ, а не молча",
          sw_ref[0] == 3.0 and abs(sw_ref[1] - min(1.0, 3.0 / real_gain / real_eta)) < 1e-9
          and sw_meas[0] == 5.0 and sw_same == (0.0, 0.0, "вариант тот же — терять нечего")
          and sw_none[0] is None and "не измерена" in sw_none[2],
          f"ссылка {sw_ref[0]:g} щитов → доля {sw_ref[1]:.3f}; замер 5 → {sw_meas[1]:.3f}; "
          f"тот же вариант {sw_same[0]:g}; нечем {sw_none[0]}")
    check("I31 пустое окно меню — не измерение, а помеха (§10.88: 187 из 2514 записей, 7.4 %)",
          E.menu_is_measured(city_menu) and not E.menu_is_measured([]),
          f"меню города: переходов {len(city_menu)}; пустое окно измерением не считается")
    # ── §10.102, правка (1): потеря при смене варианта — в расход §4.8 ────────
    ref_loss = 3.0                                   # ссылка v2: медиана 3 (80 наблюдений)
    lost_same = O.switch_loss_for("Workers", "Workers", ref_loss)
    lost_off = O.switch_loss_for("Workers", "Barracks", ref_loss)
    lost_unknown = O.switch_loss_for("Workers", None, ref_loss)
    lost_unmeasured = O.switch_loss_for("Workers", "Barracks", None)
    draw_base = O.resource_draw("city_121", "produce_Workers", costs, 7.0, 1.0)
    draw_switch = O.resource_draw("city_121", "produce_Workers", costs, 7.0, 1.0,
                                  switch_loss_shields=ref_loss, current_item="Barracks")
    draw_same = O.resource_draw("city_121", "produce_Workers", costs, 7.0, 1.0,
                                switch_loss_shields=ref_loss, current_item="Workers")
    check("I32 смена варианта постройки (§10.102, правка (1) владельца модели): разовая потеря "
          "вложенных щитов входит в расход §4.8 ТОЛЬКО при смене; тот же вариант и неназванный "
          "текущий — нулевая потеря С ПРИЧИНОЙ, а не молча",
          lost_same == (0.0, "вариант тот же — терять нечего")
          and lost_off[0] == 3.0 and "разово" in lost_off[1]
          and lost_unknown[0] == 0.0 and "не назван" in lost_unknown[1]
          and lost_unmeasured[0] == 0.0 and "не измерена" in lost_unmeasured[1]
          and draw_switch["city_121"]["energy"] == draw_base["city_121"]["energy"] - 3.0
          and draw_same["city_121"]["energy"] == draw_base["city_121"]["energy"],
          f"платёж {draw_base['city_121']['energy']:g} щитов → при смене "
          f"{draw_switch['city_121']['energy']:g}, при удержании {draw_same['city_121']['energy']:g}; "
          f"текущий не назван → {lost_unknown[1][:44]}…")
    # ── §10.116/§10.117: работа, прерывание, дисконт постоянного актива ───────
    w_hidden = W.work_continues_without_menu(False, True)
    w_absent = W.work_continues_without_menu(False, False)
    w_visible = W.work_continues_without_menu(True, False)
    i_ok = W.interrupted_by_real_departure(True, False, False)
    i_moved = W.interrupted_by_real_departure(True, True, False)
    check("I33 «действия нет в меню» ≠ «работа отпала» (§10.117): работа идёт, если действие "
          "скрыто, а extras изменились; прерывание — только реальный уход актора",
          w_hidden[0] and not w_absent[0] and not w_visible[0]
          and not i_ok[0] and i_moved[0] and "по делу" in i_moved[1],
          f"скрыто+extras {w_hidden[0]}, скрыто без изменений {w_absent[0]}, "
          f"в меню {w_visible[0]}; актор на месте {i_ok[0]}, сдвинулся {i_moved[0]}")
    # Ценность города-творца: сверка с ЗАПИСАННЫМИ числами v2 (валюта та — ln DoF, и это
    # названо: считаем их числа, чтобы проверить перенесённую ФОРМУ, а не свою валюту).
    # §10.116: принята форма `ln(DoF создаваемого города) × frac`; вариант БЕЗ frac был
    # ИСПЫТАН И ОТВЕРГНУТ (поднял поселенца над воином и вытеснил военную постройку
    # целиком: A 0 военных, выжил 5/10 против B 8/10, медиана −8).
    frac_old, _ = W.horizon_discount(38.0, 5.2)
    settler_old = math.log(13.0) * frac_old                      # старая форма v2 (по типу юнита)
    warrior_old = math.log(9.0) * W.horizon_discount(5.0, 5.2)[0]
    city_dof_v2 = 22.0                                          # DoF создаваемого города (замер v2)
    rejected_val, why_rejected = W.city_maker_value_without_discount(city_dof_v2)
    accepted_val, why_accepted = W.city_maker_value(city_dof_v2, 38.0, 5.2)
    at7, _ = W.city_maker_value(city_dof_v2, 7.0, 5.2)
    at8, _ = W.city_maker_value(city_dof_v2, 8.0, 5.2)
    check("I34 ценность города-творца — ПРИНЯТАЯ форма v2 `ln(DoF города) × frac`, а не «без дисконта» "
          "(абляция §10.116 отвергнута); форма воспроизводит записанные числа v2, включая порог eta ≈ 7",
          abs(settler_old - 0.352) < 0.002 and abs(warrior_old - 2.197) < 0.002
          and abs(rejected_val - 3.091) < 0.002 and "отвергнута" in why_rejected
          and abs(accepted_val - 0.423) < 0.002 and "×" in why_accepted
          and at7 > warrior_old > at8,
          f"принятая форма при eta 38: {accepted_val:.3f}; отвергнутая абляция: {rejected_val:.3f} "
          f"(её число в v2 — 3.091, и оно НЕ принято); у крупного города eta 7 → {at7:.3f} > воина "
          f"{warrior_old:.3f} > eta 8 → {at8:.3f} (порог «eta ≤ 7» из записей v2 воспроизведён)")
    spec_workers = None
    for tech in (obs.get("tech") or {}).values():
        for sp in (tech.get("sup_units") or []):
            if isinstance(sp, dict) and sp.get("name") == "Workers":
                spec_workers = sp
                break
    cc_real, why_cc = W.creates_city(spec_workers or {})
    cc_named, _ = W.creates_city({"build_city": True})
    cc_text, _ = W.creates_city({"flags": "CityFound"})
    check("I35 тип определяется СПОСОБНОСТЬЮ, а не именем (§10.116): названная способность и "
          "строковые flags читаются; позиционный массив flags — НЕ читается (None с причиной), "
          "а не «способности нет»",
          cc_real is None and "позиционный" in why_cc
          and cc_named is True and cc_text is True,
          f"на реальном паспорте `Workers`: {cc_real} ({why_cc[:46]}…); именованная {cc_named}, "
          f"строковая {cc_text}")
    # ── §10.67/§10.105: рост набора возможностей, коридор путей, отсечка фронтира ──
    real_size = city.get("size")
    grow_ref = W.growth_raises_capability(real_size)
    grow_missing = W.growth_raises_capability(7)
    grows = [W.growth_raises_capability(s)[0] for s in (1, 2, 3)]
    check("I36 набор возможностей города растёт с размером (§10.67): измеренные медианы 4 → 5 → 9; "
          "размер вне замера — None С ПРИЧИНОЙ, а не нулём и не средним; закрытое окно съёмки "
          "отсекается тем же правилом, что пустое меню",
          grows == [4.0, 5.0, 9.0] and None not in grows
          and grow_missing[0] is None and "не измерен" in grow_missing[1]
          and not E.menu_is_measured([]),
          f"город на съёмке размера {real_size}: {grow_ref[0]} переходов по ссылке v2 — но у нас "
          f"ДРУГОЙ счётчик (векторов {len(city_menu)}); размер 7 → {grow_missing[0]} "
          f"({grow_missing[1][:34]}…)")
    corr_hit = W.paths_limited_by_corridor(10, 2, 2)
    corr_free = W.paths_limited_by_corridor(10, 2, 200)
    front_hit = W.frontier_cutoff_denies_goal(20.0, 12.0)
    front_free = W.frontier_cutoff_denies_goal(20.0, None)
    check("I37 два артефакта «эпохи одного действия» (§10.105): предел коридора не даёт ходить всем, "
          "у кого есть цель (замер: 10 целей, 2 пути при пределе 2); порог фронтира лишает цели "
          "движения, хотя движение к нераскрытой клетке — единственный источник нового DoF",
          corr_hit[0] and not corr_free[0] and front_hit[0] and not front_free[0],
          f"коридор при пределе 2 {corr_hit[0]} / при 200 {corr_free[0]}; фронтир при пороге 12 "
          f"{front_hit[0]} / без порога {front_free[0]}")
    # ── Порт из v2: наблюдение нападения (brain/v2/attack.py) ────────────────
    # (1) ЖИВЫЕ данные: обходим съёмку по шагам и смотрим, что видит правило.
    steps = json.load(open("tests/fixtures/real_obs_01.json"))
    real_tracker = A.AttackTracker(my_player_id=int(city.get("owner", 0) or 0))
    real_events = []
    for i, rec in enumerate(steps):
        ob = rec.get("observation") if isinstance(rec, dict) else None
        if not isinstance(ob, dict):
            continue
        real_events.append(real_tracker.observe(ob, rec.get("turn", i + 1)))
    real_attacked = [e for e in real_events if e.get("attacked")]
    # (2) ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ на синтетике: правило должно СРАБАТЫВАТЬ, иначе
    # «нападений нет» на живых данных ничего не доказывает.
    def _mk_map(own_cells):
        grid = [[255] * 4 for _ in range(4)]
        for (ax, ay), aown in own_cells.items():
            grid[ax][ay] = aown          # порядок слоя — [x][y], измерен (§13.99)
        return grid

    base_unit = {"5": {"owner": 0, "x": 1, "y": 1, "health": 10}}
    our_city = {"121": {"owner": 0, "x": 2, "y": 2}}
    prev_s = {"unit": base_unit, "city": our_city, "map": {"unit_owner": _mk_map({})}}
    cur_hit = {"unit": {}, "city": our_city, "map": {"unit_owner": _mk_map({(1, 2): 3})}}
    cur_fog = {"unit": {}, "city": our_city, "map": {"unit_owner": _mk_map({})}}
    cur_wound = {"unit": {"5": {"owner": 0, "x": 1, "y": 1, "health": 6}}, "city": our_city,
                 "map": {"unit_owner": _mk_map({(1, 2): 3})}}
    hit_tr = A.AttackTracker(my_player_id=0)
    hit_tr.observe(prev_s, 5)
    hit_ev = hit_tr.observe(cur_hit, 6)
    fog_tr = A.AttackTracker(my_player_id=0)
    fog_tr.observe(prev_s, 5)
    fog_ev = fog_tr.observe(cur_fog, 6)
    own_tr = A.AttackTracker(my_player_id=0)
    own_tr.observe(prev_s, 5)
    own_tr.note_choice("5", "build_city")
    own_ev = own_tr.observe(cur_hit, 6)
    wnd_tr = A.AttackTracker(my_player_id=0)
    wnd_tr.observe(prev_s, 5)
    wnd_ev = wnd_tr.observe(cur_wound, 6)
    first_tr = A.AttackTracker(my_player_id=0)
    first_tr.prev = {}
    first_ev = first_tr.observe(cur_hit, 1)
    class _E:                      # сущность-заглушка: ядро принимает присваивание поля
        def __init__(self): self.is_collapse_source = False
    ents = {"player_3": _E(), "player_0": _E()}
    applied = hit_tr.apply(ents, 6)
    held, released = hit_tr.marks.is_source("player_3", 25), hit_tr.marks.is_source("player_3", 26)
    check("I38 наблюдение нападения — порт `v2` на ЖИВЫХ данных: правило обходит съёмку по шагам и "
          "не выдумывает нападений там, где мир их не показывал",
          len(real_events) >= 9 and not real_attacked
          and all(e.get("attacked") is False for e in real_events[1:]),
          f"шагов пройдено {len(real_events)}, нападений {len(real_attacked)}; последнее: "
          f"{real_events[-1].get('reason') if real_events else '—'}")
    check("I39 правило нападения СРАБАТЫВАЕТ, когда нападение наблюдено: видимый чужой на смежной "
          "клетке → метка на владельца; нет видимого — виновный не назначается; исчезновение по "
          "нашему действию нападением не считается; ход 1 не сравнивается; признак держится 20 ходов",
          hit_ev.get("attacked") and hit_ev.get("marked") == ["player_3"]
          and fog_ev.get("attacked") and not fog_ev.get("marked")
          and not own_ev.get("attacked")
          and wnd_ev.get("attacked") and wnd_ev.get("marked") == ["player_3"]
          and not first_ev.get("attacked") and "начало партии" in str(first_ev.get("reason"))
          and applied == ["player_3"] and ents["player_3"].is_collapse_source
          and not ents["player_0"].is_collapse_source
          and held and not released,
          f"нападение {hit_ev.get('attacked')} метка {hit_ev.get('marked')}; вслепую "
          f"{fog_ev.get('attacked')}/{fog_ev.get('marked')}; своё действие {own_ev.get('attacked')}; "
          f"ранение {wnd_ev.get('marked')}; ход 1 {first_ev.get('attacked')}; "
          f"держится до 25 {held}, на 26 {released}")
    # ── §10.102 канал `produce_switch` (порт из v2) ─────────────────────────
    sw_rows = [SC.make_row(turn=5, city="121", switched=True, lost=3,
                           stock_before=20, stock_after=17, current="Workers", chosen="Barracks"),
               SC.make_row(turn=6, city="121", switched=True, lost=5,
                           stock_before=22, stock_after=17, current="Barracks", chosen="Workers"),
               SC.make_row(turn=7, city="121", switched=True, lost=0,
                           stock_before=17, stock_after=17, current="Workers", chosen="Barracks"),
               SC.make_row(turn=8, city="121", switched=False, lost=7,
                           stock_before=24, stock_after=17)]
    sw_med, sw_n, sw_why = SC.measured_loss(sw_rows)
    sw_none, sw_n0, sw_why0 = SC.measured_loss([])
    drop, why_drop = SC.loss_from_stock(20, 17)
    grow, why_grow = SC.loss_from_stock(17, 20)
    blind, why_blind = SC.loss_from_stock(None, 17)
    r_ok, why_r_ok = SC.observe(turn=9, city="121", stock_before=20, stock_after=17,
                                current="Workers", chosen="Barracks")
    r_same, why_r_same = SC.observe(turn=9, city="121", stock_before=20, stock_after=17,
                                    current="Workers", chosen="Workers")
    r_anon, why_r_anon = SC.observe(turn=9, city="121", stock_before=20, stock_after=17,
                                    current=None, chosen="Barracks")
    check("I40 канал смены производства (§10.102, порт `produce_switch` из v2): потеря — падение "
          "запаса щитов; медиана только по ОБЪЯВЛЕННЫМ сменам и только положительная; нули, рост "
          "запаса и ненаблюдённый запас её не двигают; нечего усреднять — None С ПРИЧИНОЙ",
          sw_med == 4.0 and sw_n == 2 and "объявленным сменам" in sw_why
          and sw_none is None and sw_n0 == 0 and "ещё не измерена" in sw_why0
          and drop == 3.0 and "упал" in why_drop
          and grow == 0.0 and "не упал" in why_grow
          and blind is None and "не наблюдён" in why_blind
          and r_ok is not None and r_ok["lost"] == 3.0
          and r_same is None and "тот же" in why_r_same
          and r_anon is None and "не назван" in why_r_anon,
          f"медиана {sw_med:g} по {sw_n} сменам (нули и необъявленные не считаны); падение 20→17 "
          f"{drop:g}; рост {grow:g}; вслепую {blind}; строка смены {(r_ok or {}).get('lost')}")
    # Проводка (I41): заявка раннера закрывается ФАКТОМ мира; цена идёт в опции; корпус — во временный файл.
    import pathlib as _pl
    import tempfile as _tf
    ex = GameStateExtractor(my_player_id=MY_PLAYER)
    _tmp_dir = _tf.TemporaryDirectory()
    _tmp = _pl.Path(_tmp_dir.name) / "switch.jsonl"
    _saved_path = SC.DEFAULT_PATH
    SC.DEFAULT_PATH = _tmp
    try:
        ex._last_shield_stock = {"121": 20.0}
        ex.note_switch("Barracks", city="121", current="Workers")
        ex._close_pending_switches({"city": {"121": {"shield_stock": 17}}}, 7)
        ex._last_shield_stock = {"121": 24.0}
        ex.note_switch("Workers", city="121", current="Workers")     # заявки нет: вариант тот же
        ex._close_pending_switches({"city": {"121": {"shield_stock": 17}}}, 8)
        ex._last_shield_stock = {"121": 24.0}
        ex._close_pending_switches({"city": {"121": {"shield_stock": 17}}}, 9)   # падение без заявки
        sw_shields, sw_seen, sw_why2 = ex.switch_loss_shields()
        sw_on_disk = SC.load(path=_tmp)
    finally:
        SC.DEFAULT_PATH = _saved_path
        _tmp_dir.cleanup()
    price_hold, why_hold = O.switch_loss_for("Barracks", "Workers", sw_shields)
    check("I41 канал связан с ценой (§10.102): строка канала появляется только по ЗАЯВЛЕННОЙ смене, "
          "величину даёт мир (падение запаса), падение щитов без заявки и «тот же вариант» строки не "
          "дают; измеренная медиана идёт входом в `switch_loss_for` для опций постройки",
          sw_shields == 3.0 and sw_seen == 1 and len(sw_on_disk) == 1
          and sw_on_disk[0]["lost"] == 3.0 and sw_on_disk[0]["chosen"] == "Barracks"
          and price_hold == 3.0 and "разово" in why_hold,
          f"строк канала {len(ex.switch_rows)}, на диске {len(sw_on_disk)}, медиана {sw_shields} по "
          f"{sw_seen}; цена смены в опции {price_hold:g} щитов")
    check("I42 пустой канал даёт цену нулём С ПРИЧИНОЙ, а не выдуманной величиной: пока смена не "
          "измерена, `switch_loss_for` не начисляет потерь и говорит, почему",
          SC.measured_loss([])[0] is None and SC.measured_loss([])[2]  # причина названа
          and O.switch_loss_for("Barracks", "Workers", None)[0] == 0.0
          and "не измерена" in O.switch_loss_for("Barracks", "Workers", None)[1],
          f"пустой канал → {SC.measured_loss([])[0]}; цена без замера "
          f"{O.switch_loss_for('Barracks', 'Workers', None)[0]:g}")
    # ── §10.116/§10.108: семейство ценности города-творца (порт из v2) ──────
    fam_val, fam_why = ST.city_maker_value(22.0, 38.0, 5.2)
    fam7, _ = ST.city_maker_value(22.0, 7.0, 5.2)
    fam_switch, fam_sw_why = ST.city_maker_value(22.0, 38.0, 5.2, switch_loss=3.0)
    norm_val, why_norm = ST.city_maker_value(0.42, 38.0, 5.2)
    rejected, why_rej = ST.city_maker_value_rejected(22.0)
    check("I43 ценность города-творца (§10.116) — принятая форма `ln(счёт) × frac × cover − C_pop "
          "− цена_смены`, НЕ «без frac»; нормированный DoF отвергается С ПРИЧИНОЙ (ln ≤ 0 дал бы "
          "премию за отказ от постройки); числа сходятся с записями v2",
          abs(fam_val - 0.423) < 0.002 and "frac 0.137" in fam_why
          and abs(fam7 - 2.296) < 0.002
          and abs(fam_switch - (fam_val - 3.0)) < 1e-9 and "цена смены −3" in fam_sw_why
          and norm_val is None and "нормированный" in why_norm
          and abs(rejected - 3.091) < 0.002 and "отвергнута" in why_rej,
          f"при eta 38: {fam_val:.3f} (v2: 0.423), при eta 7: {fam7:.3f} (> воина 2.197); со сменой "
          f"{fam_switch:.3f}; нормированный DoF → {norm_val}; отвергнутая форма {rejected:.3f}")
    pop_exact, why_pop = ST.population_cost(3, {1: 4.0, 3: 9.0})
    pop_mean, why_mean = ST.population_cost(3, {1: 4.0, 5: 9.0})
    pop_none, why_pop_none = ST.population_cost(3, None)
    pop_edge, why_edge = ST.population_cost(1, {1: 4.0, 3: 9.0})
    cover_risk, why_cover = ST.cover_factor(2.0, 10.0)
    cover_blind, why_blind = ST.cover_factor(None, 10.0)
    cover_floor, _ = ST.cover_factor(20.0, 10.0)
    sp_near, _ = ST.spacing_factor(1.0)
    sp_far, _ = ST.spacing_factor(6.0)
    sp_mid, _ = ST.spacing_factor(3.5)
    unc, why_unc = ST.uncrowding_gain(2.0, 5.0)
    dist_wrap = ST.torus_distance(0, 0, 79, 0, xsize=80)
    check("I44 множители семейства (§10.108, §10.116): цена жителя по размеру города (неизмеренный "
          "размер — СРЕДНЕЕ по известным, а не ноль); город нулевого размера не даёт цены жителя; "
          "прикрытие ×1, пока риск не измерен; близость к городу структурна (1 → 0, 6 → 1); уход "
          "даёт ln отношения; дистанция по X тороидальная",
          abs(pop_exact - 0.8109) < 0.002 and "измерен" in why_pop
          and abs(pop_mean - 0.4855) < 0.002 and "среднее по известным" in why_mean
          and pop_none == 0.0 and "не измерен" in why_pop_none
          and pop_edge == 0.0 and "не видно" in why_edge
          and abs(cover_risk - 0.8) < 1e-9 and "1 − риск 2/индекс 10" in why_cover
          and cover_blind == 1.0 and "не измерен" in why_blind and cover_floor == 0.0
          and sp_near == 0.0 and sp_far == 1.0 and abs(sp_mid - 0.5) < 1e-9
          and abs(unc - 1.3863) < 0.002 and dist_wrap == 1.0,
          f"цена жителя {pop_exact:.4f} / по среднему {pop_mean:.4f} / нет данных {pop_none:g}; "
          f"прикрытие {cover_risk:.2f} / вслепую {cover_blind:.2f} / в полу {cover_floor:.2f}; "
          f"близость {sp_near:.2f}/{sp_mid:.2f}/{sp_far:.2f}; уход +{unc:.4f}; тороид {dist_wrap}")
    # ── §10.111–10.115: цена угрозы и прикрытие города ──
    _mk = A.CollapseMarks(horizon=20)
    _mk.mark_owner(3, 5, "нападение наблюдено")

    def _grid(cells, size=8):
        g = [[255] * size for _ in range(size)]
        for (x, y), own in cells.items():
            g[x][y] = own               # порядок слоя — [x][y], измерен (§13.99)
        return g

    _city = {"121": {"owner": 0, "x": 2, "y": 2, "city_radius_sq": 9}}
    _unit = {"5": {"owner": 0, "x": 2, "y": 3, "health": 10}}
    _dof = {"city_121": 9.0, "unit_5": 3.0}
    _obs_near = {"city": _city, "unit": _unit, "tech": {},
                 "map": {"unit_owner": _grid({(3, 3): 3}), "xsize": 8}}
    _obs_far = {"city": _city, "unit": _unit, "tech": {},
                "map": {"unit_owner": _grid({(2, 6): 3}), "xsize": 8}}
    r_near, det_near, why_near = SK.risk_with_reason(_obs_near, _mk, 6, 0, _dof)
    r_far, _, why_far = SK.risk_with_reason(_obs_far, _mk, 6, 0, _dof)
    r_none, _, why_none = SK.risk_with_reason(_obs_near, A.CollapseMarks(), 6, 0, _dof)
    _expect_near = math.log(9.0) + math.log(3.0)
    check("I45 цена риска (§10.111–10.115): угроза — только НАБЛЮДЁННОЕ нападение; под ударом = "
          "достаёт за τ=1 ход (дальняя угроза не достаёт); цена = Σ ln(счёт) наших сущностей под "
          "ударом (миникас, без вероятностей); «угроз нет» и «не достают» названы по-разному",
          abs(r_near - _expect_near) < 0.002 and len(det_near) == 2
          and r_far == 0.0 and "не достаёт" in why_far
          and r_none == 0.0 and "нападения ещё не наблюдалось" in why_none,
          f"рядом: {r_near:.3f} (ln9+ln3 = {_expect_near:.3f}, под ударом {len(det_near)}); "
          f"далеко: {r_far:g}; без меток: {r_none:g}")
    _obs_intr = {"city": _city, "unit": {}, "tech": {},
                 "map": {"unit_owner": _grid({(3, 3): 4}), "xsize": 8}}
    intr = SK.city_intruders(_obs_intr, "121", 0)
    cov, why_cov = SK.cover_price(9.0, intr)
    cov_none, why_cov_none = SK.cover_price(9.0, [])
    cov_nodof, why_cov_nodof = SK.cover_price(0.42, intr)
    r_peaceful, _, why_peaceful = SK.risk_with_reason(_obs_intr, _mk, 6, 0, _dof)
    dv, why_dv = SK.defensive_value(r_near, 0.0)
    cov_chain, _ = ST.cover_factor(r_near, 10.0)
    check("I46 прикрытие города и связь с семейством (§10.111, §10.113): чужой у города даёт мотив "
          "прикрыть (0.8 × ln счёта), но НЕ цену риска — чужой без наблюдённого нападения не угроза "
          "T1; без нарушителей и при нормированном счёте — нуль С ПРИЧИНОЙ; цена риска входит входом "
          "в `cover_factor` семейства (§13.19); ценность защиты = падение цены риска",
          len(intr) == 1 and abs(cov - 0.8 * math.log(9.0)) < 0.002
          and cov_none == 0.0 and "не от кого" in why_cov_none
          and cov_nodof == 0.0 and "не выводится" in why_cov_nodof
          and r_peaceful == 0.0 and "не виден" in why_peaceful
          and abs(dv - r_near) < 0.002 and "сохраняется" in why_dv
          and abs(cov_chain - max(0.0, 1.0 - r_near / 10.0)) < 1e-9,
          f"нарушителей {len(intr)}, прикрытие {cov:.3f} (0.8×ln9 = {0.8 * math.log(9.0):.3f}); без "
          f"нарушителей {cov_none:g}; нормированный счёт {cov_nodof:g}; тот же чужой как угроза → "
          f"{r_peaceful:g} ({why_peaceful[:40]}…); защита сохраняет {dv:.3f}; cover_factor(риск) {cov_chain:.2f}")
    # ── §10.79/§10.83/§10.84: запись видео и текст состояния на кадре ──
    import tempfile as _tmp
    from PIL import Image as _Img
    _vd = Path(_tmp.mkdtemp(prefix="dof_video_"))
    _vfr = []
    for _i in range(3):
        _p = _vd / f"turn_00{_i}_step_000{_i}.png"
        _Img.new("RGB", (64, 40), (30 * _i, 60, 90)).save(_p)
        _vfr.append(_p)
    _vvid = _vd / "out.mp4"
    _vok = V.to_video(_vfr, _vvid, fps=4)
    _vlst = V.frame_list_text(_vfr, 4)
    check("I47 сборка видео (§10.79, §10.84): кадры → mp4 настоящим ffmpeg (путь ищется и по "
          "nix-хранилищу); в списке кадров АБСОЛЮТНЫЕ пути — относительные ffmpeg разрешает от "
          "каталога списка, а не от cwd; имя файла несёт метку прогона, иначе попытки затирают друг друга",
          _vok and _vvid.exists() and _vvid.stat().st_size > 0
          and _vlst.count("file '/") == 3 and V.ffmpeg_path() is not None
          and V.video_name(9100, 6001, tag="rec1") == "game_9100_port6001_rec1.mp4"
          and V.video_name(9100, 6001, tag="") == "game_9100_port6001.mp4",
          f"ffmpeg {V.ffmpeg_path()}; mp4 {_vvid.stat().st_size if _vvid.exists() else 0} Б; "
          f"список: {_vlst.splitlines()[0][:44]}…")
    _sobs = {"city": {"121": {"id": 121, "owner": 0, "name": "Киев", "size": 3, "x": 2, "y": 2,
                              "production_kind": 4, "turns_to_prod_complete": 32767,
                              "prod_shield": 3, "surplus_shield": 0, "city_waste": 0,
                              "surplus_food": 1, "science": 2,
                              "improvements_present": ["Barracks", "Barracks", "Granary"]},
                     "77": {"id": 77, "owner": 0, "name": "Одесса", "size": 1, "x": 5, "y": 5,
                            "production_kind": 1, "turns_to_prod_complete": 4, "prod_shield": 5,
                            "surplus_shield": 2, "surplus_food": 2, "science": 1}},
             "unit": {"10": {"owner": 0, "type_rule_name": "Workers", "health": 10,
                             "moves_left": 3, "x": 2, "y": 2},
                      "11": {"owner": 0, "type_rule_name": "Workers", "health": 10,
                             "moves_left": 3, "x": 2, "y": 2},
                      "12": {"owner": 0, "type_rule_name": "Warriors", "health": 7,
                             "moves_left": 0, "x": 5, "y": 5},
                      "13": {"owner": 3, "type_rule_name": "Legion", "health": 10,
                             "moves_left": 1, "x": 7, "y": 7}}}
    _dl = lambda eid: {"city:121": 9.0, "city:77": 4.0, "unit:10": 3.0}.get(eid)  # noqa: E731
    _L, _R = V.state_lines(_sobs, 34, 0, dof_lookup=_dl, index=-1.3863,
                           build_names={"121": "Coining"})
    _ls, _rs = "\n".join(_L), "\n".join(_R)
    check("I48 текст состояния на кадре (§10.83, §10.84): только своё (чужой юнит не попадает); "
          "«никогда» (32767) показывается ПРИЧИНОЙ — щиты и содержание, а не числом; стройка "
          "называется записанным именем, а не кодом мира; повторы сворачиваются как «x N»; счёт "
          "действий печатается там, где посчитан, и прочерком там, где нет",
          "ХОД 34" in _ls and "индекс -1.39" in _ls and "ГОРОДА: 2" in _ls
          and "НЕ ИДЁТ: щиты 3→0 (содержание юнитов)" in _ls
          and "стройка Coining" in _ls and "за 4х" in _ls
          and "Barracks x 2" in _ls and "Киев р3" in _ls
          and "действий 9" in _ls and "действий 4" in _ls
          and "Workers HP10 ход3 (2,2) д3" in _rs and "Workers HP10 ход3 (2,2) д—" in _rs
          and "Legion" not in _rs and "ЮНИТЫ: 3" in _rs
          and V.counts(["a", "a", "b"]) == [("a", 2), ("b", 1)],
          f"слева: {_ls.splitlines()[0]} | {_ls.splitlines()[4][:60]} | {_ls.splitlines()[3][:60]}; "
          f"справа: {_rs.splitlines()[0]} | {_rs.splitlines()[1][:44] if len(_rs.splitlines()) > 1 else ''}")
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

    Отдельно проверяется **возврат** (H5, H6): исключение — вердикт текущего
    состояния, а не приговор. Поднятый до положительного значения ноль обязан
    вернуть сущность в счёт; и сильнее — появившаяся дверь обязана вернуть её при
    ТОМ ЖЕ нуле, потому что счёт следит за возможностью подъёма, а не за
    значением. Ожидания объявлены здесь, до прогона.
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

    # ── возврат: исключение — вердикт состояния, а не приговор (§13.81 в форме, где
    # вопрос отвечаем). Объявлено ДО прогона: поднятый до положительного значения ноль
    # обязан вернуть сущность в счёт; и — сильнее — появившаяся дверь обязана вернуть её
    # при ТОМ ЖЕ нуле, потому что счёт следит за возможностью подъёма, а не за значением.
    dof_back = {player_id: 0.5, city_id: 0.0, unit_id: 0.35}
    ctx_back = ctx.with_dof({unit_id: 0.35})
    st_back = G.state_with_measured_dof(state, dof_back)
    members_back, index_back = G.calc_and_index(st_back, ctx_back)
    unit_back = G.recoverability(st_back, ctx_back)[unit_id]
    check("H5 исключённая сущность возвращается в счёт, как только её ноль поднят до "
          "положительного DoF (исключение — не приговор, а вердикт текущего состояния)",
          unit_id not in members and unit_id in members_back
          and unit_back["verdict"] == "reachable",
          f"при DoF 0: {'в счёте' if unit_id in members else 'вне счёта'}; при DoF "
          f"{dof_back[unit_id]}: {'в счёте' if unit_id in members_back else 'вне счёта'}, "
          f"{unit_back['verdict']}, индекс {index_back:.4f}")

    # H6: возврат по ДВЕРИ при неизменном нуле. Мини-граф — как в H4, но спрашивается не
    # вердикт сам по себе, а место в счёте: без двери — вне, с дверью — в счёте.
    from brain.spec.calculus_core import ObservationContext as _Ctx
    mini_means = list(SPEC_MEANS_CLASS)
    mini_dof = {"a": 0.0, "b": 1.0}
    mini_t_rec = {name: 5 * TURN_DURATION_MKS for name in mini_dof}
    horizon_mini = 5.0 * TURN_DURATION_MKS
    revive = ActEdge(id="b:revive", source="b", target="a", category="production",
                     effect={"a": 1.0}, duration_mks=TURN_DURATION_MKS)
    got: dict[str, tuple] = {}
    for tag, acts in (("без двери", []), ("с дверью", [revive])):
        g_mini = WorldGraph(entities={name: EntityNode(id=name, current_dof=v)
                                      for name, v in mini_dof.items()},
                            means=["energy"], acts=list(acts))
        c_mini = _Ctx(world=g_mini, means_class=mini_means, t_rec=mini_t_rec,
                      counting_horizon_mks=horizon_mini,
                      observation_digest=g_mini.observation_digest(mini_means, mini_t_rec,
                                                                   horizon_mini),
                      dof_override=mini_dof)
        s_mini = G.state_with_measured_dof(state, mini_dof, deadlines=mini_t_rec)
        m_mini, i_mini = G.calc_and_index(s_mini, c_mini)
        got[tag] = (G.recoverability(s_mini, c_mini)["a"]["verdict"], "a" in m_mini,
                    i_mini)
    check("H6 счёт следит за ВОЗМОЖНОСТЬЮ, а не за значением: при нуле и без двери сущность "
          "вне счёта, а с появившейся дверью — вернулась, хотя её DoF не изменился",
          got["без двери"][:2] == ("proven_unreachable", False)
          and got["с дверью"][:2] == ("reachable", True),
          f"без двери: {got['без двери'][0]}, в счёте {got['без двери'][1]}, индекс "
          f"{got['без двери'][2]:.4f}; с дверью: {got['с дверью'][0]}, в счёте "
          f"{got['с дверью'][1]}, индекс {got['с дверью'][2]:.4f}")


def run_city_indices() -> None:
    """Городская ветка: оба счёта, гейт продажи, канал замера и правило эффекта.

    Проверки идут на сохранённом живом наблюдении (`tests/fixtures/real_obs_01.json`) и на числах,
    которые уже были измерены отдельно — `v2` подтвердил связь «индекс 21 = Palace» своим замером,
    а `Settlers` своей способностью обязан нашему же счёту города по каталогу цен.
    """
    import json
    import pathlib
    from env import spec_obs as SO
    from env.entity_extractor import GameStateExtractor

    path = pathlib.Path("tests/fixtures/real_obs_01.json")
    if not path.is_file():
        check("город: фикстура живого наблюдения на месте", False, str(path))
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    snap = raw[-1]["observation"]
    info = raw[-1].get("info")
    m = SO.measure_step(snap, info, (info or {}).get("turn"), GameStateExtractor(), None, 0)
    cities = [k for k in m["vectors"] if k.startswith("city")]
    check("город: в разборе есть город", bool(cities), f"сущности: {sorted(m['vectors'])[:6]}")
    if not cities:
        return
    cid = cities[0]
    v_now, v_max = float(m["counts"][cid]), float((m.get("v_max") or {}).get(cid, -1))
    check("город: V(сейчас) строго меньше V(максимума) — различение работает",
          v_max > v_now, f"сейчас {v_now}, максимум {v_max}")
    out = (m.get("city_output") or {}).get(cid) or {}
    check("город: канал замера улучшений заполнен размером и именем постройки",
          out.get("размер") == 1 and out.get("улучшения") == ["Palace"],
          f"city_output = {out}")
    rows = (m.get("production_effects") or {}).get(cid) or []
    pos = [r for r in rows if (r.get("эффект") or 0) > 0]
    settlers = [r for r in rows if r.get("имя") == "Settlers"]
    # Инвариант правила, а не ожидаемое число: у КАЖДОГО вектора-производства эффект обязан быть > 0.
    # Сколько именно имён проходит порог — свойство данных (здесь `prod_shield = 7`, поэтому платёж
    # горизонтный и проходят десятки боевых типов), и подгонять проверку под одно имя нельзя.
    vectors = set(m["vectors"].get(cid) or [])
    passing = {r["имя"] for r in pos}
    pref = L.SPEC_PRODUCTION_ACTION_PREFIX
    now_prod = {str(n)[len(pref):] for n in vectors if str(n).startswith(pref)}
    # Проверяем НАПРАВЛЕНИЕ: всё, что стоит в «сейчас» как производство, обязано иметь эффект > 0.
    # Обратное неверно и верным быть не может: имя с положительным эффектом, которого город сейчас
    # начать не может, живёт в «максимуме» и в «сейчас» его нет.
    check("город: каждый вектор-производство в «сейчас» имеет эффект > 0",
          bool(now_prod) and now_prod.issubset(passing),
          f"в «сейчас» производств {len(now_prod)}, прошли порог {len(passing)}; "
          f"без эффекта: {sorted(now_prod - passing)[:5]}")
    check("город: поселенец среди прошедших порог и его способность — счёт города по каталогу",
          "Settlers" in passing and bool(settlers)
          and abs(float(settlers[0].get("способность") or 0) - 0.9744) < 0.001,
          f"способность Settlers: {settlers[0].get('способность') if settlers else 'нет строки'}")


def run_record_keys() -> None:
    """Запись сущности читается и по строковому, и по числовому ключу.

    Живой мир отдаёт идентификаторы числом, сохранённое наблюдение — строкой; разница уже приводила
    к «поля пусты» (`moves_left`, затем `size`/`prod_shield` у города). Проверка держит этот случай
    закрытым: обе формы обязаны давать одну и ту же запись, отсутствующая — пустую, а не чужую.
    """
    from env.spec_lenses import section_for
    from env.spec_obs import _entity_record

    rec = {"size": 1, "prod_shield": 5}
    check("запись сущности: строковый ключ читается",
          _entity_record({"121": rec}, "city_121") == rec, "")
    check("запись сущности: числовой ключ читается так же, как строковый",
          _entity_record({121: rec}, "city_121") == rec, "")
    check("запись сущности: чужой идентификатор даёт пустую запись, а не первую попавшуюся",
          _entity_record({7: rec}, "city_121") == {}, "")
    check("секция: числовой ключ (живой мир) и строковый (сохранённое наблюдение) находят одно",
          section_for({121: rec}, 121) == rec and section_for({"121": rec}, "121") == rec, "")
    check("секция: чужой ключ не подменяется первым попавшимся",
          section_for({"unit": {1: rec}}, "city") is None, "")


def main() -> int:
    steps = 1
    if "--steps" in sys.argv:
        steps = int(sys.argv[sys.argv.index("--steps") + 1])
    run_real(steps)
    run_recovery()
    run_anchors()
    run_rules()
    run_horizon()
    run_record_keys()
    run_city_indices()
    run_declaration()
    print(f"\nпроверок: {PASS + FAIL}, падений: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
