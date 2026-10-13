"""Поощрение экспериментов: цена неизвестного и витрина вопросов.

Зачем это нужно. Модель знает не всё о мире: часть правил не измерена, часть
коэффициентов — предположения, а какие-то ключи мир оспаривает. Пока неизвестное
стоило ровно 0, ядро к нему было равнодушно, а с учётом штрафа Axiom 4 за
необратимость — скорее избегало: агент не имел **ни мотива, ни вопроса**.

Здесь появляются оба:

* **мотив** — действие с неизмеренным эффектом получает надбавку «цена снятия
  неопределённости», и она убывает по мере того, как агент это действие пробует
  (Axiom 5/7: неизвестное не считается нулём, но и не оплачивается вечно);
* **вопрос** — `WorldModel.unknowns()` (чего мы не знаем) и
  `WorldModel.contested()` (с чем мир спорит) превращаются в список задач, и
  действия, которые эти задачи закрывают, получают отдельную надбавку.

Констант здесь нет: величина надбавки — **уже утверждённый** штраф Axiom 4
(`AXIOM4_PENALTY_OPTIONS`). Смысл: агент готов потратить ровно столько, сколько
готов заплатить за необратимость, чтобы узнать то, чего не знает. Это делает
бюджет экспериментов явным и не вводит новых «магических» чисел.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from . import config as cfg
from .action_family import family_of  # noqa: F401 - пере-экспорт для вызывающих
from .dof_deltas import measured_delta
from .terrain_work import work_extra
from .wedged import is_wedged
from .world_model import CONFIDENCE_K

#: Какую модельную величину проверяет действие (для надбавки за эксперимент по
#: спорному ключу). Список намеренно короткий: он растёт только там, где у ключа
#: есть наблюдаемое свидетельство, а не по желанию.
PROBE_MAP: dict[str, tuple[str, ...]] = {
    "build_city": ("new_city_options",),
    "found_city": ("new_city_options",),
    "found": ("new_city_options",),
}


def action_known(ctrl_type: str, action_name: str) -> bool:
    """Измерен ли эффект действия (в том числе как измеренный НОЛЬ).

    Два источника измерения, и оба считаются знанием:
    * таблица ΔDoF по действиям (`env.dof_deltas`);
    * таблица эффектов экстр (`env.config.MEASURED_EXTRA_EFFECTS`) — работа,
      чья экстра измерена, известна даже если в первой таблице её нет: например
      `build_road` ставит `Road`, а эффект `Road` замерен (ноль на трёх
      террейнах). Иначе агент платил бы за «эксперимент» там, где уже знает
      ответ, и счётчик попыток рос бы на пустом месте.

    Третий источник — реестр клинчей (`env.wedged`): действие, о которое стенд
    уже заклинивал, тоже «известно» — известно, что им нельзя пользоваться.
    Иначе агент, ведомый любопытством, наступал бы на те же грабли в каждом
    новом матче (модель мира живёт один матч, а клинч убивает именно его).
    """
    if measured_delta(ctrl_type, action_name) is not None:
        return True
    if is_wedged(ctrl_type, action_name):
        return True
    extra = work_extra(action_name)
    if extra is None:
        return False
    if any(key == extra or key.startswith(f"{extra}@")
           for key in cfg.MEASURED_EXTRA_EFFECTS):
        return True
    # Четвёртый источник — ПРАВИЛА мира. Указание владельца: эффект — характеристика
    # мира, её достаточно узнать один раз (`classic/terrain.ruleset`). После отзыва
    # слепых нулей `map.output` работа считается известной именно отсюда: дорога
    # описана секцией `road_*`, ирригация и шахта — полями террейна. Иначе знание
    # зависело бы от отозванного нуля, и `Road` был бы «известен», а `build_road` — нет.
    from .terrain_work_effects import effect_known_from_rules
    return effect_known_from_rules(extra)


def note_choice(model, ctrl_type: str, action_name: str, turn: int = 0) -> bool:
    """Записать попытку, если выбранное действие было экспериментом.

    Живёт здесь, а не в агенте, чтобы любой путь принятия решения (агент, ручной
    прогон, будущий планировщик) считал попытки одинаково — иначе надбавка за
    незнание не убывает, и агент платит за одну и ту же неизвестность вечно.
    """
    if not ctrl_type or not action_name or action_known(ctrl_type, action_name):
        return False
    model.record_experiment(family_of(action_name), turn=turn)
    return True


def exploration_budget(attempts: int) -> float:
    """Доля бюджета любопытства, оставшаяся после `attempts` проб семейства.

    Линейно убывает до нуля на `CONFIDENCE_K` пробах: `1, 2/3, 1/3, 0` при K=3.
    Обрыв в ноль (а не асимптота) — принципиален: бесконечное любопытство
    вытеснило бы полезные действия, и агент вечно платил бы за одну и ту же
    неизвестность. Три оплаченные пробы на семейство — и дальше только польза.
    """
    return max(0.0, 1.0 - max(0, attempts) / CONFIDENCE_K)


def curiosity_enabled() -> bool:
    """Включена ли надбавка за незнание.

    Читается при каждом обращении, а не один раз при импорте: A/B-прогон
    «с любопытством / без» переключает её между матчами, не перезапуская
    процесс.
    """
    return bool(getattr(cfg, "CURIOSITY_ENABLED", True))


def uncertainty_bonus(ctrl_type: str, action_name: str, vals: dict[str, Any],
                      attempts: int) -> float:
    """Надбавка за попытку действия с неизвестным эффектом.

    Измеренный эффект (даже нулевой) надбавки не получает: это знание, а не
    незнание. Неизмеренное действие получает `AXIOM4_PENALTY_OPTIONS`, и с каждой
    пробой этого семейства надбавка падает до нуля на `CONFIDENCE_K` пробах.
    """
    if not curiosity_enabled() or action_known(ctrl_type, action_name):
        return 0.0
    budget = float(vals.get("AXIOM4_PENALTY_OPTIONS", 0.5))
    return budget * exploration_budget(attempts)


def probe_bonus(ctrl_type: str, action_name: str, contested: Iterable[dict[str, Any]],
                attempts_of, vals: dict[str, Any]) -> float:
    """Надбавка за действие, которое закрывает СПОРНЫЙ ключ модели.

    Мир оспаривает ключ (накопились `pending`-доклады), но сам сказать не может —
    значит нужен эксперимент, чей исход этот ключ различает. Надбавка считается
    тем же бюджетом, что и у незнания: снимать спор дороже, чем не знать о нём.
    """
    if not curiosity_enabled():
        return 0.0
    budget = float(vals.get("AXIOM4_PENALTY_OPTIONS", 0.5))
    probes = PROBE_MAP.get(family_of(action_name), ())
    if not probes:
        return 0.0
    bonus = 0.0
    for item in contested:
        key = item.get("key")
        if key in probes:
            bonus += budget * exploration_budget(int(attempts_of(key)))
    return bonus


def experiment_families(candidates: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    """Семейства (ctrl, family) среди кандидатов, эффект которых не измерен."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for cand in candidates:
        ctrl = cand.get("ctrl_type") or cand.get("controller") or ""
        name = cand.get("action_name") or cand.get("name") or ""
        family = family_of(name)
        key = (str(ctrl), family)
        if key in seen or action_known(str(ctrl), name):
            continue
        seen.add(key)
        out.append(key)
    return out


def questions(model, *, unknowns_limit: int = 10,
              min_reports: int = 3) -> dict[str, Any]:
    """Витрина: что неизвестно, с чем мир спорит и сколько мы уже пробовали.

    Это то, что агент (и человек) может посмотреть, чтобы понять, куда вообще
    стоит вкладывать ходы: без такой витрины незнание остаётся молчаливым.
    """
    return {
        "unknown_keys": model.unknowns(limit=unknowns_limit),
        "contested_keys": model.contested(min_reports=min_reports),
        "experiment_attempts": dict(model.experiment_attempts),
        "confidence_k": CONFIDENCE_K,
    }
