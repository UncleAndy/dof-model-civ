"""Что накопила база знаний агента: наборы возможностей типов и словарь каналов.

Читает файл базы (по умолчанию knowledge/world.json, можно передать свой) и печатает
содержимое. Ничего не измеряет сам — показывает то, что агент уже добыл в играх.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.v2.store import KnowledgeStore  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v2_knowledge.json"
store = KnowledgeStore(path)
print(store.report(limit=0))
print("\n== наборы возможностей по типам ==")
for e in sorted(store.graph.by_kind("unit_type"), key=lambda x: x.eid):
    caps = e.attrs.get("capabilities") or []
    if caps:
        print(f"  {e.name}: {len(caps)} (наблюдений {e.attrs.get('observations', 0)})")
        print(f"     {', '.join(caps)}")
print("\n== словарь каналов управления ==")
for e in sorted(store.graph.by_kind("controller"), key=lambda x: x.eid):
    caps = e.attrs.get("capabilities") or []
    print(f"  {e.name}: {len(caps)}")
print(f"\nправил мира в базе: {len(store.graph.rules)}")