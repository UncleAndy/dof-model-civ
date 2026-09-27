"""Адаптер: живое наблюдение → оценки для прогноза.

Задача — не пересчитывать то, что уже считается, а **переиспользовать** измеренные
пути проекта:

* ценность города на площадке — формулой города (`extractor._site_city_value`),
  она возвращает опции, то есть ровно ту шкалу, в которой живёт индекс;
* работы — существующим измеренным путём (`extractor._terrain_work_gains`),
  который адресует выгоду **городу**, а не клетке; нулевой измеренный эффект так и
  остаётся нулём;
* достижимость — квадратом радиуса `move_rate` (как в `_site_move_gains`), потому
  что координат цели у `goto_N` нет и точный маршрут неизвестен.

Всё, что здесь не заполнено, помечено как «пока не подключено» — с причиной.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from env.measured_facts import default_facts
from env.site_eval import evaluate_site

from .info import gap_index as jensen_gap_index
from .info import gap_options as jensen_gap_options
from .options import Valuations
from .state import ForecastState

#: Действия работы → экстра, которую они ставят (для связи с измеренной таблицей).
WORK_ACTION_EXTRA = {
    "irrigation": "Irrigation", "irrigate": "Irrigation", "mine": "Mine",
    "build_road": "Road", "road": "Road", "railroad": "Railroad",
    "farmland": "Farmland",
}


@dataclass
class LiveContext:
    state: ForecastState
    vals: Valuations
    my_id: int | None
    notes: list[str]
    #: типы, предложенные сервером, но не имеющие ИЗМЕРЕННОЙ стоимости — их
    #: прогноз не предлагает вовсе. Заполняется при первом вызове `productions`.
    unpriced: set[str]
    #: сводка склада измеренных фактов (какие стоимости известны и насколько
    #: согласованы) — попадает в отчёт прогона.
    facts_summary: dict[str, Any]
    #: что предложено городу СЕЙЧАС и не оценено: имя действия → для самозамера.
    #: Пусто, если цены известны всем предложенным типам.
    probe_offers: dict[str, tuple[str, str]]
    #: сам склад измеренных фактов — чтобы вызывающий мог ДОПИСАТЬ в него замер,
    #: сделанный в бою (постановка производства и чтение срока).
    facts: Any = None

    def probe_action(self) -> tuple[str, str, str] | None:
        """Ход на замер: поставить неоцениваемый тип производства.

        Зачем это в агенте, а не только в мерном скрипте: цену типа нельзя вывести
        из наблюдения, её можно только измерить (поставить и прочитать
        `prod_process`/`shield_stock`), а опции типа узнаются лишь тогда, когда юнит
        этого типа появится живьём. Если ход иначе пуст, потратить его на замер —
        единственный способ выйти из круга «не знаем цену → не строим → не узнаём».

        Берётся первый по алфавиту: порядок обязан быть детерминированным, иначе
        прогон нельзя повторить. Улучшения сюда не попадают: постановка улучшения
        роняет контроллер (проверено), и это не замер, а поломка.
        """
        for name in sorted(self.probe_offers):
            ctrl, actor, action = self.probe_offers[name]
            return (ctrl, actor, action)
        return None


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_wedged(ctrl: str, action_name: str) -> bool:
    """Известно ли, что это действие роняет матч.

    Ошибка чтения реестра считается «да»: без него мы не знаем, безопасно ли
    пробовать, а цена ошибки — испорченный матч, тогда как цена отказа — всего лишь
    непоставленный замер.
    """
    try:
        from env.wedged import is_wedged
        return bool(is_wedged(ctrl, action_name))
    except Exception:  # noqa: BLE001
        return True


def _own_units(obs: dict, my_id: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for uid, unit in _as_dict(obs.get("unit")).items():
        if not isinstance(unit, dict):
            continue
        try:
            if int(unit.get("owner", my_id)) != int(my_id):
                continue
        except (TypeError, ValueError):
            continue
        out[str(uid)] = unit
    return out


def reach_tiles(pos: tuple[int, int], move_rate: int,
                map_shape: tuple[int, int] | None = None) -> list[tuple[int, int]]:
    """Достижимые клетки за ход: квадрат радиуса `move_rate` вокруг юнита.

    Точный маршрут неизвестен (`goto_N` без координат), поэтому берётся верхняя
    граница достижимости — та же, что использует `_site_move_gains`.
    """
    x, y = pos
    tiles: list[tuple[int, int]] = []
    for dx in range(-move_rate, move_rate + 1):
        for dy in range(-move_rate, move_rate + 1):
            tx, ty = x + dx, y + dy
            if (tx, ty) == (x, y):
                continue
            if map_shape is not None:
                w, h = map_shape
                if w and h:
                    tx %= w
                    ty %= h
            tiles.append((tx, ty))
    return tiles


def revealed_tiles(map_obs: dict) -> set[tuple[int, int]]:
    """Раскрытые клетки: выход не `(0,0,0)`. Террейн для этого не годится."""
    try:
        layer = map_obs.get("output")
        shape = getattr(layer, "shape", None)
        if shape is None:
            return set()
        out = set()
        for x in range(shape[0]):
            for y in range(shape[1]):
                cell = layer[x][y]
                try:
                    vals = [float(v) for v in cell][:3]
                except TypeError:
                    vals = [_num(cell), 0.0, 0.0]
                if any(v != 0.0 for v in vals):
                    out.add((x, y))
        return out
    except Exception:  # noqa: BLE001
        return set()


def build_context(obs: dict, info: dict, dof_state: Any, extractor: Any, *,
                  w_info: float = 0.0,
                  world_model: Any | None = None,
                  exclude_actors: set | None = None,
                  info_gain: Callable[[tuple[int, int]], float] | None = None
                  ) -> LiveContext:
    """Собрать состояние и оценки прогноза из живого наблюдения.

    `dof_state` — результат `extractor.extract(...)`; берётся извне, чтобы не
    извлекать состояние дважды за один ход.
    """
    notes: list[str] = []
    my_id = getattr(extractor, "my_player_id", None)
    units = _own_units(obs, my_id)
    map_obs = _as_dict(obs.get("map"))
    cities = {}
    city_records: dict[str, dict] = {}
    for cid, city in _as_dict(obs.get("city")).items():
        if not isinstance(city, dict):
            continue
        try:
            own = int(city.get("owner", my_id)) == int(my_id)
        except (TypeError, ValueError):
            own = False
        if own and city.get("x") is not None and city.get("y") is not None:
            # Ключ — id из самой записи, а не ключ словаря: живьём ключи целые,
            # в фикстурах строки (§5.2f навыка).
            key = f"city_{city.get('id', cid)}"
            cities[key] = (int(city["x"]), int(city["y"]))
            city_records[key] = city

    state = ForecastState(
        positions={f"unit_{uid}": (int(u.get("x", 0)), int(u.get("y", 0)))
                   for uid, u in units.items()},
        cities=cities,
        revealed=revealed_tiles(map_obs),
    )
    try:
        entities = _as_dict(getattr(getattr(dof_state, "state", None), "entities", None))
    except Exception:  # noqa: BLE001
        entities = {}
    for entity_id, entity in entities.items():
        count = _num(getattr(entity, "dof_count", 0.0), 0.0)
        state.dof[entity_id] = count
        state.root_dof[entity_id] = count
        # Обратимы юниты (их состояние теряется и возвращается); города —
        # необратимое вложение, и вето Аксиомы 3 к ним не применяется.
        state.reversible[entity_id] = entity_id.startswith("unit_")
        if getattr(entity, "is_collapse_source", False):
            state.collapse_sources.add(entity_id)

    # Ценность города на площадке: формула города, шкала — опции.
    capital = not cities
    vals_map = getattr(extractor, "model", None)
    values = dict(vals_map.values()) if vals_map is not None else {}
    if "rules.food_cost" in values:
        values["FOOD_COST"] = values["rules.food_cost"]

    def site_of(tile: tuple[int, int]):
        return evaluate_site(map_obs, int(tile[0]), int(tile[1]), size=1,
                             vals=values)

    def city_dof(tile: tuple[int, int]) -> float:
        try:
            site = site_of(tile)
            if not site.viable:
                return 0.0
            return float(extractor._site_city_value(site, capital))
        except Exception:  # noqa: BLE001
            return 0.0

    def site_viable(tile: tuple[int, int]) -> bool:
        try:
            return bool(site_of(tile).viable)
        except Exception:  # noqa: BLE001
            return False

    move_rate = {f"unit_{uid}": max(1, int(_num(u.get("type_move_rate"), 1)))
                 for uid, u in units.items()}
    shape = getattr(map_obs.get("output"), "shape", None)
    shape = (int(shape[0]), int(shape[1])) if shape is not None else None

    def reach(unit_id: str) -> list[tuple[int, int]]:
        pos = state.positions.get(unit_id)
        if pos is None:
            return []
        return reach_tiles(pos, move_rate.get(unit_id, 1), shape)

    def is_carrier(unit_id: str) -> bool:
        try:
            from env.entity_extractor import is_population_carrier
            uid = unit_id.split("_", 1)[1]
            return bool(is_population_carrier(units.get(uid, {})))
        except Exception:  # noqa: BLE001
            return False

    # Работы: измеренный путь адресует выгоду городу. Пока подключаем только там,
    # где сервер сам предлагает работу, и только с ИЗМЕРЕННЫМ эффектом.
    work_gains: dict[str, dict[str, float]] = {}
    try:
        work_gains, _report = extractor._terrain_work_gains(obs, values, map_obs)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"работы не подключены: {type(exc).__name__}")

    def works(tile: tuple[int, int]) -> list[tuple[str, float, str | None]]:
        """Работы, которые сервер СЕЙЧАС предлагает юниту на этой клетке.

        Выгода берётся из измеренного пути (`_terrain_work_gains`), который уже
        адресует её городу формулой города. Измеренный ноль остаётся нулём —
        такой кандидат не запрещён, но и не притворяется выгодным.
        """
        offered_map = _as_dict(_as_dict(info.get("available_actions")).get("unit"))
        out: list[tuple[str, float, str | None]] = []
        for unit_id, pos in state.positions.items():
            if (int(pos[0]), int(pos[1])) != (int(tile[0]), int(tile[1])):
                continue
            uid = unit_id.split("_", 1)[1]
            offered = _as_dict(offered_map.get(int(uid))
                               if str(uid).isdigit() else None) or _as_dict(
                offered_map.get(uid))
            gains = work_gains.get(unit_id, {})
            for action, extra in WORK_ACTION_EXTRA.items():
                if not offered.get(action):
                    continue
                city_id = next(iter(cities), None)
                out.append((action, float(gains.get(extra, 0.0)), city_id))
        return out

    def productions(city_id: str) -> list[tuple[str, float, int]]:
        """Что город может построить: [(тип, опции, ходов)] — по числам мира.

        Срок не выдумывается: `ceil((стоимость − shield_stock) / prod_shield)`, где
        щиты — из записи города, а стоимость типа — из ЗАМЕРА (`env/world_model.py`).
        Если стоимость типа не измерена, тип не предлагается вовсе: подставить «один
        ход» значило бы выдумать стимул.

        Опции типа берутся в шкале опций (`unit_options` / `city_options`) — той же,
        в которой живёт индекс, поэтому шкалы аддитивны без пересчёта.
        """
        rec = city_records.get(city_id) or {}
        offered = _offered_for(offered_city, city_id)
        stock = _num(rec.get("shield_stock"), 0.0)
        shields = _num(rec.get("prod_shield"), 0.0)
        if shields <= 0.0:
            return []
        out: list[tuple[str, float, int]] = []
        for name, params in offered.items():
            if not params or not name.startswith("produce_"):
                continue
            type_name = name[len("produce_"):]
            priced = type_price(type_name)
            if priced is None:
                unpriced.add(type_name)
                # Запоминаем предложение для самозамера — но ТОЛЬКО если тип
                # доказанно юнит (есть в каталоге юнитов или уже виден живьём) и
                # раньше не клинил. Класс типа из наблюдения не выводится (каталоги
                # неполны в обе стороны), а постановка улучшения роняет контроллер —
                # проверено ценой испорченного матча. Реестр клинов — общий
                # (`env/wedged.py`), а не свой: правило обязано быть одно.
                known_unit = (type_name in catalogue["unit"]
                              or world.kind_of(type_name) == "unit")
                # Актёр на проводе — ГОЛЫЙ id города (`121`), а не `city_121`:
                # с префиксом `env.step` падает `KeyError: 'city_121'` и матч
                # умирает. Та же замена, что в `_to_wire_action`.
                # Первый аргумент `_is_wedged` — имя контроллера (`city`).
                actor = city_id.split("_", 1)[1] if "_" in city_id else city_id
                if known_unit and not _is_wedged("city", name):
                    probe_offers[type_name] = ("city", actor, name)
                continue
            options, cost = priced
            # Срок не бывает нулевым: при `stock == стоимость` сервер отвечает
            # «1 ход» (измерено), то есть он считает и текущий ход. Без нижней
            # границы прогноз обещал бы юнит «сейчас», а его не будет.
            turns = max(1, int(math.ceil(max(0.0, cost - stock) / shields)))
            out.append((type_name, float(options), turns))
        return out

    def techs() -> list[tuple[str, float, int]]:
        notes.append("исследования не подключены: цена набора берётся из "
                     "tech_research_gain и будет внесена отдельно")
        return []

    # Что сервер предлагает ПРЯМО СЕЙЧАС. Без этого фильтра прогноз выбирает
    # действия, которых нет: модель площадки не знает правил стенда (например
    # `citymindist = 2`), а провод знает. Проверено живым прогоном.
    offered_unit = _as_dict(_as_dict(info.get("available_actions")).get("unit"))
    offered_city = _as_dict(_as_dict(info.get("available_actions")).get("city"))
    offered_tech = _as_dict(_as_dict(info.get("available_actions")).get("tech"))

    def _offered_for(pool: dict, entity_id: str) -> dict:
        bare = entity_id.split("_", 1)[1] if "_" in entity_id else entity_id
        for key, acts in pool.items():
            if str(key) == str(bare):
                return _as_dict(acts)
        return {}

    def allowed(kind: str, actor: str, name: str) -> bool:
        """Может ли сервер предложить это действие сейчас.

        Неизвестный вид действия считается недоступным: ошибиться в сторону
        «не действовать» безопаснее, чем сделать то, чего мир не предлагал.
        """
        if kind == "found":
            acts = _offered_for(offered_unit, actor)
            return any(acts.get(key) for key in
                       ("build_city", "found_city", "found"))
        if kind == "move":
            acts = _offered_for(offered_unit, actor)
            return any(key.startswith("goto") and value
                       for key, value in acts.items())
        if kind == "produce":
            return bool(_offered_for(offered_city, actor).get(name))
        if kind == "research":
            cur = offered_tech.get("cur_player")
            return isinstance(cur, dict) and any(
                key.startswith("research_tech") and value
                for key, value in cur.items())
        if kind == "work":
            return bool(_offered_for(offered_unit, actor).get(name))
        return False

    world = world_model if world_model is not None else default_facts()
    unpriced: set[str] = set()
    #: тип → действие для самозамера (заполняется в `productions`)
    probe_offers: dict[str, tuple[str, str, str]] = {}

    # Живой юнит нужного типа даёт СРАЗУ два числа из мира: опции типа и его
    # стоимость (`type_build_cost`). Поэтому типы, которые уже есть у кого-то на
    # карте, не ждут мерной таблицы — а те, которых нет, ждут её и не выдумываются.
    #
    # Имя типа — поле `type_rule_name` (`Settlers`, `Workers`, `Explorer`). Именно
    # оно связывает юнита с предложением `produce_<Тип>`; без него живые типы
    # оставались без цены, и производство не предлагалось вовсе (проверено на
    # реальном наблюдении: каталог извлекателя неполон — в нём нет `Settlers`).
    live_by_type: dict[str, dict] = {}
    for unit_rec in _as_dict(obs.get("unit")).values():
        if not isinstance(unit_rec, dict):
            continue
        name = str(unit_rec.get("type_rule_name") or unit_rec.get("rule_name")
                   or unit_rec.get("type") or "")
        if name and name not in live_by_type:
            live_by_type[name] = unit_rec

    # Что видим — записываем СРАЗУ, а не когда понадобится. Урок прогона: ленивая
    # запись (в момент, когда город предлагает тип) не срабатывает никогда, если
    # носитель успел исчезнуть — а он исчезает именно на первом же ходу, основав
    # город. Тогда новые поселенцы становятся неоценимыми, и город не строит ничего.
    learned = False
    for name, unit_rec in live_by_type.items():
        try:
            from env.entity_extractor import unit_options
            options = float(unit_options(
                unit_rec, model=getattr(extractor, "model", None))[0])
            cost = _num(unit_rec.get("type_build_cost"), 0.0)
            if options > 0.0 and world.observe_type(
                    name, cost=cost or None, options=options, kind="unit",
                    source="observed", turn=getattr(dof_state, "turn", None)):
                learned = True
        except Exception:  # noqa: BLE001
            continue
    if learned:
        try:
            world.save()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"склад фактов не сохранён: {type(exc).__name__}")

    bridge = getattr(getattr(dof_state, "state", None), "bridge", None)
    catalogue = {
        "unit": _as_dict(getattr(bridge, "unit_type_options", None)),
        "improvement": _as_dict(getattr(bridge, "improvement_options", None)),
    }

    def type_price(name: str) -> tuple[float, float] | None:
        """(опции типа, стоимость) или None, если цены нет — тогда тип не предлагаем.

        Живой юнит типа даёт оба числа сразу (`type_*` + `unit_options`) — и, что
        важно, **записывается в склад**: носитель, основав город, исчезает вместе со
        своими опциями, а строить новых поселенцев прогноз должен уметь и после
        этого. Каталог извлекателя здесь не спасает — он неполон.
        """
        rec = live_by_type.get(name)
        if rec is not None:
            cost = _num(rec.get("type_build_cost"), 0.0)
            options = 0.0
            try:
                from env.entity_extractor import unit_options
                options = float(unit_options(rec,
                                             model=getattr(extractor, "model", None))[0])
            except Exception:  # noqa: BLE001
                options = 0.0
            if cost > 0.0 and options > 0.0:
                return options, cost
        cost = world.cost(name)
        if cost is None:
            return None
        options = world.options(name)
        if options:
            return float(options), float(cost)
        for kind in ("unit", "improvement"):
            options = _num(catalogue[kind].get(name), 0.0)
            if options > 0.0:
                return options, cost
        return None

    # Цена раскрытия: разрыв Дженсена по ИЗМЕРЕННОМУ разбросу ценностей площадок.
    #
    # Содержание скрытой клетки модель и так считает средним по раскрытым
    # (`evaluate_site`), поэтому «ещё одна средняя клетка» выгоды не даёт — это
    # следствие самого правила. Остаётся ОПЦИЯ: узнать, что неизвестная клетка
    # лучше того, чем мы готовы удовлетвориться.
    #
    # `best_known` — не максимум выборки (с ним разрыв тождественно ноль: максимум
    # наблюдений доминирует любое новое наблюдение), а лучшая опция, которую агент
    # ДЕРЖИТ СЕЙЧАС: раскрытая и достижимая носителем. Разрыв положителен, когда
    # распределение скошено — много посредственных клеток и редкие хорошие: тогда
    # средняя вера занижает шанс на находку, и поиск становится осмысленным.
    sample_tiles = sorted(state.revealed)[:120]
    sample: list[float] = []
    for tile in sample_tiles:
        try:
            sample.append(float(city_dof(tile)))
        except Exception:  # noqa: BLE001
            continue
    held: list[float] = []
    for unit_id, pos in state.positions.items():
        if not is_carrier(unit_id):
            continue
        for tile in reach(unit_id) + [(int(pos[0]), int(pos[1]))]:
            if tile not in state.revealed:
                continue
            try:
                held.append(float(city_dof(tile)))
            except Exception:  # noqa: BLE001
                continue
    best_known = math.log(max(max(held), 1.0)) if held else 0.0
    # Импорт назван явно, а не модулем `info`: у этой функции есть свой параметр
    # `info` (наблюдение), и модуль с тем же именем он затеняет.
    gap_index = jensen_gap_index(sample, best_known)
    gap_options = jensen_gap_options(sample, best_known)

    def info_gain_of(tile: tuple[int, int]) -> float:
        if (int(tile[0]), int(tile[1])) in state.revealed:
            return 0.0
        return gap_index

    # Кто в этом ходу уже решил. Нормализация — та же, что в `_to_wire_action`:
    # префикс снимается только если он совпадает с именем контроллера
    # (`city_121` → `121`, `unit_103` → `103`), а `cur_player` остаётся как есть.
    # Сравниваем ПО СТРОКАМ: живьём ключи актёров целые (`121`), в фикстурах
    # строки, и «актёр сохраняет тип» — правило провода, а не сравнения. Именно на
    # этом правило «один актёр за ход» молча не срабатывало (61 вызов решения при
    # 31 отправленном действии).
    used = {(str(ctrl), str(actor)) for ctrl, actor in (exclude_actors or ())}

    def _bare(ctrl: str, actor: str) -> str:
        prefix, sep, rest = str(actor).partition("_")
        return rest if sep and prefix == str(ctrl) else str(actor)

    def excluded(ctrl: str, actor: str) -> bool:
        if not used:
            return False
        return ((str(ctrl), _bare(ctrl, actor)) in used
                or (str(ctrl), str(actor)) in used)

    vals = Valuations(
        reach=reach,
        site_viable=site_viable,
        city_dof=city_dof,
        city_ids=lambda: list(cities),
        productions=productions,
        techs=techs,
        works=works,
        is_carrier=is_carrier,
        info_gain=info_gain or info_gain_of,
        allowed=allowed,
        excluded=excluded,
    )
    if info_gain is None:
        held_options = max(held) if held else 0.0
        notes.append(f"цена раскрытия: разрыв Дженсена {gap_index:.3f} (индекс) / "
                     f"{gap_options:.3f} (опции) по {len(sample)} раскрытым клеткам, "
                     f"лучшая удерживаемая площадка {held_options:.2f} опций "
                     f"(индекс {best_known:.3f})")
    # Почему семейства «основание» и «движение» пусты — числами, а не догадкой.
    # Без этого «нет улучшения» не отличить от «модель не увидела ни одной годной
    # площадки», а это разные факты: первый — про цены, второй — про гейт.
    for unit_id, pos in list(state.positions.items())[:3]:
        if not is_carrier(unit_id):
            continue
        try:
            here_site = site_of((int(pos[0]), int(pos[1])))
            here = (f"годна={here_site.viable} "
                    f"(еда {here_site.gate_food:.1f}, полоса "
                    f"{here_site.food_low:.1f}..{here_site.food_high:.1f}"
                    f" при пороге {values.get('SITE_MIN_FOOD')})")
        except Exception as exc:  # noqa: BLE001
            # Текст ошибки, а не только её вид: «не оценена» без причины — это
            # снова догадка вместо факта.
            here = f"не оценена: {type(exc).__name__}: {exc}"
        tiles = reach(unit_id)
        viable = sum(1 for t in tiles if site_viable(t))
        hidden = sum(1 for t in tiles if (int(t[0]), int(t[1])) not in state.revealed)
        best = 0.0
        for t in tiles:
            try:
                best = max(best, float(city_dof(t)))
            except Exception:  # noqa: BLE001
                continue
        notes.append(f"носитель {unit_id} ({pos}): площадка здесь {here}; "
                     f"достижимо {len(tiles)} клеток, годных {viable}, "
                     f"под туманом {hidden}, лучшая ценность {best:.2f}")
    if w_info:
        notes.append("W_INFO не используется как множитель: цена раскрытия — "
                     "разрыв Дженсена, свободного веса нет")
    return LiveContext(state=state, vals=vals, my_id=my_id, notes=notes,
                       unpriced=unpriced, facts_summary=world.summary(),
                       probe_offers=probe_offers, facts=world)
