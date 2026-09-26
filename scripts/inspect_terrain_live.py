#!/usr/bin/env python
"""Живая проверка легенды: играем N ходов разведки и собираем доказательства.

Для каждой РАСКРЫТОЙ клетки (у нераскрытых output = 0) записываем
(террейн, экстры, выход). Затем:
  * строим таблицу террейн -> выход и проверяем, что она однозначна;
  * для клеток с ресурсом считаем бонус = выход − базовый выход террейна
    (ресурс в civ2civ3 — аддитивный бонус поверх террейна, а не абсолютный выход).

Один матч, alarm-guard, без sudo. Использование:
    python scripts/inspect_terrain_live.py --turns 8
"""
import argparse
import json
import os
import signal
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)

from civrealm.freeciv.map.map_const import TERRAIN_NAMES, EXTRA_NAMES  # noqa: E402

EVIDENCE = "/tmp/terrain_evidence.json"


class MatchTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise MatchTimeout("match exceeded budget")


def harvest(obs, store):
    """Собрать доказательства по раскрытым клеткам текущего наблюдения."""
    m = obs["map"]
    ta = np.asarray(m["terrain"])
    ea = np.asarray(m["extras"])
    oa = np.asarray(m["output"])
    h, w = ta.shape[:2]
    revealed = 0
    for x in range(h):
        for y in range(w):
            out = tuple(int(v) for v in np.asarray(oa[x][y]).ravel()[:3])
            if out == (0, 0, 0):
                continue  # не раскрыта (или реально нулевая — таких в игре нет)
            revealed += 1
            t = int(ta[x][y])
            tname = TERRAIN_NAMES[t] if t < len(TERRAIN_NAMES) else f"?{t}"
            extras = tuple(EXTRA_NAMES[i] for i in range(ea.shape[2]) if ea[x][y][i]) \
                if ea.ndim == 3 else ()
            key = json.dumps([tname, sorted(extras), list(out)])
            store[key] = store.get(key, 0) + 1
    return revealed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--turns", type=int, default=8)
    p.add_argument("--max-decisions", type=int, default=12)
    p.add_argument("--settle", type=int, default=10)
    args = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(600)
    try:
        from civrealm.freeciv.utils.port_utils import Ports
        import gymnasium as gymnasium
        from civrealm.configs import fc_args

        port = Ports.get()
        print(f"slot: {port}", flush=True)
        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port)

        store = {}
        move_prefixes = ("goto", "move", "explore", "irrigate", "mine", "road", "fortify")

        for t in range(args.turns):
            turn = info.get("turn")
            decisions = 0
            while decisions < args.max_decisions:
                avail = info.get("available_actions") or {}
                chosen = None
                for ctrl_type in ("unit", "city", "gov", "tech"):
                    for actor_id, actions in (avail.get(ctrl_type) or {}).items():
                        for name, params in actions.items():
                            if not params:
                                continue
                            if ctrl_type != "unit" or any(
                                    name.startswith(w) for w in move_prefixes):
                                chosen = (ctrl_type, actor_id, name)
                                break
                        if chosen:
                            break
                    if chosen:
                        break
                if chosen is None:
                    break
                obs, _r, term, trunc, info = env.step(chosen)
                decisions += 1
                if term or trunc:
                    break
            revealed = harvest(obs, store)
            print(f"  turn {turn}: decisions={decisions} revealed_tiles={revealed} "
                  f"distinct_evidence={len(store)}", flush=True)
            obs, _r, term, trunc, info = env.step(None)
            if term or trunc:
                print("  (game ended)")
                break
    finally:
        signal.alarm(0)

    # --- анализ --------------------------------------------------------------
    print("\n=== СВОДКА ПО РАСКРЫТЫМ КЛЕТКАМ ===")
    by_terrain = defaultdict(Counter)
    by_res = defaultdict(lambda: defaultdict(Counter))
    for key, cnt in store.items():
        tname, extras, out = json.loads(key)
        out = tuple(out)
        if not extras:
            by_terrain[tname][out] += cnt
        else:
            for e in extras:
                by_res[e][tname][out] += cnt

    print("\n[террейн без экстр] террейн -> выход × клеток:")
    for name in TERRAIN_NAMES:
        if name in by_terrain:
            print(f"  {name:12s} {dict(by_terrain[name])}")

    print("\n[с экстрами] клетка -> сколько раз:")
    for e in sorted(by_res):
        for tname, outs in by_res[e].items():
            for out, cnt in outs.items():
                base = list(by_terrain.get(tname, {}).keys())
                bonus = ""
                if base:
                    b = tuple(np.array(out) - np.array(base[0]))
                    bonus = f"  бонус относительно базового {base[0]}: {tuple(int(v) for v in b)}"
                print(f"  {tname} + {e:10s} -> {out} × {cnt}{bonus}")

    with open(EVIDENCE, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    print(f"\nдоказательства сохранены: {EVIDENCE}")


if __name__ == "__main__":
    try:
        main()
    except (MatchTimeout, Exception) as exc:  # noqa: BLE001
        print(f"ERR: {type(exc).__name__}: {exc}")
        raise SystemExit(3)
