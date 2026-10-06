#!/usr/bin/env python
"""Проверка срока технологии: выведенная формула против факта.

Формула (выведена из чисел наблюдения, не замерена):

    срок = ceil((researching_cost − bulbs_researched) / bulbs_за_ход)
    bulbs_за_ход = сумма `bulbs` своих городов

Проверка ровно такая же, какую прошло производство, и по той же причине: вывод
«очевидно верен» уже один раз оказался неверным. Здесь два независимых факта:
прогресс растёт НА `bulbs_за_ход` за ход, и технология завершается на предсказанном
ходу. Заодно проверяется подозрение, что `player['science']` (у столицы 60 при
`bulbs` 7) — не выход науки за ход.

    python scripts/check_tech_timing.py --turns 25
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=25)
    args = parser.parse_args()

    import warnings

    import gymnasium

    from civrealm.configs import fc_args

    warnings.filterwarnings("ignore")
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset()
    rows = []
    predicted_done = None
    predicted_at = None

    ctl = getattr(getattr(env.unwrapped, "civ_controller", None), "player_ctrl", None)
    our_id = getattr(ctl, "my_player_id", None)
    if our_id is None:
        our_id = 0
    print(f"  наш id игрока: {our_id!r} (ключи слоя ищутся как int и как str)",
          flush=True)

    for turn in range(args.turns):
        obs, reward, terminated, truncated, info = env.step(None)
        layer = obs.get("player") or {}
        player = {}
        for key in (our_id, str(our_id), 0, "0"):
            if isinstance(layer, dict) and key in layer:
                player = layer[key] or {}
                break
        cities = obs.get("city") or {}
        bulbs = sum(float((c or {}).get("bulbs") or 0) for c in cities.values()
                    if isinstance(c, dict) and str((c or {}).get("owner")) == str(our_id))
        row = {
            "turn": turn + 1,
            "researching": player.get("researching"),
            "cost": player.get("researching_cost"),
            "progress": player.get("bulbs_researched"),
            "player_science": player.get("science"),
            "city_bulbs": bulbs,
        }
        rows.append(row)
        if len(rows) >= 2 and row["progress"] is not None \
                and rows[-2]["progress"] is not None:
            row["delta"] = float(row["progress"]) - float(rows[-2]["progress"])
        else:
            row["delta"] = None
        if predicted_done is None and row["cost"] and row["progress"] is not None \
                and bulbs > 0:
            left = max(0.0, float(row["cost"]) - float(row["progress"]))
            predicted_done = int(math.ceil(left / bulbs))
            predicted_at = row["turn"] + predicted_done
            print(f"на ходу {row['turn']}: стоимость {row['cost']}, "
                  f"накоплено {row['progress']}, наука за ход (города) {bulbs:g} → "
                  f"предсказано завершение на ходу {predicted_at} "
                  f"(через {predicted_done})", flush=True)
        print(f"  ход {row['turn']}: прогресс {row['progress']} "
              f"(+{row['delta']}), researching={row['researching']}, "
              f"player.science={row['player_science']}", flush=True)
        if terminated or truncated:
            print(f"матч завершён на ходу {row['turn']}", flush=True)
            break

    print("\nсводка: рост прогресса против выхода науки городов")
    deltas = [r["delta"] for r in rows if r["delta"] is not None]
    bulbs_seen = [r["city_bulbs"] for r in rows if r["delta"] is not None]
    science_seen = [r["player_science"] for r in rows if r["delta"] is not None]
    if deltas:
        print(f"   шагов: {len(deltas)}; рост прогресса = {sorted(set(deltas))}; "
              f"выход городов = {sorted(set(bulbs_seen))}; "
              f"player.science = {sorted(set(science_seen))}")
        match_bulbs = all(abs(d - b) < 1e-9 for d, b in zip(deltas, bulbs_seen))
        match_science = all(abs(d - s) < 1e-9 for d, s in zip(deltas, science_seen))
        print(f"   рост совпал с выходом ГОРОДОВ: {match_bulbs}")
        print(f"   рост совпал с player.science: {match_science}")
    else:
        print("   данных о прогрессе нет — формула не проверена")
    print(f"\nстрок: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
