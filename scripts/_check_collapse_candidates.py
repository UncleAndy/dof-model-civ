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
    EMPTY, classify_loss, classify_pair, extraneous_candidates, loss_events,
    standing_on_own_tile, tile_owner_at,
)

XS, YS = 10, 10
ME = 0


def make_map(tile_owner=None, unit_owner=None, status=None, city_owner=None):
    """Слои строятся В ИЗМЕРЕННОМ ПОРЯДКЕ МИРА: grid[x][y] (§13.99).

    Порядок установлен замером на своих: координаты юнитов и города публикуются в `unit`/`city`, и
    `map.unit_owner` показывает наш id на них только при чтении `[x][y]` — четыре из четырёх.
    Сетка тут квадратная (10x10), поэтому транспозиция формой не ловится: её надо именно знать.
    """
    m = {}
    if tile_owner is not None:
        m["tile_owner"] = [[EMPTY for _ in range(YS)] for _ in range(XS)]
        for (x, y), v in tile_owner.items():
            m["tile_owner"][x][y] = v
    if city_owner is not None:
        m["city_owner"] = [[EMPTY for _ in range(YS)] for _ in range(XS)]
        for (x, y), v in city_owner.items():
            m["city_owner"][x][y] = v
    if unit_owner is not None:
        m["unit_owner"] = [[EMPTY for _ in range(YS)] for _ in range(XS)]
        for (x, y), v in unit_owner.items():
            m["unit_owner"][x][y] = v
    if status is not None:
        m["status"] = [[0 for _ in range(YS)] for _ in range(XS)]
        for (x, y) in status:
            m["status"][x][y] = 1
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

# 12. Чужие потери: исчезнувший юнит и город, сменивший владельца.
prev12 = make_map(tile_owner={(4, 4): 5, (3, 3): 4}, unit_owner={(4, 4): 5},
                  city_owner={(3, 3): 4}, status={(4, 4)})
obs12 = make_map(tile_owner={(3, 3): 6}, city_owner={(3, 3): 6}, status={(3, 3)})
ev12 = loss_events(prev12, obs12, ME)
check("исчезновение чужого юнита -> событие",
      any(e["kind"] == "unit" and e["owner"] == 5 for e in ev12), f"событий {len(ev12)}")
check("город сменил владельца -> событие перехода",
      any(e["kind"] == "city" and e.get("new_owner") == 6 for e in ev12), f"событий {len(ev12)}")

# 13. Единственный видимый чужой рядом с местом потери -> кандидат.
obs13 = make_map(tile_owner={(4, 3): 6}, unit_owner={(4, 3): 6}, status={(4, 3)})
r13 = classify_loss(obs13, {"x": 4, "y": 4}, ME)
check("один чужой рядом с местом потери -> кандидат",
      len(r13["candidates"]) == 1 and r13["candidates"][0]["owner"] == 6, r13["reason"])

# 14. Двое рядом: на своей клетке — защитник, на чужой — нападающий.
obs14 = make_map(tile_owner={(4, 3): 6, (5, 4): 3},
                 unit_owner={(4, 3): 6, (5, 4): 7}, status={(4, 3), (5, 4)})
r14 = classify_loss(obs14, {"x": 4, "y": 4}, ME)
check("двое рядом -> нападающий различим по клетке",
      r14["attacker"] is not None and r14["attacker"]["owner"] == 7, r14["reason"])

# 15. Никого рядом -> кандидатов нет: догадка из тумана не считается.
r15 = classify_loss(make_map(tile_owner={(8, 8): 6}), {"x": 4, "y": 4}, ME)
check("никого рядом -> кандидатов нет",
      not r15["candidates"] and "не наблюдён" in r15["reason"], r15["reason"])

print()
if failures:
    print(f"ПРОВЕРКА НЕ ПРОЙДЕНА: {len(failures)} — {failures}")
    raise SystemExit(1)
print("все проверки пройдены")
