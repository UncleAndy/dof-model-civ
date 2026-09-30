"""Сенсорная система v2.

Внешние сенсоры: наблюдение мира (карта, игроки, устав, чужие сущности).
Внутренние сенсоры: свои акторы (юниты, города) и их остаток хода.
Меню: объявленный миром список переходов по актёрам — основа ИЗМЕРЕННОГО DoF.

Ничего не выводит и не додумывает: только то, что мир отдал.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .provenance import Origin, Value

UNKNOWN_TERRAIN = 255  # нераскрытая клетка (см. §10.34/§10.42 проекта)


def _as_list(v) -> list:
    """Мир отдаёт массивы как numpy/ndarray или BitVector: `v or []` на них падает."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    try:
        return list(v)
    except TypeError:
        return []


@dataclass
class WorldView:
    xsize: int
    ysize: int
    terrain: list
    output: list
    status: list
    tile_owner: list
    city_owner: list
    unit_owner: list
    extras: list
    players: dict[int, dict]
    rules: dict
    own_id: int

    def terrain_at(self, x: int, y: int) -> int:
        return self.terrain[x][y]

    def output_at(self, x: int, y: int) -> list:
        return self.output[x][y]

    def is_revealed(self, x: int, y: int) -> bool:
        return self.terrain_at(x, y) != UNKNOWN_TERRAIN

    def area(self) -> int:
        return self.xsize * self.ysize


@dataclass
class Actor:
    """Юнит (свой или чужой)."""
    aid: int
    owner: int
    type_name: Optional[str]
    x: Optional[int]
    y: Optional[int]
    moves_left: Optional[int]
    attrs: dict = field(default_factory=dict)

    @property
    def is_own(self) -> bool:
        return self.owner == 0

    def capability_vector(self) -> tuple:
        """Вектор признаков для аналогии (решение 6.3). Только измеренные поля."""
        a = self.attrs
        return (
            a.get("type_attack_strength"),
            a.get("type_defense_strength"),
            a.get("type_move_rate"),
            bool(a.get("type_worker")),
            bool(a.get("type_can_transport")),
            a.get("type_vision_radius_sq"),
        )


@dataclass
class City:
    cid: int
    owner: int
    name: Optional[str]
    size: Optional[int]
    x: Optional[int]
    y: Optional[int]
    prod_food: Optional[int]
    prod_shield: Optional[int]
    prod_trade: Optional[int]
    surplus_food: Optional[int]
    shield_stock: Optional[int]
    turns_to_prod_complete: Optional[int]
    can_build_unit: list
    improvements: list
    attrs: dict = field(default_factory=dict)

    @property
    def n_buildable(self) -> int:
        """Сколько позиций меню производства мир разрешает (число, имена неизвестны)."""
        return sum(1 for v in _as_list(self.can_build_unit) if v)


def read_world(obs: dict, own_id: int = 0) -> WorldView:
    m = obs.get("map") or {}
    terrain = _as_list(m.get("terrain"))
    xsize = len(terrain)
    ysize = len(terrain[0]) if xsize else 0
    players = {int(k): v for k, v in (obs.get("player") or {}).items()}
    return WorldView(
        xsize=xsize, ysize=ysize,
        terrain=terrain, output=_as_list(m.get("output")), status=_as_list(m.get("status")),
        tile_owner=_as_list(m.get("tile_owner")), city_owner=_as_list(m.get("city_owner")),
        unit_owner=_as_list(m.get("unit_owner")), extras=_as_list(m.get("extras")),
        players=players, rules=obs.get("rules") or {}, own_id=own_id,
    )


def read_actors(obs: dict) -> list[Actor]:
    out = []
    for uid, u in (obs.get("unit") or {}).items():
        out.append(Actor(
            aid=int(uid), owner=u.get("owner"), type_name=u.get("type_rule_name"),
            x=u.get("x"), y=u.get("y"), moves_left=u.get("moves_left"), attrs=dict(u),
        ))
    return out


def read_cities(obs: dict) -> list[City]:
    out = []
    for cid, c in (obs.get("city") or {}).items():
        out.append(City(
            cid=int(cid), owner=c.get("owner"), name=c.get("name"), size=c.get("size"),
            x=c.get("x"), y=c.get("y"), prod_food=c.get("prod_food"),
            prod_shield=c.get("prod_shield"), prod_trade=c.get("prod_trade"),
            surplus_food=c.get("surplus_food"), shield_stock=c.get("shield_stock"),
            turns_to_prod_complete=c.get("turns_to_prod_complete"),
            can_build_unit=_as_list(c.get("can_build_unit")),
            improvements=_as_list(c.get("improvements")), attrs=dict(c),
        ))
    return out


def own_actors(obs: dict, own_id: int = 0) -> list[Actor]:
    return [a for a in read_actors(obs) if a.owner == own_id]


def foreign_actors(obs: dict, own_id: int = 0) -> list[Actor]:
    return [a for a in read_actors(obs) if a.owner is not None and a.owner != own_id]


def own_cities(obs: dict, own_id: int = 0) -> list[City]:
    return [c for c in read_cities(obs) if c.owner == own_id]


def foreign_cities(obs: dict, own_id: int = 0) -> list[City]:
    return [c for c in read_cities(obs) if c.owner is not None and c.owner != own_id]


# ---------------------------------------------------------------- меню действий

def read_menu(available: dict) -> dict[str, dict[str, dict[str, bool]]]:
    """Меню мира: секция -> актор -> {действие: допустимо}.

    Мир сам объявляет, какие переходы доступны каждому актору. Это измеренная
    характеристика мира (не мнение агента), и она же — база счёта DoF.

    ВАЖНО (turn_manager.get_info, строки 159–168): мир **удаляет секцию из меню, если у неё
    ноль опций**. Поэтому «секции нет» = «переходов не предложено» = DoF актора 0, а не
    «API не умеет». Ключи акторов приводятся к строке: живой мир отдаёт int, JSON — str.
    """
    menu: dict[str, dict[str, dict[str, bool]]] = {}
    for section, actors in (available or {}).items():
        if not isinstance(actors, dict):
            continue
        menu[section] = {}
        for actor_key, actions in actors.items():
            if isinstance(actions, dict):
                menu[section][str(actor_key)] = {a: bool(v) for a, v in actions.items()}
    return menu


def valid_options(menu: dict, section: str, actor_key: str) -> list[str]:
    """Действия, которые мир разрешает этому актору прямо сейчас."""
    actions = (menu.get(section) or {}).get(actor_key) or {}
    return sorted(a for a, ok in actions.items() if ok)


def measured_dof(menu: dict, section: str, actor_key: str, actor_known: bool = False) -> Value:
    """Измеренный DoF_сейчас = число переходов, предложенных миром этому актору НА ЭТОМ ходу.

    Различие, которое нельзя терять: это НЕ весь будущий спектр состояний сущности (аксиома 1),
    а мгновенный срез. У юнита без остатка хода переходов сейчас ноль, но будущий спектр не ноль.
    Поэтому DoF_сейчас = 0 не означает смерти сущности (см. правило `calc` в спеке).

    `actor_known=True` — актор точно существует (виден в наблюдении). Тогда молчание мира
    означает «переходов не предложено» = измеренный ноль, а не «неизвестно».
    """
    src = f"меню:{section}/{actor_key}"
    if section not in menu:
        if actor_known:
            return Value.measured(0, source=src, note="секции нет: мир не предложил переходов")
        return Value.unknown(source=src, note="секции нет в меню мира")
    if actor_key not in (menu.get(section) or {}):
        if actor_known:
            return Value.measured(0, source=src, note="актор известен, переходов не предложено")
        return Value.unknown(source=src, note="актор не предложен миром")
    opts = valid_options(menu, section, actor_key)
    return Value.measured(len(opts), source=src,
                          note=";".join(opts[:6]) + ("…" if len(opts) > 6 else ""))


def city_option_count(city: City, menu: dict) -> tuple[int, str]:
    """Число возможных действий города (поправка Andy: город не двигается, но меню у него есть).

    Мир отдаёт меню города **в самой записи города** — вектор `can_build_unit` с разрешёнными
    позициями производства, — а не секцией меню turn_manager. Если секция `city` всё же
    появилась, берём её: там у позиций есть имена.
    """
    sec = menu.get("city") or {}
    if str(city.cid) in sec:
        opts = valid_options(menu, "city", str(city.cid))
        return len(opts), "меню города: " + ",".join(opts[:8])
    n = city.n_buildable
    return n, f"can_build_unit: {n} разрешённых позиций (имена мир не отдаёт)"


def detect_own_id(obs: dict, own_name: Optional[str] = None) -> Optional[int]:
    """Определить свой player_id по имени (если мир отдал имена)."""
    if not own_name:
        return None
    for pid, p in (obs.get("player") or {}).items():
        if p.get("name") == own_name:
            return int(pid)
    return None