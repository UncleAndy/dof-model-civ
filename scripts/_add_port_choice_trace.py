"""Связанный след: что перенос отложил и что осталось ПОСЛЕ отбора (§13.289).

Зачем. Из следа нельзя было отличить три разных случая: правило отложило работу, правило
промолчало, или отбор случился в другом решении того же хода (замер дал одновременно
«irrigation отложено» и отправку `unit/irrigation` — без связи по ходу это неразличимо).
Теперь печатается и что отложено, и что ОСТАЛОСЬ, одним сообщением на отбор.

Идемпотентно.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

OLD = """        out.append(c)
    if not out:
        return cands
    return out"""

NEW = """        out.append(c)
    if not out:
        return cands
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # След связывает отбор с исходом: видно, что осталось ПОСЛЕ правила, а не только что
        # оно отложило. Без этого «отложено» и «отправлено» в одном ходу выглядят как
        # противоречие, хотя могут быть разными решениями.
        _left = sorted({str(_to_action(c)[2]) for c in out
                        if _to_action(c) and str(_to_action(c)[2]) in ("mine", "irrigation")})
        _picked = ", ".join(f"{a}->{w}" for a, w in sorted(keep.items()))
        print(f"  [работа-перенос] выбор: {_picked}; осталось работ: {_left}", flush=True)
    return out"""

text = PATH.read_text(encoding="utf-8")
if "[работа-перенос] выбор:" in text:
    print("уже внесено")
else:
    assert text.count(OLD) == 1, "якорь не однозначен"
    PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("внесено")
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
