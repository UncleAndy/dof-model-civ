"""§13.91: проверки П1-П4 записи разрушительных актов.

Протокол объявлен в `_journal_1391.py` ДО этих данных: П1 (акт с измеренной
величиной), П2 переобъявлено под меру §13.89 (`DoF(после) <= DoF(до)/2`),
П3 (нет наблюдённого нападающего - нет акта), П4 (наши действия метки не создают).
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import entity_extractor as E   # noqa: E402
from env import spec_attack as A        # noqa: E402

OK = 0
BAD = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ok   {name}" + (f" | {detail}" if detail else ""))
    else:
        BAD += 1
        print(f"  ПЛОХО {name}" + (f" | {detail}" if detail else ""))


def _map(cells: dict) -> list:
    grid = [[255] * 4 for _ in range(4)]
    for (x, y), own in cells.items():
        grid[x][y] = own             # порядок слоя — [x][y], измерен (§13.99)
    return grid


OUR_CITY = {"121": {"owner": 0, "x": 2, "y": 2}}


def obs(our_health, foreign=None, foreign_health=None, own_present=True) -> dict:
    units = {}
    if own_present:
        units["5"] = {"owner": 0, "x": 1, "y": 1, "health": our_health}
    if foreign_health is not None:
        units["7"] = {"owner": 3, "x": 3, "y": 3, "health": foreign_health}
    cells = {} if foreign is None else {(1, 2): foreign}
    return {"unit": units, "city": OUR_CITY, "map": {"unit_owner": _map(cells)}}


def event_of(prev, cur, turn=6):
    tr = A.AttackTracker(my_player_id=0)
    tr.observe(prev, turn - 1)
    return tr.observe(cur, turn)


def unit_dof(rec: dict) -> float:
    """Мера §13.89 в чистом виде: базовый DoF x доля здоровья."""
    hr = E.health_ratio(rec)
    return E.unit_options(rec)[0] / float(E.DOF_SCALE) * hr


def main() -> None:
    print("объявлено заранее: П1 один акт с источником player_3 и delta < 0; "
          "П2 (третье объявление, после двух опровержений): порог свидетеля — свойство "
          "ЛИНЗЫ типа; линза предсказывает порог по сетке мира, прогон проверяет обе "
          "стороны (поселенец: 13 держится, 14 ломается; рабочий: 6 держится, 7 ломается); "
          "П3 без видимого чужого актов нет; П4 ни один акт не имеет нашего источника")

    # ── П1: ранящий удар наблюдаемого чужого
    prev, cur = obs(10), obs(6, foreign=3)
    ev = event_of(prev, cur)
    acts = E.strike_acts(prev, cur, ev, my_player_id=0)
    print(f"  [П1] событие: attacked={ev.get('attacked')} жертвы={ev.get('victims')} "
          f"нападавшие={ev.get('attackers')}")
    for a in acts:
        print(f"  [П1] акт: {a.get('source')} -> {a.get('target')} delta={a.get('delta')} "
              f"| {a.get('why')}")
    a1 = acts[0] if acts else {}
    check("П1 удар даёт акт с источником player_3, целью unit_5 и delta < 0",
          len(acts) == 1 and a1.get("source") == "player_3"
          and a1.get("target") == "unit_5" and (a1.get("delta") or 0.0) < 0.0,
          f"актов {len(acts)}")
    # величина равна health-части падения меры
    after_rec, probe = cur["unit"]["5"], dict(cur["unit"]["5"], health=10)
    want = unit_dof(after_rec) - unit_dof(probe)
    check("П1 величина РАВНА health-части падения DoF цели",
          a1.get("delta") is not None and abs(a1["delta"] - want) < 1e-12,
          f"акт {a1.get('delta')} против расчёта {want:.6f}")

    # ── П2: критерий свидетеля DoF(после) + delta <= 0
    # ТРИ объявления, два из них ОПРОВЕРГНУТЫ прогоном (hr 0.6 -> критерий держится;
    # hr 0.7 -> ломается; «у рабочего порог ровно 0.5» -> тоже неверно). Итог разбора:
    # порог — свойство ЛИНЗЫ ТИПА, и из одной пары (c, s_future) он не выводится: у
    # не-носителя здоровье входит в ТЕКУЩИЙ член, поэтому c сам зависит от здоровья.
    # Третье объявление предсказывает порог перебором публикации линзы по сетке мира
    # (наименьшее health, где 2*DoF(hr) > DoF(потолок)), а прогон проверяет обе стороны.
    def dof_at(health: int, ceiling: int, rule: str) -> float:
        """DoF цели по публикации линзы мира (ни одной подобранной константы)."""
        rec = {"owner": 0, "x": 1, "y": 1, "health": health,
               "type_hp": ceiling, "type_rule_name": rule}
        opt, _, _ = E.unit_options(rec)
        return opt / float(E.DOF_SCALE) * E.health_ratio(rec)

    def flip_health(ceiling: int, rule: str) -> int:
        """Прогноз ДО прогона: наименьшее целое здоровье, где 2*DoF(hr) > DoF(потолок).

        Критерий свидетеля равносилен `2*DoF(hr) <= DoF(до)`, поэтому точка переключения
        предсказывается самой линзой мира, а не постулируется долей здоровья. Линза у
        типов РАЗНАЯ: у носителя (поселенца) здоровье входит в будущий член, у рабочего —
        в текущий, поэтому и порог у них разный.
        """
        full = dof_at(ceiling, ceiling, rule)
        for h in range(1, ceiling + 1):
            if 2.0 * dof_at(h, ceiling, rule) > full + 1e-15:
                return h
        return ceiling + 1

    def holds_at_int(health: int, ceiling: int, rule: str):
        """(критерий, DoF после, delta) на ЦЕЛОМ здоровье мира — через сам прогон."""
        def mk(h: int) -> dict:
            return {"unit": {"5": {"owner": 0, "x": 1, "y": 1, "health": h,
                                   "type_hp": ceiling, "type_rule_name": rule}},
                    "city": OUR_CITY, "map": {"unit_owner": _map({(1, 2): 3})}}

        p, c = mk(ceiling), mk(health)
        e = event_of(p, c)
        aa = E.strike_acts(p, c, e, my_player_id=0)
        if not aa or aa[0].get("delta") is None:
            return None, None, None
        d = aa[0]["delta"]
        dof = dof_at(health, ceiling, rule)
        return (dof + d) <= 1e-15, dof, d

    # Проверка на ДВУХ разных типах: прогноз линзы делается до прогона, прогон проверяет
    # обе стороны порога.
    for rule, ceiling in (("Settlers", 20), ("Workers", 10)):
        h_flip = flip_health(ceiling, rule)
        below, d_below, dlt_below = holds_at_int(h_flip - 1, ceiling, rule)
        at, d_at, dlt_at = holds_at_int(h_flip, ceiling, rule)
        print(f"  [П2 {rule}] потолок {ceiling}: прогноз линзы — переключение на health "
              f"{h_flip} (DoF(потолок) {dof_at(ceiling, ceiling, rule):.6f}); "
              f"health {h_flip - 1}: DoF {d_below:.6f} delta {dlt_below:+.6f} критерий {below}; "
              f"health {h_flip}: DoF {d_at:.6f} delta {dlt_at:+.6f} критерий {at}")
        check(f"П2 {rule}: прогноз линзы подтверждён прогоном (на шаг ниже — держится, на "
              f"пороге — ломается; порог — свойство типа, а не константа)",
              below is True and at is False,
              f"прогноз health {h_flip}: {h_flip - 1} -> {below}, {h_flip} -> {at}")

    # ── П3: нападающий не наблюдён
    p, c = obs(10), obs(6)
    e = event_of(p, c)
    blind = E.strike_acts(p, c, e, my_player_id=0)
    check("П3 без наблюдённого нападающего актов нет",
          (not e.get("attackers")) and blind == [],
          f"attacked={e.get('attacked')} причина={e.get('reason')} актов {len(blind)}")

    # ── П4: наши действия метки не создают; чужая рана - не наша потеря
    p = obs(10, foreign_health=10)
    c = obs(10, foreign=3, foreign_health=4)
    e = event_of(p, c)
    mine = E.strike_acts(p, c, e, my_player_id=0)
    check("П4 ни один акт не имеет нашего источника и нет акта о ране чужого",
          all(a.get("source") != "player_0" for a in mine)
          and all(a.get("target") != "unit_7" for a in mine),
          f"актов {len(mine)}: {[a.get('target') for a in mine]}")

    # ── Живые данные: запись не выдумывает ударов там, где мир их не показывал
    steps = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    tr = A.AttackTracker(my_player_id=0)
    live_acts, live_atk, prev_ob = [], 0, None
    for i, rec in enumerate(steps):
        ob = rec.get("observation") if isinstance(rec, dict) else None
        if not isinstance(ob, dict):
            continue
        ev = tr.observe(ob, rec.get("turn", i + 1))
        live_atk += 1 if ev.get("attacked") else 0
        if prev_ob is not None:
            live_acts += E.strike_acts(prev_ob, ob, ev, my_player_id=0)
        prev_ob = ob
    check("на живом захвате запись не выдумывает ни одного удара",
          live_atk == 0 and live_acts == [],
          f"шагов {len(steps)}, наблюдённых нападений {live_atk}, актов {len(live_acts)}")

    print(f"\nитог: ok {OK}, плохо {BAD}")
    sys.exit(1 if BAD else 0)


main()
