"""Прирост от работы на клетке — его приёмом «виртуальной клетки» (§13.474).

Как у него. Оценка улучшения у встроенного ИИ строится не на таблице приростов, а так:
берётся КОПИЯ клетки с применённым изменением и снова спрашивается ценность
(`server/advisors/infracache.c`: `tile_virtual_new` → применить изменение → `city_tile_value`),
и эта ценность сравнивается с ценностью клетки сейчас. Ровно тот же приём здесь: выходы клетки
считаются по правилам мира ДО и ПОСЛЕ работы, а разница переводится в ценность весами
управляющего городом (`server/cityturn.c:320-338`, §13.455 — размер 1: еда 20; размер 2+:
еда 15/10, щиты 5, торговля 0).

Почему так, а не таблицей. Таблица эффектов отвечает на вопрос «сколько даёт шахта», но не
отвечает на вопрос «станет ли от неё ЛУЧШЕ именно этой клетке»: на клетке без щитов шахта может
не дать ничего, а на клетке со щитами — дать два. Разница до/после отвечает на настоящий вопрос.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from brain.ai_default.tile_outputs import tile_outputs_from_rules

#: Веса управляющего городом (`cityturn.c:320-338`): (еда, щиты, торговля).
CITY_WEIGHTS_DEFAULT: tuple[float, float, float] = (15.0, 5.0, 0.0)


def output_value(outputs: tuple[float, float, float] | None,
                 weights: tuple[float, float, float] = CITY_WEIGHTS_DEFAULT) -> float | None:
    """Ценность выхода клетки весами управляющего городом. None — если выход неизвестен."""
    if outputs is None:
        return None
    return float(outputs[0]) * weights[0] + float(outputs[1]) * weights[1] + float(outputs[2]) * weights[2]


def work_gain(terrain: str, extras: Iterable[str], work: str,
              weights: tuple[float, float, float] = CITY_WEIGHTS_DEFAULT) -> float | None:
    """Прирост ценности клетки от работы `work` — разность «после минус до» (его приём).

    Возвращает None, когда выходы неизвестны (незнакомый террейн) или работа уже стоит на клетке:
    «неизвестно» и «уже сделано» не должны выглядеть как прирост.
    """
    present = [str(e) for e in (extras or ())]
    if str(work) in present:
        return None
    before = output_value(tile_outputs_from_rules(terrain, present), weights)
    after = output_value(tile_outputs_from_rules(terrain, present + [str(work)]), weights)
    if before is None or after is None:
        return None
    return after - before


def best_work(candidates: Mapping[str, tuple[str, Iterable[str]]],
              weights: tuple[float, float, float] = CITY_WEIGHTS_DEFAULT) -> tuple[str | None, float | None]:
    """Лучшая работа из кандидатов: `{key: (terrain, extras)}` → `(key, прирост)`.

    Ноль в качестве прироста годной работой НЕ считается (у него `best_oldv = 9999` и «0 значит
    годных действий нет»): возвращается `(None, None)`, если ни одна работа не даёт прироста.
    """
    best_key, best_gain = None, 0.0
    for key, (terrain, extras) in candidates.items():
        for work in ("Irrigation", "Mine", "Road", "Railroad"):
            gain = work_gain(terrain, extras, work, weights)
            if gain is not None and gain > best_gain:
                best_key, best_gain = key, gain
    if best_key is None:
        return None, None
    return best_key, best_gain
