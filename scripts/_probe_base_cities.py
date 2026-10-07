"""Что база `v2` (baselines/world.json) уже знает про города.

Правило проекта: прежде чем мерить заново, посмотри, что уже измерено. База — это
28 244 наблюдения из 107 партий прошлой линии; здесь из неё вынимается всё, что
касается города: намеренные эффекты, каналы наблюдений, сущности.

Только чтение.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "baselines" / "world.json"


def main() -> None:
    w = json.loads(BASE.read_text())
    print("верхние разделы:", sorted(w.keys()))
    world = w.get("world") or {}
    print("мир:", {k: world.get(k) for k in ("xsize", "ysize", "players", "games") if k in world})
    print("наблюдений:", w.get("observations"))

    print("\n-- эффекты, связанные с городом --")
    effects = w.get("effects") or {}
    for key, rec in sorted(effects.items()):
        if "city" not in key.lower():
            continue
        if not isinstance(rec, dict):
            print(f"  {key}: {type(rec).__name__}")
            continue
        print(f"  {key}: seen={rec.get('seen')}")
        cc = rec.get("change_counts") or {}
        num = [(int(k), v) for k, v in cc.items() if str(k).lstrip("-").isdigit()]
        if num:
            print(f"      переходы (топ-5): {sorted(num, key=lambda kv: -kv[1])[:5]}")
        horiz = rec.get("horizon") or {}
        if horiz:
            print(f"      горизонт: {horiz}")

    print("\n-- каналы наблюдений --")
    observed = w.get("observed") or {}
    for key, rec in sorted(observed.items()):
        if not isinstance(rec, dict):
            print(f"  {key}: {type(rec).__name__}")
            continue
        print(f"  {key}: полей {len(rec)}, ключи {sorted(rec.keys())[:7]}")

    print("\n-- сущности --")
    ents = w.get("entities") or {}
    kinds: dict[str, int] = {}
    for name in ents:
        kind = str(name).split("/")[0].split("_")[0]
        kinds[kind] = kinds.get(kind, 0) + 1
    print("  видов:", sorted(kinds.items(), key=lambda kv: -kv[1])[:8])
    for key in ("rules", "edges"):
        v = w.get(key)
        if isinstance(v, dict):
            print(f"  {key}: разделов {len(v)}, ключи {sorted(v.keys())[:5]}")
        elif isinstance(v, list):
            print(f"  {key}: элементов {len(v)}")
        else:
            print(f"  {key}: {type(v).__name__}")


main()
