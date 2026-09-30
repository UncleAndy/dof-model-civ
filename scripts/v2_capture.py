"""Живая съёмка: наблюдение + меню с одного хода, затем накопление графа по ходам.

Зачем: (1) фикстуры сняты в разное время и между собой не согласованы, поэтому измеренный DoF
на них не проверить; (2) набор возможностей сущности обязан НАКАПЛИВАТЬСЯ (нулевое знание).

Только чтение стенда: reset + N ходов «ничего не делать» (None закрывает ход). Запись — в /tmp.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401  (регистрирует civrealm/FreecivBase-v0)
from civrealm.configs import fc_args  # noqa: E402

from brain.v2 import knowledge, sensors  # noqa: E402
from brain.v2.provenance import json_default  # noqa: E402

SEED = int(os.environ.get("V2_SEED", "9000"))
PORT = int(os.environ.get("V2_PORT", "6300"))
TURNS = int(os.environ.get("V2_TURNS", "6"))
OUT = f"/tmp/v2_capture_seed{SEED}.json"


def main() -> int:
    fc_args["client_port"] = PORT
    print(f"[съёмка] порт {PORT}, сид {SEED}, ходов {TURNS}", flush=True)
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=PORT, seed=SEED)
    try:
        my_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        my_id = None
    own_id = my_id if my_id is not None else 0
    print(f"[съёмка] свой id: {own_id}", flush=True)

    graph: knowledge.KnowledgeGraph | None = None
    city_section_seen = False
    for t in range(1, TURNS + 1):
        available = (info or {}).get("available_actions") or {}
        if "city" in available:
            city_section_seen = True
        graph = knowledge.build_graph(obs, available, own_id=own_id, prior=graph)
        turn = (info or {}).get("turn")
        units = [e for e in graph.by_kind("unit") if e.is_own]
        cities = [e for e in graph.by_kind("city") if e.is_own]
        print(f"\n── ход {t} (мир: turn={turn}) ──")
        print(f"  наблюдений в графе: {graph.observations}; своих юнитов {len(units)}, "
              f"городов {len(cities)}; секция city: {'да' if 'city' in available else 'нет'}")
        for e in sorted(units, key=lambda x: x.eid):
            caps = graph.entity(f"unit_type:{e.name}").attrs.get("capabilities") if e.name else []
            print(f"    {e.eid} {e.name}: DoF={e.dof} (набор типа: {len(caps or [])})")
        for e in sorted(cities, key=lambda x: x.eid):
            print(f"    {e.eid} {e.name}: DoF={e.dof} size={e.attrs.get('size')}")
        if t == 1:
            Path(OUT).write_text(json.dumps(
                {"seed": SEED, "port": PORT, "my_id": my_id, "turn": turn,
                 "observation": obs, "available_actions": available},
                ensure_ascii=False, default=json_default))
            print(f"  [съёмка] записано: {OUT}")
        obs, _reward, terminated, truncated, info = env.step(None)
        if terminated or truncated:
            print("  партия окончена миром")
            break

    assert graph is not None
    print("\n== накопленные наборы возможностей по типам ==")
    for e in sorted(graph.by_kind("unit_type"), key=lambda x: x.eid):
        caps = e.attrs.get("capabilities")
        if caps:
            print(f"  {e.name}: {len(caps)} — {', '.join(caps)}")
    print("\n== каналы управления (набор накоплен) ==")
    for e in sorted(graph.by_kind("controller"), key=lambda x: x.eid):
        caps = e.attrs.get("capabilities") or []
        print(f"  {e.name}: DoF={e.dof}, накоплено {len(caps)}")
    print(f"\n  секция city за {TURNS} ходов: {'появлялась' if city_section_seen else 'НЕ появлялась'}")

    gp = graph.freeze(f"/tmp/v2_graph_seed{SEED}.json")
    print(f"[съёмка] граф заморожен: {gp} ({gp.stat().st_size} байт)")
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())