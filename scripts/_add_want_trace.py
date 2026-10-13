"""След желания Workers/Settlers: причина обнуления должна быть ВИДНА замером.

Без этого `_reason` вычисляется и выбрасывается, а «поселенец не ставится» остаётся
догадкой. Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "forecast" / "live.py"

OLD = '''            if type_name == "Workers":
                _w, _reason = worker_want(rec)
                if _w > 0.0:'''
NEW = '''            if type_name == "Workers":
                _w, _reason = worker_want(rec)
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [желание] город {city_id}: Workers {_w:.3f} — {_reason}",
                          flush=True)
                if _w > 0.0:'''

OLD2 = '''            elif type_name == "Settlers":
                _w, _reason = founder_want(rec)
                if _w > 0.0:'''
NEW2 = '''            elif type_name == "Settlers":
                _w, _reason = founder_want(rec)
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [желание] город {city_id}: Settlers {_w:.3f} — {_reason}",
                          flush=True)
                if _w > 0.0:'''

text = PATH.read_text(encoding="utf-8")
n = 0
for old, new in ((OLD, NEW), (OLD2, NEW2)):
    if new in text:
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old.strip()[:40]}"
    text = text.replace(old, new)
    n += 1
PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {n}")
assert "import os" in text.split("\n\n", 1)[0] or "\nimport os" in text, "нет import os"
print("import os на месте")
