"""Тесты выбора цели рабочего (§13.451).

Правило проверяется на данных, а не на поведении стенда: важно, что модуль выбирает клетку ПО
выигрышу работы, не выдумывает ценность там, где вариантов нет, и не уводит рабочего за предел
радиуса.

Соглашение о данных: `options_for(клетка)` возвращает `{имя работы: выигрыш}` — выигрыш берётся
МАКСИМУМОМ по вариантам, потому что рабочий делает одну работу, а не все сразу (у него это выбор
`best_impr` с дисконтом `amortize(total, delay)`).
"""

from brain.ai_default.worker_destination import best_work_tile


def _options(table):
    def options_for(pos):
        return table.get(pos)
    return options_for


def _gain(opts):
    return max(opts.values())


def test_picks_highest_gain():
    table = {(1, 0): {"irrigate": 2.0}, (0, 1): {"build_road": 5.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain) == (0, 1)


def test_ignores_tiles_without_options():
    table = {(1, 0): None, (0, 1): {"build_road": 3.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain) == (0, 1)


def test_ignores_zero_and_negative_gain():
    table = {(1, 0): {"build_road": 0.0}, (0, 1): {"build_road": -1.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain) is None


def test_returns_none_when_no_options():
    assert best_work_tile(worker_pos=(0, 0), tiles=[(1, 0), (0, 1)],
                          options_for=lambda p: None, gain_of=lambda o: 9.0) is None


def test_respects_radius():
    table = {(9, 0): {"build_road": 100.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain, radius=6) is None


def test_radius_boundary_still_allowed():
    table = {(6, 0): {"build_road": 1.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain, radius=6) == (6, 0)


def test_never_picks_own_tile():
    table = {(0, 0): {"build_road": 99.0}}
    assert best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                          gain_of=_gain) is None


def test_prefers_tile_in_use_on_equal_gain():
    table = {(1, 0): {"build_road": 4.0}, (0, 1): {"build_road": 4.0}}
    got = best_work_tile(worker_pos=(0, 0), tiles=list(table), options_for=_options(table),
                         gain_of=_gain, in_use=[(0, 1)])
    assert got == (0, 1), "клетка в обработке города должна выигрывать при равном выигрыше"


def test_empty_tiles():
    assert best_work_tile(worker_pos=(0, 0), tiles=[], options_for=lambda p: {},
                          gain_of=_gain) is None
