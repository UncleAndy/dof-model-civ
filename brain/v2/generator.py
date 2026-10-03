"""Генератор решений v2 — шаг 1 Decision Calculus («Dynamic Generation & Time-Bounded
Diversification»).

ЧТО ОН ДЕЛАЕТ. Порождает **пути** (а не одиночные действия), опираясь на граф знаний:
цель выводится из графа, путь к цели собирается по грамматике семейств, каждый шаг проверяется
на законность (меню), на клин стенда (внешний фильтр `avoid`) и помечается обратимостью.

ЧЕГО ОН НЕ ДЕЛАЕТ. Не ранжирует и не оценивает полезность: любая оценка здесь была бы моим
коэффициентом, то есть подгонкой. Ранжирует calculus (шаги 3–4 спеки). Генератор только
порождает, помечает и указывает происхождение ожидания.

РЕШЕНИЯ, ОБЪЯВЛЕННЫЕ ДО ДАННЫХ (Andy: «выбери на своё усмотрение», 2026-09-30):

* **D1. Семейство действия** — имя без числовых и именных хвостовых параметров
  (`brain/v2/families.py`): `goto_0..7` = одно семейство `goto`, но `build_city` и `build_road`
  остаются разными. DoF хранится в двух видах: механическое число (все варианты) и семейное
  (различные возможности). В индекс идёт **семейное** — иначе «различность» путей фиктивна.
* **D2. Глубина пути — 3 шага** (как в v1; H = 3).
* **D3. Путей — от 3 до 5**, нижняя граница спеки; отбор внутри — по объявленному порядку целей
  (структура, не оценка полезности).
* **D4. Пробный путь** включается всегда, когда граф имеет открытые вопросы; он конкурирует
  наравне (решает calculus), а при всех NetDelta ≤ 0 остаётся единственным законным ходом.
* **D5. План на несколько ходов**: исполняется **первый шаг**, план пересобирается каждый ход
  (шаг 5 спеки: значимое изменение состояния → немедленный пересмотр).

ПОРЯДОК ЦЕЛЕЙ (объявлен, не оценка): снять неизвестность → основать город → поднять канал →
проба. Цель без достижимого пути **докладывается как открытая**, а не выдумывается.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from metrics.reversibility import classify_reversibility

from . import explore as explore_mod
from . import threat
from .families import action_family, family_counts
from .horizon import is_noop
from .horizon import tau as tau_window
from .knowledge import KnowledgeGraph

#: Пределы коридора. БЫЛИ 5 и 2 — это артефакт эпохи «одно действие за ход»: коридор урезался,
#: потому что за ход исполнялось одно действие. Замер §10.105: при таких пределах из 15 юнитов
#: двигались 2 (у остальных цели были, а пути не строились), юниты копились в городах и города
#: теряли производство (§10.98). Теперь агент выполняет все действия за ход, поэтому коридор
#: ограничивать нечем: дубли отсекает «генуинно различные пути» (по эффекту), а повтор — правило
#: «одна настройка на актора за ход». Число оставлено как предохранитель от вырожденного роста.
MAX_PATHS = 200
MIN_PATHS = 3
MAX_DEPTH = 3
#: Сколько путей ОДНОГО вида цели допускается (было 2 — та же причина, что у MAX_PATHS).
PER_KIND_CAP = 200

#: порядок целей — структура, объявленная до данных (не оценка полезности).
#: «выход из-под удара» первым: аксиома 3 (некомпенсация) — не дать сущности коллапсировать,
#: это приоритетнее любого приобретения.
GOAL_ORDER = ("escape", "strike", "cover", "intercept", "explore", "unknown", "found_city",
              "channel", "probe")


@dataclass
class Step:
    ctrl: str
    actor: str
    action: str
    reversible: bool = True
    variants: int = 1          # сколько вариантов у этого семейства в меню
    #: Все законные варианты семейства (кроме «ничего не меняющих»). Генератор их НЕ ранжирует:
    #: выбор варианта — работа calculus, иначе представитель по алфавиту решает за модель
    #: (измерено: канал tech получал `Alphabet`, который не открывает ничего, и агент простаивал).
    alternatives: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ctrl": self.ctrl, "actor": self.actor, "action": self.action,
                "reversible": self.reversible, "variants": self.variants,
                "alternatives": self.alternatives[:12],
                "alternatives_total": len(self.alternatives)}


@dataclass
class Path:
    goal: str                  # unknown | found_city | channel | probe
    kind: str                  # "цель" | "проба"
    steps: list[Step]
    expectation: str           # ожидаемый эффект — словами, с происхождением
    source: str                # откуда взята цель (из графа: почему)
    irreversible: bool = False
    effect: tuple = ()         # признак ЭФФЕКТА (для требования спеки «генуинно различные»)

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "kind": self.kind,
                "steps": [s.to_dict() for s in self.steps],
                "expectation": self.expectation, "source": self.source,
                "irreversible": self.irreversible, "effect": list(self.effect)}

    def summary(self) -> str:
        acts = " → ".join(f"{s.ctrl}/{s.actor}/{s.action}" for s in self.steps)
        irr = " [НЕОБРАТИМ]" if self.irreversible else ""
        return f"[{self.kind}/{self.goal}]{irr} {acts} — {self.expectation}"


def _own_actors(graph: KnowledgeGraph) -> list:
    return [e for e in graph.by_kind("unit") if e.is_own]


def _caps_of_type(graph: KnowledgeGraph, type_name: Optional[str]) -> list[str]:
    if not type_name:
        return []
    te = graph.entity(f"unit_type:{type_name}")
    return list((te.attrs.get("capabilities") if te else None) or [])


def _legal(graph: KnowledgeGraph, menu: dict, ctrl: str, actor: str) -> list[str]:
    from .sensors import valid_options
    return valid_options(menu, ctrl, actor)


#: Структурный минимум защитников в городе (решение Andy: «некоторое количество военных юнитов в
#: городе — это его защитный ресурс в случае нападения»). Число объявлено структурой, а НЕ подобрано:
#: сколько защитников реально нужно, должен показать замер боёв (`v2_defense_report.py`), после чего
#: константа заменяется измеренной величиной.
GARRISON_MIN = 1


def _is_defender(e) -> bool:
    """Юнит способен защищать: в паспорте типа есть атака > 0."""
    atk = e.attrs.get("type_attack_strength")
    return isinstance(atk, (int, float)) and atk > 0


def garrison_set(graph: KnowledgeGraph) -> set:
    """Юниты-гарнизоны: в каждом своём городе остаются первые GARRISON_MIN защитников (по номеру).

    Гарнизон не получает цели «исследовать»: иначе город оголяется. От угрозы он по-прежнему
    уходит (цель `escape`) и бьёт (цель `strike`) — это не отменяется.
    """
    cities = [c for c in graph.by_kind("city") if c.is_own and c.attrs.get("x") is not None]
    if not cities:
        return set()
    xsize = int((graph.world or {}).get("xsize") or 0)
    units = [u for u in graph.by_kind("unit")
             if u.is_own and u.attrs.get("x") is not None and _is_defender(u)]
    keep: set = set()
    for c in cities:
        cx, cy = c.attrs["x"], c.attrs["y"]
        near = [u for u in units
                if threat.cheb(u.attrs["x"], u.attrs["y"], cx, cy, xsize) <= 1]
        near.sort(key=lambda u: (int(u.eid.split(":")[1])
                                 if u.eid.split(":")[1].isdigit() else 0))
        keep.update(u.eid for u in near[:GARRISON_MIN])
    return keep


# ---------------------------------------------------------------- цели из графа

def hold_set(graph: KnowledgeGraph) -> set:
    """Дежурные защитники угрожаемых городов — см. `threat.hold_set`.

    Вынесено в `threat`, потому что его учитывает цена сближения (§10.115): дежурный защитник
    не бросает город, чтобы догнать нападающего.
    """
    return threat.hold_set(graph)


def derive_goals(graph: KnowledgeGraph, menu: dict) -> list[dict]:
    """Цели выводятся из графа и меню. Ни одна не выдумана человеком."""
    goals: list[dict] = []
    # Гарнизоны городов: эти юниты остаются защищать и не получают цели «исследовать».
    keep_garrison = garrison_set(graph)
    # Дежурные защитники угрожаемых городов: они держат позицию и не бегут (город дороже юнита).
    hold = hold_set(graph)

    # 0) выйти из-под удара: наши сущности, досягаемые наблюдённой угрозой (аксиомы 3/4/5).
    # Исключение — дежурные защитники: их уход оголил бы город (см. `hold_set`).
    for eid, info in sorted(threat.exposure(graph, threat.STRIKE_TURNS).items()):
        if eid.startswith("unit:") and eid not in hold:
            goals.append({"goal": "escape", "eid": eid,
                          "why": f"{eid} под ударом ({info['угроза']} в {info['клеток']} клетках, "
                                 f"{info['ходов']} ход.)"})

    # 0-бис) СНЯТЬ источник коллапса ударом: цель появляется, только если у нас есть юнит,
    # СПОСОБНЫЙ бить (паспорт типа: attack > 0), стоящий вплотную к видимому источнику.
    # Ценность удара считает calculus — по ИЗМЕРЕННЫМ исходам боёв, а не по догадке.
    for src in threat.threats(graph):
        for u in graph.by_kind("unit"):
            if not u.is_own or u.attrs.get("x") is None:
                continue
            atk = u.attrs.get("type_attack_strength")
            if not isinstance(atk, (int, float)) or atk <= 0:
                continue
            xsize = int((graph.world or {}).get("xsize") or 0)
            if threat.cheb(u.attrs["x"], u.attrs["y"], src["x"], src["y"], xsize) <= 1:
                goals.append({"goal": "strike", "eid": u.eid, "target": src["eid"],
                              "why": f"{u.eid} может ударить по источнику коллапса {src['eid']}"})

    # 0-тер-0) ПРИКРЫТЬ город: у города, рядом с которым стоит чужой, военные идут к нему.
    # Цена прикрытия считается calculus (`threat.cover_gain`) — из условной («потенциальной»)
    # угрозы города. Здесь только ПУТЬ: без цели движение военного к своему городу не
    # рассматривалось бы вовсе (он получал `explore` и уходил прочь).
    xsize_g = int((graph.world or {}).get("xsize") or 0)
    own_mil_g = [u for u in graph.by_kind("unit")
                 if u.is_own and u.attrs.get("x") is not None
                 and isinstance(u.attrs.get("type_attack_strength"), (int, float))
                 and u.attrs["type_attack_strength"] > 0]
    for c in [e for e in graph.by_kind("city") if e.is_own and e.attrs.get("x") is not None]:
        rsq = (c.attrs or {}).get("city_radius_sq")
        radius = int(math.isqrt(int(rsq))) if isinstance(rsq, (int, float)) and rsq >= 0 else 4
        foes_near = [f for f in graph.by_kind("unit")
                     if (not f.is_own) and f.attrs.get("x") is not None
                     and threat.cheb(f.attrs["x"], f.attrs["y"], c.attrs["x"], c.attrs["y"],
                                     xsize_g) <= radius]
        if not foes_near:
            continue
        for u in own_mil_g:
            goals.append({"goal": "cover", "eid": u.eid, "city": c.eid,
                          "why": f"у {c.eid} рядом чужой ({foes_near[0].eid}) — прикрыть город"})

    # 0-тер-0-бис) СБЛИЖЕНИЕ с объявленным источником коллапса (§10.115): военный идёт к
    # нападающему, чтобы встать вплотную и ударить. Не для дежурных защитников (их уход оголил
    # бы город) и только пока НЕ вплотную — вплотную уже дело удара (цель `strike`).
    for src in threat.threats(graph):
        for u in own_mil_g:
            if u.eid in hold:
                continue
            if threat.cheb(u.attrs["x"], u.attrs["y"], src["x"], src["y"], xsize_g) <= 1:
                continue
            goals.append({"goal": "intercept", "eid": u.eid, "target": src["eid"],
                          "why": f"{u.eid} сближается с источником коллапса {src['eid']}"})

    # 0-тер) ИССЛЕДОВАНИЕ: раскрыть карту — единственный способ увидеть чужие города, юниты и
    # ресурсы, а мирные чужие ПЛЮСУЮТСЯ к общему DoF (решение Andy, §10.33). Цена — из измеренного
    # (см. `explore.explore_gain`). Цель появляется, только если рядом есть нераскрытая клетка.
    for u in graph.by_kind("unit"):
        if not u.is_own or u.attrs.get("x") is None:
            continue
        if u.eid in keep_garrison:
            continue          # гарнизон города не уходит исследовать (решение Andy, §10.101)
        near = explore_mod.unrevealed_near(graph, u.attrs["x"], u.attrs["y"])
        if near is None:
            continue
        # Отсечки по расстоянию НЕТ (замер §10.105): при пороге 12/30 юнит, у которого ближний круг
        # раскрыт, не получал цели вовсе и оставался в городе — города набивались своими юнитами и
        # теряли производство (§10.98). Движение к ближайшей нераскрытой клетке — единственный
        # источник нового DoF, и оно осмысленно на любой дистанции; порог был догадкой.
        goals.append({"goal": "explore", "eid": u.eid,
                      "why": f"{u.eid}: нераскрытая клетка ({near[0]},{near[1]})"})

    # 1) снять неизвестность: сущности с неизвестным DoF, которые нам доступны
    for u in graph.unknowns():
        if u["kind"] in ("unit", "city", "controller"):
            goals.append({"goal": "unknown", "eid": u["eid"], "why": u["why"],
                          "probe": u["probe"]})
    # 2) основать город: у своего юнита есть возможность build_city. Порога «сколько городов
    # достаточно» здесь нет: это была бы моя оценка. Считать ли основание выгодным — работа
    # calculus (аксиома 6: предпочитать то, что умножает способность порождать новое).
    own_cities = [e for e in graph.by_kind("city") if e.is_own]
    for a in _own_actors(graph):
        caps = _caps_of_type(graph, a.name)
        if "build_city" in caps:
            goals.append({"goal": "found_city", "eid": a.eid,
                          "why": f"у типа {a.name} есть возможность build_city; городов {len(own_cities)}"})
    # 3) поднять канал: у канала есть законные переходы
    for e in sorted(graph.by_kind("controller"), key=lambda x: x.eid):
        if not e.is_own or not e.name:
            continue
        ctrl, _, actor = e.name.partition("/")
        opts = _legal(graph, menu, ctrl, actor)
        if opts:
            goals.append({"goal": "channel", "eid": e.eid, "ctrl": ctrl, "actor": actor,
                          "options": opts,
                          "why": f"канал {e.name}: {len(opts)} законных переходов"})
    return goals


# ---------------------------------------------------------------- пути к цели

def _step(menu: dict, ctrl: str, actor: str, action: str, family_variants: int,
          alternatives: Optional[list] = None) -> Step:
    return Step(ctrl=ctrl, actor=actor, action=action,
                reversible=classify_reversibility(action), variants=family_variants,
                alternatives=list(alternatives or []))


def _path_unknown(goal: dict, graph: KnowledgeGraph, menu: dict) -> Optional[Path]:
    """Снять неизвестность: цель достижима, если её можно закрыть доступным действием.

    Если речь о типе юнита, которого у нас нет, — путь не строится: цель остаётся открытой
    (её закроет появление такого юнита). Это честнее, чем выдумать путь.
    """
    eid = goal["eid"]
    if eid.startswith("city:"):
        # имена городских переходов неизвестны: закрыть можно только имея город и наблюдая меню
        return None
    if eid.startswith("controller:"):
        ctrl, _, actor = eid.split(":", 1)[1].partition("/")
        opts = _legal(graph, menu, ctrl, actor)
        if not opts:
            return None
        fam = family_counts(opts)
        a = opts[0]
        return Path(goal="unknown", kind="проба",
                    steps=[_step(menu, ctrl, actor, a, fam[action_family(a)])],
                    expectation=f"закрыть неизвестность {eid}: увидеть эффект перехода",
                    source=goal["why"])
    return None


def _path_found_city(goal: dict, graph: KnowledgeGraph, menu: dict) -> Optional[Path]:
    eid = goal["eid"]
    actor = eid.split(":", 1)[1]
    opts = _legal(graph, menu, "unit", actor)
    if "build_city" not in opts:
        return None
    e = graph.entity(eid)
    site = ""
    if e is not None and e.attrs.get("x") is not None:
        site = f" в клетке ({e.attrs['x']},{e.attrs['y']})"
    return Path(goal="found_city", kind="цель",
                steps=[_step(menu, "unit", actor, "build_city", 1)],
                expectation=f"+1 сущность (город){site} со своим набором возможностей → "
                            "DoF множится, а не складывается",
                source=goal["why"],
                effect=("found_city", e.attrs.get("x") if e else None,
                        e.attrs.get("y") if e else None))


def _path_escape(goal: dict, graph: KnowledgeGraph, menu: dict,
                 avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Выйти из-под удара: шаги движения предлагаются ВСЕ, выбор делает calculus.

    Генератор не решает, куда идти (это была бы оценка). Он отдаёт все законные направления,
    а calculus выбирает то, которое выводит сущность из досягаемости наблюдённой угрозы.
    """
    actor = goal["eid"].split(":", 1)[1]
    opts = [o for o in _legal(graph, menu, "unit", actor) if o in threat.DIR8_MEASURED]
    if avoid is not None:
        opts = [o for o in opts if not avoid("unit", o)]
    if not opts:
        return None
    # ПЛАН, а не один шаг (решение D2, до сих пор не использованное): измерено, что против
    # угрозы со скоростью 3 один шаг из-под удара не выводит — выводят несколько шагов подряд
    # в одном направлении. Исполняется первый шаг, план пересобирается каждый ход (D5).
    steps = [_step(menu, "unit", actor, opts[0], 1, alternatives=opts)
             for _ in range(MAX_DEPTH)]
    return Path(goal="escape", kind="цель",
                steps=steps,
                expectation="выход из-под удара: сохранить слагаемое ln(DoF) сущности "
                            "(миникас, аксиома 5)",
                source=goal["why"], effect=("escape", actor))


def _path_cover(goal: dict, graph: KnowledgeGraph, menu: dict,
                avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Прикрыть город: военный юнит идёт к своему городу, у которого стоит чужой.

    Геометрия — как у выхода из-под удара: план из H шагов в одном направлении, потому что цена
    прикрытия (`threat.cover_gain`) считает КОНЕЦ плана. Юнит, стоящий в 2–3 шагах от города,
    иначе не получил бы мотива вовсе. Направления предлагаются ВСЕ, выбор — за calculus.
    """
    actor = goal["eid"].split(":", 1)[1]
    opts = [o for o in _legal(graph, menu, "unit", actor) if o in threat.DIR8_MEASURED]
    if avoid is not None:
        opts = [o for o in opts if not avoid("unit", o)]
    if not opts:
        return None
    steps = [_step(menu, "unit", actor, opts[0], 1, alternatives=opts)
             for _ in range(MAX_DEPTH)]
    return Path(goal="cover", kind="цель",
                steps=steps,
                expectation="прикрыть город: встать вплотную к своему городу, у которого чужой; "
                            "цена — условная угроза (измеряется calculus)",
                source=goal["why"], effect=("cover", actor, goal.get("city")))


def _path_intercept(goal: dict, graph: KnowledgeGraph, menu: dict,
                    avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Сближение с объявленным источником коллапса (§10.115) — чтобы встать вплотную и ударить.

    Геометрия та же, что у прикрытия: план из H шагов в одном направлении, цена
    (`threat.intercept_gain`) считает конец плана. Направления предлагаются ВСЕ, выбор — calculus.
    """
    actor = goal["eid"].split(":", 1)[1]
    opts = [o for o in _legal(graph, menu, "unit", actor) if o in threat.DIR8_MEASURED]
    if avoid is not None:
        opts = [o for o in opts if not avoid("unit", o)]
    if not opts:
        return None
    steps = [_step(menu, "unit", actor, opts[0], 1, alternatives=opts)
             for _ in range(MAX_DEPTH)]
    return Path(goal="intercept", kind="цель",
                steps=steps,
                expectation="сблизиться с источником коллапса и встать вплотную, чтобы ударить; "
                            "цена — риск, который держит источник (измеряется calculus)",
                source=goal["why"], effect=("intercept", actor, goal.get("target")))


def _path_explore(goal: dict, graph: KnowledgeGraph, menu: dict,
                  avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Идти к нераскрытой зоне: направления предлагаются все, выбор — за calculus.

    Генератор не решает, куда идти (это была бы оценка). Он отдаёт все законные направления, а
    calculus выбирает то, которое приближает к нераскрытой клетке, и считает цену из измеренного.
    """
    actor = goal["eid"].split(":", 1)[1]
    opts = [o for o in _legal(graph, menu, "unit", actor) if o in threat.DIR8_MEASURED]
    if avoid is not None:
        opts = [o for o in opts if not avoid("unit", o)]
    if not opts:
        return None
    return Path(goal="explore", kind="цель",
                steps=[_step(menu, "unit", actor, opts[0], 1, alternatives=opts)],
                expectation="раскрыть карту: цена из измерения (клеток/ход × сущностей/клетка)",
                source=goal["why"], effect=("explore", actor))


def _path_strike(goal: dict, graph: KnowledgeGraph, menu: dict,
                 avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Ударить по источнику коллапса: направления предлагаются все, выбор делает calculus.

    `attack_N` — та же измеренная геометрия dir8, что и `goto_N` (код: `ActAttack(focus, dir8)`,
    `mapstep(ptile, dir8)`). Все законные направления отдаются вариантами, а цена удара считается
    calculus по ИЗМЕРЕННЫМ исходам наших боёв.
    """
    actor = goal["eid"].split(":", 1)[1]
    opts = [o for o in _legal(graph, menu, "unit", actor) if o.startswith("attack_")]
    if avoid is not None:
        opts = [o for o in opts if not avoid("unit", o)]
    if not opts:
        return None
    return Path(goal="strike", kind="цель",
                steps=[_step(menu, "unit", actor, opts[0], 1, alternatives=opts)],
                expectation="снять источник коллапса ударом: цена удара — по измеренным исходам "
                            "боёв, а не по догадке",
                source=goal["why"], effect=("strike", actor, goal.get("target")))


def _path_channel(goal: dict, graph: KnowledgeGraph, menu: dict,
                  avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    ctrl, actor, opts = goal["ctrl"], goal["actor"], goal["options"]
    fam = family_counts(opts)
    # представитель семейства выбирается детерминированно; выбор внутри семейства —
    # вопрос ценности, и его решает проекция (её пока нет), поэтому здесь только пометка
    real = [o for o in opts if not is_noop(graph, o)]
    if avoid is not None:
        # клины стенда вычитаем ДО выбора представителя: иначе путь целиком отбрасывался
        # из-за того, что первым по алфавиту стоял клин (`city_buy_production`)
        real = [o for o in real if not avoid(ctrl, o)]
    if not real:
        return None      # всё, что предлагает канал, уже стоит — путь ничего не меняет
    a = real[0]
    return Path(goal="channel", kind="цель",
                steps=[_step(menu, ctrl, actor, a, fam[action_family(a)], alternatives=real)],
                expectation=f"канал {ctrl}: смена раскладки/цели; в семействе "
                            f"{action_family(a)} вариантов {fam[action_family(a)]}",
                source=goal["why"],
                effect=("channel", ctrl, action_family(a)))


def _eta_known(graph: KnowledgeGraph, action: str) -> bool:
    """Известен ли срок постройки этого варианта: замером, публикацией или из цены."""
    from .horizon import _derived_eta, _measured_eta, _published_eta
    name = str(action)[len("produce_"):]
    for fn in (_measured_eta, _published_eta, _derived_eta):
        try:
            if fn(graph, name)[0] is not None:
                return True
        except TypeError:
            if fn(graph)[0] is not None:
                return True
    return False


def _path_probe(graph: KnowledgeGraph, menu: dict,
                used: Optional[set] = None,
                avoid: Optional[Callable[[str, str], bool]] = None) -> Optional[Path]:
    """Проба: законное действие, чей ЭФФЕКТ ещё не наблюдался ни разу.

    Определение механическое и единое для всех видов сущностей: берём семейство
    `контроллер/семейство`, для которого в базе знаний нет записи об эффекте. Исполнение
    записывает эффект — это и есть прирост знания (аксиома 5).

    Измерено, почему не «исполнялось этим типом»: такая формулировка (а) не покрывала каналы
    (`gov`, `tech`) вовсе — из-за этого 155 ходов из 367 агент просто закрывал, и (б) считалась
    по каждому юниту отдельно, из-за чего одно и то же действие повторялось десятки раз
    (`cancel_order` — 49, `keep_activity` — 47).

    `used` — занятые пары (актор, семейство) этого хода; `avoid` — внешний фильтр клинов.
    """
    # Порядок контроллеров объявлен (структура, не оценка): сначала то, что действует на карте,
    # затем ГОРОД (множитель: `produce_Settlers` создаёт новую сущность, `city_work_*` растит
    # город), затем каналы игрока. Измерено: без `city` в этом списке рычаг города не пробовался
    # ни разу, хотя мир его предлагал (`produce_Barracks`, `city_work_*`, 20–26 позиций).
    used = used or set()
    for ctrl in ("unit", "city", "gov", "tech", "player", "dipl"):
        actors = menu.get(ctrl) or {}
        for actor in sorted(actors, key=str):
            opts = _legal(graph, menu, ctrl, str(actor))
            for o in sorted(opts):
                fam = action_family(o)
                if graph.effect_of(ctrl, fam) is not None:
                    # ИСКЛЮЧЕНИЕ для постройки: у семейства `produce` эффект уже наблюдён, но
                    # СРОК каждого варианта мир публикует только когда вариант стал текущим
                    # производством. Поэтому вариант с неизвестным сроком — законная проба:
                    # запустив его, агент получает измеренный срок (см. `horizon._measured_eta`).
                    if fam != "produce" or _eta_known(graph, o):
                        continue                  # эффект уже наблюдён — не проба
                if is_noop(graph, o):
                    continue                      # ничего не меняет — не проба
                if (str(actor), fam) in used or (ctrl, str(actor), fam) in used:
                    continue
                if avoid is not None and avoid(ctrl, o):
                    continue
                fams = family_counts(opts)
                return Path(goal="probe", kind="проба",
                            steps=[_step(menu, ctrl, str(actor), o, fams[fam])],
                            expectation="+1 записанный эффект: прирост знания о мире",
                            source=f"эффект семейства {ctrl}/{fam} ещё не наблюдался",
                            effect=("probe", ctrl, fam))
    return None


# ---------------------------------------------------------------- сборка

def generate(graph: KnowledgeGraph, menu: dict, own_id: int = 0,
             avoid: Optional[Callable[[str, str], bool]] = None) -> tuple[list[Path], list[dict]]:
    """Порождает пути (3–5) и отдельно — цели без достижимого пути.

    `avoid` — внешний фильтр запрещённых действий (реестр клинов стенда). Модель не знает про
    стенд, поэтому фильтр передаёт вызывающий.
    """
    goals = derive_goals(graph, menu)
    by_kind: dict[str, list[dict]] = {}
    for g in goals:
        by_kind.setdefault(g["goal"], []).append(g)

    paths: list[Path] = []
    #: Не более двух путей ОДНОГО вида цели до урезания коридора (объявлено). Измерено: пять
    #: юнитов под ударом давали пять путей «выход», которые выдавливали из коридора удар по
    #: источнику — и цель, у которой была ЧИСЛОМ посчитанная цена, не рассматривалась вовсе.
    per_kind: dict[str, int] = {}
    for kind in GOAL_ORDER:
        for g in by_kind.get(kind, []):
            if per_kind.get(kind, 0) >= PER_KIND_CAP:
                break
            p = (_path_escape(g, graph, menu, avoid=avoid) if kind == "escape"
                 else _path_strike(g, graph, menu, avoid=avoid) if kind == "strike"
                 else _path_cover(g, graph, menu, avoid=avoid) if kind == "cover"
                 else _path_intercept(g, graph, menu, avoid=avoid) if kind == "intercept"
                 else _path_explore(g, graph, menu, avoid=avoid) if kind == "explore"
                 else _path_unknown(g, graph, menu) if kind == "unknown"
                 else _path_found_city(g, graph, menu) if kind == "found_city"
                 else _path_channel(g, graph, menu, avoid=avoid) if kind == "channel"
                 else None)
            if p is not None:
                paths.append(p)
                per_kind[kind] = per_kind.get(kind, 0) + 1

    # «генуинно различные пути» (спека): пути с одинаковым ЭФФЕКТОМ — один путь, а не два.
    # Измерено: два Settlers в одной клетке давали два «разных» пути основания, которые на
    # деле были одним и тем же городом в (30,25).
    seen_effects: set = set()
    distinct: list[Path] = []
    for p in paths:
        if p.effect and p.effect in seen_effects:
            continue
        seen_effects.add(p.effect)
        distinct.append(p)
    paths = distinct

    # коридор 3–5 путей. Пробному пути **зарезервировано место** (решение D4): без этого его
    # вытесняют целевые пути, и правило «при всех NetDelta ≤ 0 ход тратится на знание» не
    # выполняется вовсе.
    has_unknowns = bool(graph.unknowns())
    cap = MAX_PATHS - 1 if has_unknowns else MAX_PATHS
    paths = paths[:cap]
    if has_unknowns:
        used = {(s.ctrl, s.actor, action_family(s.action)) for p in paths for s in p.steps}
        p = _path_probe(graph, menu, used, avoid=avoid)
        if p is not None:
            if not p.effect or p.effect not in seen_effects:
                paths.append(p)

    # фильтр клинов стенда (внешний) — ПОСЛЕДНИМ, иначе пробный путь его минует (измерено:
    # `unit/plant` прошёл фильтр именно так и подвесил партию).
    if avoid is not None:
        paths = [p for p in paths
                 if all(not avoid(s.ctrl, s.action) for s in p.steps)]

    for p in paths:
        p.irreversible = any(not s.reversible for s in p.steps)

    # цели, для которых пути не нашлось: докладываем как открытые, не выдумываем
    covered = {p.goal for p in paths}
    open_goals = [g for g in goals if g["goal"] not in covered
                  or g["goal"] == "unknown" and not any(p.goal == "unknown" for p in paths)]
    return paths, open_goals