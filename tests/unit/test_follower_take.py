"""Взятие державы follower'ом: проверка результата и повтор.

Дефект, который эти тесты закрывают (измерен на живом стенде 2026-09-27): дуэль
шла в режиме «host против наблюдателя». Follower отправлял `/take` ОДИН раз и
сразу помечал дело сделанным. Если команда не срабатывала (гонка с созданием
державы, другое написание имени: сервер делает `Duela` из учётки `duela`),
сторона до конца игры не имела ни одного действия: 0.00 решений за 50 ходов при
живом наблюдении. В дуэлях это давало ~25 % брака.
"""
import pytest

from civrealm.freeciv.connectivity import client_state as cs
from civrealm.freeciv.connectivity.client_state import ClientState


class _Ws:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)


def _stub(username="duelb", player_num=-1, follower=True,
          take_attempts=0, attempts_max=5):
    s = _Attr()
    s.username = username
    s.follower = follower
    s.follower_take = False
    s.take_attempts = take_attempts
    s.take_attempts_max = attempts_max
    s.client_frozen = True
    s.ws_client = _Ws()
    s.player_num = (lambda: player_num) if not callable(player_num) else player_num
    return s


class _Attr:
    """Пустышка с методами ClientState, привязанными к ней самой."""

    player_is_mine = ClientState.player_is_mine
    take_name_candidates = ClientState.take_name_candidates
    handle_thaw_client = ClientState.handle_thaw_client


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(cs, "fc_args", {"follower_take_player": True})


class TestPlayerIsMine:
    def test_an_observer_connection_is_not_mine(self):
        assert ClientState.player_is_mine(_stub(player_num=-1)) is False

    def test_a_missing_player_num_is_not_mine(self):
        assert ClientState.player_is_mine(_stub(player_num=None)) is False

    def test_player_number_zero_is_a_real_player(self):
        # Ноль — законный номер игрока: нельзя проверять на истинность.
        assert ClientState.player_is_mine(_stub(player_num=0)) is True

    def test_a_string_number_counts(self):
        assert ClientState.player_is_mine(_stub(player_num="1")) is True

    def test_garbage_does_not_crash(self):
        assert ClientState.player_is_mine(_stub(player_num="нет")) is False


class TestTakeNameCandidates:
    def test_both_spellings_are_tried(self):
        assert ClientState.take_name_candidates(_stub(username="duelb")) == ["duelb", "Duelb"]

    def test_an_already_capitalised_name_is_not_duplicated(self):
        assert ClientState.take_name_candidates(_stub(username="Duelb")) == ["Duelb"]


class TestThawClient:
    def test_the_take_is_retried_while_no_player(self):
        s = _stub(player_num=-1)
        ClientState.handle_thaw_client(s, {})
        ClientState.handle_thaw_client(s, {})
        assert s.ws_client.sent == ["/take duelb", "/take Duelb"]
        assert s.take_attempts == 2

    def test_the_latch_waits_for_the_player_to_actually_arrive(self):
        s = _stub(player_num=-1)
        ClientState.handle_thaw_client(s, {})
        assert s.follower_take is False        # не «сделано», пока не подтверждено
        s.player_num = lambda: 3
        ClientState.handle_thaw_client(s, {})
        assert s.follower_take is True

    def test_a_taken_player_is_not_taken_twice(self):
        s = _stub(player_num=1)
        ClientState.handle_thaw_client(s, {})
        ClientState.handle_thaw_client(s, {})
        assert s.ws_client.sent == []

    def test_attempts_are_bounded_and_the_failure_is_announced(self):
        s = _stub(player_num=-1)
        for _ in range(10):
            ClientState.handle_thaw_client(s, {})
        # Пять попыток — и стоп: спамить `/take` каждый ход нельзя.
        assert len(s.ws_client.sent) == 5
        assert s.take_attempts == 6            # шестая «попытка» — объявление отказа

    def test_single_agent_runs_are_untouched(self, monkeypatch):
        monkeypatch.setattr(cs, "fc_args", {})
        s = _stub(player_num=-1)
        ClientState.handle_thaw_client(s, {})
        assert s.ws_client.sent == []

    def test_host_does_not_take_anything(self):
        s = _stub(player_num=0, follower=False)
        ClientState.handle_thaw_client(s, {})
        assert s.ws_client.sent == []

    def test_the_client_is_thawed_in_every_case(self):
        s = _stub(player_num=-1, take_attempts=99, attempts_max=5)
        ClientState.handle_thaw_client(s, {})
        assert s.client_frozen is False
