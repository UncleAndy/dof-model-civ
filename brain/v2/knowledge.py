"""Система знаний v2: граф мира.

Сущности (кто есть), связи (что с чем связано), числа (с происхождением).

ЧТО ТАКОЕ DoF СУЩНОСТИ (поправка Andy, 2026-09-30). DoF — это **набор возможных действий
сущности**, а не то, что доступно в данную секунду. Город не может двигаться, но у него есть
меню постройки; юнит без остатка хода всё равно способен фортифицироваться, строить дорогу и
т.д. Поэтому:

* DoF юнита = размер **накопленного набора возможностей его типа** (наблюдаем меню по ходу
  игры и объединяем увиденное). Набор растёт с наблюдением — это и есть «нулевое знание»:
  в начале он пуст, затем наполняется миром.
* DoF города = размер его меню постройки (мир отдаёт его в записи города, а не секцией меню).
* DoF каналов управления (налог/наука/роскошь, технологии, дипломатия) = размер меню секции.

Скелет связей «что открывает что» публикует сам мир (`tech.reqs`, `tech.sup_units`,
`tech.sup_improvements`); динамические связи добываются пробой (позже).

DoF чужой сущности — по аналогии со своими (решение 6.3): точное совпадение типа, иначе
ближайший свой тип по вектору признаков, с пессимистичной границей; происхождение «выведено».
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from . import sensors
from .families import family_of_options
from .provenance import Origin, Value, json_default

# признаки для аналогии (решение 6.3), в порядке сравнения
FEATURES = ("attack", "defense", "move_rate", "worker", "can_transport", "vision")

# Область знания: что живёт между партиями, а что принадлежит одной партии.
# Типы, технологии, улучшения и словарь меню (каналы) — знание о МИРЕ, оно постоянное.
# Конкретные юниты, города и клетки — состояние ПАРТИИ, между партиями не переносится.
PERMANENT_KINDS = ("unit_type", "tech", "improvement", "controller")
GAME_KINDS = ("unit", "city", "tile", "player")


@dataclass
class Entity:
    eid: str
    kind: str                     # player | tech | unit_type | improvement | city | unit | controller | tile
    owner: Optional[int] = None
    is_own: bool = False
    name: Optional[str] = None
    attrs: dict = field(default_factory=dict)
    dof: Optional[Value] = None

    def to_dict(self) -> dict[str, Any]:
        return {"eid": self.eid, "kind": self.kind, "owner": self.owner, "is_own": self.is_own,
                "name": self.name, "attrs": self.attrs,
                "dof": self.dof.to_dict() if self.dof else None}

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        return cls(eid=d["eid"], kind=d["kind"], owner=d.get("owner"), is_own=d.get("is_own", False),
                   name=d.get("name"), attrs=d.get("attrs") or {},
                   dof=Value.from_dict(d["dof"]) if d.get("dof") else None)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str                     # requires | unlocks | belongs_to | located_at | observed_capability
    origin: Origin = Origin.MEASURED
    attrs: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.src, self.dst, self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "kind": self.kind,
                "origin": self.origin.value, "attrs": self.attrs}

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(src=d["src"], dst=d["dst"], kind=d["kind"],
                   origin=Origin(d.get("origin", Origin.MEASURED.value)), attrs=d.get("attrs") or {})


class KnowledgeGraph:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple] = set()
        self.rules: dict = {}
        self.world: dict = {}
        self.observations: int = 0     # сколько раз мир наблюдался в этот граф

    # --- сборка ---
    def add_entity(self, e: Entity) -> Entity:
        self.entities[e.eid] = e
        return e

    def ensure(self, eid: str, kind: str, **kw: Any) -> Entity:
        """Найти или создать сущность; известные поля обновляются."""
        e = self.entities.get(eid)
        if e is None:
            return self.add_entity(Entity(eid=eid, kind=kind, **kw))
        for k, v in kw.items():
            if v is not None:
                setattr(e, k, v)
        return e

    def add_edge(self, e: Edge) -> None:
        if e.key() in self._edge_keys:
            return
        self._edge_keys.add(e.key())
        self.edges.append(e)

    def entity(self, eid: str) -> Optional[Entity]:
        return self.entities.get(eid)

    def out_edges(self, eid: str, kind: Optional[str] = None) -> list[Edge]:
        return [e for e in self.edges if e.src == eid and (kind is None or e.kind == kind)]

    def in_edges(self, eid: str, kind: Optional[str] = None) -> list[Edge]:
        return [e for e in self.edges if e.dst == eid and (kind is None or e.kind == kind)]

    def by_kind(self, kind: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.kind == kind]

    def permanent_only(self) -> "KnowledgeGraph":
        """Копия графа только с постоянным знанием (типы, технологии, словарь меню).

        Состояние партии (конкретные юниты, города, клетки) между партиями не переносится:
        иначе юнит из прошлой игры «склеится» с одноимённым юнитом новой и знание испортится.
        """
        g = KnowledgeGraph()
        g.world = {k: v for k, v in self.world.items() if k != "games"}
        g.world["games"] = self.world.get("games", 0)
        g.rules = dict(self.rules)
        g.observations = self.observations
        for e in self.entities.values():
            if e.kind in PERMANENT_KINDS:
                g.add_entity(Entity(eid=e.eid, kind=e.kind, owner=e.owner, is_own=e.is_own,
                                    name=e.name, attrs=dict(e.attrs), dof=e.dof))
        for e in self.edges:
            if e.src in g.entities and e.dst in g.entities:
                g.add_edge(Edge(src=e.src, dst=e.dst, kind=e.kind, origin=e.origin,
                                attrs=dict(e.attrs)))
        return g

    def unknowns(self) -> list[dict]:
        """Открытые вопросы, ВЫВЕДЕННЫЕ из самого графа (не список, написанный человеком).

        Это то, что агент обязан добыть сам: пробой в игре, а не замером со стороны. Пока
        вопрос открыт, он давит на выбор действия (аксиома 5: незнание сужает путь).
        """
        out: list[dict] = []
        for e in self.entities.values():
            if e.kind in ("tile", "tech", "improvement", "player"):
                continue
            if e.dof is None or e.dof.origin is Origin.UNKNOWN:
                out.append({"eid": e.eid, "kind": e.kind, "why": "DoF неизвестен",
                            "probe": "наблюсти меню этого актора"})
            elif e.kind == "unit_type" and not e.attrs.get("capabilities"):
                out.append({"eid": e.eid, "kind": e.kind, "why": "набор возможностей типа пуст",
                            "probe": "иметь юнит этого типа и посмотреть его меню"})
        # типы, наблюдённые мало: знание есть, но неполное
        for e in self.by_kind("unit_type"):
            n = e.attrs.get("observations") or 0
            if 0 < n < 3:
                out.append({"eid": e.eid, "kind": e.kind,
                            "why": f"набор наблюдён всего {n} ход(ов)",
                            "probe": "подержать юнит этого типа в разных ситуациях"})
        return out

    def stats(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for e in self.entities.values():
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        eedges: dict[str, int] = {}
        for e in self.edges:
            eedges[e.kind] = eedges.get(e.kind, 0) + 1
        origins: dict[str, int] = {}
        for e in self.entities.values():
            if e.dof:
                origins[e.dof.origin.value] = origins.get(e.dof.origin.value, 0) + 1
        return {"entities": len(self.entities), "by_kind": dict(sorted(kinds.items())),
                "edges": len(self.edges), "edges_by_kind": dict(sorted(eedges.items())),
                "dof_origins": dict(sorted(origins.items())), "observations": self.observations}

    # --- заморозка ---
    def to_dict(self) -> dict[str, Any]:
        return {"world": self.world, "rules": self.rules, "observations": self.observations,
                "entities": [e.to_dict() for e in self.entities.values()],
                "edges": [e.to_dict() for e in self.edges]}

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeGraph":
        g = cls()
        g.world = d.get("world") or {}
        g.rules = d.get("rules") or {}
        g.observations = d.get("observations", 0)
        for ed in d.get("entities") or []:
            g.add_entity(Entity.from_dict(ed))
        for ed in d.get("edges") or []:
            g.add_edge(Edge.from_dict(ed))
        return g

    def freeze(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1, default=json_default))
        return p

    @classmethod
    def load(cls, path: str | Path) -> "KnowledgeGraph":
        return cls.from_dict(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------- вспомогательное

def _feature_vector(attrs: dict) -> tuple:
    """Вектор признаков юнита для аналогии. Отсутствующее поле — None (не 0: аксиома 5)."""
    return (
        attrs.get("type_attack_strength"),
        attrs.get("type_defense_strength"),
        attrs.get("type_move_rate"),
        attrs.get("type_worker"),
        attrs.get("type_can_transport"),
        attrs.get("type_vision_radius_sq"),
    )


def _dist(f1: tuple, f2: tuple) -> Optional[float]:
    """L1 по сопоставимым признакам. None, если сравнивать нечего."""
    pairs = [(x, y) for x, y in zip(f1, f2) if x is not None and y is not None]
    if not pairs:
        return None
    return sum(abs(float(x) - float(y)) for x, y in pairs)


def _dof_by_type(g: "KnowledgeGraph") -> dict[str, tuple]:
    """Тип -> (вектор признаков, DoF). База для аналогии (6.3)."""
    table: dict[str, tuple] = {}
    for e in g.by_kind("unit"):
        if e.is_own and e.name:
            table[e.name] = (_feature_vector(e.attrs), e.dof)
    return table


def _analogy_dof(g: "KnowledgeGraph", attrs: dict, type_name: Optional[str]) -> Value:
    """DoF чужой сущности по аналогии. Никогда не 0 (аксиома 7)."""
    table = _dof_by_type(g)
    if type_name and type_name in table:
        _, dof = table[type_name]
        if dof and dof.comparable:
            return Value.inferred(float(dof.v), float(dof.lo), float(dof.hi),
                                  source=f"аналогия:{type_name}", note="точное совпадение типа")
    fv = _feature_vector(attrs)
    scored = []
    for tname, (ofv, odof) in table.items():
        if not odof or not odof.comparable:
            continue
        d = _dist(fv, ofv)
        if d is not None:
            scored.append((d, tname, float(odof.v)))
    if scored:
        scored.sort()
        near = scored[:3]
        vals = [v for _, _, v in near]
        return Value.inferred(max(vals), min(vals), max(vals),
                              source="аналогия:ближайший тип",
                              note="похожие свои типы: " + ", ".join(t for _, t, _ in near))
    allv = sorted(float(e.dof.v) for e in g.by_kind("unit")
                  if e.is_own and e.dof and e.dof.comparable)
    if allv:
        return Value.inferred(allv[-1], allv[0], allv[-1], source="аналогия:верхняя граница",
                              note="сравнимых типов нет — пессимистичная оценка (аксиома 5)")
    return Value.unknown(source="аналогия", note="нет своих юнитов для сравнения")


# ---------------------------------------------------------------- сборка графа

def build_graph(obs: dict, available: dict, own_id: int = 0,
                prior: Optional[KnowledgeGraph] = None) -> KnowledgeGraph:
    """Сенсоры -> граф знаний.

    `prior` — граф прошлого наблюдения: наборы возможностей и связи **накапливаются**, а не
    перезаписываются (иначе «нулевое знание» никогда не наполнится). Граф обновляется на месте.
    """
    g = prior if prior is not None else KnowledgeGraph()
    w = sensors.read_world(obs, own_id)
    menu = sensors.read_menu(available)
    g.world = {"xsize": w.xsize, "ysize": w.ysize, "area": w.area(),
               "n_players": len(w.players), "own_id": own_id}
    g.rules = dict(w.rules)
    g.observations += 1

    # --- игроки ---
    for pid, p in w.players.items():
        g.ensure(f"player:{pid}", "player", owner=pid, is_own=(pid == own_id), name=p.get("name"))
        e = g.entity(f"player:{pid}")
        e.attrs.update({k: p.get(k) for k in
                        ("is_alive", "score", "nation", "government_name", "gold")})

    # --- технологии и то, что они открывают (скелет публикует мир) ---
    for tid, t in (obs.get("tech") or {}).items():
        teid = f"tech:{tid}"
        g.ensure(teid, "tech", name=t.get("name"))
        g.entity(teid).attrs.update({k: t.get(k) for k in
                                     ("inv_state", "is_researching", "is_req_for_goal")})
        for req in (t.get("reqs") or {}):
            g.add_edge(Edge(src=teid, dst=f"tech:{req}", kind="requires"))
        for u in (t.get("sup_units") or []):
            uname = u.get("name") or u.get("rule_name") or u.get("type_name")
            if not uname:
                continue
            ueid = f"unit_type:{uname}"
            g.ensure(ueid, "unit_type", name=uname)
            g.entity(ueid).attrs.update({k: u.get(k) for k in
                                         ("attack_strength", "defense_strength", "build_cost", "move_rate")})
            g.add_edge(Edge(src=teid, dst=ueid, kind="unlocks"))
        for im in (t.get("sup_improvements") or []):
            iname = im.get("name") or im.get("rule_name")
            if not iname:
                continue
            ieid = f"improvement:{iname}"
            g.ensure(ieid, "improvement", name=iname)
            g.add_edge(Edge(src=teid, dst=ieid, kind="unlocks"))

    # --- свои юниты: наблюдаем их меню и накапливаем в набор возможностей ТИПА ---
    own_u = sensors.own_actors(obs, own_id)
    for a in own_u:
        eid = f"unit:{a.aid}"
        g.ensure(eid, "unit", owner=a.owner, is_own=True, name=a.type_name)
        e = g.entity(eid)
        e.attrs.update({"x": a.x, "y": a.y, "moves_left": a.moves_left,
                        **_type_feature_attrs(a)})
        opts = sensors.valid_options(menu, "unit", str(a.aid))
        if a.type_name:
            g.add_edge(Edge(src=eid, dst=f"unit_type:{a.type_name}", kind="observed_capability"))
            te = g.ensure(f"unit_type:{a.type_name}", "unit_type", name=a.type_name)
            caps = set(te.attrs.get("capabilities") or []) | set(opts)
            te.attrs["capabilities"] = sorted(caps)
            if opts:
                te.attrs["observations"] = te.attrs.get("observations", 0) + 1
            # DoF в двух видах (решение D1): механическое число и семейное (различные
            # возможности). В индекс идёт семейное — иначе `goto_0..7` раздувают счёт.
            fams = family_of_options(caps)
            te.attrs["families"] = sorted(fams)
            te.attrs["dof_mechanical"] = len(caps)
            te.attrs["dof_families"] = len(fams)
            te.dof = Value.measured(len(caps), source=f"набор возможностей типа {a.type_name}",
                                    note=f"наблюдён за {te.attrs.get('observations', 0)} ходов")
            e.dof = te.dof
        else:
            e.dof = sensors.measured_dof(menu, "unit", str(a.aid), actor_known=True)

    # --- свои города: DoF = меню постройки из записи города ---
    for c in sensors.own_cities(obs, own_id):
        eid = f"city:{c.cid}"
        g.ensure(eid, "city", owner=c.owner, is_own=True, name=c.name)
        e = g.entity(eid)
        e.attrs.update({"x": c.x, "y": c.y, "size": c.size, "surplus_food": c.surplus_food,
                        "prod_food": c.prod_food, "prod_shield": c.prod_shield,
                        "shield_stock": c.shield_stock,
                        "turns_to_prod_complete": c.turns_to_prod_complete,
                        "n_buildable": c.n_buildable})
        n, note = sensors.city_option_count(c, menu)
        e.dof = Value.measured(n, source="город:меню постройки", note=note)
        g.add_edge(Edge(src=eid, dst=f"player:{own_id}", kind="belongs_to"))

    # --- чужие акторы: DoF по аналогии ---
    for a in sensors.foreign_actors(obs, own_id):
        eid = f"unit:{a.aid}"
        g.ensure(eid, "unit", owner=a.owner, is_own=False, name=a.type_name)
        e = g.entity(eid)
        e.attrs.update({"x": a.x, "y": a.y, "moves_left": a.moves_left,
                        **_type_feature_attrs(a)})
        e.dof = _analogy_dof(g, e.attrs, a.type_name)
        g.add_edge(Edge(src=eid, dst=f"player:{a.owner}", kind="belongs_to"))
        if a.type_name:
            g.add_edge(Edge(src=eid, dst=f"unit_type:{a.type_name}", kind="observed_capability"))

    for c in sensors.foreign_cities(obs, own_id):
        eid = f"city:{c.cid}"
        g.ensure(eid, "city", owner=c.owner, is_own=False, name=c.name)
        e = g.entity(eid)
        e.attrs.update({"x": c.x, "y": c.y, "size": c.size})
        e.dof = Value.unknown(source="аналогия:город",
                              note="чужой город: аналогия по размеру не реализована")
        g.add_edge(Edge(src=eid, dst=f"player:{c.owner}", kind="belongs_to"))

    # --- каналы управления: меню секций (кроме unit) ---
    for section, actors in menu.items():
        if section == "unit":
            continue
        for actor_key in actors:
            eid = f"controller:{section}:{actor_key}"
            g.ensure(eid, "controller", name=f"{section}/{actor_key}", is_own=True)
            e = g.entity(eid)
            opts = sensors.valid_options(menu, section, actor_key)
            e.attrs["capabilities"] = sorted(set(e.attrs.get("capabilities") or []) | set(opts))
            e.attrs["dof_mechanical"] = len(e.attrs["capabilities"])
            e.attrs["dof_families"] = len(family_of_options(e.attrs["capabilities"]))
            e.dof = sensors.measured_dof(menu, section, actor_key, actor_known=True)

    # --- занятые клетки ---
    for e in list(g.entities.values()):
        if e.kind in ("unit", "city") and e.attrs.get("x") is not None:
            tile_eid = f"tile:{e.attrs['x']},{e.attrs['y']}"
            g.ensure(tile_eid, "tile")
            te = g.entity(tile_eid)
            te.attrs.update({"x": e.attrs["x"], "y": e.attrs["y"],
                             "terrain": w.terrain_at(e.attrs["x"], e.attrs["y"]),
                             "revealed": w.is_revealed(e.attrs["x"], e.attrs["y"])})
            g.add_edge(Edge(src=e.eid, dst=tile_eid, kind="located_at"))

    return g


def _type_feature_attrs(a: sensors.Actor) -> dict:
    """Признаки типа юнита — под именами, по которым сравнивает аналогия (6.3)."""
    src = a.attrs
    return {
        "type_attack_strength": src.get("type_attack_strength"),
        "type_defense_strength": src.get("type_defense_strength"),
        "type_move_rate": src.get("type_move_rate"),
        "type_worker": src.get("type_worker"),
        "type_can_transport": src.get("type_can_transport"),
        "type_vision_radius_sq": src.get("type_vision_radius_sq"),
    }