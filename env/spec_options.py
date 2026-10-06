"""§4.3–4.5: кандидаты из меню, проекция прироста и выбор ядра.

Мост между миром и ядром. Генератор объявляет, что изменится, если действие
исполнить, и передаёт решение ядру — сам он не выбирает и ничего не ранжирует:
порядок ключей §4.5, барьерные условия и разрешение ничьей живут в ядре.

Что объявлено — и потому проверяемо:

* **Длительность.** У каждого действия меню `estimated_duration_mks` равно
  ``TURN_DURATION_MKS``: действие занимает ход. Это не время до *последствия*
  (постройка завершится позже) — последствие в горизонт счёта не входит и в
  приросте не объявляется.
* **Срок.** `deadlines[X]` = горизонт восстановления сущности ``X``. `τ` есть
  самый срочный из сроков (§3.2b), и модель объявляет срок одной величиной с
  горизонтом восстановления: обе отвечают на один вопрос — сколько у сущности
  есть. Разводить их без данных значило бы выдумать вторую.
* **Обратимость.** Действие откатывается, если оно не в списке
  ``SPEC_IRREVERSIBLE_ACTIONS``. Мир объявляет себя списком, а не выводом.
* **Расход.** У постройки он объявляется по наблюдённой цене (`build_cost` в
  спеках технологии), у исследования — не объявляется: цены исследования мир не
  публикует. Необъявленный расход — названный пробел, и отчёт печатает, у скольких
  опций цена неизвестна, рядом с вердиктом.
* **Прирост.** Считается **пересчётом линз** на спроецированном меню, а не
  объявленной таблицей: у исследования дверь закрывается у игрока и открывается
  у городов. Где спроецировать нечего (перемещение, смена правления), прирост
  пуст — пустой прирост не выдумывается.

Закрытий (§4.4) пока не объявлено ни у одной опции: списки пусты, и это тоже
названный пробел, а не утверждение, что действие ничего не разрушает.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from brain.spec.calculus_core import ActionOption, ResourceObservation

from .config import (
    SPEC_COUNTING_HORIZON_TURNS,
    SPEC_ENTITY_CONSUMING_ACTIONS,
    SPEC_IRREVERSIBLE_ACTIONS,
    SPEC_MEAN_CONSUMING_ACTIONS,
    SPEC_MEANS_HORIZON_TURNS,
    SPEC_PRODUCTION_ACTION_PREFIX,
    SPEC_RECOVERY_HORIZON_TURNS,
    SPEC_RESEARCH_ACTION_PREFIX,
    SPEC_TECH_GOAL_ACTION_PREFIX,
    TURN_DURATION_MKS,
)
from .spec_lenses import entity_type_of, gate_opens

#: Пересчёт DoF по спроецированному меню и спроецированным средствам: `remeasure(меню, средства)`.
Remeasure = Callable[..., Mapping[str, float]]

__all__ = [
    "act_id_for",
    "build_options",
    "budget_deadlines",
    "closures_for",
    "decide",
    "is_reversible_action",
    "payment_in_horizon",
    "project_option",
    "resource_draw",
    "resource_observations",
    "requires_for",
]


def _pay(means: Optional[Mapping[str, float]], resource: str,
         amount: float) -> dict[str, float]:
    """Средства после платежа: не больше, чем есть.

    Долга модель не объявляет: потратить больше, чем есть, нельзя, и урезать
    средства в минус значило бы выдумать возможность, которой у агента нет.
    Опция, которой не хватает средств, — не «в минусе», а неплатёжеспособна, и
    это вердикт §4.8, а не число.
    """
    out = {str(k): float(v) for k, v in (means or {}).items()}
    out[str(resource)] = max(0.0, out.get(str(resource), 0.0) - float(amount))
    return out


def payment_in_horizon(cost: Optional[float], production: Optional[float],
                       horizon_turns: float = SPEC_MEANS_HORIZON_TURNS) -> float:
    """Сколько уходит из средств **за горизонт**: платёж, а не цена.

    Цена (§4.8) и платёж (§4.3) отвечают на разные вопросы: цена — «подъёмно ли
    вообще», платёж — «сколько убывает сейчас». Предмет, который город успевает
    построить за горизонт, платится и в тот же срок приходит приобретением
    города, поэтому за горизонт средства не убывают. Предмет, который не
    успевает, забирает за горизонт **производительность** города (наблюдаемое
    поле) — и только её: остаток цены ещё не уплачен.

    Число ходов — не догадка, а деление наблюдённых величин: `ceil(цена /
    производительность)`.
    """
    if cost is None or production is None or float(production) <= 0.0:
        return 0.0                     # нечем платить или нечего платить — платежа не объявляем
    turns = math.ceil(float(cost) / float(production))
    if turns <= float(horizon_turns):
        return 0.0                     # успевает: за горизонт средства не убывают
    return float(min(float(production), float(cost)))


def is_reversible_action(action: str) -> bool:
    """Обратимо ли действие **по объявлению**.

    Это объявление о мире, а не вывод о конкретной опции: ядро выводит обратимость
    опции из её списка закрытий (§4.4) и объявлению не верит. Функция нужна, чтобы
    сверять одно с другим: объявленная необратимой опция обязана назвать потерю.
    """
    return not any(str(action).startswith(p) for p in SPEC_IRREVERSIBLE_ACTIONS)


def closures_for(entity_id: str, action: str,
                 vectors: Mapping[str, Sequence[str]],
                 act_id: str) -> list[dict[str, str]]:
    """Что опция разрушает — списком §4.4, а не ярлыком.

    Необратимость без названной потери недопустима (охранник 2), а назвать
    потерянным собственный путь — противоречие (охранник 1). Поэтому список
    строится из объявления: тратящая сущность закрывает **все свои акты, кроме
    исполняемого**, тратящая средство — само средство.
    """
    out: list[dict[str, str]] = []
    name = str(action)
    if any(name.startswith(p) for p in SPEC_ENTITY_CONSUMING_ACTIONS):
        out += [{"kind": "act", "id": f"{entity_id}:{other}"}
                for other in vectors.get(entity_id, [])
                if f"{entity_id}:{other}" != act_id]
    for prefix, mean in SPEC_MEAN_CONSUMING_ACTIONS.items():
        if name.startswith(str(prefix)):
            out.append({"kind": "mean", "id": str(mean)})
    return out


def requires_for(action: str) -> list[str]:
    """Какие ресурсы действие требует для проверки §4.8."""
    name = str(action)
    if name.startswith(SPEC_PRODUCTION_ACTION_PREFIX):
        return ["energy"]
    if name.startswith((SPEC_RESEARCH_ACTION_PREFIX, SPEC_TECH_GOAL_ACTION_PREFIX)):
        return ["tech"]
    return []


def act_id_for(entity_id: str, action: str, graph: Any) -> str:
    """Идентификатор акта, которым опция исполняется.

    У действия может быть несколько актов (исследование ведёт по ребру к каждому
    городу, которому оно открывает дверь). Опция называет **свой** акт, если он
    есть, иначе — первый мост: так §4.4 сможет сослаться на акт, а отчёт — на
    путь.
    """
    own = f"{entity_id}:{action}"
    bridge = None
    for act in getattr(graph, "acts", []) or []:
        if getattr(act, "id", None) == own:
            return own
        if bridge is None and str(getattr(act, "id", "")).startswith(own + "->"):
            bridge = str(act.id)
    return bridge or own


def project_option(entity_id: str, action: str,
                   vectors: Mapping[str, Sequence[str]],
                   raw_menus: Mapping[str, Sequence[str]],
                   catalogue: Optional[Mapping[str, Any]],
                   known_techs: Iterable[str],
                   remeasure: Remeasure,
                   means: Optional[Mapping[str, float]] = None,
                   pay: Optional[tuple[str, float]] = None) -> tuple[dict[str, float], str]:
    """Что изменится в DoF мира, если действие исполнить, и откуда это известно.

    Возвращается **только то, что модель умеет спроецировать**, и только
    изменения: пустая карта означает «проекции нет», а не «изменения нет».
    """
    name = str(action)
    if name.startswith(SPEC_PRODUCTION_ACTION_PREFIX):
        resource, amount = (pay or ("", 0.0))
        if not resource or float(amount) <= 0.0:
            return {}, "платежа в горизонте нет — средства не убывают"
        current = list(vectors.get(entity_id, []))
        before = remeasure({entity_id: current}, means)
        after = remeasure({entity_id: current}, _pay(means, resource, amount))
        delta = float(after[entity_id]) - float(before[entity_id])
        if abs(delta) < 1e-12:
            return {}, "платёж линзу средств не сдвинул"
        return ({entity_id: delta},
                f"платёж {float(amount):.0f} {resource} за горизонт "
                f"из {float((means or {}).get(resource, 0.0)):.0f}")
    if not name.startswith(SPEC_RESEARCH_ACTION_PREFIX):
        return {}, "прирост не объявлен"
    tech_id = str(action).rsplit("_", 1)[-1]
    opened = gate_opens(tech_id, catalogue, known_techs)
    if not opened:
        return {}, "дверь ничего не открывает"
    projected: dict[str, list[str]] = {k: list(v) for k, v in vectors.items()}
    # Дверь закрывается: у игрока исчезают и исследование этой технологии, и её цель.
    projected[entity_id] = [
        n for n in vectors.get(entity_id, [])
        if not (str(n).startswith((SPEC_RESEARCH_ACTION_PREFIX,
                                   SPEC_TECH_GOAL_ACTION_PREFIX))
                and str(n).rsplit("_", 1)[-1] == tech_id)
    ]
    touched = [entity_id]
    for city_id, raw in raw_menus.items():
        if not str(city_id).startswith("city_"):
            continue
        buildable = {str(n) for n in raw}
        gained = sorted(f"{SPEC_PRODUCTION_ACTION_PREFIX}{item}" for item in opened
                        if f"{SPEC_PRODUCTION_ACTION_PREFIX}{item}" in buildable)
        if not gained:
            continue                         # открывать нечего: город этого не строит
        projected[city_id] = sorted(set(projected.get(city_id, [])) | set(gained))
        touched.append(str(city_id))
    before = remeasure({k: vectors[k] for k in touched}, means)
    after = remeasure({k: projected[k] for k in touched}, means)
    delta = {k: float(after[k]) - float(before[k]) for k in touched
             if abs(float(after[k]) - float(before[k])) > 1e-12}
    return delta, (f"открывает предметов {len(opened)}, "
                   f"достанется городам {len(touched) - 1}")


def resource_draw(entity_id: str, action: str,
                  costs: Optional[Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Наблюдённый расход действия по ресурсам — для §4.8.

    Постройка платит щитами по своей цене (`build_cost`). Чего цена неизвестна —
    того и расхода: незнание не превращается ни в ноль, ни в запрет.
    """
    name = str(action)
    if not name.startswith(SPEC_PRODUCTION_ACTION_PREFIX) or not costs:
        return {}
    cost = costs.get(name[len(SPEC_PRODUCTION_ACTION_PREFIX):])
    if cost is None:
        return {}
    return {str(entity_id): {"energy": -float(cost)}}


def build_options(vectors: Mapping[str, Sequence[str]],
                  raw_menus: Mapping[str, Sequence[str]],
                  catalogue: Optional[Mapping[str, Any]],
                  known_techs: Iterable[str],
                  graph: Any,
                  remeasure: Remeasure,
                  only: Optional[Sequence[str]] = None,
                  costs: Optional[Mapping[str, float]] = None,
                  means: Optional[Mapping[str, float]] = None,
                  production: Optional[Mapping[str, float]] = None,
                  horizon_turns: float = SPEC_MEANS_HORIZON_TURNS) -> list[ActionOption]:
    """Кандидаты §3.3 для объявленных сущностей — по одной опции на вектор.

    Кандидат не выбирает и ничего не взвешивает: он объявляет прирост (§4.3),
    закрытия (§4.4), обратимость, длительность и требуемые ресурсы.
    """
    targets = list(only) if only is not None else sorted(vectors)
    options: list[ActionOption] = []
    for entity_id in targets:
        for action in vectors.get(entity_id, []):
            pay: Optional[tuple[str, float]] = None
            if str(action).startswith(SPEC_PRODUCTION_ACTION_PREFIX):
                item = str(action)[len(SPEC_PRODUCTION_ACTION_PREFIX):]
                pay = ("energy", payment_in_horizon((costs or {}).get(item),
                                                    (production or {}).get(entity_id),
                                                    horizon_turns))
            delta, why = project_option(entity_id, action, vectors, raw_menus,
                                        catalogue, known_techs, remeasure,
                                        means=means, pay=pay)
            act_id = act_id_for(entity_id, action, graph)
            closed = closures_for(entity_id, action, vectors, act_id)
            options.append(ActionOption(
                option_id=f"{entity_id}:{action}",
                description=f"{action} — {why}",
                projected_dof_delta=delta,
                closed=closed,
                # §4.4: обратимость выводится из списка закрытий, а не назначается.
                is_reversible=not closed,
                estimated_duration_mks=TURN_DURATION_MKS,
                projected_resource_delta=resource_draw(entity_id, action, costs),
                requires=requires_for(action),
                act_id=act_id,
            ))
    return options


def budget_deadlines(entities: Iterable[str]) -> dict[str, float]:
    """Срок каждой сущности — её горизонт восстановления, в абсолютном времени.

    `τ` берётся из сроков (§3.2b), поэтому объявление одно: сколько сущности
    дано. Неизвестный вид сущности получает горизонт счёта — названно, а не
    молча.
    """
    out: dict[str, float] = {}
    for entity_id in entities:
        kind = entity_type_of(str(entity_id))
        turns = SPEC_RECOVERY_HORIZON_TURNS.get(
            kind, SPEC_RECOVERY_HORIZON_TURNS.get("default", SPEC_COUNTING_HORIZON_TURNS))
        out[str(entity_id)] = float(turns) * TURN_DURATION_MKS
    return out


def resource_observations(means: Mapping[str, float]) -> dict[str, ResourceObservation]:
    """Средства как наблюдения ресурсов — для §4.8."""
    return {str(name): ResourceObservation(value=float(value), unit=str(name),
                                           scale=1.0, source="наблюдение империи")
            for name, value in means.items()}


def decide(core: Any, state: Any, options: Sequence[ActionOption],
           ctx: Any) -> tuple[Optional[ActionOption], list[dict[str, object]],
                              list[dict[str, str]]]:
    """§4.10.1 + §4.5: допустимость, затем выбор. Ядро решает, драйвер платит.

    Допустимость — одно предикатное условие из трёх семейств: применимость
    (`viable`, §4.8b), оплата (`resources_ok`, §4.8) и структура (`D1=D2=D3=0`).
    Отказ любого из них барит кандидата, и отказ **печатается**: барьер — это
    вердикт, а не фильтр отображения.
    """
    rows: list[dict[str, object]] = []
    admissible: list[ActionOption] = []
    payable, barred = core.apply_resource_gate(state, list(options))
    payable_ids = {o.option_id for o in payable}
    for option in options:
        vector = core.candidate_vector(state, option, ctx)
        viability = core.viability(state, option)
        vector["viable"] = bool(viability["viable"])
        vector["resources_ok"] = option.option_id in payable_ids
        vector["barred_by"] = core.barring_key(vector)
        rows.append(vector)
        if vector["barred_by"] is None:
            admissible.append(option)
    winner, _ = core.select_candidate(state, admissible, ctx)
    return winner, rows, barred
