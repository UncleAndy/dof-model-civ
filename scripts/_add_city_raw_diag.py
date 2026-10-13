"""Диагностика: сырая запись своего города — её собственные числа (§13.290).

Зачем. Излишек еды 0 при размере 1 не сходится с ожиданием: у города размера 1 горожанин
должен стоять на клетке, и тогда еды должно быть больше. Прежде чем что-то чинить, надо
прочитать числа САМОГО мира (`prod`, `food_surplus`, `specialists`, обработанные клетки), а не
наши производные. `city_work` по логике клиента (`city_actions.py:150`,
`sum(specialists) <= 0` → недействительно) означает, что свободного горожанина нет вовсе.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

OLD = """    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # §13.290: сколько клеток обрабатывает каждый свой город."""

NEW = """    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # §13.290: сырая запись города — его собственные числа. Печатаем ОДИН раз за ход,
        # чтобы сравнить наши производные с тем, что мир сообщает сам.
        try:
            _map_city = (as_dict(obs.get("map")) or {})
            _raw_cities = [c for c in (city_recs or []) if c.get("owner") in _OWN_IDS]
            for _c in _raw_cities[:2]:
                _keys = sorted(_c.keys())
                print(f"      [город-сырой] {_keys}", flush=True)
                print(f"      [город-сырой] prod={_c.get('prod')} food_surplus={_c.get('food_surplus')} "
                      f"specialists={_c.get('specialists')} size={_c.get('size')} "
                      f"радиус_sq={_c.get('city_radius_sq')}", flush=True)
        except Exception as _exc:  # noqa: BLE001
            print(f"      [город-сырой] не прочитан: {_exc!r}", flush=True)
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # §13.290: сколько клеток обрабатывает каждый свой город."""

text = PATH.read_text(encoding="utf-8")
if "[город-сырой]" in text:
    print("уже внесено")
else:
    assert text.count(OLD) == 1, "якорь не однозначен"
    PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("внесено")
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
