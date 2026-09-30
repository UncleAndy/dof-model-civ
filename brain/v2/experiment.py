"""Длящийся опыт: прирост знания, которого одношаговая проба дать не может.

ЗАЧЕМ. Одношаговая проба измеряет **немедленный** эффект. Но часть мира проявляется только на
дистанции: назначение граждан (`city_work_*`) растит город за десятки ходов, постройка — за
10–13. Измерено (§10.67): набор возможностей города растёт вместе с городом (4 → 5 → 9), то есть
рост города — это рост DoF. Значит ценность роста известна, а **средство** роста — нет: эффект
`city/city_work` записан как `city_prod_eta_changed`, а не `city_grew`.

ЧТО ДЕЛАЕТ. Агент выбирает семейство, у которого **нет измерения на дистанции**, и удерживает его
N ходов, а затем сравнивает базовую линию с результатом. Полученная связь («удержание F за N ходов
→ город вырос на k, переходов стало +m») записывается в базу знаний как **горизонтный эффект** и
дальше используется проекцией и индексом.

ОБЪЯВЛЕНО ДО ДАННЫХ:

* **E1. Длина опыта** — по опубликованному миром сроку амбара (`granary_turns`), если он разумен
  (≤ 60 ходов), иначе 20 ходов. Не подбирается по результату.
* **E2. Порядок выбора семейства** — `city`, `unit`, `gov`, `tech`, `dipl` (структура: сначала то,
  что способно растить город — множитель DoF).
* **E2-бис (измерено, исправлено).** Опыт ставится только на **процессы** — `city` и `unit`.
  Первый прогон показал, почему: агент «удерживал» `gov/change_gov` — то есть держал страну в
  анархии 19 ходов, — потому что выбрал первое семейство по алфавиту. Держать можно работу
  (постройку, назначение граждан), но не **команду** (смену правительства, выбор технологии):
  у команды нет длящегося процесса, а её удержание — это повтор вредного состояния.
* **E3. Опыт прерывается**, если действие перестало быть законным; прерванный опыт записывается
  как прерванный, а не как результат.
* **E4. Опыт — это прирост знания (аксиома 5)**, поэтому он берётся только тогда, когда ни один
  путь не даёт `NetDelta > 0` и нет одношаговой пробы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from . import sensors
from .families import action_family
from .horizon import is_noop
from .knowledge import KnowledgeGraph

DEFAULT_TURNS = 20
MAX_TURNS = 60


@dataclass
class Experiment:
    ctrl: str
    actor: str
    action: str
    family: str
    started_turn: int
    turns: int
    baseline: dict = field(default_factory=dict)
    hypothesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ctrl": self.ctrl, "actor": self.actor, "action": self.action,
                "family": self.family, "ход_начала": self.started_turn, "ходов": self.turns,
                "гипотеза": self.hypothesis, "базовая_линия": self.baseline}


def _baseline(graph: KnowledgeGraph, menu: dict) -> dict:
    cities = {}
    for e in graph.by_kind("city"):
        if not e.is_own:
            continue
        opts = sensors.valid_options(menu, "city", e.eid.split(":")[-1])
        # МЕРА РОСТА — опубликованное миром `n_buildable` (вектор `can_build_unit` в записи
        # города). Число ПРЕДЛОЖЕННЫХ переходов зависит от окна обёртки
        # `PersistentCityProduction` и потому как мера роста негодно: измерено, что оно давало
        # «+20 переходов» просто от открывшегося окна. Держим его только как справку.
        cities[e.eid] = {"размер": e.attrs.get("size"),
                         "постройки": e.attrs.get("n_buildable"),
                         "переходов": len(opts)}
    return {"города": cities}


def experiment_turns(graph: KnowledgeGraph) -> int:
    """E1: длина опыта по опубликованному сроку амбара."""
    for e in graph.by_kind("city"):
        if not e.is_own:
            continue
        g = e.attrs.get("granary_turns")
        if isinstance(g, int) and 0 < g <= MAX_TURNS:
            return max(5, g)
    return DEFAULT_TURNS


def start(graph: KnowledgeGraph, menu: dict, turn: Optional[int],
          avoid=None) -> Optional[tuple[Experiment, Any]]:
    """Начать опыт: ПРОЦЕСС без измерения на дистанции (E2/E2-бис), удержание N ходов (E1)."""
    # команды, чьё удержание — повтор состояния, а не процесс: их не пробуем «держать»
    COMMAND_KEYS = ("government_changed", "researching_changed", "player_gold_delta",
                    "player_science_delta", "player_bulbs_researched_delta")
    for ctrl in ("city", "unit"):
        actors = menu.get(ctrl) or {}
        for actor in sorted(actors, key=str):
            opts = sensors.valid_options(menu, ctrl, str(actor))
            for o in sorted(opts):
                fam = action_family(o)
                rec = graph.effect_of(ctrl, fam) or {}
                if rec.get("horizon"):
                    continue                       # на дистанции уже измерено
                if any(k in (rec.get("change_counts") or {}) for k in COMMAND_KEYS):
                    continue                       # это команда, а не процесс
                if is_noop(graph, o):
                    continue
                if avoid is not None and avoid(ctrl, o):
                    continue
                from .generator import Step
                from metrics.reversibility import classify_reversibility
                step = Step(ctrl=ctrl, actor=str(actor), action=o,
                            reversible=classify_reversibility(o), variants=1,
                            alternatives=[o])
                exp = Experiment(ctrl=ctrl, actor=str(actor), action=o, family=fam,
                                 started_turn=turn if isinstance(turn, int) else 0,
                                 turns=experiment_turns(graph),
                                 baseline=_baseline(graph, menu),
                                 hypothesis=f"удержание {ctrl}/{fam} вырастит город или сменит "
                                            f"число его переходов")
                return exp, step
    return None


def finish(graph: KnowledgeGraph, exp: Experiment, menu: dict,
           interrupted: bool = False) -> dict:
    """Закрыть опыт: сравнить базовую линию с результатом и записать связь."""
    now = _baseline(graph, menu)
    grew = 0
    build_delta = 0
    for cid, base in (exp.baseline.get("города") or {}).items():
        cur = (now.get("города") or {}).get(cid)
        if not cur:
            continue
        if isinstance(base.get("размер"), int) and isinstance(cur.get("размер"), int):
            grew += cur["размер"] - base["размер"]
        if isinstance(base.get("постройки"), int) and isinstance(cur.get("постройки"), int):
            build_delta += cur["постройки"] - base["постройки"]

    changes = {}
    if grew:
        changes["city_grew"] = grew
    if build_delta:
        changes["city_buildable_delta"] = build_delta
    if interrupted:
        changes["прерван"] = 1

    graph.record_effect(exp.ctrl, exp.family, changes,
                        {"опыт": exp.to_dict(), "прерван": interrupted})
    rec = graph.effects.get(f"{exp.ctrl}/{exp.family}")
    if rec is not None:
        rec["horizon"] = {"ходов": exp.turns, "city_grew": grew,
                          "city_buildable_delta": build_delta, "прерван": interrupted}
    # измеренная связь «размер города -> сколько позиций постройки разрешено» (устойчивая мера)
    for _cid, cur in (now.get("города") or {}).items():
        if isinstance(cur.get("размер"), int) and isinstance(cur.get("постройки"), int):
            graph.note_observation("city_size_buildable",
                                   {"размер": cur["размер"], "значение": cur["постройки"]})
    return {"city_grew": grew, "city_buildable_delta": build_delta, "прерван": interrupted}