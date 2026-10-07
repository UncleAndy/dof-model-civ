"""Содержимое городских каналов базы `v2`: что именно в них лежит и сколько.

База — 28 244 наблюдения из 107 партий. Каналы города: `city_output`,
`city_own_families`, `city_size_options`, `city_size_buildable`, `dof_city`,
`dof_city_reach`, `produce_eta`, `produce_switch`. Здесь показывается объём каждого
и структура одной записи; плюс агрегаты по `dof_city`, если они в числах.

Только чтение.
"""
from __future__ import annotations

import collections
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "baselines" / "world.json"

CHANNELS = ("city_output", "city_own_families", "city_size_options", "city_size_buildable",
            "dof_city", "dof_city_reach", "produce_eta", "produce_switch",
            "нападение", "бой", "владелец_нападал")


def shape(x: Any) -> str:
    if isinstance(x, dict):
        return f"объект, полей {len(x)}: {sorted(x.keys())[:8]}"
    if isinstance(x, list):
        return f"список, элементов {len(x)}"
    return type(x).__name__


def numbers(x: Any, out: list[float]) -> None:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        out.append(float(x))
    elif isinstance(x, dict):
        for v in x.values():
            numbers(v, out)
    elif isinstance(x, list):
        for v in x:
            numbers(v, out)


def main() -> None:
    w = json.loads(BASE.read_text())
    obs = w.get("observed") or {}
    print("каналов всего:", len(obs))
    for name in CHANNELS:
        rec = obs.get(name)
        if rec is None:
            print(f"\n== {name}: НЕТ В КАНАЛАХ ==")
            continue
        print(f"\n== {name}: {shape(rec)} ==")
        sample = rec[0] if isinstance(rec, list) and rec else (rec if isinstance(rec, dict) else None)
        if isinstance(sample, dict):
            print("   поля записи:", sorted(sample.keys()))
            for k, v in list(sample.items())[:8]:
                print(f"     {k} = {str(v)[:90]}")
        nums: list[float] = []
        numbers(rec, nums)
        if nums:
            nums.sort()
            n = len(nums)
            print(f"   чисел {n}: мин {nums[0]:.3f}  медиана {nums[n // 2]:.3f}  макс {nums[-1]:.3f}")

    print("\n-- эффекты города и нападений (seen, горизонт) --")
    effects = w.get("effects") or {}
    for key, rec in sorted(effects.items()):
        low = key.lower()
        if not ("city" in low or "attack" in low or "бой" in low):
            continue
        if not isinstance(rec, dict):
            continue
        h = rec.get("horizon") or {}
        grew = h.get("city_grew") if isinstance(h, dict) else None
        print(f"  {key}: seen={rec.get('seen')}, city_grew={grew}")

    print("\n-- нападения: сколько и с какими полями --")
    att = obs.get("нападение") or obs.get("бой") or []
    if isinstance(att, list) and att:
        c = collections.Counter()
        for e in att:
            if isinstance(e, dict):
                c.update(e.keys())
        print("   записи:", len(att), "поля:", dict(c))


main()
