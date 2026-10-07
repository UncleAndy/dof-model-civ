"""Откуда у города берётся `V(сейчас) = 53` — разбор состава по живому наблюдению, офлайн.

Стенд не занят: читается сброс `knowledge/obs_dump_*.json`, снятый прибором `--dump-obs`. Печатает:
(1) что считает наша процедура (`measure_step` → `counts` для города, ровно то число, что идёт в индекс);
(2) из чего состоит меню города: все имена, имена с флагом мира `True`, и раскладка по семействам
(`city_work_*`, `city_unwork_*`, `produce_*`, `city_sell_improvement_*`, прочее).
Ответ на вопрос «норма для `V(сейчас)`»: узкое «сейчас» — флаги мира, широкое — то, что считает процедура.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civrealm" / "src"))
sys.path.insert(0, str(ROOT))


def family(name: str) -> str:
    for pref in ("city_work_", "city_unwork_", "city_sell_improvement_",
                 "produce_", "city_buy_", "city_change_"):
        if name.startswith(pref):
            return pref
    return "прочее"


def main() -> int:
    dumps = sorted((ROOT / "knowledge").glob("obs_dump_*.json"))
    if not dumps:
        print("[разбор] сбросов нет — сначала прогон с --dump-obs")
        return 1
    dump = dumps[-1]
    d = json.loads(dump.read_text(encoding="utf-8"))
    obs, info = d["observation"], {"available_actions": d.get("available_actions"), "turn": d.get("turn")}
    print(f"[разбор] {dump.name}, ход {d.get('turn')}")

    from env import spec_obs as SO           # noqa: PLC0415
    from env.entity_extractor import GameStateExtractor  # noqa: PLC0415

    ex = GameStateExtractor(my_player_id=0)
    m = SO.measure_step(obs, info, d.get("turn"), ex, prev_obs=None, my_player_id=0)
    counts = m.get("counts") or {}
    cities = {k: v for k, v in counts.items() if str(k).startswith("city_")}
    print(f"[разбор] считает наша процедура (идёт в индекс): {cities}")
    print(f"[разбор] всего сущностей в счёте {len(counts)}; V_всего {sum(counts.values()):.1f}")
    vm = m.get("v_max") or {}
    print(f"[разбор] потолок города (весь каталог): {vm}")

    for cid in sorted(cities):
        names = list(m["raw_menus"].get(cid) or [])
        acts = ((info["available_actions"] or {}).get("city") or {})
        offered = None
        for k in (cid.split("_", 1)[1], int(cid.split("_", 1)[1]) if cid.split("_", 1)[1].isdigit() else None):
            if isinstance(acts, dict) and k in acts:
                offered = acts[k]
                break
        flags = offered if isinstance(offered, dict) else {}
        truthy = [n for n, v in flags.items() if v] if flags else []
        all_names = list(flags) or names
        print(f"\n[город {cid}] считано {cities[cid]:.1f}")
        print(f"  имён в меню: {len(all_names)}; флаг мира True: {len(truthy)} → {sorted(truthy)}")
        print("  раскладка ВСЕХ имён: " + ", ".join(
            f"{fam}={n}" for fam, n in sorted(Counter(family(str(x)) for x in all_names).items())))
        print("  раскладка ИСТИННЫХ: " + ", ".join(
            f"{fam}={n}" for fam, n in sorted(Counter(family(str(x)) for x in truthy).items())))
        print(f"  в сырых векторах процедуры имён: {len(names)}")
        counted = (m.get("vectors") or {}).get(cid) or []
        print(f"  СЧИТАННЫЕ имена ({len(counted)}): {sorted(counted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())