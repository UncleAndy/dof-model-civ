#!/usr/bin/env python
"""Есть ли параметры типов в каталоге извлекателя? (офлайн, без стенда)

От этого зависит, можно ли оценить производство: опции типа берутся из каталога
(`unit_type_options`), а стоимость — из замера. Если каталога на нужный тип нет,
тип честно не предлагается (и попадает в отчёт как «без измеренной стоимости»).

Проверка идёт по сохранённой фикстуре реального наблюдения — стенд не нужен.

    python scripts/inspect_type_catalogue.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from env.entity_extractor import GameStateExtractor

    path = os.path.join(HERE, "tests", "fixtures", "real_obs_01.json")
    with open(path, encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    extractor = GameStateExtractor(my_player_id=0)
    result = extractor.extract(obs, {}, turn=1)
    bridge = result.state.bridge

    catalogue = bridge.unit_type_options
    print(f"каталог типов: {len(catalogue)} → {sorted(catalogue)[:14]}")
    print(f"улучшения: {len(bridge.improvement_options)} → "
          f"{sorted(bridge.improvement_options)[:10]}")

    units = obs.get("unit") or {}
    live = [(u.get("rule_name") or u.get("type"), u.get("type_build_cost"))
            for u in units.values() if isinstance(u, dict)]
    print(f"живых юнитов: {len(live)} → {live[:8]}")
    print(f"городов: {len(obs.get('city') or {})}")
    print(f"правил: {sorted((obs.get('rules') or {}).keys())[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
