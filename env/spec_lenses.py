"""DOF-Core v0.11 §4.6 — отображение игровых величин в линзы ψ_var · ψ_opt · ψ_con.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ
---------------------------------------
Делает: добывает **счётчики** из игры — векторы реакции (`V`, `V_env`), требования
к ресурсам (`c_g`), средства (`C_g`), различаемые переменные (`F`, `F_env`).

Не делает: **не считает линзы сам**. `ψ_var`, `ψ_opt`, `ψ_con`, произведение,
дайджесты и весь §4.6/§4.7 живут в эталонном ядре (`brain/spec/measurement.py`),
вложенном в проект как `brain/spec` (DOF-Core v0.11, см. `brain/spec/__init__.py`).
Правило простое: **счётчики добывает мир, математику делает ядро**. Своя формула
здесь была бы второй линейкой — и любые числа стали бы несравнимы с эталоном.

Объявление (§3.4.1) — в `env/config.py`, блок `SPEC_*`. Оно хешируемое: меняете
значение там — меняется `ruler_digest`, и сравнение с прежними числами запрещено
(§3.4.4). Здесь — только процедуры, которые превращают наблюдение в счётчики.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from brain.spec.measurement import (
    LENS_ORDER,
    EntityMeasurement,
    LensObservation,
    MeasurementDeclaration,
    build_declaration,
    canonical_groups,
    derive_blocks,
    measure_entity,
)

from .config import (
    CONFIG,
    SPEC_ACTION_CATEGORY,
    SPEC_COUNTING_HORIZON_TURNS,
    SPEC_ENERGY_UNIT,
    SPEC_GROUP_NUMERAIRE,
    SPEC_HOSTILE_DIPLOMATIC_STATES,
    SPEC_ITEM_REQ_KIND_ADVANCE,
    SPEC_PRODUCTION_ACTION_PREFIX,
    SPEC_LENS_ORDER,
    SPEC_MANDATE_CAP,
    SPEC_MEANS_HORIZON_TURNS,
    SPEC_V_ENV_COUNTS_FOREIGN_POWERS,
    SPEC_VARIABLE_BY_CATEGORY,
    SPEC_OBSERVED_RATES,
    SPEC_PSI_ID,
    SPEC_REQUIREMENT_REDUCTION,
    SPEC_RESOURCE_GROUPS,
    SPEC_RESOURCE_UNITS,
    SPEC_RESPONSE_VECTOR_RULE,
    SPEC_V_ENV_SOURCES,
    SPEC_VARIABLE_SET_BY_TYPE,
)

#: Контроллеры, чьи действия адресованы сущности, которую экстрактор назвал
#: `<ctrl>_<actor>` (см. `env/entity_extractor.py`: `unit_<id>`, `city_<id>`,
#: `tech_<id>`). `gov` и `player` — системные: своей сущности у них нет.
ENTITY_CTRLS = ("unit", "city", "tech", "dipl")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Векторы реакции (V) — из настоящего меню мира
# ═══════════════════════════════════════════════════════════════════════════════

#: Контроллер CivRealm → префикс имени сущности. Дипломатия названа
#: `diplomacy_<id>`, а её контроллер — `dipl`, отсюда таблица, а не склейка строк.
_CTRL_PREFIX = {"unit": "unit", "city": "city", "dipl": "diplomacy"}

#: Контроллеры, действия которых мир адресует **игроку**, а не тому, кого действие
#: называет: `tech/cur_player` (исследование) и `gov/0` (форма правления). Технология
#: здесь — не сущность, а предмет действия: исследуемая — цель акта, известная —
#: открытая дверь. Поэтому и акт, и вектор реакции принадлежат игроку.
_PLAYER_CONTROLLERS = ("tech", "gov")

#: Действия над технологией: имя несёт её номер в хвосте (`research_tech_Alphabet_2`).
_TECH_ACTION_PREFIXES = ("research_tech_", "set_tech_goal_")


def action_entity(ctrl_type: Any, actor_id: Any, action_name: Any) -> Optional[str]:
    """Сущность, которой адресовано действие, или None (действие системное).

    Исследование и смена правления адресованы игроку, хотя записаны под
    контроллерами `tech` и `gov`: мир хранит их как `tech/cur_player` и `gov/0`.
    """
    ctrl = str(ctrl_type)
    name = str(action_name)
    if ctrl in _CTRL_PREFIX:
        return f"{_CTRL_PREFIX[ctrl]}_{actor_id}"
    if ctrl in _PLAYER_CONTROLLERS:
        return f"player_{CONFIG.my_player_id}"
    return None


def _iter_actions(actions: Any) -> list[tuple[str, Any]]:
    """Действия актора в любой из форм, которые публикует мир.

    Наблюдены две: `{имя: params}` (так их отдаёт civrealm клиенту) и просто
    `[имя, ...]` (так они лежат в сохранённом наблюдении). Читать одну и падать на
    другой — значит мерить не мир, а формат сериализации.
    """
    if isinstance(actions, Mapping):
        return [(str(k), v) for k, v in actions.items()]
    if isinstance(actions, (list, tuple)):
        out: list[tuple[str, Any]] = []
        for item in actions:
            if isinstance(item, str):
                out.append((item, True))
            elif isinstance(item, (list, tuple)) and item:
                out.append((str(item[0]), item[1] if len(item) > 1 else True))
        return out
    return []


def menu_by_entity(available_actions: Mapping[str, Any],
                   valid_only: bool = True) -> dict[str, list[str]]:
    """Меню мира → {сущность: [имена действий]}.

    Формат CivRealm: `{ctrl_type: {actor_id: {action_name: params}}}`. Действие с
    пустыми параметрами мир не примет (civrealm срезает такие до предложения), и
    считать его вектором реакции значило бы объявить свободой то, чего нет.
    """
    menu: dict[str, list[str]] = {}
    for ctrl_type, actors in (available_actions or {}).items():
        if not isinstance(actors, Mapping):
            continue
        for actor_id, actions in actors.items():
            for action_name, params in _iter_actions(actions):
                if valid_only and not _truthy(params):
                    continue
                entity_id = action_entity(ctrl_type, actor_id, action_name)
                if entity_id is None:
                    continue
                menu.setdefault(entity_id, []).append(action_name)
    return menu


def _truthy(value: Any) -> bool:
    """Пустой словарь/список/None/массив — «мир это не предложит»."""
    if value is None:
        return False
    if isinstance(value, Mapping):
        return bool(value)
    try:
        return bool(value) and len(value) > 0
    except TypeError:
        return bool(value)


def response_vector_count(names: Iterable[str],
                          rule: str = SPEC_RESPONSE_VECTOR_RULE) -> int:
    """V — число различимых векторов реакции.

    `per_action_name`: каждое имя действия — свой вектор (`goto_0`…`goto_7` —
    восемь разных реакций). Правило объявлено в конфиге и входит в дайджест.
    """
    unique = {str(n) for n in names}
    if rule == "per_action_name":
        return len(unique)
    raise ValueError(f"неизвестное правило счёта векторов реакции: {rule!r}")


def foreign_powers(obs: Mapping[str, Any],
                   my_player_id: Optional[int] = None) -> list[str]:
    """Чужие державы, о существовании которых мир сообщает (§4.6).

    Существование державы — **наблюдаемое** свойство мира (`obs["player"]`), а
    нейтралитет — состояние, а не способность: пока держава есть, она может
    действовать против нас, и это внешнее возмущение. Считается по числу держав,
    потому что числа добывает мир; весов здесь нет.
    """
    me_id = CONFIG.my_player_id if my_player_id is None else my_player_id
    return [f"player_{p}" for p in sorted((obs.get("player") or {}), key=str)
            if str(p) != str(me_id)]


def disturbance_count(active_sources: Iterable[str],
                      declared: Sequence[str] = SPEC_V_ENV_SOURCES,
                      foreign_powers: Iterable[str] = ()) -> int:
    """`V_env` — внешние возмущения, СНИМАЮЩИЕ вектор реакции (§4.6).

    Считаются только объявленные источники: счёт за разные списки — разные
    линейки. Источник, которого нет в объявлении, игнорируется молча НЕ здесь —
    он просто не входит в объявленный набор, а набор и есть объявление.

    Наблюдённые виды возмущений считаются по видам, чужие державы — по числу
    держав (`SPEC_V_ENV_COUNTS_FOREIGN_POWERS`): одна держава — одно возмущение.
    """
    declared_set = set(declared)
    kinds = len({str(s) for s in active_sources} & declared_set)
    powers = len({str(p) for p in foreign_powers}) if SPEC_V_ENV_COUNTS_FOREIGN_POWERS else 0
    return kinds + powers


def active_disturbances(obs: Mapping[str, Any], entity_id: str, entity_type: str,
                        my_player_id: Optional[int] = None) -> list[str]:
    """Наблюдённые возмущения сущности — из объявленного набора источников (§4.6).

    Возмущение **снимает вектор реакции**: вражеский боевой юнит в радиусе
    «ход + удар» может уничтожить сущность, а с ней исчезают все её векторы.
    Заморозка размерности (лимит, закон, мандат) сюда НЕ входит — она в `F_env`.

    Источник, которого мир не публикует, не выдумывается: он просто не активен.
    Считаются только источники из объявления — иначе два счёта по разным спискам
    были бы несравнимы.
    """
    me_id = CONFIG.my_player_id if my_player_id is None else my_player_id
    active: list[str] = []

    # Война снимает векторы реакции и видна БЕЗ контакта: вражеский юнит не обязан
    # попасть в поле зрения, чтобы состояние войны было известно. Поэтому источник
    # читается из дипломатических состояний, а не из карты.
    hostile_states = set(SPEC_HOSTILE_DIPLOMATIC_STATES)
    for rec in (obs.get("dipl") or {}).values():
        if isinstance(rec, Mapping) and _num(rec.get("diplomatic_state"), -1.0) in hostile_states:
            active.append("hostile_diplo")
            break

    hostile = [
        u for u in (obs.get("unit") or {}).values()
        if isinstance(u, Mapping) and u.get("owner") != me_id
    ]
    if not hostile:
        return active
    collection = obs.get("unit") if entity_type == "unit" else obs.get("city")
    rec = (collection or {}).get(str(entity_id).split("_", 1)[-1])
    if not isinstance(rec, Mapping) or "x" not in rec or "y" not in rec:
        return active
    x, y = float(rec.get("x") or 0.0), float(rec.get("y") or 0.0)
    reach = (float(rec.get("moves_left") or 0.0) + 1.0) if entity_type == "unit" else 3.0
    for u in hostile:
        if "x" in u and "y" in u:
            if max(abs(float(u["x"]) - x), abs(float(u["y"]) - y)) <= reach:
                active.append("hostile_in_strike_range")
                break
    return active


def variety_counters(menu_names: Iterable[str],
                     active_disturbances: Iterable[str] = (),
                     foreign_powers: Iterable[str] = ()) -> dict[str, float]:
    """Пара счётчиков линзы разнообразия (§4.6). Целые счётчики, не доли."""
    return {
        "V": float(response_vector_count(menu_names)),
        "V_env": float(disturbance_count(active_disturbances, foreign_powers=foreign_powers)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Требования → блоки (c_g, C_g)
# ═══════════════════════════════════════════════════════════════════════════════

def reduce_requirements(
    per_transition: Sequence[Mapping[str, float]],
    rule: str = SPEC_REQUIREMENT_REDUCTION,
) -> dict[str, float]:
    """Требования переходов → одно требование на ресурс (§4.6).

    Спека требует, чтобы `c_g` выводилось **именованной процедурой** из
    «per-resource requirements of the entity's transitions»; свёртка набора
    переходов в одно число — и есть эта процедура, поэтому она объявлена.

    `min` (принято): требование самого дешёвого доступного перехода — «хватает
    на что-то одно ⇒ канал открыт». `mean` — середина. `selected` — требование
    выбранного перехода (тогда линза читает кандидата, а не сущность).
    """
    resources = {str(r) for t in per_transition for r in t}
    out: dict[str, float] = {}
    for res in sorted(resources):
        amounts = [max(0.0, float(t.get(res, 0.0))) for t in per_transition]
        if not amounts:
            out[res] = 0.0
        elif rule == "min":
            out[res] = min(amounts)
        elif rule == "mean":
            out[res] = sum(amounts) / len(amounts)
        elif rule == "selected":
            raise ValueError(
                "правило 'selected' требует конкретного перехода: передайте "
                "per_transition из одного перехода"
            )
        else:
            raise ValueError(f"неизвестное правило свёртки требований: {rule!r}")
    return out


def option_blocks(requirements: Mapping[str, float],
                  means: Mapping[str, float],
                  groups: Sequence[Sequence[str]] = SPEC_RESOURCE_GROUPS,
                  rates: Mapping[tuple[str, str], float] = SPEC_OBSERVED_RATES,
                  cap: Optional[float] = SPEC_MANDATE_CAP
                  ) -> list[tuple[float, float]]:
    """Блоки `(c_g, C_g)` — **эталонной** процедурой `derive_blocks` (§4.6).

    Курсы `w_j` берутся из объявленных наблюдённых курсов в нумэрайр группы.
    Сейчас объявленный набор пуст — значит «курс не измерен», и эталон подставляет
    1.0. Это записано в объявлении, а не растворено в коде.
    """
    weights = _weights_to_numeraire(groups, rates)
    return derive_blocks(dict(requirements), dict(means), groups, weights, cap)


def means_with_income(stocks: Mapping[str, float],
                      incomes: Mapping[str, float],
                      horizon: float = SPEC_MEANS_HORIZON_TURNS,
                      measured_tech_rate: Optional[float] = None) -> dict[str, float]:
    """Средства группы `C_g`: запас + доход за окно (§4.6).

    Запас без дохода объявлял бы город без накопленных щитов неспособным ни на что,
    хотя игра платит за постройку **из дохода по ходам**. Окно объявлено
    (`SPEC_MEANS_HORIZON_TURNS`), а не выбрано на месте: у него та же природа, что у
    горизонта счёта, — два счёта за разные окна несравнимы.

    `measured_tech_rate` — ИЗМЕРЕННАЯ скорость науки (Δ `bulbs_researched` за ход,
    §13.11). У группы `tech` публикуемого поля дохода нет
    (`SPEC_INCOME_FIELDS["tech"] == ()`), поэтому без измерения группа получает
    доход 0 — названно, а не выдуманным числом (`science` и колбы города темпом не
    являются: замер 2026-10-06).
    """
    out = {str(r): float(v) for r, v in stocks.items()}
    for res, income in incomes.items():
        key = str(res)
        out[key] = out.get(key, 0.0) + float(income) * float(horizon)
    if measured_tech_rate is not None:
        out["tech"] = out.get("tech", 0.0) + float(measured_tech_rate) * float(horizon)
    return out


def measured_science_rate(prev_obs: Optional[Mapping[str, Any]],
                          obs: Optional[Mapping[str, Any]],
                          player_id: Any = 0) -> Optional[float]:
    """Измеренная скорость науки: Δ `bulbs_researched` между двумя наблюдениями.

    §13.11: скорость науки — величина ИЗМЕРЯЕМАЯ, а не публикуемое поле. Замер на
    стенде (2026-10-06): 1 балл за ход при `player["science"]` 60 и колбах города 5,
    и технология с ценой 28 завершилась ровно через 28 ходов. Возвращается `None`,
    когда измерять не по чему (нет предыдущего наблюдения) или цель сменилась —
    тогда накопление сброшено и разность темпом не является. Это незнание, а не
    ноль: ноль здесь был бы утверждением «наука не идёт».
    """
    if not prev_obs or not obs:
        return None

    def rec(source: Mapping[str, Any]) -> Mapping[str, Any]:
        for layer_name in ("player", "players"):
            layer = (source or {}).get(layer_name) or {}
            if isinstance(layer, Mapping):
                for key in (player_id, str(player_id), 0, "0"):
                    if key in layer:
                        return layer[key] or {}
        return {}

    before, after = rec(prev_obs), rec(obs)
    if "bulbs_researched" not in before or "bulbs_researched" not in after:
        return None
    if before.get("researching") != after.get("researching"):
        return None
    delta = float(after.get("bulbs_researched") or 0.0) - float(before.get("bulbs_researched") or 0.0)
    return delta if delta >= 0.0 else None


def _group_numeraire(group: Sequence[str]) -> Optional[str]:
    """Нумэрайр группы — по её членам, отсортированным как в объявлении."""
    return SPEC_GROUP_NUMERAIRE.get(",".join(sorted(str(m) for m in group)))


def _weights_to_numeraire(groups: Sequence[Sequence[str]],
                          rates: Mapping[tuple[str, str], float]
                          ) -> dict[str, float]:
    """`(ресурс, нумэрайр) → курс` в вид, который ждёт `derive_blocks`."""
    weights: dict[str, float] = {}
    for group in groups:
        members = [str(m) for m in group]
        numeraire = _group_numeraire(members)
        if numeraire is None:
            continue
        for member in members:
            rate = rates.get((member, numeraire))
            if rate is not None:
                weights[member] = float(rate)
    return weights


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Различаемые переменные (F) — и замороженный извне спрос (F_env)
# ═══════════════════════════════════════════════════════════════════════════════

def constraint_counters(variables: Sequence[str],
                        frozen: Sequence[str] = ()) -> dict[str, float]:
    """Пара счётчиков линзы ограничения (§4.6).

    `F` — сколько объявленных переменных **ещё не заморожено**;
    `F_env` — сколько заморожено **извне** (лимит правил, мандат, физический
    закон, унаследованное требование совместимости).

    Заморозка, которой нет в объявленном наборе, — ошибка входа, а не ноль:
    молча проигнорированная, она сделала бы `F` больше, чем есть переменных.
    """
    declared = {str(v) for v in variables}
    frozen_set = {str(v) for v in frozen}
    unknown = frozen_set - declared
    if unknown:
        raise ValueError(
            f"заморожены переменные вне объявленного набора {sorted(declared)}: "
            f"{sorted(unknown)}"
        )
    return {"F": float(len(declared - frozen_set)), "F_env": float(len(frozen_set))}


def entity_type_of(entity_id: str) -> str:
    """Тип сущности по имени, как их даёт экстрактор (`unit_113` → `unit`)."""
    return str(entity_id).split("_", 1)[0]


def frozen_variables(entity_type: str, fields: Mapping[str, Any]) -> list[str]:
    """Замороженные извне переменные сущности — по наблюдаемым полям.

    Заморозка — это **спрос извне**, а не решение агента (§4.6): ход, израсходованный
    правилами; производство, остановленное беспорядком; уже известная технология.
    Возмущения (враг, осада) сюда НЕ относятся: они снимают векторы реакции и живут
    в `V_env`. Спека прямо запрещает менять эти два места местами.
    """
    declared = SPEC_VARIABLE_SET_BY_TYPE.get(entity_type, ())
    frozen: list[str] = []
    if entity_type == "unit":
        # Правила мира дают юниту конечное число ходов: **наблюдённые** исчерпанные ходы
        # замораживают позицию. Ненаблюдённое число ходов заморозки НЕ создаёт — это незнание,
        # а не отсутствие возможности (§4.6: заморожено только то, что навязано ИЗВНЕ, и это
        # должно быть наблюдено). Здесь стоял дефолт `0.0`, и он срабатывал всегда, потому что
        # `moves_left` в поля юнита не попадало: заморозка снимала все восемь направлений и все
        # работы на клетке, `V` падало с 12 до 1–2, и мотив пропадал у перемещения и работ.
        moves = fields.get("moves_left")
        if moves is not None and _num(moves, 0.0) <= 0.0:
            frozen.append("position")
    elif entity_type == "city":
        # Беспорядок останавливает производство — это то, что останавливает игра.
        if _num(fields.get("ppl_unhappy"), 0.0) > _num(fields.get("ppl_happy"), 0.0):
            frozen.append("production")
    elif entity_type == "tech":
        # Известная технология — ОТКРЫТАЯ ДВЕРЬ, а не сущность с решением: мир
        # не даёт её исследовать, и `research` заморожен внешними правилами.
        if gate_is_open(fields):
            frozen.append("research")
    return [v for v in frozen if v in declared]


def action_category(name: str) -> str:
    """Категория акта по имени действия — по самому длинному совпавшему префиксу.

    Неопознанное действие получает `"misc"`, которого нет в классе средств `M(S)`:
    акт, о котором мы не знаем, что он меняет, путей не создаёт.
    """
    best, category = "", "misc"
    for prefix, cat in SPEC_ACTION_CATEGORY:
        if name.startswith(prefix) and len(prefix) > len(best):
            best, category = prefix, cat
    return category


def action_targets_open_gate(name: str, known_gates: Iterable[str] = ()) -> bool:
    """Ведёт ли действие к уже открытой двери (`research_tech_Alphabet_2`).

    Мир перечисляет в меню исследование и известных технологий — как список для
    выбора, а не как возможность. Исследовать известное нельзя, и считать такое
    действие вектором реакции значило бы объявить свободой то, чего нет.
    """
    if not name.startswith(_TECH_ACTION_PREFIXES):
        return False
    tail = name.rsplit("_", 1)[-1]
    return tail in {str(g) for g in known_gates}


def catalogue_index(tech_records: Mapping[str, Any]) -> dict[str, Any]:
    """Каталог мира: чем открывается предмет и какие технологии ему нужны.

    Меню города — **каталог**, а не репертуар: в нём перечислено всё, что в
    принципе можно построить (на первом ходу там «AEGIS Cruiser» и «Apollo
    Program»). Доступность решает не меню, а требования самого предмета:
    `build_reqs` у юнита и `reqs` у улучшения, где `kind == 1` значит «нужна
    технология». Отсюда две вещи сразу: что доступно сейчас и что откроется, если
    технологию исследовать.

    Требования прочих видов не оцениваются — их число возвращается в
    `unevaluated`, а не размазывается молчанием по результату.
    """
    items: dict[str, dict[str, Any]] = {}
    unlocks: dict[str, list[str]] = {}
    for tech_id, rec in (tech_records or {}).items():
        if not isinstance(rec, Mapping):
            continue
        for key, req_key in (("sup_units", "build_reqs"), ("sup_improvements", "reqs")):
            for spec in (rec.get(key) or []):
                if not isinstance(spec, Mapping):
                    continue
                name = spec.get("name")
                if not name:
                    continue
                advance: set[str] = set()
                other = 0
                for req in (spec.get(req_key) or []):
                    if not isinstance(req, Mapping) or not req.get("present"):
                        continue
                    if req.get("kind") == SPEC_ITEM_REQ_KIND_ADVANCE:
                        advance.add(str(req.get("value")))
                    else:
                        other += 1
                entry = items.setdefault(str(name), {"advance": set(), "unevaluated": 0})
                entry["advance"] |= advance
                entry["unevaluated"] = max(int(entry["unevaluated"]), other)
                unlocks.setdefault(str(tech_id), []).append(str(name))
    unevaluated = sum(int(e["unevaluated"]) for e in items.values())
    return {"items": items, "unlocks": unlocks, "unevaluated": unevaluated}


def item_available(name: str, catalogue: Optional[Mapping[str, Any]],
                   known: Iterable[str] = ()) -> bool:
    """Доступен ли предмет сейчас: все его технологические требования известны.

    Предмет с неоценёнными требованиями недоступным не объявляется — он просто не
    судится (`True`), иначе незнание читалось бы как запрет. Предмет, которого нет
    в каталоге, тоже не судится.
    """
    if not catalogue:
        return True
    entry = (catalogue.get("items") or {}).get(str(name))
    if entry is None:
        return True
    if entry["unevaluated"]:
        return True
    return set(entry["advance"]) <= {str(k) for k in known}


def gate_opens(tech_id: Any, catalogue: Optional[Mapping[str, Any]],
               known: Iterable[str] = ()) -> list[str]:
    """Что откроет дверь: предметы, которым **этой технологии** и не хватает.

    Это и есть мост «технология → кому она открывает»: возвращаются только те
    предметы, которые станут доступны ровно из-за неё, а не вообще всё, что она
    перечисляет.
    """
    if not catalogue:
        return []
    known_set = {str(k) for k in known}
    after = known_set | {str(tech_id)}
    out: list[str] = []
    for name in (catalogue.get("unlocks") or {}).get(str(tech_id)) or []:
        entry = (catalogue.get("items") or {}).get(str(name))
        if entry is None or entry["unevaluated"]:
            continue
        advance = set(entry["advance"])
        if advance <= after and not advance <= known_set:
            out.append(str(name))
    return sorted(out)


def available_vectors(entity_type: str, fields: Mapping[str, Any],
                      names: Iterable[str],
                      known_gates: Iterable[str] = (),
                      catalogue: Optional[Mapping[str, Any]] = None,
                      known_techs: Iterable[str] = (),
                      production_effects: Optional[Mapping[str, float]] = None,
                      allowed_now: Optional[Iterable[str]] = None) -> list[str]:
    """Векторы реакции сущности: меню минус то, что мертво (§4.6).

    Меню — предложение мира, а не список возможного. Вектором реакции не является
    ни запись, переменная которой у сущности заморожена, ни действие над уже
    открытой дверью, ни позиция каталога, требования которой ещё не выполнены.
    Одно правило на всё — и для счёта `V`, и для блоков `c/C`, и для актов графа
    (§3.5): иначе `V` считал бы то, чего сущность не может, а граф строил бы пути,
    которых нет.
    """
    frozen = set(frozen_variables(entity_type, fields))
    out: list[str] = []
    for name in names:
        if action_targets_open_gate(name, known_gates):
            continue
        if name.startswith(SPEC_PRODUCTION_ACTION_PREFIX) and catalogue:
            item = name[len(SPEC_PRODUCTION_ACTION_PREFIX):]
            if not item_available(item, catalogue, known_techs):
                continue
        variable = SPEC_VARIABLE_BY_CATEGORY.get(action_category(name))
        if variable is not None and variable in frozen:
            continue
        if name.startswith(SPEC_PRODUCTION_ACTION_PREFIX) and production_effects is not None:
            item = name[len(SPEC_PRODUCTION_ACTION_PREFIX):]
            if float(production_effects.get(item, 0.0)) <= 0.0:
                continue        # имя, которое ничего не даёт системе, вектором реакции не является
        if (name.startswith(SPEC_PRODUCTION_ACTION_PREFIX) and allowed_now is not None
                and name not in set(allowed_now)):
            # «Сейчас» судит МИР: имя, которого нет среди предложенных им действий
            # (`produce_<Имя>` с непустыми параметрами), городом сейчас не начато быть не может.
            # Для «максимума» этот список не передаётся — тогда судится весь каталог.
            continue
        out.append(name)
    return out


#: Объявленный список типов-основателей (структура `v2` §3.1; ОБЪЯВЛЕНИЕ, не замер).
SPEC_CITY_FOUNDING_UNIT_TYPES: tuple[str, ...] = ("Settlers", "Engineers", "Migrants", "Nomads")

#: Путь к `units.ruleset` мира — источник порядка типов юнитов для маски города `can_build_unit`.
SPEC_UNIT_RULESET_PATH: str = os.environ.get(
    "SPEC_UNIT_RULESET_PATH",
    "civrealm/src/civrealm/freeciv/misc/modified_server_code/units.ruleset")


def unit_specs_index(tech_records: Optional[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Имя предмета → его запись каталога с полями типа.

    `catalogue_index` хранит только требования; для способности нужны поля типа
    (атака, защита, цена), поэтому они собираются отдельным индексом.
    """
    out: dict[str, dict[str, Any]] = {}
    for _tid, rec in (tech_records or {}).items():
        if not isinstance(rec, Mapping):
            continue
        for key in ("sup_units", "sup_improvements"):
            for spec in (rec.get(key) or []):
                if isinstance(spec, Mapping) and spec.get("name"):
                    out.setdefault(str(spec["name"]), dict(spec))
    return out


def unit_order_index(ruleset_path: Optional[Any] = None) -> dict[int, str]:
    """Отображение «номер позиции в маске города → имя типа юнита».

    Источник — мировая таблица `UNIT_TYPES` (`civrealm/src/civrealm/freeciv/utils/unit_improvement_const.py`):
    52 имени, ровно как длина маски `can_build_unit`. Порядок из `units.ruleset` для этого **не годится**:
    там 56 секций и есть лишний `Migrants`, из-за чего позиции сдвигаются (проверено: по ruleset
    истины `[0, 3]` читались как «Settlers + Engineers», а по мировой таблице — «Settlers + Warriors»,
    и верно второе: инженеры требуют технологий, воины — нет).
    """
    try:                                    # мировая таблица — основной источник
        from civrealm.freeciv.utils.unit_improvement_const import UNIT_TYPES  # type: ignore
        return {i: str(n) for i, n in enumerate(UNIT_TYPES)}
    except Exception:
        pass
    path = Path(str(ruleset_path or SPEC_UNIT_RULESET_PATH))   # запасной путь: разбор ruleset
    if not path.is_file():
        return {}
    out: dict[int, str] = {}
    idx = -1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("[unit_"):
            idx += 1
            continue
        if idx >= 0 and s.startswith("name") and "=" in s:
            if idx not in out:
                value = s.split("=", 1)[1].strip()
                if "(" in value and value.endswith(")"):
                    value = value[value.find("(") + 1:-1].strip()   # `name = _("Settlers")` → литерал
                value = value.strip('"').strip("'")
                if value and value not in out.values():
                    out[idx] = value
    return out


def median_combat_share(specs: Mapping[str, Mapping[str, Any]]) -> tuple[float, int, str]:
    """Медиана «атака+защита» по боевым типам каталога — опора нормировки.

    Константа не вводится: опора — статистика самого каталога. Медиана, а не
    максимум, потому что одиночный выброс (`Nuclear`: 99 при следующем 24) обнулил бы
    весь каталог.
    """
    vals: list[float] = []
    for spec in specs.values():
        a, d = spec.get("attack_strength"), spec.get("defense_strength")
        if isinstance(a, (int, float)) and isinstance(d, (int, float)) and (a + d) > 0:
            vals.append(float(a) + float(d))
    if not vals:
        return 0.0, 0, "боевых типов в каталоге нет — нормировать нечем"
    vals.sort()
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    return float(med), n, f"медиана (атака+защита) по {n} боевым типам каталога"


def production_capability(item: str, spec: Mapping[str, Any], *, median_combat: float,
                          creating_dof: Optional[float] = None,
                          opened_options: int = 0) -> tuple[Optional[float], str]:
    """Способность имени по объявленному правилу (один уровень раскрытия).

    Порядок оснований: (1) имя, создающее город, — способность равна `DoF` создаваемого
    («город по каталогу»); (2) имя, открывающее опции города, — 1.0 (число открытых
    называется рядом); (3) прочий юнит — медианная боевая доля. Если ни одно основание не
    измерено, способность НЕИЗМЕРЕНА (`None`), а не ноль: незнание не подменяется числом.
    """
    if item in SPEC_CITY_FOUNDING_UNIT_TYPES:
        if creating_dof is None:
            return None, "создаёт город, но DoF города не измерен (каталог цен пуст)"
        return float(creating_dof), "создаёт город: способность = DoF города по каталогу"
    if opened_options > 0:
        return 1.0, f"открывает опции города: {opened_options} (величина названа рядом)"
    a, d = spec.get("attack_strength"), spec.get("defense_strength")
    if not isinstance(a, (int, float)) or not isinstance(d, (int, float)) or median_combat <= 0:
        return None, "боевая доля не измерена: нет полей типа или медианы каталога"
    share = (float(a) + float(d)) / float(median_combat)
    return min(1.0, share), f"боевая доля: ({a}+{d}) / медиана {median_combat:g}"


def constraint_observation(entity_type: str,
                           fields: Mapping[str, Any]) -> dict[str, float]:
    """Готовая пара `F`/`F_env` для сущности — объявленный набор + наблюдённая заморозка."""
    variables = SPEC_VARIABLE_SET_BY_TYPE.get(entity_type, ())
    return constraint_counters(variables, frozen_variables(entity_type, fields))


def _num(value: Any, default: float = 0.0) -> float:
    """CivRealm пропускает и обнуляет поля — читаем как число, не падая."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════════
# 3b. Гейты: что вообще является сущностью-субъектом решения
# ═══════════════════════════════════════════════════════════════════════════════

def gate_is_open(fields: Mapping[str, Any]) -> bool:
    """Открыт ли гейт технологии — известна ли она.

    Наблюдено: `inv_state` = 1 у известной (Alphabet), 0 у неизвестной
    (Advanced Flight).
    """
    return _num(fields.get("inv_state"), 0.0) >= 1.0


# `is_lens_subject` снят: гейт теперь не фильтр отображения, а вычисляемый вердикт
# §4.9 (`proven_unreachable` ⇒ исключение из `calc`), см. `env/spec_graph.py`.


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Сборка наблюдения и замер — эталонным ядром
# ═══════════════════════════════════════════════════════════════════════════════

def lens_observation(variety: Optional[Mapping[str, float]] = None,
                     requirements: Optional[Mapping[str, float]] = None,
                     constraint: Optional[Mapping[str, float]] = None
                     ) -> LensObservation:
    """Сырые входы линз одной сущности (§4.6).

    Линза, оставленная `None`, — **неизмеренная**: она не ноль и не идеал, и
    §4.7 начислит за неё `u(t)`. Это и есть механизм «незнание ≠ отсутствие
    возможностей».
    """
    return LensObservation(
        variety=dict(variety) if variety is not None else None,
        requirements=dict(requirements) if requirements is not None else None,
        constraint=dict(constraint) if constraint is not None else None,
    )


def measure(bindings: Mapping[str, LensObservation],
            means: Mapping[str, float],
            u_value: float = 0.5,
            groups: Sequence[Sequence[str]] = SPEC_RESOURCE_GROUPS,
            rates: Mapping[tuple[str, str], float] = SPEC_OBSERVED_RATES,
            cap: Optional[float] = SPEC_MANDATE_CAP
            ) -> dict[str, EntityMeasurement]:
    """Замер всех сущностей **эталонным** ядром (§4.6–§4.7).

    `u_value` — цена незнания для неизмеренной линзы; при `τ = null` это `u₀`
    (§4.7). Передаётся вызывающим явно, чтобы не прятать решение внутри.
    """
    weights = _weights_to_numeraire(groups, rates)
    return {
        eid: measure_entity(eid, obs, u_value, dict(means), groups, weights, cap)
        for eid, obs in bindings.items()
    }


def total_index(measurements: Mapping[str, EntityMeasurement]) -> float:
    """`TotalDoF_index(S) = Σ ln(DoF(e))` (§4.1) — **отрицательный** по построению.

    Величина читается **только порядком**: сравниваются состояния, а не модули.
    Отсечение по `calc(S)` (§4.2) здесь не делается — это следующий шаг.
    """
    return sum(m.contribution for m in measurements.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Объявление линейки (§3.4.1) — хешируемое содержимое
# ═══════════════════════════════════════════════════════════════════════════════

def spec_layer() -> dict[str, Any]:
    """Объявленный ресурсный слой и процедуры — в форме, которую ждёт ядро."""
    return {
        "resources": [
            {"id": res, "unit": SPEC_RESOURCE_UNITS[res]}
            for res in sorted(SPEC_RESOURCE_UNITS)
        ],
        "groups": [list(g) for g in SPEC_RESOURCE_GROUPS],
        "rates": {
            f"{src}->{dst}": {"rate": float(rate)}
            for (src, dst), rate in sorted(SPEC_OBSERVED_RATES.items())
        },
        "mandate": {"cap": SPEC_MANDATE_CAP},
        "numeraire": _group_numeraire(SPEC_RESOURCE_GROUPS[0]),
        "procedures": {
            "variety": f"{SPEC_PSI_ID}:count_response_vectors",
            "options_blocks": f"{SPEC_PSI_ID}:derive_blocks",
            "constraint": f"{SPEC_PSI_ID}:count_variables",
            "counting_horizon_turns": f"{SPEC_PSI_ID}:{SPEC_COUNTING_HORIZON_TURNS}",
            "v_env_counts_foreign_powers": f"{SPEC_PSI_ID}:{int(SPEC_V_ENV_COUNTS_FOREIGN_POWERS)}",
            "requirement_reduction": SPEC_REQUIREMENT_REDUCTION,
            "response_vector_rule": SPEC_RESPONSE_VECTOR_RULE,
        },
    }


def declaration(bindings: Mapping[str, LensObservation],
                means: Mapping[str, float],
                tau_mks: float) -> MeasurementDeclaration:
    """Собрать замороженное объявление состояния (§3.4.1) — эталонной сборкой."""
    layer = spec_layer()
    return build_declaration(
        psi_id=SPEC_PSI_ID,
        lens_observations=dict(bindings),
        tau_mks=tau_mks,
        procedures=layer["procedures"],
        resources=layer["resources"],
        groups=layer["groups"],
        rates=layer["rates"],
        mandate=layer["mandate"],
        numeraire=layer["numeraire"],
        weights=_weights_to_numeraire(SPEC_RESOURCE_GROUPS, SPEC_OBSERVED_RATES),
        mandate_cap=SPEC_MANDATE_CAP,
    )


__all__ = [
    "ENTITY_CTRLS",
    "action_entity",
    "menu_by_entity",
    "response_vector_count",
    "disturbance_count",
    "foreign_powers",
    "active_disturbances",
    "variety_counters",
    "reduce_requirements",
    "option_blocks",
    "means_with_income",
    "constraint_counters",
    "entity_type_of",
    "frozen_variables",
    "constraint_observation",
    "gate_is_open",
    "action_category",
    "action_targets_open_gate",
    "catalogue_index",
    "item_available",
    "gate_opens",
    "available_vectors",
    "lens_observation",
    "measure",
    "total_index",
    "spec_layer",
    "declaration",
]
