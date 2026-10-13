"""Желание Workers/Settlers — внутрь `type_price`: правило одно для всех путей.

Измерено: общий путь (без DoF) берёт цену через `ctx.type_price_of` = `type_price`, а не
через `productions()`, поэтому встроенное туда желание НЕ вызывалось вовсе — за 12 ходов
в следе не было ни одной строки `[желание]`, город остался один. Это тот же класс ошибки,
о котором предупреждает справочник: правило обязано действовать везде, где этот род можно
выбрать.

Правка идемпотентна.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "brain" / "forecast" / "live.py"

ANCHOR = '''        этого. Каталог извлекателя здесь не спасает — он неполон.
        """
        rec = live_by_type.get(name)
'''

INSERT = '''        этого. Каталог извлекателя здесь не спасает — он неполон.
        """
        # Workers/Settlers: цена — ЖЕЛАНИЕ города (формулы встроенного ИИ, перенесены
        # из `daicity.c`/`daisettler.c`). Живёт ЗДЕСЬ, а не у вызывающего: иначе общий
        # путь (без DoF) брал обычную цену, желание не спрашивалось вовсе, и поселенец
        # после первого города не ставился никогда — измерено: за 12 ходов ни одной
        # строки `[желание]`, город остался единственным. Правило обязано действовать
        # везде, где этот род можно выбрать.
        if city_rec is not None and str(name) in ("Workers", "Settlers"):
            _want, _reason = (worker_want(city_rec) if str(name) == "Workers"
                              else founder_want(city_rec))
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [желание] {name}: {_want:.3f} — {_reason}", flush=True)
            if _want <= 0.0:
                return None
            _cost = world.cost(name) or spec_costs.get(name)
            if _cost is None:
                try:
                    from env.rules_costs import build_cost_of as _rules_cost
                    _cost = _rules_cost(name)
                except Exception:  # noqa: BLE001
                    _cost = None
            if _cost is None:
                return None
            return float(_want), float(_cost)
        rec = live_by_type.get(name)
'''

START = '            if type_name == "Workers":\n'
END = '                priced = type_price(type_name, rec)\n'
REPLACEMENT = '            priced = type_price(type_name, rec)\n'

text = PATH.read_text(encoding="utf-8")
changed = 0

if INSERT in text:
    print("вставка в type_price уже есть")
else:
    assert text.count(ANCHOR) == 1, "якорь начала type_price не однозначен"
    text = text.replace(ANCHOR, INSERT)
    changed += 1

i = text.find(START)
assert i >= 0, "не найден блок Workers в productions()"
j = text.find(END, i)
assert j >= 0, "не найден конец блока желаний в productions()"
j += len(END)
old_block = text[i:j]
assert "founder_want" in old_block and "worker_want" in old_block, "блок не тот"
text = text[:i] + REPLACEMENT + text[j:]
changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")
print(f"упоминаний worker_want={text.count('worker_want')} founder_want={text.count('founder_want')}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
