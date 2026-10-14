"""ЗАМЕР перед правкой: какую расстановку жителей выбрал бы УПРАВЛЯЮЩИЙ, а какую — наша мера.

Зачем. В его коде это два разных решения разными мерами (§13.314):

* какие клетки обрабатывают жители — управляющий `cm.c`: максимум взвешенной суммы
  (`city_manager.score`) при обязательных порогах (`city_manager.minimums_ok`,
  `server/cityturn.c:346-355`), с его ПОВТОРОМ при неудаче (`cityturn.c:430-434`);
* какую клетку улучшать рабочему — `city_tile_value` (`infracache.c:293`, наш `city_tiles`).

Наш путь расстановки построен на второй. Замер отвечает на вопрос, РАЗЛИЧАЮТСЯ ли выборы —
и если да, то насколько по еде и щитам. Никаких правок здесь нет: только счёт.

Вход: срез `/tmp/dof_state_dump.jsonl`, поле города `рабочие_клетки` (числа нашего читателя
карты — те же, что видит живой путь).
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.ai_default import city_manager as cm  # noqa: E402
from brain.ai_default.values import city_tile_value  # noqa: E402


def _rows(path: str = "/tmp/dof_state_dump.jsonl") -> list[dict]:
    return [json.loads(line) for line in
            pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _weighted(tile: dict, food_factor: int) -> float:
    """Взвешенный вклад клетки по `city_manager.score` (торговля делится как в его формуле)."""
    return (tile["food"] * food_factor
            + tile["shield"] * cm.SHIELD_FACTOR
            + tile.get("trade", 0.0) * cm.GOLD_FACTOR)


def _arrangements(city: dict, tiles: list[dict]):
    """Две расстановки: по мере рабочего и по мере управляющего (обе — лучшие `размер` клеток)."""
    size = int(city.get("size") or 1)
    known = [t for t in tiles if t.get("known") and not t.get("center")]
    center = [t for t in tiles if t.get("known") and t.get("center")]
    if not known:
        return None
    by_worker = sorted(known, key=lambda t: -float(
        city_tile_value(t["food"], t["shield"], t["trade"])))[:size]
    granary_full = bool(int(city.get("food_stock") or 0) >= cm.granary_size(size))
    factor = cm.food_factor(size, granary_full)
    by_manager = sorted(known, key=lambda t: -_weighted(t, factor))[:size]
    return size, by_worker + center, by_manager + center, granary_full


def _totals(tiles: list[dict], size: int, food_cost: float) -> tuple[float, float]:
    # центр уже добавлен вызывающим: он обрабатывается без жителя
    food = sum(t["food"] for t in tiles)
    shield = sum(t["shield"] for t in tiles)
    return food - food_cost * size, shield


def main() -> None:
    rows = _rows()
    cities = [(r, c) for r in rows for c in (r.get("my_cities") or [])]
    if not cities:
        print("в срезе нет наших городов")
        return
    last_id = cities[-1][1].get("id")
    same = [c for _, c in cities if c.get("id") == last_id]
    diffs = Counter()
    print(f"город {last_id}: наблюдений {len(same)}")
    for city in same:
        got = _arrangements(city, city.get("рабочие_клетки") or [])
        if not got:
            continue
        size, by_worker, by_manager, granary_full = got
        food_cost = float(city.get("food_cost") or 2.0)
        w_surplus, w_shield = _totals(by_worker, size, food_cost)
        m_surplus, m_shield = _totals(by_manager, size, food_cost)
        key = (int(w_surplus), int(m_surplus), int(w_shield), int(m_shield))
        diffs[key] += 1
    print(f"\n{'мера рабочего (излишек/щиты)':>30} | {'управляющий (излишек/щиты)':>28} | раз")
    for (ws, ms, wsh, msh), n in diffs.most_common():
        flag = "  ← РАЗНЫЕ" if (ws != ms or wsh != msh) else ""
        print(f"{f'{ws}/{wsh}':>30} | {f'{ms}/{msh}':>28} | {n}{flag}")
    differ = sum(n for (ws, ms, wsh, msh), n in diffs.items()
                 if ws != ms or wsh != msh)
    total = sum(diffs.values())
    print(f"\nрасстановки РАЗЛИЧАЮТСЯ в {differ} из {total} наблюдений")
    if differ:
        food_gain = sum((ms - ws) * n for (ws, ms, _w, _m), n in diffs.items())
        print(f"управляющий даёт суммарно на {food_gain} больше излишка еды (по наблюдениям)")


if __name__ == "__main__":
    main()
