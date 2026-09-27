"""Ловушка живых ключей — третья по счёту в проекте, поэтому проверяется отдельно.

Живьём `obs['tech']` ключуется ЧИСЛАМИ (`{2: {...}}`), в фикстурах строками. Прямой
`.get(str(id))` на живом наблюдении молча возвращает `{}` — и семейство технологии
оказывается пустым не потому, что наука недооценена, а потому, что запись не
нашлась. Измерено 2026-09-27: за 15 ходов `research` не появился среди кандидатов
ни разу, хотя технология исследовалась.
"""
from __future__ import annotations

from brain.forecast.live import _record_by_id


class TestRecordById:
    def test_int_keys_like_a_live_observation(self):
        pool = {2: {"id": 2, "name": "Alphabet"}}
        assert _record_by_id(pool, 2)["name"] == "Alphabet"
        assert _record_by_id(pool, "2")["name"] == "Alphabet"

    def test_string_keys_like_a_fixture(self):
        pool = {"2": {"name": "Alphabet"}}
        assert _record_by_id(pool, 2)["name"] == "Alphabet"

    def test_matched_by_name_when_the_key_is_something_else(self):
        pool = {7: {"id": 7, "name": "Alphabet"}}
        assert _record_by_id(pool, "Alphabet")["id"] == 7

    def test_missing_record_is_empty_not_a_crash(self):
        assert _record_by_id({2: {"name": "Alphabet"}}, 99) == {}
        assert _record_by_id(None, 2) == {}
        assert _record_by_id({2: {"name": "Alphabet"}}, None) == {}

    def test_an_empty_record_does_not_count_as_found(self):
        # Пустая запись — это «не нашли»: иначе `techs()` вернул бы кандидата с
        # нулевым открытым набором и он бы навсегда заслонял настоящее отсутствие.
        assert _record_by_id({2: {}}, 2) == {}
