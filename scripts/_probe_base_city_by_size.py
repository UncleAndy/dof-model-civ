"""Город по размерам и боевые каналы в базе `v2` — распределения.

Отвечает на два вопроса до всякого стенда:
  1. растёт ли DoF города с его размером (основа критерия «чем больше города, тем лучше»);
  2. различала ли прошлая линия инициатора боя (`бой.инициатор`) и как часто нападающий
     остаётся не наблюдённым (`нападение.нападающий = None`).

Только чтение.
"""
from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "baselines" / "world.json"


def median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def by_size(rec: list, field: str) -> dict[int, list[float]]:
    out: dict[int, list[float]] = collections.defaultdict(list)
    for e in rec:
        if not isinstance(e, dict):
            continue
        try:
            size = int(e.get("размер"))
            val = float(e.get(field))
        except (TypeError, ValueError):
            continue
        out[size].append(val)
    return out


def main() -> None:
    w = json.loads(BASE.read_text())
    obs = w.get("observed") or {}

    for field, name in (("значение", "dof_city"), ("значение", "dof_city_reach"),
                        ("значение", "city_size_options"), ("значение", "city_size_buildable")):
        rec = obs.get(name) or []
        groups = by_size(rec, field)
        if not groups:
            print(f"\n== {name}: нет записей с размером ==")
            continue
        print(f"\n== {name}: медиана по размеру города ==")
        for size in sorted(groups):
            vals = groups[size]
            print(f"   размер {size}: n={len(vals):4d}  медиана {median(vals):7.3f}  макс {max(vals):7.3f}")

    print("\n== бой: кто инициатор ==")
    combats = obs.get("бой") or []
    init = collections.Counter(str(e.get("инициатор")) for e in combats if isinstance(e, dict))
    print("   инициатор:", dict(init))
    owner = collections.Counter(str(e.get("владелец")) for e in combats if isinstance(e, dict))
    print("   владелец (чья сторона бой):", dict(owner))
    flags = collections.Counter()
    for e in combats:
        if isinstance(e, dict):
            for k in ("наш_потерян", "наш_ранен", "чужой_исчез", "чужой_ранен"):
                if e.get(k):
                    flags[k] += 1
    print("   что наблюдалось в бою:", dict(flags))

    print("\n== нападение: насколько часто виновный не наблюдён ==")
    att = obs.get("нападение") or []
    unknown = sum(1 for e in att if isinstance(e, dict) and not e.get("нападающий"))
    print(f"   записей {len(att)}, без нападающего {unknown}")
    kinds = collections.Counter(str(e.get("вид")) for e in att if isinstance(e, dict))
    print("   вид жертвы:", dict(kinds))
    hows = collections.Counter(str(e.get("как"))[:20] for e in att if isinstance(e, dict))
    print("   как (первые 20 знаков):", dict(hows.most_common(6)))


main()
