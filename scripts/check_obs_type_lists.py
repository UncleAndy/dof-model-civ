#!/usr/bin/env python
"""Есть ли в наблюдении список типов (чтобы надёжно отличить юнит от улучшения)?

Нужен признак «это юнит»: постановка производства-улучшения роняет контроллер
(`server_timeout_handle`), поэтому замер можно делать только по типам-юнитам. Гадать
по неполным каталогам нельзя — оба каталога извлекателя оказались неполными.

Проверка идёт по сохранённому наблюдению — стенд не нужен.

    python scripts/check_obs_type_lists.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def show(label, value, limit=200):
    text = json.dumps(value, default=str)
    print(f"{label}: {text[:limit]}")


def main() -> int:
    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    print("ключи наблюдения:", sorted(obs.keys()))
    for key in ("options", "game", "client", "rules"):
        section = obs.get(key) or {}
        print(f"\n=== {key}: {type(section).__name__}, ключей "
              f"{len(section) if hasattr(section, '__len__') else '—'}")
        if isinstance(section, dict):
            for name in sorted(section)[:40]:
                show(f"   {name}", section[name], 160)

    city = next(iter((obs.get("city") or {}).values()), {})
    if isinstance(city, dict):
        mask = city.get("can_build_unit")
        print(f"\n=== город 121: can_build_unit — {type(mask).__name__}, "
              f"истинных {sum(bool(v) for v in (mask or []))} из {len(mask or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
