"""Правило F «еда необратима» (`env/food_gate.py`, замер §10.30).

Проверяется ровно то, что правило объявляет: три семейства и границы, взятые ИЗ ЗАМЕРА
(`food_cost = 2`, наибольшая еда клетки = 3), а не «на глаз». Отдельно проверяется, что
правило НЕ трогает остальные действия и не выносит запрет без факта мира.
"""
import pytest

from env.food_gate import (
    DEFAULT_FOOD_COST,
    MAX_TILE_FOOD,
    city_at,
    city_by_id,
    denial_report,
    denies,
    food_cost_of,
    reset_log,
    tile_food,
)


def _obs(cells=None, rules=None, cities=None):
    """Наблюдение с картой: `cells[(x, y)] = [еда, щиты, торговля, 0, 0, 0]`."""
    size = 6
    output = [[[0, 0, 0, 0, 0, 0] for _ in range(size)] for _ in range(size)]
    for (x, y), vec in (cells or {}).items():
        output[x][y] = list(vec)
    obs = {"map": {"output": output}}
    if rules is not None:
        obs["rules"] = rules
    if cities is not None:
        obs["city"] = cities
    return obs


def _city(x=3, y=3, surplus=1.0, size=2, owner=0):
    return {"id": 131, "x": x, "y": y, "size": size,
            "surplus_food": surplus, "owner": owner}


@pytest.fixture(autouse=True)
def _clean_log():
    reset_log()
    yield
    reset_log()


class TestUnwork:
    """`city_unwork_<idx>_<dx>_<dy>` убирает еду ЦЕЛЕВОЙ клетки."""

    def test_below_tile_food_is_denied(self):
        # Клетка (−1,+2) даёт 2 еды, у города запас 1 → после перевода будет −1.
        obs = _obs({(2, 5): [2, 1, 0, 0, 0, 0]})
        deny, why = denies("city_unwork_16_-1_2", city=_city(surplus=1.0), obs=obs)
        assert deny is True
        assert "2" in why and "1" in why

    def test_equal_to_tile_food_is_allowed(self):
        # surplus == еда клетки → после перевода ровно 0; замер: surplus 0 — город жив.
        obs = _obs({(2, 5): [2, 1, 0, 0, 0, 0]})
        deny, _why = denies("city_unwork_16_-1_2", city=_city(surplus=2.0), obs=obs)
        assert deny is False

    def test_above_tile_food_is_allowed(self):
        obs = _obs({(2, 5): [1, 1, 0, 0, 0, 0]})
        deny, _why = denies("city_unwork_16_-1_2", city=_city(surplus=3.0), obs=obs)
        assert deny is False

    def test_unseen_tile_uses_measured_maximum(self):
        # Слоя карты нет: клетка не видна, и незнание НЕ выдаётся за безопасность —
        # берётся наибольшая измеренная еда клетки (MAX_TILE_FOOD).
        obs = {"map": {}}          # слоя `output` нет вовсе
        deny, why = denies("city_unwork_16_-1_2", city=_city(surplus=2.0), obs=obs)
        assert deny is True
        assert "не видно" in why

    def test_tile_outside_map_uses_measured_maximum(self):
        # Город у края, целевая клетка за границей по Y: то же правило — граница,
        # а не ноль (иначе город у края карты считался бы безопасным всегда).
        obs = _obs({})
        deny, _why = denies("city_unwork_1_-2_-2",
                            city=_city(x=0, y=0, surplus=2.0), obs=obs)
        assert deny is True

    def test_wrap_around_x_reads_real_tile(self):
        # Карта — цилиндр по X: город в x=0 обрабатывает клетку x=−1 → x=xsize−1.
        obs = _obs({(5, 3): [3, 0, 0, 0, 0, 0]})
        assert tile_food(obs, -1, 3) == 3.0

    def test_maximum_matches_measurement(self):
        assert MAX_TILE_FOOD == 3.0

    def test_report_counts_denials(self):
        obs = _obs({(2, 5): [2, 1, 0, 0, 0, 0]})
        denies("city_unwork_16_-1_2", city=_city(surplus=0.0), obs=obs)
        report = denial_report()
        assert report["counts"].get("city_unwork") == 1
        assert report["total"] == 1
        assert report["examples"], "пример запрета нужен для отчёта"


class TestJoinCity:
    """`join_city` — плюс житель, то есть плюс `food_cost` расхода."""

    def test_below_food_cost_is_denied(self):
        deny, why = denies("join_city", city=_city(surplus=1.0), obs=_obs())
        assert deny is True
        assert str(int(DEFAULT_FOOD_COST)) in why

    def test_equal_to_food_cost_is_allowed(self):
        deny, _why = denies("join_city", city=_city(surplus=2.0), obs=_obs())
        assert deny is False

    def test_food_cost_comes_from_world_rules(self):
        # Правила мира важнее константы: стенд может объявить другой food_cost.
        obs = _obs(rules={"food_cost": 3})
        deny, _why = denies("join_city", city=_city(surplus=2.0), obs=obs)
        assert deny is True
        deny, _why = denies("join_city", city=_city(surplus=3.0), obs=obs)
        assert deny is False


class TestSpecialist:
    """`city_change_specialist` — цена еды из имени не видна: консервативная граница."""

    def test_below_maximum_tile_food_is_denied(self):
        deny, _why = denies("city_change_specialist_0",
                            city=_city(surplus=2.0), obs=_obs())
        assert deny is True

    def test_at_maximum_tile_food_is_allowed(self):
        deny, _why = denies("city_change_specialist_0",
                            city=_city(surplus=3.0), obs=_obs())
        assert deny is False


class TestNotTouched:
    """Правило не должно касаться ничего, кроме трёх семейств."""

    @pytest.mark.parametrize("name", [
        "city_work_13_-2_-1", "produce_Warriors", "produce_Temple",
        "build_city", "goto_3", "fortify", "keep_activity",
        "research_tech_12", "set_sci_lux_tax_0_40_60", "city_buy_production",
        "hut_enter_0",
    ])
    def test_other_actions_always_allowed(self, name):
        deny, _why = denies(name, city=_city(surplus=0.0), obs=_obs())
        assert deny is False

    def test_no_city_record_means_no_verdict(self):
        # Без записи города правило молчит: запрет выносится по факту мира.
        deny, _why = denies("city_unwork_16_-1_2", city=None, obs=_obs())
        assert deny is False

    def test_missing_surplus_means_no_verdict(self):
        deny, _why = denies("city_unwork_16_-1_2",
                            city={"x": 3, "y": 3, "size": 2}, obs=_obs())
        assert deny is False


class TestMapReading:
    def test_tile_food_reads_xy(self):
        obs = _obs({(4, 2): [3, 1, 0, 0, 0, 0]})
        assert tile_food(obs, 4, 2) == 3.0

    def test_tile_food_out_of_map_is_none(self):
        assert tile_food(_obs(), 99, 99) is None

    def test_numpy_array_map_does_not_raise(self):
        numpy = pytest.importorskip("numpy")
        obs = {"map": {"output": numpy.zeros((4, 4, 6))}}
        obs["map"]["output"][1][2] = [2, 0, 0, 0, 0, 0]
        assert tile_food(obs, 1, 2) == 2.0

    def test_city_by_id_accepts_int_and_str_keys(self):
        obs = {"city": {"131": {"id": 131, "x": 1, "y": 1}}}
        assert city_by_id(obs, 131) == {"id": 131, "x": 1, "y": 1}
        assert city_by_id(obs, 999) is None

    def test_city_at_finds_city_on_tile(self):
        obs = {"city": {131: {"id": 131, "x": 5, "y": 6}}}
        assert city_at(obs, 5, 6)["id"] == 131
        assert city_at(obs, 5, 7) is None

    def test_food_cost_defaults_to_measured_value(self):
        assert food_cost_of({}) == DEFAULT_FOOD_COST == 2.0

    def test_food_cost_from_rules(self):
        assert food_cost_of({"rules": {"food_cost": 3}}) == 3.0
        # мусор в правилах не должен ломать правило
        assert food_cost_of({"rules": {"food_cost": None}}) == 2.0