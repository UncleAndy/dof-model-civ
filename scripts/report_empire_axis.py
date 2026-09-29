#!/usr/bin/env python
"""Ось ИМПЕРИИ: исход по категориям, не зависящим от количества построенных юнитов.

Ядро (объявлено в §10.53): population, cities, researched_techs, research_speed,
economics, production, gold, wonders. Площади (land_area, settled_area) и все
«юнитовые» категории (military_units, units_built/used/killed/lost) в ядро НЕ входят:
первые потому, что счёт по ним в этих играх не меняется, вторые потому, что разность по
ним механически следует из политики — это и есть тавтология, от которой мы уходим.

Вызов: python scripts/report_empire_axis.py <префикс> [--explore]
"""
import json
import math
import statistics
import sys

CORE = ("population", "cities", "researched_techs", "research_speed", "economics",
        "production", "gold", "wonders")


def load(pre, tag):
    d = json.load(open(f"/tmp/{pre}_{tag}.json"))
    eps = list(d["results"].values())[0]
    out = []
    for e in eps:
        cats = e.get("category_scores") or {}
        out.append({
            "sc": float(e.get("score_cum") or 0),
            "err": str(e.get("error") or ""),
            "empire": sum(float(cats.get(k, 0.0)) for k in CORE),
            "cats": {k: float(v) for k, v in cats.items()},
        })
    return out


def sign_p(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def main() -> int:
    pre = sys.argv[1] if len(sys.argv) > 1 else "c300"
    base, ban = load(pre, "base"), load(pre, "ban")
    n = min(len(base), len(ban))
    pairs = [(base[i], ban[i]) for i in range(n)
             if not base[i]["err"] and not ban[i]["err"]]
    d = [b["empire"] - a["empire"] for b, a in pairs]
    k = sum(1 for x in d if x > 0)
    nn = sum(1 for x in d if x != 0)
    print(f"годных пар {len(pairs)} из {n}")
    print(f"ось империи (ядро {CORE}):")
    print(f"   база   по играм: {[round(b['empire']) for b, a in pairs]}")
    print(f"   запрет по играм: {[round(a['empire']) for b, a in pairs]}")
    print(f"   разности: {[round(x) for x in d]}")
    print(f"   медиана разности {statistics.median(d):+.1f}, выигрышей {k} из {nn}, "
          f"знаковый p={sign_p(k, nn) if nn else 1.0:.3f}")
    print(f"   для сравнения — медиана общей разности счёта: "
          f"{statistics.median([b['sc'] - a['sc'] for b, a in pairs]):+.1f}")
    # Правило вердикта §10.48/§10.55: все три условия.
    cm = statistics.median([a["empire"] for b, a in pairs])
    med = statistics.median(d)
    p = sign_p(k, nn) if nn else 1.0
    ok_abs = med >= 2.0
    ok_rel = med >= 0.10 * cm
    ok_sign = p < 0.05 and k > nn / 2
    print(f"   контрольная медиана оси империи {cm:.1f}; условия: абс {'✓' if ok_abs else '✗'}, "
          f"отн {'✓' if ok_rel else '✗'}, знаки {'✓' if ok_sign else '✗'} -> "
          f"{'H1 ПОДТВЕРЖДЕНА' if (ok_abs and ok_rel and ok_sign) else 'H1 НЕ ПОДТВЕРЖДЕНА'}")

    # Разведочный характер: данные уже собраны ДО объявления этого конца,
    # поэтому результат читается как ориентир, а не как вердикт.
    if "--explore" in sys.argv:
        print("ВНИМАНИЕ: это разведочный взгляд на уже собранные данные "
              "(конец объявлен после их получения). Для вердикта нужна отдельная серия.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())