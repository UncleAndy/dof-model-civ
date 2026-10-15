"""Сторожа §13.418: кто опасен по правилам встроенного ИИ (`adv_is_player_dangerous`).

Правило (`server/advisors/advdata.c:1103`): опасен только тот, с кем война или перемирие,
либо у кого есть повод расторгнуть договор. Без него мы держали десять воинов против нуля
военных у каждой стороны-ИИ (замер r980, отношения «Never met» у всех).
"""

from __future__ import annotations

from env.diplomacy_from_save import dangerous_players

_HEAD = ('diplstate={"current","closest","first_contact_turn","turns_left",'
         '"has_reason_to_cancel","contact_turns_left","embassy"')

_NEVER = '"Never met","Never met",0,0,0,0,FALSE'
_WAR = '"War","War",3,0,0,0,FALSE'
_REASON = '"Peace","Peace",5,0,1,0,FALSE'


def _save(*rows: str) -> str:
    return "[player0]\n" + _HEAD + "\n" + "\n".join(rows) + "\n}\nai={...}\n"


class TestDangerousPlayers:
    def test_never_met_is_not_dangerous(self):
        text = _save(_NEVER, _NEVER, _NEVER, _NEVER)
        assert dangerous_players(text, 0) == set()

    def test_war_counts(self):
        text = _save(_NEVER, _WAR, _NEVER, _NEVER)
        # строки идут по игрокам БЕЗ строки про себя: для нас (0) это игроки 1..4, поэтому
        # воина во ВТОРОЙ строке — это игрок 2.
        assert dangerous_players(text, 0) == {2}

    def test_row_order_excludes_self(self):
        # Строки идут по другим игрокам, строки про себя в сейве нет: для нас (индекс 1) четыре
        # строки означают игроков 0, 2, 3, 4 — воина в ПЕРВОЙ строке это игрок 0, а не 1 (мы).
        text = _save(_WAR, _NEVER, _NEVER, _NEVER)
        assert dangerous_players(text, 1) == {0}

    def test_reason_to_cancel_counts(self):
        text = _save(_NEVER, _NEVER, _REASON, _NEVER)
        assert dangerous_players(text, 0) == {3}

    def test_missing_save_is_unknown_not_safe(self):
        assert dangerous_players(None, 0) is None
        assert dangerous_players("", 0) is None
        assert dangerous_players("[player0]\nno diplstate here\n", 0) is None
