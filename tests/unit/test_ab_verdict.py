"""Правило вердикта A/B: проверяем ПРАВИЛО, а не результат.

Зачем эти тесты до серии. Вердикт считается кодом, и если правило фильтрации или
порог работают не так, как записано в §10.19, то ошибка будет выглядеть как результат
эксперимента. Поэтому каждая часть правила проверяется на выдуманных записях:
отбраковка (клин, таймаут, `error`, `min_entities == 0`, ноль действий у ВКЛ),
недобор как отсутствие вердикта, «различие есть» только при интервале без нуля,
и «различия не показано» на честном шуме.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ab_two_arm_verdict.py"


def _load():
    spec = importlib.util.spec_from_file_location("ab_verdict", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ab = _load()


def row(*, turns=30, actions=10, skipped=0, score=5.0, error="", wedge=None,
        min_entities=95):
    return {"turns": turns, "actions_issued": actions, "skipped_turns": skipped,
            "score_cum": score, "error": error, "wedge_action": wedge,
            "min_entities": min_entities, "source": "synthetic.json"}


class TestDropping:
    def test_a_clean_game_is_kept(self):
        assert ab.rejection_reason(row(), "on") is None

    def test_every_refusal_of_the_stand_drops_the_game_and_names_itself(self):
        assert "error" in ab.rejection_reason(row(error="timeout: wedged"), "off")
        assert "клин" in ab.rejection_reason(row(wedge={"ctrl_type": "unit"}), "on")
        assert "min_entities" in ab.rejection_reason(row(min_entities=0), "on")
        assert "0 ходов" in ab.rejection_reason(row(turns=0), "off")

    def test_zero_actions_drops_the_game_only_for_the_forecast_arm(self):
        """Ноль действий у ВКЛ — отказ инструмента: прогноз обязан действовать.

        У ВЫКЛ ноль действий — это как раз предмет измерения (простой), поэтому
        там игра остаётся.
        """
        assert "ноль действий" in ab.rejection_reason(row(actions=0), "on")
        assert ab.rejection_reason(row(actions=0), "off") is None


class TestVerdict:
    def test_short_series_has_no_verdict(self):
        on = [row(score=9.0) for _ in range(3)]
        off = [row(score=1.0) for _ in range(3)]
        name, diff, _low, _high = ab.verdict(on, off, require=16)
        assert "недобор" in name and diff > 0

    def test_clear_separation_is_a_verdict(self):
        on = [row(score=9.0 + 0.1 * i) for i in range(16)]
        off = [row(score=1.0 + 0.1 * i) for i in range(16)]
        name, diff, low, high = ab.verdict(on, off, require=16)
        assert name == "различие есть" and low > 0.0 and diff > 0.0

    def test_noise_is_honestly_no_difference(self):
        """Разброс шире разницы → интервал накрывает ноль, вердикта нет."""
        rng = random.Random(11)
        on = [row(score=rng.uniform(0.0, 20.0)) for _ in range(16)]
        off = [row(score=rng.uniform(0.0, 20.0)) for _ in range(16)]
        name, _diff, low, high = ab.verdict(on, off, require=16)
        assert name == "различия не показано" and low <= 0.0 <= high

    def test_negative_difference_is_not_a_positive_verdict(self):
        """Обратная разница не должна выдаваться за победу прогноза."""
        on = [row(score=1.0) for _ in range(16)]
        off = [row(score=9.0) for _ in range(16)]
        name, diff, _low, _high = ab.verdict(on, off, require=16)
        assert name == "различия не показано" and diff < 0.0

    def test_the_seed_makes_the_interval_reproducible(self):
        on = [row(score=5.0 + 0.3 * i) for i in range(16)]
        off = [row(score=4.0 + 0.3 * i) for i in range(16)]
        first = ab.bootstrap_diff_ci([r["score_cum"] for r in on],
                                     [r["score_cum"] for r in off])
        second = ab.bootstrap_diff_ci([r["score_cum"] for r in on],
                                      [r["score_cum"] for r in off])
        assert first == second


class TestReport:
    def test_the_report_names_every_dropped_game_with_its_reason(self):
        on = [row(score=5.0), row(error="AttributeError: x")]
        off = [row(score=4.0), row(wedge={"ctrl_type": "city"})]
        text = ab.report(on, off, [("a.json", "error: boom")],
                         [("b.json", "клин: {'ctrl_type': 'city'}")], [])
        assert "отброшено: a.json — error: boom" in text
        assert "отброшено: b.json — клин" in text
        assert "ВЕРДИКТ" in text

    def test_the_report_shows_the_mechanism_beside_the_outcome(self):
        on = [row(actions=31, skipped=0, score=5.0)]
        off = [row(actions=9, skipped=23, score=4.0)]
        text = ab.report(on, off, [], [], [], require=1, allow_short=True)
        assert "действий за ход 1.03" in text.replace(",", ".")
        assert "простоев 0%" in text and "простоев 77%" in text


if pytest is None:  # pragma: no cover - страховка от случайного удаления импорта
    raise SystemExit(1)
