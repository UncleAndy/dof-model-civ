"""Проверка правила кандидатов (§13.64) на синтетических наблюдениях.

Положительный контроль рядом с отрицательным: правило обязано и различать, и ОТКАЗЫВАТЬ,
когда признак клетки недоступен. Живые данные этого не покажут: молчание правила и его
верное срабатывание выглядят одинаково.

Числа кандидатов проверяются ТОЧНО (== 1), а не «есть хоть один»: первая версия проверки
пропустила дефект — пустышка слоя 255 (`юнита нет`) читалась как чужой юнит на каждой
клетке, и «кандидатов 100» прошло как успех.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from env.spec_collapse_candidates import (       # noqa: E402
    EMPTY, classify_pair, extraneous_candidates, standing_on_own_tile, tile_owner_at,
)

XS, YS = 10, 10
ME = 0


def make_map(tile_owner=None, unit_owner=None, status=None):
    """Слои строятся В ПОРЯДКЕ МИРА: grid[y][x] (см. `spec_threat.foreign_units_from_map`)."""
    m = {}
    if tile_owner is not None:
        m["tile_owner"] = [[EMPTY for _ in range(XS)] for _ in range(YS)]
        for (x, y), v in tile_owner.items():
            m["tile_owner"][y][x] = v
    if unit_owner is not None:
        m["unit_owner"] = [[EMPTY for _ in range(XS)] for _ in range(YS)]
        for (x, y), v in unit_owner.items():
            m["unit_owner"][y][x] = v
    if status is not None:
        m["status"] = [[0 for _ in range(XS)] for _ in range(YS)]
        for (x, y) in status:
            m["status"][y][x] = 1
    return {"map": m}


failures = []


def check(name, cond, detail=""):
    print(f"{'OK  ' if cond else 'ПЛОХО'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


a = {"id": "uA", "owner": 2, "x": 5, "y": 5}
b = {"id": "uB", "owner": 3, "x": 6, "y": 6}

# 1. Положительный: A на чужой клетке, B на своей -> A нападающий, B защитник.
r = classify_pair(make_map(tile_owner={(5, 5): 1, (6, 6): 3}), a, b)
check("A на чужой клетке -> нападающий", r["attacker"] is a and r["defender"] is b, r["reason"])

# 2. Признак клетки недоступен (слоя tile_owner нет) -> ОБА кандидаты.
r2 = classify_pair(make_map(), a, b)
check("слой владельца клеток отсутствует -> оба кандидаты",
      r2["attacker"] is None and len(r2["candidates"]) == 2, r2["reason"])

# 3. Оба на своих клетках -> нападающий неразличим.
r3 = classify_pair(make_map(tile_owner={(5, 5): 2, (6, 6): 3}), a, b)
check("оба на своих клетках -> оба кандидаты",
      r3["attacker"] is None and len(r3["candidates"]) == 2, r3["reason"])

# 4. Оба на чужих -> оба кандидаты.
r4 = classify_pair(make_map(tile_owner={(5, 5): 1, (6, 6): 1}), a, b)
check("оба на чужих клетках -> оба кандидаты",
      r4["attacker"] is None and len(r4["candidates"]) == 2, r4["reason"])

# 5. Защитник не становится нападающим: B на своей клетке остаётся защитником.
r5 = classify_pair(make_map(tile_owner={(5, 5): 1, (6, 6): 3}), b, a)
check("порядок аргументов не меняет роль защитника",
      r5["attacker"] is a and r5["defender"] is b, r5["reason"])

# 6. Чужой юнит на нашей территории -> РОВНО один кандидат.
obs6 = make_map(tile_owner={(4, 4): ME}, unit_owner={(4, 4): 5}, status={(4, 4), (3, 4)})
c6 = extraneous_candidates(obs6, ME)
check("чужой юнит на нашей территории -> ровно один кандидат",
      len(c6) == 1 and c6[0]["owner"] == 5 and "нашей территории" in c6[0]["why"],
      f"кандидатов {len(c6)}")

# 7. Чужой юнит в открытых клетках, но не на нашей земле -> тоже кандидат, тоже один.
obs7 = make_map(tile_owner={(4, 4): 7}, unit_owner={(4, 4): 5}, status={(4, 4)})
c7 = extraneous_candidates(obs7, ME)
check("чужой юнит в открытых клетках -> ровно один кандидат",
      len(c7) == 1 and "открытых" in c7[0]["why"], f"кандидатов {len(c7)}")

# 8. Пустышка 255 не читается как чужой юнит (дефект первой версии).
obs8 = make_map(tile_owner={(2, 2): ME}, status={(2, 2)})
c8 = extraneous_candidates(obs8, ME)
check("пустышка слоя 255 не даёт кандидатов", len(c8) == 0, f"кандидатов {len(c8)}")

# 9. Наш собственный юнит кандидатом не становится.
obs9 = make_map(tile_owner={(2, 2): ME}, unit_owner={(2, 2): ME}, status={(2, 2)})
c9 = extraneous_candidates(obs9, ME)
check("свой юнит кандидатом не объявляется", len(c9) == 0, f"кандидатов {len(c9)}")

# 10. Чтение клетки: порядок мира [y][x].
obs10 = make_map(tile_owner={(3, 5): 42})
check("клетка читается как [y][x]", tile_owner_at(obs10, 3, 5) == 42,
      f"прочитано {tile_owner_at(obs10, 3, 5)}")
check("соседняя клетка не подменяется", tile_owner_at(obs10, 5, 3) is None,
      f"прочитано {tile_owner_at(obs10, 5, 3)}")

# 11. Признак «на своей клетке»: True / False / None.
check("на своей клетке -> True",
      standing_on_own_tile(make_map(tile_owner={(1, 1): 4}), 4, 1, 1) is True)
check("на чужой клетке -> False",
      standing_on_own_tile(make_map(tile_owner={(1, 1): 4}), 9, 1, 1) is False)
check("клетка не наблюдена -> None",
      standing_on_own_tile(make_map(), 4, 1, 1) is None)
check("пустышка клетки -> None (а не владелец 0)",
      standing_on_own_tile(make_map(tile_owner={(1, 1): EMPTY}), ME, 1, 1) is None)

print()
if failures:
    print(f"ПРОВЕРКА НЕ ПРОЙДЕНА: {len(failures)} — {failures}")
    raise SystemExit(1)
print("все проверки пройдены")
