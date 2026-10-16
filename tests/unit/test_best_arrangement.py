"""Тесты полного поиска расстановки (§13.461).

Главная проверка — сравнение с ПОЛНЫМ перебором на случайных данных: отсечение ветвей не имеет
права менять ответ. Если поиск хоть раз вернёт не максимум, тест это покажет.

Поведение при отсутствии годной расстановки взято у него: `cmr->found_a_valid = FALSE`, то есть
«годной нет» и вызывающий ничего не меняет. Поэтому при невыполнимости возвращается ПУСТОЙ набор, а
не «лучший из плохих»: выдумывать замену, которую он не делает, нельзя.
"""

import itertools
import random

from brain.ai_default.worker_manager import best_arrangement, factors, minimal_surplus, tile_value


def _bruteforce(yields_by_offset, *, size, candidates, food_cost=2.0, granary_full=False,
                notradesize=0):
    weights = factors(size, granary_full=granary_full, notradesize=notradesize)
    mins = minimal_surplus(granary_full=granary_full)
    slots = max(1, int(round(size)) + 1) - 1          # без центра
    need = food_cost * size
    c = yields_by_offset.get((0, 0), (1.0, 1.0, 0.0))
    cand = list(candidates)
    best = None
    for combo in itertools.combinations(cand, min(slots, len(cand))):
        food = c[0] + sum(yields_by_offset.get(o, (0.0, 0.0, 0.0))[0] for o in combo)
        shield = c[1] + sum(yields_by_offset.get(o, (0.0, 0.0, 0.0))[1] for o in combo)
        feas = (food - need >= mins["food"] - 1e-9) and (shield >= mins["shield"] - 1e-9)
        if not feas:
            continue
        val = (tile_value(*c, weights)
               + sum(tile_value(*yields_by_offset.get(o, (0.0, 0.0, 0.0)), weights) for o in combo))
        if best is None or val > best:
            best = val
    return best


def test_matches_bruteforce_on_random_sets():
    rnd = random.Random(20261016)
    checked = 0
    for _ in range(80):
        n = rnd.randint(1, 8)
        tiles = {(i, 0): (float(rnd.randint(0, 3)), float(rnd.randint(0, 2)),
                          float(rnd.randint(0, 2))) for i in range(1, n + 1)}
        size = rnd.choice([1, 2, 3])
        got = best_arrangement(tiles, size=size, candidates=list(tiles))
        bf = _bruteforce(tiles, size=size, candidates=list(tiles))
        if got["feasible"]:
            assert bf is not None, "поиск нашёл расстановку, а полный перебор — нет"
            assert abs(got["value"] - bf) < 1e-6, (got, bf)
            checked += 1
        else:
            assert bf is None, "полный перебор нашёл выполнимую, а поиск её пропустил"
    assert checked > 0, "на выбранных наборах ни разу не нашлось выполнимой расстановки"


def test_center_is_always_taken_and_free():
    tiles = {(1, 0): (3.0, 0.0, 0.0), (2, 0): (2.0, 0.0, 0.0)}
    got = best_arrangement(tiles, size=1, candidates=list(tiles))
    assert got["feasible"]
    assert (0, 0) in got["chosen"]


def test_picks_wanted_number_of_cells():
    tiles = {(i, 0): (2.0, 1.0, 1.0) for i in range(1, 6)}
    got = best_arrangement(tiles, size=2, candidates=list(tiles))
    assert got["feasible"], "центр 1 еды + две клетки по 2 еды при содержании 4 — годно"
    assert len(got["chosen"]) == 3, "центр + два жителя при размере 2"


def test_food_requirement_respected():
    # Без клетки с едой город размера 2 не пропитается: поиск обязан её взять, даже если по весам
    # щитовая клетка «дороже».
    tiles = {(1, 0): (0.0, 5.0, 0.0), (1, 1): (0.0, 5.0, 0.0), (2, 0): (5.0, 0.0, 0.0)}
    got = best_arrangement(tiles, size=2, candidates=list(tiles))
    assert got["feasible"], "еда есть — решение обязано быть выполнимым"
    assert (2, 0) in got["chosen"], "без этой клетки еды не хватает"
    assert got["surplus"]["food"] >= 0.0


def test_infeasible_reported_not_hidden():
    tiles = {(1, 0): (0.0, 5.0, 0.0)}
    got = best_arrangement(tiles, size=3, candidates=list(tiles))
    assert got["feasible"] is False, "невыполнимость обязана быть видна"
    assert got["chosen"] == [], "выдумывать замену он не делает: годной нет — набор пуст"
