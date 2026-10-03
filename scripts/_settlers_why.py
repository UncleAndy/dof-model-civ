"""Замер A: почему produce_Settlers не выбирается.

Печатает разложение цены производства (production_gain) по вариантам: DoF типа, срок (eta),
доля горизонта (frac), итог. Без правки кода — только чтение живой базы.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2.horizon import production_gain, eta_of, _horizon  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_def7.json")
H, hw = _horizon(g)
print(f"горизонт H = {H} ({hw})")
print(f"{'вариант':14s} {'DoF':>5s} {'eta':>6s} {'frac':>6s} {'gain':>8s}")
for t in ("Settlers", "Warriors", "Barracks", "Phalanx", "Horsemen", "Workers",
          "Chariot", "Catapult", "Courthouse"):
    eta, src = eta_of(g, t)
    te = g.entity(f"unit_type:{t}")
    fam = te.attrs.get("dof_families") if te is not None else None
    gv, why = production_gain(g, f"produce_{t}", actor=None)
    frac = min(1.0, H / float(max(1, eta))) if eta else None
    fr = f"{frac:.2f}" if frac is not None else "-"
    print(f"{t:14s} {str(fam):>5s} {str(eta):>6s} {fr:>6s} {gv:>8.3f}")
    if t in ("Settlers", "Warriors"):
        print(f"    почему: {why[:320]}")
