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
from env.entity_extractor import GameStateExtractor  # noqa: E402
from env import spec_graph as G  # noqa: E402
from env import spec_lenses as L  # noqa: E402

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
                      menu: list[str]) -> dict[str, float]:
    """Требования города: стоимости того, что мир предлагает ему построить."""
    per_transition: list[dict[str, float]] = []
    for name in menu:
        if not name.startswith("produce_"):
            continue
        item = name[len("produce_"):]
        cost = costs.get(item)
        if cost is not None:
            per_transition.append({"energy": float(cost)})
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
    last: dict = {}
    for snap in snaps[:steps]:
        obs, info = snap["observation"], snap["info"]
        state = extractor.extract(obs, info, snap["turn"]).state
        menu = L.menu_by_entity(info.get("available_actions") or {})
        costs = build_cost_index(obs)
        means = L.means_with_income(empire_stocks(obs), empire_incomes(obs))

        bindings = {}
        vectors: dict[str, list[str]] = {}
        fields_of: dict[str, dict] = {}
        for eid, ent in state.entities.items():
            kind = L.entity_type_of(eid)
            names = menu.get(eid, [])
            if not names:
                continue                     # сущности без меню не о чем мерить
            raw = obs.get("dipl" if kind == "diplomacy" else kind, {}) or {}
            fields = raw.get(eid.split("_", 1)[1], {}) or {}
            names = L.available_vectors(kind, fields, names)
            if not names:
                gates += 1                   # все векторы заморожены — дверь открыта
            vectors[eid] = names
            fields_of[eid] = fields
            variety = L.variety_counters(names, disturbances(obs, eid, kind))
            if kind == "city":
                requirements = city_requirements(fields, costs, names)
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
                "fields": fields_of, "measured": measured,
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
    tech_obs = json.load(open(OBS_FILE))[0]["observation"]["tech"]
    known = {eid for _, eid, _ in rows
             if eid.startswith("tech_")
             and L.gate_is_open(tech_obs.get(eid.split("_", 1)[1], {}))}
    techs_seen = {eid for _, eid, _ in rows if eid.startswith("tech_")}
    check("A4 у открытой двери нет ни одного вектора реакции, у исследуемой — есть",
          bool(known) and known < techs_seen
          and all(not m.variety_counters["V"] for _, eid, m in rows if eid in known)
          and all(m.variety_counters["V"] > 0 for _, eid, m in rows
                  if eid in techs_seen - known),
          f"открытых: {len(known)}, исследуемых: {len(techs_seen - known)}")

    # ── G. §3.5/§4.9/§4.2: граф мира, вердикты, множество счёта ─────────────
    print(f"\n=== G. Граф мира, вердикты и calc(S) (ход {last['turn']}) ===")
    graph = G.world_graph(last["vectors"], last["fields"], last["dof"])
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
    check("G2 открытая дверь исключена вычисленным вердиктом, а не фильтром отображения",
          bool(excluded) and all(verdicts[e]["verdict"] == "proven_unreachable"
                                 for e in excluded),
          f"исключено: {len(excluded)}")
    check("G3 у каждой исключённой сущности свидетель пуст, а наблюдение полное",
          all(not verdicts[e]["witness"] and verdicts[e]["observation"] == "complete"
              for e in excluded))
    check("G4 в счёте не остаётся сущности с известным нулём",
          all(st.entities[e].current_dof > 0.0 for e in members),
          f"нулей в счёте: {sum(1 for e in members if st.entities[e].current_dof <= 0.0)}")
    check("G5 индекс по calc(S) конечен и отрицателен (§4.1)",
          math.isfinite(index) and index < 0, f"{index:.4f}")


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


def main() -> int:
    steps = 1
    if "--steps" in sys.argv:
        steps = int(sys.argv[sys.argv.index("--steps") + 1])
    run_real(steps)
    run_anchors()
    run_rules()
    run_horizon()
    run_declaration()
    print(f"\nпроверок: {PASS + FAIL}, падений: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
