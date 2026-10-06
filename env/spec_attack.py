"""Порт ПРАВИЛА НАБЛЮДЕНИЯ НАПАДЕНИЯ из ветки `v2` (`brain/v2/attack.py`) под `v0.11`.

Переносится реализация, а не переизобретённое правило (§15 журнала). Что делает
модуль и чего не делает:

* **Ведёт срезы между ходами.** Правило сравнивает два ПОЛНЫХ среза: наши юниты
  (позиция, здоровье), наши города и ВИДИМЫЕ чужие. Одиночное наблюдение о нападении
  не говорит ничего.
* **Ход 1 не сравнивается ни с чем.** Прежний срез прошлой партии с первым срезом
  новой давал ложное событие «наш город потерян без нападающего» (измерено в `v2`:
  два таких события на ходу 1 прогона `long4`).
* **Нападение = наша сущность исчезла — и это НЕ объясняется нашим же измеренным
  действием** (мир публикует `build_city` / `join_city` как потребляющие юнита) —
  **или** здоровье нашей сущности упало между срезами; **и** на смежной клетке
  текущего среза виден чужой. Видимость = раскрытая клетка, поэтому решение владельца
  модели «догадка из тумана нападением не считается» выполняется по построению.
* **Виновный не выдумывается.** Нет видимого соседа — факт записывается как
  «нападающий не наблюдён», и НИЧЕГО не помечается.
* **Признак держится весь срок прогноза** (`COLLAPSE_HORIZON` = 20 ходов), а не один
  ход: помечается и юнит-нападающий (если он вообще есть сущностью), и его ВЛАДЕЛЕЦ —
  владелец и есть та система, чьи возможности не наши (§10.33).
* **Метка ставится на основании НАБЛЮДЕНИЯ.** Ядро `v0.11` запрещает менять
  `is_collapse_source` гипотезой (`brain/spec/hypothesis.py`; проверка (c) харнесса),
  поэтому метка — вход, а не параметр модели.

Чего модуль не делает: атрибуцию по типам юнитов, цену удара и статистику боёв из `v2`
(`risk_price`, `STRIKE_TURNS`) — это следующий пункт, а не этот.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from env.config import SPEC_COLLAPSE_HORIZON_TURNS
from env import spec_threat as T

#: Семейства НАШИХ действий, которые по измеренному эффекту мира потребляют своего юнита.
#: Их исчезновение нападением не считается — иначе основание города читалось бы как атака.
OWN_CONSUMES: tuple[str, ...] = ("build_city", "join_city", "found_city")

#: Префикс идентификатора сущности владельца в графе `v0.11` (решение пишется как `player_0:...`).
OWNER_PREFIX = "player_"


def owns(record: Mapping[str, Any], my_player_id: Any) -> bool:
    """Наша ли запись: у юнитов/городов мира владелец публикуется, но может и молчать."""
    return int((record or {}).get("owner", my_player_id) or my_player_id) == int(my_player_id)


def slice_of(obs: Mapping[str, Any], my_player_id: Any) -> dict[str, Any]:
    """Полный срез: наши юниты (позиция, здоровье), наши города и видимые чужие.

    Нужен как ЧИТАЕМЫЙ ВИД наблюдения (отчёт, проверки). Сравнение срезов делает
    `env.spec_threat.observed_attack`, и оно работает по СЫРЫМ наблюдениям — поэтому
    в `AttackTracker` хранится именно сырое наблюдение, а не этот вид.
    """
    units: dict[str, dict[str, Any]] = {}
    unit_sec = (obs or {}).get("unit")
    for key, rec in (unit_sec.items() if isinstance(unit_sec, Mapping) else ()):
        if isinstance(rec, Mapping) and owns(rec, my_player_id):
            units[str(key)] = {"x": rec.get("x"), "y": rec.get("y"),
                               "health": rec.get("health")}
    cities: dict[str, dict[str, Any]] = {}
    city_sec = (obs or {}).get("city")
    for key, rec in (city_sec.items() if isinstance(city_sec, Mapping) else ()):
        if isinstance(rec, Mapping) and owns(rec, my_player_id):
            cities[str(key)] = {"x": rec.get("x"), "y": rec.get("y")}
    foe = {f"{owner}:{x},{y}": {"owner": owner, "x": x, "y": y}
           for owner, x, y in T.foreign_units_from_map(obs, my_player_id)}
    return {"units": units, "cities": cities, "foe": foe}


class CollapseMarks:
    """Метки «источник коллапса» со сроком держания.

    Хранится владелец и ход постановки; признак живёт `horizon` ходов включительно.
    Помечается и владелец (система, чьи возможности не наши), и сам нападающий, если
    он оказался сущностью графа, — чтобы исключение §10.33 работало в обоих видах.
    """

    def __init__(self, horizon: int = SPEC_COLLAPSE_HORIZON_TURNS) -> None:
        self.horizon = int(horizon)
        self._marks: dict[str, dict[str, Any]] = {}

    def mark(self, entity_id: str, turn: int, why: str,
             owner: Optional[Any] = None) -> str:
        name = str(entity_id)
        self._marks[name] = {"turn": int(turn), "why": str(why), "owner": owner}
        return name

    def mark_owner(self, owner: Any, turn: int, why: str) -> Optional[str]:
        """Пометить ВЛАДЕЛЬЦА нападающего: система — вот чей набор возможностей не наш."""
        if owner is None:
            return None
        return self.mark(f"{OWNER_PREFIX}{int(owner)}", turn, why, owner=owner)

    def is_source(self, entity_id: str, turn: int) -> bool:
        mark = self._marks.get(str(entity_id))
        return bool(mark) and int(turn) - int(mark["turn"]) < self.horizon

    def active(self, turn: int) -> dict[str, dict[str, Any]]:
        return {eid: m for eid, m in self._marks.items()
                if int(turn) - int(m["turn"]) < self.horizon}

    def expired(self, turn: int) -> list[str]:
        return [eid for eid, m in self._marks.items()
                if int(turn) - int(m["turn"]) >= self.horizon]

    def __len__(self) -> int:
        return len(self._marks)


class AttackTracker:
    """Ведёт срезы и ставит метки. Состояние живёт в извлекателе `v0.11`."""

    def __init__(self, my_player_id: Any = 0,
                 horizon: int = SPEC_COLLAPSE_HORIZON_TURNS,
                 marks: Optional[CollapseMarks] = None) -> None:
        self.my_player_id = my_player_id
        self.marks = marks if marks is not None else CollapseMarks(horizon)
        self.prev: Optional[dict[str, Any]] = None
        self._choice: Optional[tuple[str, str]] = None   # (актор, семейство) последнего действия

    def note_choice(self, actor: Any, family: Any) -> None:
        """Запомнить наше последнее исполненное действие: им объясняется исчезновение актора.

        Без этого вызова исчезнувший по нашему же действию юнит (`build_city` /
        `join_city`) будет прочитан как потеря от нападения — дефект, который в `v2`
        лечился этим же механизмом (`consumed`).
        """
        self._choice = (str(actor), str(family)) if actor is not None and family is not None else None

    def observe(self, obs: Mapping[str, Any], turn: Any,
                last_choice: Optional[Iterable[Any]] = None) -> dict[str, Any]:
        """Сравнить срез с предыдущим, поставить метки, вернуть событие (объявление).

        Возвращает то же, что `env.spec_threat.observed_attack`, плюс `marked` и `owner`,
        чтобы вызывающий видел, что именно помечено и с какой причиной.
        """
        if last_choice is not None:
            choice = tuple(last_choice)
            self.note_choice(choice[0] if len(choice) > 0 else None,
                             choice[1] if len(choice) > 1 else None)
        # Хранится СЫРОЕ наблюдение: сравнение срезов делает `observed_attack`, и оно
        # читает секции мира (`unit`, `city`, `map`) напрямую — вид `slice_of` для
        # сравнения не годится (дефект моей первой проводки: срезы вместо наблюдений
        # дали «потерь не наблюдено» на синтетике с наблюдаемым нападением).
        prev, self.prev = self.prev, obs
        if prev is None:
            return {"attacked": False, "victims": [], "attackers": [], "marked": [],
                    "reason": "предыдущего среза нет"}
        try:
            turn_int = int(turn)
        except (TypeError, ValueError):
            turn_int = 0
        if turn_int <= 1:
            # Начало партии: сравнивать не с чем (замер v2: иначе прошлая партия
            # даёт ложное «наш город потерян без нападающего»).
            return {"attacked": False, "victims": [], "attackers": [], "marked": [],
                    "reason": f"ход {turn_int}: начало партии — сравнивать не с чем"}

        consumed: tuple[str, ...] = ()
        if self._choice is not None and self._choice[1] in OWN_CONSUMES:
            # В срезе ключи наших юнитов — как их отдаёт мир; в графе `v0.11` — `unit_<id>`.
            consumed = (self._choice[0], f"unit_{self._choice[0]}")

        seen = T.observed_attack(prev, obs, my_player_id=self.my_player_id,
                                 consumed_by_us=consumed, horizon=self.marks.horizon)
        if not seen.get("attacked"):
            return {**seen, "marked": []}

        marked: list[Any] = []
        if seen.get("attackers"):
            why = (f"нападение наблюдено на ходу {turn_int}: "
                   + "; ".join(f"{v['id']} — {v['how']}" for v in seen.get("victims") or []))
            for owner, _x, _y in seen["attackers"]:
                eid = self.marks.mark_owner(owner, turn_int, why)
                if eid:
                    marked.append(eid)
        else:
            # Виновный не назначается: факт записан, метки нет.
            why = "нападающий не наблюдён — метка не ставится (догадка из тумана нападением не считается)"
        return {**seen, "marked": marked, "hold_turns": self.marks.horizon,
                "reason": why if marked or seen.get("attackers") else seen.get("reason")}

    def apply(self, entities: Mapping[str, Any], turn: Any) -> list[str]:
        """Проставить `is_collapse_source=True` тем сущностям, на которых есть живая метка.

        Сущности `v0.11` — pydantic-модели, поэтому присваивание поля, а не `dict[...]`.
        Возвращает список помеченных идентификаторов (для отчёта и проверок).
        """
        try:
            turn_int = int(turn)
        except (TypeError, ValueError):
            turn_int = 0
        applied: list[str] = []
        for eid in list(entities.keys()):
            if self.marks.is_source(eid, turn_int):
                try:
                    entities[eid].is_collapse_source = True
                except (AttributeError, TypeError, ValueError):
                    continue
                applied.append(str(eid))
        return applied
