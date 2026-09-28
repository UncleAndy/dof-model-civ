"""Адаптер: живое наблюдение → оценки для прогноза.

Задача — не пересчитывать то, что уже считается, а **переиспользовать** измеренные
пути проекта:

* ценность города на площадке — формулой города (`extractor._site_city_value`),
  она возвращает опции, то есть ровно ту шкалу, в которой живёт индекс;
* работы — существующим измеренным путём (`extractor._terrain_work_gains`),
  который адресует выгоду **городу**, а не клетке; нулевой измеренный эффект так и
  остаётся нулём;
* достижимость — квадратом радиуса `move_rate` (как в `_site_move_gains`): это
  цена ПОТЕНЦИАЛА площадок, а не маршрут. Для самого движения берётся не она, а
  точная цель каждой предложенной сервером команды `goto_N` — см. ниже.

**Отозвано (2026-09-27, измерено по исходнику стенда).** Здесь стояло: «координат
цели у `goto_N` нет, точный маршрут неизвестен». Неверно. `ActGoto` в
`civrealm/freeciv/units/unit_actions.py` строит имя как `"goto_%i" % dir8`, а сама
команда — это `ORDER_MOVE` с `"dir": dir8` и `dest_tile = mapstep(ptile, dir8)`,
то есть **один шаг в направлении dir8** (0=СЗ, 1=С, 2=СВ, 3=З, 4=В, 5=ЮЗ, 6=Ю, 7=ЮВ).
Значит цель хода вычислима: `(x + DIR_DX[N], y + DIR_DY[N])`, X замыкается, по Y —
полюс (`map_pos_to_tile` возвращает None). Движение перестало быть семейством.


Всё, что здесь не заполнено, помечено как «пока не подключено» — с причиной.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from env import config as _cfg
from env.food_gate import denies as _food_gate_denies
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

#: Направления freeciv (`map_const.DIR_DX/DIR_DY`), индекс — dir8 в имени `goto_N`.
#: Скопированы, а не импортированы: этот модуль обязан оставаться проверяемым без
#: живого стенда. Порядок: 0 СЗ, 1 С, 2 СВ, 3 З, 4 В, 5 ЮЗ, 6 Ю, 7 ЮВ.
DIR_DX = (-1, 0, 1, -1, 1, -1, 0, 1)
DIR_DY = (-1, -1, -1, 0, 0, 1, 1, 1)


def direction_target(pos: tuple[int, int], dir8: int,
                     shape: tuple[int, int] | None) -> tuple[int, int] | None:
    """Клетка, на которую встанет юнит, выполнив `goto_<dir8>`, или None.

    Арифметика — из стенда (`map_ctrl.mapstep` → `map_pos_to_tile`): X замыкается
    (цилиндр), по Y — полюс, за краем клетки нет. Внутри `map_pos_to_tile`
    переполнение по X идёт через `y -= 1`, но индекс `x + y*xsize` даёт ту же
    клетку, что и простое `x %= xsize` при том же y, — проверено арифметикой.
    """
    try:
        d = int(dir8)
    except (TypeError, ValueError):
        return None
    if not 0 <= d < len(DIR_DX):
        return None
    x, y = int(pos[0]) + DIR_DX[d], int(pos[1]) + DIR_DY[d]
    if shape is not None:
        w, h = int(shape[0]), int(shape[1])
        if w > 0:
            x %= w
        if h > 0 and not 0 <= y < h:
            return None
    return (x, y)



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


def _player_record(obs: dict, my_id: Any) -> dict:
    """Запись своего игрока — правило живёт в ОДНОМ месте (`env.entity_extractor`).

    Раньше поиск был скопирован здесь, и правка потребовалась бы дважды; живое
    наблюдение ключует `player` числами, а `city` — строками, и на этом уже терялись
    прогоны («нет данных» вместо ошибки).
    """
    from env.entity_extractor import player_record

    return player_record(obs, my_id)


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

    Это цена ПОТЕНЦИАЛА (какие площадки вообще можно рассмотреть), а не маршрут;
    точные цели хода берутся из предложенных `goto_<dir8>` (см. `direction_target`).

    Замыкание — по X, как у карты-цилиндра: по Y клеток за краем НЕТ, и «взять
    чужую клетку с другого края» здесь так же неверно, как в оценке площадки
    (правка осей 2026-09-27). Раньше здесь стояло `ty %= h` — остаток той же
    ошибки, из-за которой город у полюса собирал еду с противоположного края.
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
                    if not 0 <= ty < h:
                        continue
            tiles.append((tx, ty))
    return tiles


#: Номер «рода производства» для ЮНИТА в записи города (`production_kind`).
#: Измерено на живом городе (2026-09-27): город строивший Settlers отдавал kind = 6.
#: Другие роды НЕ маппим — угадывать цену предмета нельзя, поэтому покупку для них
#: просто не предлагаем (это ограничение, а не «ноль»).
UNIT_PRODUCTION_KIND = 6


def _record_by_id(pool: Any, wanted: Any) -> dict:
    """Запись из словаря-слоя по идентификатору — НЕ по типу ключа.

    Ловушка живых ключей, уже третья в проекте: живьём `obs['tech']` ключуется
    ЧИСЛАМИ (`{2: {...}}`), в фикстурах строками. Прямой `.get(str(id))` на живом
    наблюдении молча возвращает `{}` — и семейство технологии оказывается пустым
    не потому, что наука недооценена, а потому, что запись не нашлась. Измерено
    2026-09-27: `research` не появлялся среди кандидатов ни разу за 15 ходов, а
    диагностика печатала «открывает=—» при живой записи технологии в наблюдении.

    Правило то же, что и везде: смотрим ЗНАЧЕНИЯ, сравниваем по `id`/`name`, и
    только потом пробуем оба вида ключа.
    """
    pool = _as_dict(pool)
    if wanted is None:
        return {}
    for key in (wanted, str(wanted)):
        rec = pool.get(key)
        if isinstance(rec, dict) and rec:
            return rec
    for key, rec in pool.items():
        if not isinstance(rec, dict):
            continue
        for field in ("id", "name", "rule_name"):
            value = rec.get(field)
            if value is not None and str(value) == str(wanted):
                return rec
        if str(key) == str(wanted):
            return rec
    return {}


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
                  info_gain: Callable[[tuple[int, int]], float] | None = None,
                  type_names: dict | None = None,
                  gold: Any = None,
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

    # ── ПОРОГ ДЛЯ ПЕРВОГО ГОРОДА ПАДАЕТ С ХОДОМ (§10.27, решение Andy) ──────
    # Пока города нет, порог 6.0 при бедном старте делает НЕВОЗМОЖНЫМ само
    # основание: ни одна достижимая площадка не годна → кандидата нет → сторона
    # стоит вечно (измерено: 60 ходов, 0 действий). Поэтому для первого города
    # порог падает по объявленной формуле. Для последующих городов — остаётся 6.0.
    # Порог подменяется ОДНИМ местом (здесь), поэтому и прогноз, и диагностика,
    # и оценка площадок берут одно и то же число.
    if capital:
        try:
            _turn_no = max(1, int((info or {}).get("turn") or 1))
        except (TypeError, ValueError):
            _turn_no = 1
        values["SITE_MIN_FOOD"] = _cfg.first_city_food_gate(_turn_no)
        notes.append(f"первый город: порог площадки падает с ходом "
                     f"({_cfg.SITE_MIN_FOOD_FIRST:.1f} − "
                     f"{_cfg.SITE_MIN_FOOD_FIRST_DECAY:.2f}/ход, пол "
                     f"{_cfg.SITE_MIN_FOOD_FIRST_FLOOR:.1f}); на ходу {_turn_no} он "
                     f"{values['SITE_MIN_FOOD']:.2f}")

    # ── НАБИВКА СКРЫТЫХ КЛЕТОК — ИЗ ИЗМЕРЕННОГО (§10.27.1) ─────────────────
    # Средний и лучший выход по РАСКРЫТЫМ клеткам этой карты. Нужны там, где окно
    # площадки целиком под туманом: там «среднего по видимым» взять неоткуда, а
    # ноль запрещён («незнание — это не отсутствие возможностей»). Источник —
    # само наблюдение, поэтому набивка измеренная, а не выдуманная.
    try:
        import numpy as _np
        _layer = (map_obs or {}).get("output")
        if _layer is not None:
            arr = _np.asarray(_layer)
            flat = arr.reshape(-1, arr.shape[-1])
            flat = flat[:, :3]
            revealed = flat[(flat != 0).any(axis=1)]
            if len(revealed):
                values["UNKNOWN_FILL"] = tuple(float(v) for v in revealed.mean(axis=0))
                values["UNKNOWN_BEST"] = tuple(float(v) for v in revealed.max(axis=0))
                notes.append(
                    f"набивка тумана: по {len(revealed)} раскрытым клеткам среднее "
                    f"{values['UNKNOWN_FILL'][0]:.2f} еды, лучшее "
                    f"{values['UNKNOWN_BEST'][0]:.2f}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"набивка тумана: не посчиталась ({type(exc).__name__}: {exc}) — "
                     f"берётся измеренная легенда террейнов")

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

    def moves(unit_id: str) -> list[tuple[str, tuple[int, int]]]:
        """Предложенные серверу шаги этого юнита: [(имя `goto_N`, клетка назначения)].

        Цель каждой команды вычисляется из направления (`direction_target`), а не
        выдумывается: `goto_N` — это dir8. Команды, чья цель за полюсом, отбрасываются
        (клетки там нет). Юнит, у которого нет ни одного предложенного шага, не ходит.
        """
        uid = unit_id.split("_", 1)[1] if "_" in unit_id else unit_id
        acts = _offered_for(offered_unit, uid)
        pos = state.positions.get(unit_id)
        if pos is None:
            return []
        out: list[tuple[str, tuple[int, int]]] = []
        for name, params in acts.items():
            if not params or not name.startswith("goto"):
                continue
            suffix = name.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                # `goto` без направления (например `keep_activity`-подобные формы) —
                # цель не определена, шагом это не считается.
                continue
            tile = direction_target(pos, int(suffix), shape)
            if tile is not None:
                out.append((name, tile))
        return out

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
            # Улучшения — ОТДЕЛЬНОЕ семейство (`improvements`): они не создают
            # сущность, а растут опциями города. Здесь пропускаются, иначе одно и
            # то же здание предлагалось бы дважды и считалось дважды.
            if type_name in spec_improvements and type_name not in live_by_type:
                continue
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

    player = _player_record(obs, my_id)
    # Наука за ход считается ниже по ИЗМЕРЕННОМУ драйверу. Отдельно и явно:
    # `bulbs` города не двигают прогресс технологии (измерено: рост +0/+1 при
    # bulbs 1…3), поэтому это поле здесь только для следа, а не для цены.
    bulbs_per_turn = 0.0
    for city in city_records.values():
        bulbs_per_turn += _num(city.get("bulbs"), 0.0)
    if bulbs_per_turn > 0.0:
        notes.append(f"сумма bulbs городов {bulbs_per_turn:.1f} — в цену технологии "
                     f"НЕ идёт (измерено: прогресс ей не равен; драйвер — "
                     f"round(Σ торговля × ставка / 100), см. `techs`)")

    # Стоимость типов из спецификаций технологий: и юнитов, и улучшений. Это
    # снимает необходимость замерять цену постановкой производства (замер улучшения
    # роняет контроллер) — стоимость публикуется миром там же, где и у юнитов.
    # Отдельно запоминаем, какие имена пришли из `sup_improvements`: это и есть
    # признак «тип есть улучшение», по которому юниты и улучшения не путаются.
    spec_costs: dict[str, float] = {}
    spec_improvements: set[str] = set()
    for rec in _as_dict(obs.get("tech")).values():
        if not isinstance(rec, dict):
            continue
        for field in ("sup_units", "sup_improvements"):
            for spec in (rec.get(field) or []):
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get("rule_name") or spec.get("name") or "")
                cost = _num(spec.get("build_cost"), 0.0)
                if name and cost > 0.0 and name not in spec_costs:
                    spec_costs[name] = cost
                if name and field == "sup_improvements":
                    spec_improvements.add(name)


    def improvement_gain(city_id: str, name: str) -> float:
        """Насколько улучшение поднимает опции ЭТОГО города (в шкале опций).

        Не константа «улучшение = +N»: считает сама формула города — сколько у
        города опций сейчас и сколько станет, если флаг улучшения добавится.
        Иначе потолок первого множителя (`CITY_CAP_M1`) не виден, и город на
        потолке получал бы надбавку за то, что у него и так есть.
        """
        rec = city_records.get(city_id)
        if not isinstance(rec, dict):
            return 0.0
        try:
            from env.entity_extractor import city_options
            model = getattr(extractor, "model", None)
            flags = list(rec.get("improvements") or [])
            before = float(city_options(rec, model=model))
            with_flag = dict(rec)
            with_flag["improvements"] = flags + [True]
            after = float(city_options(with_flag, model=model))
        except Exception:  # noqa: BLE001
            return 0.0
        return max(0.0, after - before)


    def improvements(city_id: str) -> list[tuple[str, float, int, float | None]]:
        """Улучшения, которые город может поставить: [(имя, Δопций, ходов, доля времени)].

        Улучшение — не новая сущность (иначе здание считалось бы живым и индекс
        рос бы дважды), а рост опций САМОГО города: город с храмом удерживает
        больше возможностей, чем без него.

        Стоимость — из спецификаций технологий (`sup_improvements[].build_cost`),
        срок — измеренным правилом для улучшений. Если улучшение ничего не
        добавляет (город уже на потолке множителя), оно не предлагается:
        измеренное «ноль» не притворяется выгодой. Замер цены постановкой
        производства НЕ делается: он роняет контроллер (проверено), а
        спецификация даёт цену без боя.

        Две величины-НАСТРОЙКИ, объявленные, а не измеренные (§10.25.4):

        * `IMPROVEMENT_BUILD_BONUS` — множитель прироста;
        * доля времени `(H − срок)/H` вместо `γ^срок` — постройка, встающая на
          30-м ходу 50-ходовой игры, отрабатывает остаток горизонта.
        """
        rec = city_records.get(city_id) or {}
        offered = _offered_for(offered_city, city_id)
        stock = _num(rec.get("shield_stock"), 0.0)
        # Значения берём из модели, а если её нет (проба/синтетика) — из config:
        # иначе выключенный флаг выглядел бы как «семейство пустое».
        rate = float(values.get("IMPROVEMENT_SHIELD_RATE",
                                _cfg.IMPROVEMENT_SHIELD_RATE) or 1.0)
        bonus = float(values.get("IMPROVEMENT_BUILD_BONUS",
                                 _cfg.IMPROVEMENT_BUILD_BONUS) or 1.0)
        horizon = int(values.get("IMPROVEMENT_HORIZON_TURNS",
                                 _cfg.IMPROVEMENT_HORIZON_TURNS) or 0)
        if rate <= 0.0:
            return []
        out: list[tuple[str, float, int, float | None]] = []
        for name, params in offered.items():
            if not params or not name.startswith("produce_"):
                continue
            type_name = name[len("produce_"):]
            # Юнит — не улучшение, даже если имя встретилось в спецификациях.
            if type_name in live_by_type or catalogue["unit"].get(type_name):
                continue
            if type_name not in spec_improvements and not \
                    catalogue["improvement"].get(type_name):
                continue
            cost = world.cost(type_name)
            if cost is None:
                cost = spec_costs.get(type_name)
            if cost is None:
                unpriced.add(type_name)
                continue
            gain = improvement_gain(city_id, type_name)
            if gain <= 0.0:
                continue
            # Срок — ИЗМЕРЕННЫМ правилом для улучшений, а не формулой юнитов.
            #
            # Измерено (2026-09-27, одна проба, 15 последовательных наблюдений,
            # два улучшения): накопленное растёт ровно на 1 щит за ход
            # (`Δstock = 1` во всех наблюдениях, `Δготовность = 1/стоимость`), а
            # публикуемый `prod_shield` при этом равен 5. Срок сервера совпал с
            # `стоимость − stock`: 58 против 58.0 (City Walls 60) и 293 против
            # 293.0 (Great Wall 300). Формула юнитов
            # `ceil((стоимость − stock) / prod_shield)` дала бы 11.6 и 58.6 —
            # то есть обещала бы улучшение в 5 раз быстрее, чем оно будет.
            #
            # Если стенд обновят, правило надо перемерить: это факт об этом
            # наборе правил, а не «так устроено везде».
            turns = max(1, int(math.ceil((cost - stock) / rate)))
            # Доля горизонта, которую постройка успевает отработать. Срок больше
            # горизонта → ровно ноль: такое здание в этой игре не построится, и
            # притворяться, что оно даст что-то, нельзя.
            tf: float | None = None
            if horizon > 0:
                tf = max(0.0, (horizon - turns) / float(horizon))
            out.append((type_name, gain * bonus, turns, tf))
        return out

    # ── Клетки города: перевод жителя (§10.25.4) ─────────────────────────────
    # Цена — формулой города: сколько опций прибавится городу, если выходы этой
    # клетки войдут в его экономику (и убавится, если выйдут). Замер 2026-09-27
    # совпал по знаку во всех шести парах: предсказание +1.2000 → наблюдение
    # +0.41/+0.48; −0.6000 → −0.63/−0.57; +0.6000 → +0.78/+0.85.
    #
    # Оговорка честности: одиночное действие оценивается по СВОЕЙ клетке, а не по
    # паре «взял X, отдал Y» — какая клетка будет освобождена, сервер не сообщает.
    # Сумму пары даёт сам поиск, когда проигрывает оба шага: вклады складываются
    # как логарифмы, поэтому итог равен точному (телескопирование), а
    # промежуточное состояние не завышает итог.
    # Слой карты — МАССИВ (numpy/список списков), а не словарь: `_as_dict` его не
    # переживёт (вернёт пустое), поэтому берём его как есть из блока карты.
    output_layer = _as_dict(obs.get("map")).get("output")

    def _tile_outputs(city_id: str, name: str) -> list[float] | None:
        """Выходы клетки из имени `city_{work,unwork}_<id>_<dx>_<dy>`.

        Источник — слой карты (`map['output']`, каналы 0..2) от координат города:
        тот же источник, на котором стоял замер, иначе предсказание и замер
        говорили бы о разных числах.
        """
        rec = city_records.get(city_id)
        if not isinstance(rec, dict):
            return None
        parts = str(name).split("_")
        try:
            dx, dy = int(parts[-2]), int(parts[-1])
        except (TypeError, ValueError):
            return None
        try:
            cx = int(_num(rec.get("x"), 0.0) + dx)
            cy = int(_num(rec.get("y"), 0.0) + dy)
            cell = output_layer[cx][cy]
            return [float(v) for v in list(cell)[:3]]
        except Exception:  # noqa: BLE001
            return None

    def tiles(city_id: str) -> list[tuple[str, float]]:
        """Переводы жителя, предложенные сервером: [(действие, Δопций города)].

        Нулевой перевод остаётся кандидатом с нулём: «измеренный ноль — знание»,
        и решать о нём должен поиск, а не генератор (та же политика, что у работ).
        """
        if not values.get("CITY_TILE_FAMILY", _cfg.CITY_TILE_FAMILY):
            return []
        rec = city_records.get(city_id)
        if not isinstance(rec, dict) or output_layer is None:
            return []
        try:
            from env.entity_extractor import city_options
            model = getattr(extractor, "model", None)
            before = float(city_options(rec, model=model))
        except Exception:  # noqa: BLE001
            return []
        out: list[tuple[str, float]] = []
        for name, params in _offered_for(offered_city, city_id).items():
            if not params:
                continue
            text = str(name)
            if text.startswith("city_work_"):
                sign = 1.0
            elif text.startswith("city_unwork_"):
                sign = -1.0
            else:
                continue
            # Правило F (§10.30): перевод жителя, после которого город не прокормит
            # себя, отсекается ДО поиска. Цена в опциях этого не выражает: голод
            # уничтожает город целиком (и сторона выбывает), а не «уменьшает выгоду».
            if getattr(_cfg, "FOOD_GATE_ENABLED", True):
                deny, _why = _food_gate_denies(text, city=rec, obs=obs)
                if deny:
                    continue
            outputs = _tile_outputs(city_id, text)
            if not outputs:
                continue
            shifted = dict(rec)
            for field, index in (("prod_food", 0), ("prod_shield", 1),
                                 ("prod_trade", 2), ("surplus_food", 0),
                                 ("surplus_shield", 1), ("surplus_trade", 2)):
                cur = shifted.get(field)
                if cur is None:
                    continue
                try:
                    shifted[field] = float(cur) + sign * float(outputs[index])
                except (TypeError, ValueError):
                    continue
            try:
                after = float(city_options(shifted, model=model))
            except Exception:  # noqa: BLE001
                continue
            out.append((text, after - before))
        return out

    def techs() -> list[tuple[str, float, int]]:
        """[(имя вида `tech_<id>`, выигрыш в опциях, ходов)] — числа из мира.

        Срок = `ceil((стоимость − накоплено) / наука_за_ход)`, где

            наука_за_ход = round(Σ торговля своих городов × ставка науки / 100)

        — **драйвер установлен замером**, а не выведен. Проверено на двух прогонах
        с разной торговлей:

        | торговля | ставка | рост прогресса | Σ торговля | floor | ceil | round |
        |---|---|---|---|---|---|---|
        | 1 | 60 | +1 (24/24) | 24/24 | 0/24 | 24/24 | 24/24 |
        | 3 | 60 | +2 (35/35) | 0/35 | 18/35 | 17/35 | **35/35** |

        Первый прогон не различал `Σ торговля` и `round(торговля × ставка)`: при
        торговле 1 они совпадают. Второй различил. Отдельно проверены и отброшены
        `bulbs` города (3) и `player.science` (60) — оба поля обманки: рост им не
        равен ни в одном ходу.

        Оговорка, названная прямо: при ставке 60 % произведение торговли на ставку
        никогда не даёт ровно .5, поэтому правило округления половин проверено не
        было (при смене ставки на 50 % это надо перенастроить).

        Выигрыш берётся из открытого набора технологии (без деления на срок: срок
        прогноз применяет сам, и деление применилось бы дважды).
        """
        current = player.get("researching")
        if current is None:
            return []
        cost = _num(player.get("researching_cost"), 0.0)
        done = _num(player.get("bulbs_researched"), 0.0)
        rate = _num(player.get("science"), 0.0)
        trade = 0.0
        for city in city_records.values():
            trade += _num(city.get("prod_trade"), 0.0)
        per_turn = round(trade * rate / 100.0)
        if cost <= 0.0 or per_turn <= 0.0:
            return []
        record = _record_by_id(obs.get("tech"), current)
        if not record:
            return []
        try:
            from env.entity_extractor import tech_options
            base = _num((values or {}).get("TECH_BASE_OPTIONS"), 0.0)
            unlocked = float(tech_options(record, as_known=True,
                                          model=getattr(extractor, "model", None))) - base
        except Exception:  # noqa: BLE001
            return []
        if unlocked <= 0.0:
            return []
        turn_count = max(1, int(math.ceil(max(0.0, cost - done) / per_turn)))
        return [(f"tech_{current}", unlocked, turn_count)]

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
            # Может ли сервер предложить ИМЕННО этот шаг: `goto_3` — это шаг в
            # направлении 3, подменить его другим значит увести юнита не туда.
            acts = _offered_for(offered_unit, actor)
            return bool(acts.get(name))
        if kind == "produce":
            return bool(_offered_for(offered_city, actor).get(name))
        if kind == "improve":
            return bool(_offered_for(offered_city, actor).get(name))
        if kind == "tile":
            # Перевод жителя — тоже действие города: имя целиком (`city_work_…`)
            # приходит от сервера, и подменять его нельзя.
            return bool(_offered_for(offered_city, actor).get(name))
        if kind == "buy":
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
            # Стоимость типа из спецификаций технологий (`build_cost`): второй
            # законный источник, без замера и без постановки производства.
            cost = spec_costs.get(name)
        if cost is None:
            return None
        options = world.options(name)
        if options:
            return float(options), float(cost)
        for kind in ("unit", "improvement"):
            options = _num(catalogue[kind].get(name), 0.0)
            if options > 0.0:
                return options, float(cost)
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
    # Пол цены раскрытия (§10.27.1, подтверждено Andy). Если раскрытые клетки дали
    # ВЫРОЖДЕННУЮ выборку (все значения равны), разброс берётся из ИЗМЕРЕННОГО
    # несмещённым забором, а не из нуля: нулевой разброс здесь означал бы «знать
    # больше нечего», хотя 80.9 % окна под туманом (измерено). Число — перевод
    # замера (ст.откл 1.77 еды в опции формулой города), а не подобранная величина.
    gap_floor = float(_cfg.INFO_GAP_FLOOR_OPTIONS)
    gap_potential_applied = False
    gap_potential: float | None = None
    if sample:
        # Раскрытые клетки — выборка ВИДИМОГО; покупка же — узнать НЕВИДИМОЕ.
        # Поэтому в розыгрыш ВСЕГДА входит потенциал неизвестного: среднее по
        # видимым плюс ИЗМЕРЕННЫЙ разброс (§10.27.1, ст.откл 1.77 еды → 1.27 опции).
        # Без него разрыв Дженсена тождественно ноль в обычном случае: лучшая
        # УДЕРЖИВАЕМАЯ площадка и есть максимум выборки, поэтому ни один розыгрыш её
        # не превышает и цена раскрытия выходит 0.000 (измерено на живом прогоне:
        # индекс 0.000 при опциях 0.279). Ход в туман из-за этого отвергался ВСЕГДА.
        # Потенциал входит в РОЗЫГРЫШ, но НЕ в веру: вера — среднее по видимому,
        # а потенциал — то, что может открыться. Если удерживаемая площадка и так
        # выше потенциала, разрыв остаётся нулём — и это честно: искать нечего.
        mean_sample = sum(sample) / len(sample)
        gap_potential = mean_sample + gap_floor
        gap_potential_applied = True
    # Импорт назван явно, а не модулем `info`: у этой функции есть свой параметр
    # `info` (наблюдение), и модуль с тем же именем он затеняет.
    gap_index = jensen_gap_index(sample, best_known, potential=gap_potential)
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

    def buys(city_id: str) -> list[tuple[str, str, float, float]]:
        """Покупка производства: [(действие, тип предмета, опции, цена в золоте)].

        Цена золота ИЗМЕРЕНА (§10.25.1): уходит ровно `buy_cost`. Вклад в индекс —
        тот же предмет, но БЕЗ дисконта срока (покупка завершает его сейчас), поэтому
        кандидат отличается от производства только задержкой. Золото в модели нигде
        больше не оценено, поэтому единственное ограничение — доступность:
        `золото игрока ≥ buy_cost` (и это ограничение, а не цена).

        Предмет очереди называем ТОЛЬКО когда он опознан: `production_kind == 6`
        (юнит — измерено) и тип найден в таблице клиента. Иначе покупку не
        предлагаем: угадывать цену предмета нельзя.
        """
        rec = city_records.get(city_id) or {}
        offered_here = _offered_for(offered_city, city_id)
        if not offered_here.get("city_buy_production"):
            return []
        turns = _num(rec.get("turns_to_prod_complete"), 0.0)
        cost_gold = _num(rec.get("buy_cost"), 0.0)
        if turns <= 1 or cost_gold <= 0.0:
            return []
        try:
            kind = int(_num(rec.get("production_kind"), -1))
        except (TypeError, ValueError):
            return []
        if kind != UNIT_PRODUCTION_KIND:
            return []
        value = rec.get("production_value")
        table = type_names or {}
        if not table and "покупка: таблицы типов нет" not in notes:
            # Без таблицы типов предмет очереди назвать нечем, и покупку предлагать
            # нельзя — но молчание тут неотличимо от «покупать нечего». Говорим прямо.
            notes.append("покупка: таблицы типов нет (смотри env.")
        name = None
        for key in (value, str(value)):
            if key in table:
                name = table[key]
                break
        if not name:
            if "покупка: предмет не опознан" not in notes:
                notes.append(f"покупка: предмет не опознан (kind={kind}, "
                             f"value={value})")
            return []
        # Доступность НЕ проверяем своей формулой: сервер сам помечает
        # `city_buy_production` недействительным, когда золота не хватает
        # (измерено: при `buy_cost == золото` предложение уже False). Одна проверка
        # вместо двух — своя формула тут была бы выдуманным порогом.
        priced = type_price(name)
        if priced is None:
            return []
        options, _cost = priced
        return [("city_buy_production", str(name), float(options), float(cost_gold))]

    vals = Valuations(
        reach=reach,
        moves=moves,
        site_viable=site_viable,
        city_dof=city_dof,
        city_ids=lambda: list(cities),
        productions=productions,
        improvements=improvements,
        tiles=tiles,
        buys=buys,
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
                     f"{'с потенциалом из замера' if gap_potential_applied else 'без потенциала'} "
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
