"""v2: sensors -> knowledge. Сборка графа мира из реального наблюдения и заморозка.

Проверка на реальных данных (правило проекта: сначала замер, потом интеграция).
Только чтение фикстур, запись — во временный файл.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.v2 import knowledge, sensors  # noqa: E402

OBS = "tests/fixtures/real_obs_01.json"
AVAIL = "tests/fixtures/real_available_actions.json"
OUT = "/tmp/v2_graph.json"


def main() -> int:
    obs = json.loads(Path(OBS).read_text())[0]["observation"]
    available = json.loads(Path(AVAIL).read_text())

    menu = sensors.read_menu(available)
    print("== секции меню мира ==")
    for section, actors in menu.items():
        n_valid = sum(1 for ak in actors for a, ok in actors[ak].items() if ok)
        n_all = sum(len(actors[ak]) for ak in actors)
        print(f"  {section}: акторов {len(actors)}, действий {n_all}, разрешено {n_valid}")
    print("  ВЫВОД: секции 'city' в меню нет" if "city" not in menu else "  секция city есть")

    g = knowledge.build_graph(obs, available, own_id=0)
    st = g.stats()
    print("\n== граф ==")
    print("  мир:", g.world)
    print("  сущностей:", st["entities"], st["by_kind"])
    print("  связей:", st["edges"], st["edges_by_kind"])
    print("  происхождение DoF:", st["dof_origins"])

    print("\n== измеренный DoF: каналы управления ==")
    for e in sorted(g.by_kind("controller"), key=lambda x: x.eid):
        print(f"  {e.name}: DoF = {e.dof}")

    print("\n== измеренный DoF: свои юниты ==")
    for e in sorted(g.by_kind("unit"), key=lambda x: x.eid):
        if e.is_own:
            print(f"  {e.eid} ({e.name}) x={e.attrs.get('x')},y={e.attrs.get('y')} "
                  f"moves={e.attrs.get('moves_left')}: DoF = {e.dof}")

    print("\n== DoF своих городов ==")
    for e in g.by_kind("city"):
        tag = "свой" if e.is_own else f"чужой(owner={e.owner})"
        print(f"  {e.eid} ({e.name}, {tag}) size={e.attrs.get('size')} "
              f"еда_прирост={e.attrs.get('surplus_food')} строимых={e.attrs.get('n_buildable')}: DoF = {e.dof}")

    print("\n== чужие акторы ==")
    for e in g.by_kind("unit"):
        if not e.is_own:
            print(f"  {e.eid} ({e.name}) owner={e.owner}: DoF = {e.dof}")

    # --- заморозка и обратная загрузка ---
    p = g.freeze(OUT)
    g2 = knowledge.KnowledgeGraph.load(OUT)
    same = (g2.stats()["entities"] == st["entities"] and g2.stats()["edges"] == st["edges"])
    print(f"\n== заморозка ==\n  {p} ({p.stat().st_size} байт); обратная загрузка совпала: {same}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())