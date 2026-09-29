#!/usr/bin/env python
"""§10.53: разложение разности счёта по категориям Freeciv.

ЮНИТОВЫЕ категории: military_units, units_built, units_used, units_killed, units_lost.
ИМПЕРСКИЕ: population, cities, researched_techs, research_speed, economics, production,
land_area, settled_area, gold, wonders, literacy, culture.
Правило чтения — объявлено заранее (см. документ §10.53).
"""
import json
import statistics
import sys

UNIT_CATS = ("military_units", "units_built", "units_used", "units_killed", "units_lost")
EMPIRE_CATS = ("population", "cities", "researched_techs", "research_speed", "economics",
               "production", "land_area", "settled_area", "gold", "wonders")


def load(pre, tag):
    d = json.load(open(f"/tmp/{pre}_{tag}.json"))
    eps = list(d["results"].values())[0]
    out = []
    for e in eps:
        cats = e.get("category_scores") or {}
        out.append({
            "sc": float(e.get("score_cum") or 0),
            "err": str(e.get("error") or ""),
            "cats": {k: float(v) for k, v in cats.items()},
        })
    return out


def med(xs):
    return statistics.median(xs) if xs else 0.0


if __name__ == "__main__":
    PRE = sys.argv[1] if len(sys.argv) > 1 else "c300"
    base = load(PRE, "base")
    ban = load(PRE, "ban")
    n = min(len(base), len(ban))
    pairs = [(base[i], ban[i]) for i in range(n) if not base[i]["err"] and not ban[i]["err"]]
    print(f"годных пар: {len(pairs)} из {n}")
    if not pairs:
        raise SystemExit("нет годных пар")
    d_sc = [b["sc"] - a["sc"] for b, a in pairs]
    print(f"разность счёта (база − запрет): {[round(x) for x in d_sc]}, "
          f"медиана {med(d_sc):+.1f}")
    keys = sorted(set(k for b, a in pairs for k in list(b["cats"]) + list(a["cats"])))
    print(f"{'категория':>16} | {'база (мед.)':>12} | {'запрет (мед.)':>13} | "
          f"{'разность (мед.)':>15}")
    rows = {}
    for k in keys:
        bv = [b["cats"].get(k, 0.0) for b, a in pairs]
        av = [a["cats"].get(k, 0.0) for b, a in pairs]
        dd = [x - y for x, y in zip(bv, av)]
        rows[k] = med(dd)
        print(f"{k:>16} | {med(bv):12.1f} | {med(av):13.1f} | {med(dd):+15.1f}")
    unit_share = sum(rows.get(k, 0.0) for k in UNIT_CATS)
    empire_share = sum(rows.get(k, 0.0) for k in EMPIRE_CATS)
    print("-" * 70)
    print(f"сумма разностей по ЮНИТОВЫМ категориям: {unit_share:+.1f} "
          f"({', '.join(f'{k} {rows.get(k, 0.0):+.1f}' for k in UNIT_CATS)})")
    print(f"сумма разностей по ИМПЕРСКИМ категориям: {empire_share:+.1f}")
    tot = med(d_sc)
    print(f"медиана общей разности счёта: {tot:+.1f}")
    if tot > 0 and unit_share >= tot:
        print("ЧТЕНИЕ: разность целиком объясняется юнитовыми категориями -> «производство "
              "полезно» верно через свои же категории; счёт не независимая мера исхода.")
    elif tot > 0 and unit_share < 0.5 * tot:
        print("ЧТЕНИЕ: юнитовые категории объясняют меньше половины разности -> вывод "
              "остаётся в силе как свойство поведения.")
    else:
        print("ЧТЕНИЕ: результат не подпадает ни под одно из объявленных правил — "
              "доложить как есть, без вывода.")