"""Адаптер советников: развязка вариантов по ведомствам и решение каркаса — без игры.

Проверяется ровно то, за что отвечает адаптер: к какому ведомству попадает имя, что советники
отдают те же числа, что получили, и что решение каркаса берётся по его шкалам.
"""

from brain.ai_default import advisor_adapter as aa
from brain.ai_default import want_scales as ws


def _opts(*rows):
    return [tuple(r) for r in rows]


def test_military_founder_domestic_split():
    mil, dom, found = aa.split_options(
        _opts(("Phalanx", 1200.0, 3), ("Settlers", 300.0, 5), ("Granary", 8.0, 4)),
        military_names=("Phalanx", "Warriors"),
        founder_names=("Settlers",))
    assert mil == {"Phalanx": 1200.0}
    assert found == {"Settlers": 300.0}
    assert dom == {"Granary": 8.0}


def test_unknown_name_goes_to_domestic():
    """Имя, которого нет ни в боевых, ни в поселенческих, — внутреннее ведомство."""
    mil, dom, found = aa.split_options(_opts(("Library", 40.0, 6)),
                                       military_names=("Phalanx",))
    assert mil == {} and found == {}
    assert dom == {"Library": 40.0}


def test_advisors_return_what_they_were_given():
    """Советники не пересчитывают числа: отдают ровно то, что им передали."""
    adv = aa.advisors({"Phalanx": 1200.0}, {"Granary": 8.0}, {"Settlers": 300.0})
    assert adv["military"]({}) == {"Phalanx": 1200.0}
    assert adv["domestic"]({}) == {"Granary": 8.0}
    assert adv["founder"]({}) == {"Settlers": 300.0}


def test_advisors_are_callables_ignoring_rec():
    """Каркас зовёт советника как `fn(rec)`; запись города на результат не влияет."""
    adv = aa.advisors({"Phalanx": 10.0}, {}, {})
    assert adv["military"]({"size": 1}) == adv["military"]({"size": 9})


def test_choose_picks_largest_want():
    """Побеждает наибольшее желание — как в каркасе."""
    name, want = aa.choose_from_options(
        _opts(("Phalanx", 900.0, 2), ("Granary", 8.0, 4)),
        {}, military_names=("Phalanx",))
    assert name == "Phalanx"
    assert want == 900.0


def test_military_capped_below_emergency():
    """Военное желание ограничено порогом тревоги — шкалой каркаса."""
    name, want = aa.choose_from_options(
        _opts(("Phalanx", 5000.0, 2)), {}, military_names=("Phalanx",))
    assert name == "Phalanx"
    assert want == ws.DAI_WANT_BELOW_MIL_EMERGENCY


def test_founder_capped_by_domestic_max():
    """Желание поселенца ограничено потолком внутреннего ведомства."""
    name, want = aa.choose_from_options(
        _opts(("Settlers", 5000.0, 5)), {}, founder_names=("Settlers",))
    assert name == "Settlers"
    assert want == ws.DAI_WANT_DOMESTIC_MAX


def test_empty_options_gives_none():
    """Пустой список вариантов — «нечего выбирать», а не выдуманное имя."""
    assert aa.choose_from_options([], {}) == (None, 0.0)


def test_malformed_rows_do_not_crash():
    """Битая строка списка не должна ронять выбор — она просто не участвует."""
    name, want = aa.choose_from_options(
        [None, ("Granary",), ("Library", "не число"), ("Temple", 12.0, 3)],
        {})
    assert name == "Temple"
    assert want == 12.0


def test_choose_build_matches_direct_framework_call():
    """Адаптер не добавляет своей логики поверх каркаса: решение совпадает с прямым вызовом."""
    from brain.ai_default.build_choice import choose_build
    rows = _opts(("Phalanx", 1100.0, 2), ("Settlers", 200.0, 4), ("Granary", 30.0, 3))
    direct = choose_build({}, aa.advisors(
        *aa.split_options(rows, military_names=("Phalanx",), founder_names=("Settlers",))))
    assert aa.choose_from_options(rows, {}, military_names=("Phalanx",),
                                  founder_names=("Settlers",)) == direct
