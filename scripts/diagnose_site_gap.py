"""Почему ни одно правило не сходится: две узкие гипотезы о постоянном сдвиге.

Вердикт `analyze_selection_rule.py` отрицательный: ни одно правило назначения
жителей не воспроизводит факт (лучшее — 39% против порога 70%). Но ошибка по
еде у ВСЕХ правил почти одинакова (≈1), а это признак не «неверного набора», а
постоянного сдвига. Здесь проверяются две гипотезы, каждая — одной осью:

* **нетто против валового**: возможно, наблюдённая еда города — это уже излишек
  после еды жителей (`food_cost × size`), а модель суммирует валовой выход;
* **меньше обработанных клеток**: недовольные не работают, поэтому клеток может
  быть меньше, чем `size + 1`.

Сетка: {валовое, нетто} × {size+1, size, size−1} клеток × два правила-лидера.
Порог вердикта задан ДО данных и тот же, что в основном анализаторе.

    python scripts/diagnose_site_gap.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env.site_outcomes import load  # noqa: E402
from env.site_rules import all_rules, predict, verdict  # noqa: E402

CHANNELS = ("еда", "щиты", "торговля")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--food-cost", type=float, default=2.0)
    p.add_argument("--tol", type=float, default=1e-9)
    args = p.parse_args()

    rows = load(None)
    usable = [r for r in rows
              if not r.get("lost") and r.get("size") is not None
              and r.get("obs_food") is not None and r.get("tiles")
              and len(r["tiles"]) == 21
              and all(r.get("tiles_known") or [])]

    print("=" * 92)
    print("Диагностика сдвига: нетто/валовое и число обработанных клеток")
    print("=" * 92)
    print(f"  пригодных площадок: {len(usable)}")
    if not usable:
        print("  нет данных — вердикта нет")
        return 0

    print()
    print(f"{'правило':<18}{'клеток':<12}{'еда':>16}{'щиты':>16}{'торговля':>16}")
    print("-" * 92)
    results: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    for rule in all_rules():
        for cells_name, delta in (("size+1", 0), ("size", -1), ("size-1", -2)):
            for gross_name, net in (("валовое", False), ("нетто", True)):
                exact = [0, 0, 0]
                err = [0.0, 0.0, 0.0]
                for r in usable:
                    size = int(r["size"])
                    need = max(1, size) + 1 + delta
                    if need < 1:
                        continue
                    got = list(predict([tuple(t) for t in r["tiles"]], need - 1, rule))
                    if net:
                        got[0] -= args.food_cost * max(1, size)
                    for ch, observed in enumerate((r["obs_food"], r["obs_shield"],
                                                   r["obs_trade"])):
                        try:
                            observed = float(observed)
                        except (TypeError, ValueError):
                            continue
                        if abs(got[ch] - observed) <= args.tol:
                            exact[ch] += 1
                        err[ch] += abs(got[ch] - observed)
                n = len(usable)
                cells = "".join(
                    f"{exact[ch]/n:>10.0%}/{err[ch]/n:>5.2f}" for ch in range(3))
                print(f"{rule:<18}{cells_name:<7}{gross_name:<6}{cells}")
                results[(rule, cells_name, gross_name)] = exact

    print()
    best = None
    for rule in all_rules():
        v = verdict({k[0]: val for k, val in results.items()
                     if k[1] == "size+1" and k[2] == "валовое" and k[0] == rule},
                    len(usable))
        hits = sum(results[(rule, "size+1", "валовое")])
        if best is None or hits > best[1]:
            best = (rule, hits)
    print(f"Лучшее в сетке: {best[0]} — {best[1]} точных из {3*len(usable)} "
          f"({best[1]/(3*len(usable)):.0%})")
    print()
    print("Как читать: если у какой-то комбинации точность резко выше, значит")
    print("именно она описывает мир, и модель надо править в одном месте. Если все")
    print("комбинации кучкуются около 30–40%, то дело не в этих допущениях, и")
    print("наблюдённый выход города строится по правилу, которого здесь нет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
