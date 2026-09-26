#!/usr/bin/env python
"""Подтверждение легенды map['terrain'] / map['extras'] данными мира.

Проверяем не репозиторий, а САМ СТЕНД:
  1) как закодирован слой extras (битовая маска или id-слой);
  2) совпадают ли выходы клеток с террейном (одинаковый террейн+экстра -> одинаковый output);
  3) даёт ли клетка с именованным ресурсом ровно тот выход, который задокументирован
     для civ2civ3 (Wheat 2/0/0, Oasis 3/0/0, Gold 0/0/6, Peat 0/4/0 ...).

Каждое совпадение — независимая проверка легенды. Использование:
    python scripts/inspect_terrain_legend.py                       # фикстура
    python scripts/inspect_terrain_legend.py --live                # живая игра (1 матч)
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

# Задокументированный выход клеток с именованными ресурсами (civ2civ3, из obs['rules']/руководства).
# Мы НЕ выводим из него выход — мы проверяем, что мир ему соответствует.
RESOURCE_OUTPUT = {
    "Wheat": (2, 0, 0), "Buffalo": (0, 2, 0), "Fish": (2, 0, 0), "Whales": (1, 1, 0),
    "Oasis": (3, 0, 0), "Oil": (0, 3, 0), "Gold": (0, 0, 6), "Iron": (0, 3, 0),
    "Wine": (0, 0, 4), "Silk": (0, 0, 3), "Gems": (0, 0, 4), "Fruit": (3, 0, 1),
    "Peat": (0, 4, 0), "Spice": (1, 0, 4), "Pheasant": (2, 0, 0), "Game": (2, 1, 0),
    "Coal": (0, 2, 0), "Ivory": (1, 1, 4), "Furs": (1, 0, 3),
}


def _load_fixture():
    d = json.load(open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json")))
    rec = d[0] if isinstance(d, list) else d
    obs = rec.get("observation", rec) if isinstance(rec, dict) else rec
    return obs


def _load_live(turns=1):
    import warnings
    warnings.filterwarnings("ignore")
    from civrealm.freeciv.utils.port_utils import Ports
    import gymnasium as gym
    import civrealm  # noqa: F401

    class MatchTimeout(Exception):
        pass

    def _on_alarm(signum, frame):
        raise MatchTimeout("match exceeded budget")

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(300)
    try:
        from civrealm.configs import fc_args
        env = gym.make("civrealm/FreecivBase-v0")
        port = Ports.get()
        print(f"live port: {port}", flush=True)
        obs, info = env.reset(client_port=port)
        return obs
    finally:
        signal.alarm(0)


def decode_extras(raw, x, y):
    """Слой extras — one-hot по каналу: канал i == экстра EXTRA_NAMES[i].

    Подтверждено на живом наблюдении: extras имеет форму (X, Y, 34) с булевыми
    значениями, то есть это не битовая маска и не id-слой.
    """
    a = np.asarray(raw)
    if a.ndim == 3:  # (X, Y, n_extras) — one-hot по каналу
        return [EXTRA_NAMES[i] for i in range(a.shape[2]) if a[x][y][i]], "onehot"
    v = int(a[x][y])  # (X, Y) — запасной вариант: битовая маска
    return [EXTRA_NAMES[i] for i in range(len(EXTRA_NAMES)) if v >> i & 1], "mask"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="взять карту из живой игры")
    p.add_argument("--turns", type=int, default=1)
    args = p.parse_args()

    obs = _load_live(args.turns) if args.live else _load_fixture()
    m = obs["map"]
    terrain, extras, output = m["terrain"], m["extras"], m["output"]
    ta, ea, oa = np.asarray(terrain), np.asarray(extras), np.asarray(output)
    print(f"shapes: terrain={ta.shape} extras={ea.shape} output={oa.shape}")

    # --- 1. кодировка extras и каналы output ---------------------------------
    eu = np.unique(ea)
    print(f"\n[1] extras: shape={ea.shape} dtype={ea.dtype} uniq={eu[:5].tolist()}"
          f"{' ...' if eu.size > 5 else ''} (n={eu.size})")
    if ea.ndim == 3:
        print(f"    -> one-hot по каналу: канал i == EXTRA_NAMES[i] "
              f"(каналов {ea.shape[2]} = {len(EXTRA_NAMES)} имён)")
        present = np.where(ea.any(axis=(0, 1)))[0]
        print(f"    экстры, реально встречающиеся на карте: "
              f"{[EXTRA_NAMES[i] for i in present]}")
    if oa.ndim == 3 and oa.shape[2] >= 3:
        print(f"    output: shape={oa.shape} (каналы {oa.shape[2]})")
        for c in range(oa.shape[2]):
            vals = oa[:, :, c]
            print(f"      канал {c}: min={vals.min()} max={vals.max()} "
                  f"сумма={vals.sum()} ненулевых={int((vals != 0).sum())}")

    # --- 2. согласованность террейн -> выход --------------------------------
    by_terrain = defaultdict(Counter)
    by_extra = Counter()
    h, w = ta.shape[:2]
    for x in range(h):
        for y in range(w):
            t = int(ta[x][y])
            if t >= len(TERRAIN_NAMES):
                continue
            out = tuple(np.asarray(oa[x][y]).ravel()[:3].astype(int).tolist())
            names, _ = decode_extras(ea, x, y)
            if names:
                continue  # чистый террейн — без экстр
            by_terrain[TERRAIN_NAMES[t]][out] += 1

    print("\n[2] выход клеток по террейну (без экстр): террейн -> выход × сколько клеток")
    for name in TERRAIN_NAMES:
        c = by_terrain.get(name)
        if not c:
            continue
        print(f"    {name:12s} {dict(c)}")

    # --- 2b. невидимые (незнаемые) клетки — Axiom 5/7 ------------------------
    tcount = Counter(int(ta[x][y]) for x in range(h) for y in range(w))
    total = h * w
    unknown = tcount.get(0, 0) + tcount.get(1, 0)  # Inaccessible / Lake
    known_tiles = total - unknown
    zero_out = int(((oa[:, :, 0] + oa[:, :, 1] + oa[:, :, 2]) == 0).sum())
    print(f"\n[2b] клеток всего {total}; Inaccessible={tcount.get(0, 0)}, "
          f"Lake={tcount.get(1, 0)}; клеток с нулевым выходом {zero_out}")
    print("     (нулевой выход у неисследованной клетки — это НЕ 'нулевые опции', "
          "а отсутствие знания: Axiom 5/7)")

    # --- 3. ресурсы: выход должен совпасть с задокументированным -------------
    for x in range(h):
        for y in range(w):
            names, _ = decode_extras(ea, x, y)
            resources = [n for n in names if n in RESOURCE_OUTPUT]
            if not resources:
                continue
            out = tuple(np.asarray(oa[x][y]).ravel()[:3].astype(int).tolist())
            for r in resources:
                by_extra[(r, out)] += 1

    print("\n[3] ресурс -> наблюдаемый выход (проверка против задокументированного):")
    ok = bad = unknown = 0
    for r in sorted(RESOURCE_OUTPUT, key=lambda n: (RESOURCE_OUTPUT[n])):
        rows = {o: c for (name, o), c in by_extra.items() if name == r}
        if not rows:
            print(f"    {r:10s} — на карте не встретился")
            unknown += 1
            continue
        want = RESOURCE_OUTPUT[r]
        for o, c in sorted(rows.items()):
            mark = "OK " if o == want else "MISMATCH"
            if o == want:
                ok += 1
            else:
                bad += 1
            print(f"    {r:10s} expected={want} observed={o} × {c:3d}  {mark}")
    print(f"\n  итог: совпало {ok}, расхождений {bad}, не встретилось {unknown}")

    if ok and not bad:
        print("  => ЛЕГЕНДА ПОДТВЕРЖДЕНА данными мира: имена ресурсов и их выход согласованы.")
    elif bad:
        print("  => ЛЕГЕНДА НЕ ПОДТВЕРЖДЕНА: есть расхождения, см. MISMATCH.")


if __name__ == "__main__":
    main()
