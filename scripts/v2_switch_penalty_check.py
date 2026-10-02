"""Проверка цены отказа от постройки (§10.102) на живой базе знаний.

Считает `switch_penalty` для каждого своего города и показывает, перевешивает ли она выгоду смены
варианта производства. Печатает также медианную потерю щитов и текущую постройку города.

Запуск: .venv/bin/python scripts/v2_switch_penalty_check.py [knowledge/world.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.v2.horizon import switch_penalty, production_gain, eta_of  # noqa: E402
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "knowledge" / "world.json"
    g = KnowledgeGraph.from_dict(json.loads(path.read_text()))
    rows = [r for r in (g.observed.get("produce_switch") or [])
            if isinstance(r, dict) and r.get("сменил") is True]
    losses = sorted(int(r.get("потеряно") or 0) for r in rows)
    print(f"записей смены производства: {len(rows)}; потери щитов: "
          f"{losses[:12]}{'…' if len(losses) > 12 else ''}")
    cities = [e for e in g.by_kind("city") if e.is_own]
    print(f"своих городов в графе: {len(cities)}")
    for c in cities:
        actor = c.eid.split(":")[1]
        print(f"\nгород {actor}: размер {c.attrs.get('size')}, щиты {c.attrs.get('shield_stock')}, "
              f"чистый прирост {c.attrs.get('surplus_shield')}, стройка {c.attrs.get('стройка')!r}")
        for name in ("Barracks", "Warriors", "Settlers"):
            pen, pwhy = switch_penalty(g, actor, name)
            gain, gwhy = production_gain(g, f"produce_{name}", actor=actor)
            eta, esrc = eta_of(g, name)
            print(f"  produce_{name:9} срок {eta} ({esrc}); выгода {gain:+.3f}; "
                  f"цена отказа {pen:.3f}" + (f" — {pwhy}" if pwhy else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())