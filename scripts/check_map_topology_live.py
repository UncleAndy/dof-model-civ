#!/usr/bin/env python
"""Замыкается ли карта по Y — спрашиваем у САМОГО стенда.

Зачем. Наш `tile_output` делает `x %= xa; y %= ya`, то есть замыкает обе оси. Если
по Y карта не замыкается (у неё полюса), то площадка у полюса получает соседей с
другого края карты — величина площадки и гейт годности считаются по клеткам, которых
рядом нет.

У стенда есть прямые флаги: `TF_WRAPX = 1`, `TF_WRAPY = 2` и `wrap_has_flag()`.
Значит на вопрос можно ответить фактом, а не рассуждением о freeciv.

    python scripts/check_map_topology_live.py
"""
from __future__ import annotations

import os
import sys
import warnings

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def find_map_ctrl(root, max_depth=3):
    """Найти объект с `map_info` (идём по атрибутам пакета civrealm)."""
    stack = [(root, "env", 0)]
    seen: set[int] = set()
    while stack:
        obj, path, depth = stack.pop()
        if id(obj) in seen or depth > max_depth:
            continue
        seen.add(id(obj))
        info = getattr(obj, "map_info", None)
        if isinstance(info, dict) and ("wrap_id" in info or "topology_id" in info):
            return path, obj, info
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:  # noqa: BLE001
                continue
            if type(value).__module__.startswith("civrealm"):
                stack.append((value, f"{path}.{name}", depth + 1))
    return None, None, None


def main() -> int:
    import gymnasium

    from civrealm.configs import fc_args

    warnings.filterwarnings("ignore")
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset()

    path, ctrl, map_info = find_map_ctrl(env.unwrapped)
    if map_info is None:
        print("map_info не найден — вопрос о топологии остаётся открытым")
        return 0

    keys = ("topology_id", "wrap_id", "xsize", "ysize", "map_width", "map_height")
    print(f"map_info найден: {path}")
    print("   " + ", ".join(f"{k}={map_info.get(k)}" for k in keys
                            if map_info.get(k) is not None))
    for flag, name in ((1, "X"), (2, "Y")):
        try:
            answer = ctrl.wrap_has_flag(flag)
        except Exception as exc:  # noqa: BLE001
            answer = f"не прочиталось ({exc})"
        print(f"   замыкание по {name}: {answer}")
    try:
        print(f"   топология: iso={ctrl.topo_has_flag(4)} hex={ctrl.topo_has_flag(8)}")
    except Exception:  # noqa: BLE001
        pass

    # Размер карты из наблюдения — чтобы понять, насколько широка полоса у полюсов.
    layers = ((obs.get("map") or {}).get("output"))
    shape = getattr(layers, "shape", None)
    print(f"   форма слоя карты: {shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
