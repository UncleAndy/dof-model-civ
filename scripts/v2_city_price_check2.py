"""Что агент знает про основание города: правила мира и оценка found_city.

Печатает из базы знаний (world.json) параметры мира, относящиеся к городам, и как считается цена
`found_city` (проекция семейства build_city). Не меняет ничего.

Запуск: .venv/bin/python scripts/v2_city_price_check2.py [knowledge/world.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "knowledge" / "world.json"
    data = json.loads(path.read_text())
    world = data.get("world") or {}
    print("== параметры мира (по городу) ==")
    for k in ("citymindist", "border_city_radius_sq", "xsize", "ysize", "food_box", "full_tile_info"):
        if k in world:
            print(f"  {k} = {world[k]}")
    rules = data.get("rules") or {}
    print(f"  rules.citymindist = {rules.get('citymindist')}")
    print(f"  rules.border_city_radius_sq = {rules.get('border_city_radius_sq')}")

    # работовая зона города (радиус-то квадратичный) и оценка основания
    br = rules.get("border_city_radius_sq", rules.get("border_city_radius_sq"))
    print(f"  border_city_radius_sq = {br} → радиус работовой зоны = "
          f"{sum(1 for a in range(-4, 5) for b in range(-4, 5) if a * a + b * b <= int(br or 0))} "
          f"клеток (при r_sq={br})")

    # есть ли у агента в эффекте `build_city` измеренная зависимость от места/урожая
    ents = data.get("entities") or []
    it = ents.items() if isinstance(ents, dict) else ((e.get("eid"), e) for e in ents)
    found = False
    for k, v in it:
        if not k:
            continue
        strk = str(k)
        if strk.startswith("unit") or "build_city" in strk:
            pass
        # контроллеры unit
        if strk.startswith("controller:unit"):
            rec = (v.get("effects") or {}).get("build_city") if isinstance(v.get("effects"), dict) else None
            if rec:
                found = True
                cc = rec.get("change_counts") or {}
                print(f"  эффект {strk}/build_city: наблюдений {rec.get('seen')}, "
                      f"изменений: {dict(list(cc.items())[:8])}")
    if not found:
        print("  записи эффекта build_city в базе нет (не наблюдался)")

    # сколько своих городов хранится и их урожай (если есть)
    cities = [e for k, e in (ents.items() if isinstance(ents, dict) else
                             ((e.get("eid"), e) for e in ents))
              if str(k).startswith("city:")]
    print(f"  городов в базе (последняя партия): {len(set(c.get('eid') for c in cities))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())