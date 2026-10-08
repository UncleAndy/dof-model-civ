"""Проверка §13.79: пустой набор расчёта называет своё состояние, непустой — молчит.

Три предмета: (1) посылка долга — индекс по пустому набору равен 0.0; (2) названное состояние
ноля — `calc_set_reason`; (3) проводка — ключи доехали до записи хода в прогоне.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_lenses as L            # noqa: E402
from env.spec_obs import calc_set_reason     # noqa: E402

ok = fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok   {name}")
    else:
        fail += 1
        print(f"  ПАДЕНИЕ {name} {detail}")


print("── посылка долга: индекс по пустому набору ──")
empty = L.total_index({})
check("пустой набор даёт ровно 0.0", empty == 0.0, f"получено {empty!r}")

print("── названное состояние ноля ──")
r_empty = calc_set_reason(0, 7)
check("пустой набор назван", isinstance(r_empty, str) and "пуст" in r_empty, f"{r_empty!r}")
check("в причине сказано, что 0.0 значит «считать нечего»",
      isinstance(r_empty, str) and "считать нечего" in r_empty, f"{r_empty!r}")
check("в причине названо число измеренных",
      isinstance(r_empty, str) and "7" in r_empty, f"{r_empty!r}")
check("непустой набор молчит", calc_set_reason(3, 3) is None,
      f"{calc_set_reason(3, 3)!r}")
check("не посчитанный набор назван по ошибке",
      "ValueError" in (calc_set_reason(None, 2, "ValueError: boom") or ""),
      f"{calc_set_reason(None, 2, 'ValueError: boom')!r}")
check("непосчитанный без причины тоже назван",
      calc_set_reason(None, 2) is not None)

print("── проводка: ключи в записи хода ──")
runner = (ROOT / "scripts" / "v011_live_run.py").read_text(encoding="utf-8")
for key in ('"в_расчёте"', '"индекс_ядра"', '"причина_набора"'):
    check(f"в прогоне есть ключ {key}", key in runner)

print(f"\nитог: проверок {ok + fail}, прошло {ok}, падений {fail}")
sys.exit(1 if fail else 0)
