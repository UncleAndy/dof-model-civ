"""Вариант 1: ценность produce_Settlers по городу, который он создаст.

Считает цену по формуле production_gain для разных eta и показывает, при каком сроке
поселенец обгоняет воина. Ничего не меняет — только числа.
"""
from __future__ import annotations

import math
import sys

sys.path.insert(0, ".")
from brain.v2.knowledge import KnowledgeGraph  # noqa: E402
from brain.v2.calculus import impute  # noqa: E402

g = KnowledgeGraph.load(sys.argv[1] if len(sys.argv) > 1 else "knowledge/world_def7.json")
H, hw = _h = __import__("brain.v2.horizon", fromlist=["_horizon"])._horizon(g)

ic, _ = impute(g, "city")      # DoF города (достижимое, размер 1)
sett = g.entity("unit_type:Settlers")
dof_sett = sett.attrs.get("dof_families") if sett is not None else None
war = g.entity("unit_type:Warriors")
dof_war = war.attrs.get("dof_families") if war is not None else None

print(f"H = {H:.2f},  DoF города = {ic},  DoF Settlers = {dof_sett},  DoF Warriors = {dof_war}")
print(f"ln(город) = {math.log(ic):.3f}   ln(Settlers) = {math.log(dof_sett):.3f}   "
      f"ln(Warriors) = {math.log(dof_war):.3f}")

war_gain = math.log(dof_war)  # eta воина 5 ≤ H → frac = 1
print(f"\nцена Warriors (eta 5, frac=1) = {war_gain:.3f}")
print(f"{'eta':>5s} {'frac':>6s} {'СЕЙЧАС ln13×f':>14s} {'ВАР1 ln22×f':>13s} {'ВАР1 без frac':>14s}")

def fmt(x):
    return f"{x:.3f}"

for eta in (38, 30, 20, 15, 10, 8, 7, 6, 5, 4):
    frac = min(1.0, H / float(eta))
    now = math.log(dof_sett) * frac
    v1 = math.log(ic) * frac
    v1nf = math.log(ic)
    mark = "  ← обгоняет воина" if v1 > war_gain else ""
    print(f"{eta:>5d} {frac:>6.2f} {fmt(now):>14s} {fmt(v1):>13s} {fmt(v1nf):>14s}{mark}")

# порог: при каком eta вариант 1 (с frac) обгоняет воина
frac_need = war_gain / math.log(ic)
eta_need = H / frac_need
print(f"\nПорог: чтобы обогнать воина, нужно frac ≥ {frac_need:.3f} → eta ≤ {eta_need:.1f} ходов")
print("Фактический срок поселенца в игре: 38 ходов (размер города 1).")
