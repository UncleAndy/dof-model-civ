"""Каркас выбора производства города — порядок советников как у встроенного ИИ (шаг 1 плана).

Устроен как `dai_city_choose_build` (`ai/default/daicity.c:250`): военный советник -> внутренний ->
ветвь поселенца, побеждает НАИБОЛЬШЕЕ желание. Советники передаются снаружи функциями, поэтому
каркас не зависит от раннера и проверяется юнит-тестами без игры.
"""

from brain.ai_default import want_scales as _ws


def choose_build(rec: dict, advisors, *, rand_value: int = 0):
    """Выбрать постановку города: `(имя, желание)` или `(None, 0.0)`."""
    def _call(name: str) -> dict:
        fn = advisors.get(name) if isinstance(advisors, dict) else getattr(advisors, name, None)
        if not callable(fn):
            return {}
        try:
            out = fn(rec) or {}
        except Exception:  # noqa: BLE001
            return {}
        return out if isinstance(out, dict) else {}

    wants: dict[str, float] = {}
    for name, raw in _call("military").items():
        wants[str(name)] = _ws.below_mil_emergency(raw)
    for name, raw in _call("domestic").items():
        value = _ws.domestic_capped(raw)
        if _ws.enough(value):
            value = float(_ws.RESULT_IS_ENOUGH)
        wants[str(name)] = max(wants.get(str(name), 0.0), value)
    for name, raw in _call("founder").items():
        wants[str(name)] = max(wants.get(str(name), 0.0), _ws.domestic_capped(raw))
    if not wants:
        return None, 0.0
    best = max(wants, key=lambda k: (wants[k], k))
    return best, float(wants[best])


def recalc_due(turn: int, city_turn: int, rand_value: int = 0) -> bool:
    """Пора ли пересчитывать желания: раз в `rand(speed) + speed` ходов."""
    return (int(turn) - int(city_turn)) >= _ws.recalc_period(rand_value)
