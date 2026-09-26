"""Сверка «прогноз площадки ↔ факт города»: корпус и математика ошибки.

Здесь проверяется то, что легко испортить незаметно: что строки пишутся,
читаются, что ошибка считается там, где её можно считать (факт не ноль), и что
корреляция не выдумывается при отсутствии разброса.
"""
from __future__ import annotations

import json

import pytest

from env import site_outcomes
from env.site_outcomes import load, record, summarize


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    path = tmp_path / "site_outcomes.jsonl"
    monkeypatch.setattr(site_outcomes, "OUTCOMES_FILE", path)
    return path


class TestCorpus:
    def test_records_and_reads_back(self, corpus):
        assert record([{"pred_food": 3.0, "obs_food": 3.0}]) == 1
        assert record([{"pred_food": 1.0, "obs_food": 2.0}]) == 1
        rows = load(corpus)
        assert len(rows) == 2 and rows[0]["pred_food"] == 3.0

    def test_nothing_to_record_is_not_an_error(self, corpus):
        assert record([]) == 0
        assert load(corpus) == []

    def test_a_broken_line_does_not_spoil_the_corpus(self, corpus):
        corpus.write_text('{"pred_food": 1, "obs_food": 1}\n{{ битая строка\n')
        rows = load(corpus)
        assert len(rows) == 1

    def test_unwritable_path_returns_zero_instead_of_raising(self, tmp_path):
        # Корпус не критичен для матча: не смогли записать — матч продолжается.
        # Путь-каталог гарантированно не открывается на дозапись (IsADirectoryError).
        assert record([{"pred_food": 1.0}], path=tmp_path) == 0


class TestErrorMath:
    def test_relative_error_and_exact_share(self):
        rows = [
            {"pred_food": 3.0, "obs_food": 3.0},   # точно
            {"pred_food": 4.0, "obs_food": 2.0},   # ошибка 1.0
        ]
        stats = summarize(rows)["channels"]["food"]
        assert stats["n_usable"] == 2
        assert stats["error_mean"] == pytest.approx(0.5)
        assert stats["error_max"] == pytest.approx(1.0)
        assert stats["exact_share"] == pytest.approx(0.5)

    def test_zero_facts_are_excluded_not_divided_by(self):
        # Делить на ноль — выдумывать число; такие пары не считаются вообще.
        rows = [{"pred_food": 3.0, "obs_food": 0.0},
                {"pred_food": 2.0, "obs_food": 2.0}]
        stats = summarize(rows)["channels"]["food"]
        assert stats["n_usable"] == 1
        assert stats["error_mean"] == pytest.approx(0.0)

    def test_perfect_correlation_for_a_linear_relation(self):
        rows = [{"pred_food": float(p), "obs_food": float(p * 2 + 1)}
                for p in (1, 2, 3, 4, 5)]
        assert summarize(rows)["channels"]["food"]["corr"] == pytest.approx(1.0)

    def test_no_spread_means_no_correlation_claim(self):
        # Все прогнозы одинаковы — корреляция не определена, и это надо
        # возвращать как None, а не как «0.0» или «1.0».
        rows = [{"pred_food": 2.0, "obs_food": float(o)} for o in (1, 2, 3)]
        assert summarize(rows)["channels"]["food"]["corr"] is None

    def test_gross_comparison_adds_back_the_losses(self):
        # Модель предсказывает валовое, мир публикует чистое: если не вернуть
        # потери, торговля будет «не сходиться» из-за коррупции, а не из-за модели.
        rows = [{"pred_trade": 6.0, "obs_trade": 2.0, "obs_corruption": 4.0},
                {"pred_trade": 6.0, "obs_trade": 3.0, "obs_corruption": 3.0},
                {"pred_trade": 9.0, "obs_trade": 5.0, "obs_corruption": 4.0}]
        stats = summarize(rows)["channels"]["trade"]
        assert stats["n_usable"] == 3
        assert stats["error_mean"] == pytest.approx((4 / 2 + 3 / 3 + 4 / 5) / 3)
        assert stats["gross_n"] == 3
        assert stats["gross_error_mean"] == pytest.approx(0.0)
        assert stats["gross_corr"] == pytest.approx(1.0)
        assert stats["corr"] < stats["gross_corr"]

    def test_channels_without_losses_compare_to_themselves(self):
        # У еды потерь нет: валовое и чистое совпадают, и это видно в ответе.
        rows = [{"pred_food": 6.0, "obs_food": 4.0},
                {"pred_food": 5.0, "obs_food": 3.0},
                {"pred_food": 7.0, "obs_food": 5.0}]
        stats = summarize(rows)["channels"]["food"]
        assert stats["gross_error_mean"] == pytest.approx(stats["error_mean"])

    def test_missing_losses_are_treated_as_zero_not_as_missing(self):
        # Старые строки корпуса потерь не знали: считать их нулём честнее, чем
        # выкидывать наблюдение.
        rows = [{"pred_shield": 4.0, "obs_shield": 2.0},
                {"pred_shield": 5.0, "obs_shield": 3.0},
                {"pred_shield": 6.0, "obs_shield": 4.0}]
        stats = summarize(rows)["channels"]["shield"]
        assert stats["n_usable"] == 3 and stats["gross_n"] == 3

    def test_missing_channel_is_reported_as_no_pairs(self):
        stats = summarize([{"pred_food": 1.0, "obs_food": 1.0}])
        assert stats["channels"]["trade"]["n_usable"] == 0


class TestExtractorHook:
    def _obs(self, turn: int, size: int = 1, with_city: bool = True,
             int_keys: bool = False):
        record = {"id": 121, "owner": 0, "x": 25, "y": 43,
                  "size": size, "prod_food": 2, "prod_shield": 7,
                  "prod_trade": 3}
        # Живое наблюдение отдаёт ключи словаря целыми, JSON-фикстура — строками.
        # Именно на этом различии инструмент потерял 30 городов из 30, поэтому
        # проверяются оба вида.
        key = 121 if int_keys else "121"
        obs = {
            "city": ({key: record} if with_city else {}),
            "unit": {}, "tech": {}, "dipl": {}, "map": {},
        }
        return obs

    def test_initial_city_is_checked_after_the_grace_period(self, corpus):
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        assert load(corpus) == []          # ещё рано: городу 0 ходов
        ex.extract(self._obs(3), {}, 3)
        assert load(corpus) == []          # возраст 2 < OUTCOME_AGE_TURNS
        ex.extract(self._obs(6, size=2), {}, 6)
        rows = load(corpus)
        assert len(rows) == 1
        row = rows[0]
        assert row["cause"] == "start" and row["city_id"] == "121"
        assert row["size"] == 2 and row["age"] == 5
        assert row["obs_food"] == 2.0 and row["obs_shield"] == 7.0
        assert row["lost"] is False

    def test_a_city_is_checked_once(self, corpus):
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        ex.extract(self._obs(6), {}, 6)
        ex.extract(self._obs(7), {}, 7)
        assert len(load(corpus)) == 1      # не по строке на каждый ход

    def test_a_city_missing_once_is_not_called_lost(self, corpus):
        # Слой городов приходит пакетами: промах в одном наблюдении — это «пакет
        # не пришёл», а не «город исчез». Первый прогон так «потерял» все 30
        # городов подряд, поэтому теперь даётся несколько попыток.
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        ex.extract(self._obs(6, with_city=False), {}, 6)
        assert load(corpus) == []

    def test_a_city_that_stays_absent_is_recorded_as_lost(self, corpus):
        from env.entity_extractor import GameStateExtractor
        from env.site_outcomes import LOST_AFTER_TURNS

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        for turn in range(6, 1 + LOST_AFTER_TURNS + 2):
            ex.extract(self._obs(turn, with_city=False), {}, turn)
        rows = load(corpus)
        assert len(rows) == 1 and rows[0]["lost"] is True
        assert rows[0]["misses"] >= 2
        assert "available_city_ids" in rows[0]

    def test_int_keyed_observation_is_found(self, corpus):
        # Живой стенд отдаёт ключи словаря целыми (121), фикстура — строками.
        # Поиск по строке терял город: 30 «потерь» из 30 в первом прогоне.
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1, int_keys=True), {}, 1)
        ex.extract(self._obs(6, size=2, int_keys=True), {}, 6)
        rows = load(corpus)
        assert len(rows) == 1 and rows[0]["lost"] is False
        assert rows[0]["size"] == 2 and rows[0]["obs_food"] == 2.0

    def test_the_key_kind_does_not_matter_for_the_lookup(self, corpus):
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1, int_keys=True), {}, 1)
        ex.extract(self._obs(6, size=1), {}, 6)      # тот же id, но ключ-строка
        rows = load(corpus)
        assert len(rows) == 1 and rows[0]["lost"] is False

    def test_a_city_that_reappears_is_measured_normally(self, corpus):
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        ex.extract(self._obs(6, with_city=False), {}, 6)   # пакет не пришёл
        ex.extract(self._obs(8, size=2), {}, 8)            # пришёл снова
        rows = load(corpus)
        assert len(rows) == 1 and rows[0]["lost"] is False
        assert rows[0]["size"] == 2 and rows[0]["age"] == 7

    def test_other_players_cities_are_not_tracked(self, corpus):
        from env.entity_extractor import GameStateExtractor

        obs = self._obs(1)
        obs["city"]["121"]["owner"] = 2
        ex = GameStateExtractor(my_player_id=0)
        ex.extract(obs, {}, 1)
        ex.extract(obs, {}, 6)
        assert load(corpus) == []

    def test_corpus_lines_are_json(self, corpus):
        from env.entity_extractor import GameStateExtractor

        ex = GameStateExtractor(my_player_id=0)
        ex.extract(self._obs(1), {}, 1)
        ex.extract(self._obs(6), {}, 6)
        for line in corpus.read_text().splitlines():
            json.loads(line)
