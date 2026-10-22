#!/usr/bin/env python3
"""
Real CivRealm tournament runner.

Plays actual games against a running Freeciv-web server so that agent actions
genuinely affect the game state, and measures every agent through the same
recorder (:mod:`metrics.tracker`) so the comparison is apples-to-apples.

Usage:
    bash do.sh real-tournament --episodes 15 --turns 30 --only random,dof_defensive
    bash do.sh real-tournament --episodes 15 --turns 30 --output tournament_results.json

Operational notes
-----------------
* CivRealm agent "ports" are server-side game slots. Singleplayer/pbem occupy
  6000-6009, the idle multiplayer pool handed out by ``Ports.get()`` is
  6300-6331. A slot is single-use *until its game ends*: Publite2 restarts it
  and the slot returns to the pool, so long runs cycle through the same slots
  without restarting the container.
* ``env.reset`` and ``Ports.get`` block forever with no free slot, so every
  match is guarded by a wall-clock alarm.
* Gymnasium's passive env checker warns on CivRealm's non-standard observation
  space; those warnings are silenced on purpose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import sys
import time
import traceback
import warnings

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"


# CivRealm's config module runs its own argparse over sys.argv at import time,
# so our CLI must be resolved before civrealm is imported and the leftover
# arguments handed back untouched.
def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_real_tournament.py",
        description="Real CivRealm tournament (agents play actual games).",
    )
    parser.add_argument("--episodes", type=int, default=15,
                        help="matches per agent")
    parser.add_argument("--turns", type=int, default=30,
                        help="max decision steps per match")
    parser.add_argument("--port", type=int, default=6001,
                        help="base slot; only used when --no-auto-port is set")
    parser.add_argument("--timeout", type=int, default=240,
                        help="per-match wall-clock budget in seconds")
    parser.add_argument("--auto-port", dest="auto_port", action="store_true",
                        default=True,
                        help="pick a free slot via civrealm Ports.get() (default)")
    parser.add_argument("--no-auto-port", dest="auto_port", action="store_false",
                        help="use --port + episode index instead")
    parser.add_argument("--port-wait", type=int, default=180,
                        help="seconds to wait for a free slot before falling back")
    parser.add_argument("--retries", type=int, default=2,
                        help="extra attempts per match when the server stalls")
    parser.add_argument("--settle", type=float, default=10.0,
                        help="seconds between matches (gives Publite2 time to "
                             "restart a recycled slot before it is reused)")
    parser.add_argument("--pace", type=float, default=0.0,
                        help="seconds to sleep between decisions — use for a slow, "
                             "watchable demo game an observer can join")
    parser.add_argument("--trace", action="store_true",
                        help="print every decision and every turn end, so an observer "
                             "can correlate the agent's play with the map")
    parser.add_argument("--max-decisions-per-turn", type=int, default=20,
                        help="cap decisions issued inside one turn before the turn "
                             "is ended explicitly")
    parser.add_argument("--duel", action="store_true",
                        help="this match is one side of a duel: several players in "
                             "one game, so a turn ends only when EVERY player's "
                             "phase has ended. Count turns by the GLOBAL turn "
                             "counter instead of by our own phase endings.")
    parser.add_argument("--duel-wait", type=float, default=0.5,
                        help="seconds to wait while the other player takes its "
                             "phase (duel mode); without it we would hammer the "
                             "server with end-turn steps in the same turn")
    parser.add_argument("--lookahead", type=int, default=3,
                        help="DOF-Core lookahead horizon in turns (core default 3). "
                             "Cost grows ~ candidates**horizon, so raise it together "
                             "with a smaller --max-candidates.")
    parser.add_argument("--context-switch-penalty", type=float, default=0.5,
                        help="DOF-Core penalty charged to irreversible actions "
                             "(Axiom 4); core default 0.5")
    parser.add_argument("--max-candidates", type=int, default=8,
                        help="max branches handed to DOF-Core per decision")
    parser.add_argument("--forecast", dest="forecast", action="store_true",
                        default=True,
                        help="решение принимает ПРОГНОЗ (brain/forecast): перебор "
                             "вариантов с перевыводом возможностей в будущем "
                             "состоянии, дисконт за ход, вето/штраф по аксиомам")
    parser.add_argument("--no-food-gate", dest="food_gate", action="store_false",
                        default=True,
                        help="выключить Правило F «еда необратима» (§10.30) — это "
                             "КОНТРОЛЬ, а не режим результатов: без него нельзя "
                             "отличить «правило помогло» от «серия была мягче»")
    parser.add_argument("--no-forecast", dest="forecast", action="store_false",
                        help="прежний путь: ядро оценивает один шаг по сегодняшнему "
                             "меню (для сравнения, а не для результатов)")
    parser.add_argument("--tile-every-turn", dest="tile_every_turn",
                        action="store_true", default=False,
                        help="подавать приказ по клетке КАЖДЫЙ ход: наш приказ живёт один ход "
                             "(управляющий сервера перекрывает его, §13.234), но именно он даёт "
                             "прирост еды (§13.235: без приказов городов 0–1 вместо 2–3)")
    parser.add_argument("--city-manager", dest="city_manager", action="store_true",
                        default=True,  # §13.329: его ИИ ставит эти числа ВСЕГДА (cityturn.c:313),
                                       # поэтому перенос обязан быть включён, а не ждать флага
                        help="сказать городскому управляющему СЕРВЕРА наши требования "
                             "(PACKET_WEB_CMA_SET 257): раскладку жителей выбирает он, и без "
                             "наших требований берёт умолчание (§13.237)")
    parser.add_argument("--no-worker-work", dest="worker_work", action="store_false",
                        default=True,
                        help="выключить отдельное решение рабочего (§13.259) — сверочная ветвь")
    parser.add_argument("--no-tile-actions", dest="no_tile_actions",
                        action="store_true", default=False,
                        help="не тратить ходы на клетки: раскладку жителей выбирает "
                             "управляющий СЕРВЕРА (auto_arrange_workers, cityturn.c:366) "
                             "теми же числами, а наш приказ живёт один ход (§13.234)")
    parser.add_argument("--no-dof", dest="no_dof", action="store_true", default=False,
                        help="ВЫКЛЮЧИТЬ DoF: ни прогноза, ни индекса, ни вето ядра — "
                             "выбор только предпочтением стратегии. Указание владельца: "
                             "сначала доказать, что САМА ИГРА (города, рост, производство) "
                             "не хуже встроенного ИИ, и лишь потом накладывать индекс")
    parser.add_argument("--seed-base", type=int, default=None,
                        help="if set, episode i calls env.reset(seed=seed_base+i). "
                             "NOTE: observed ineffective on the standard stand -- "
                             "Publite2 creates the game (and its map) before the "
                             "client connects, so episodes repeat the SAME scenario. "
                             "Confidence intervals are therefore within-scenario, "
                             "not across environments.")
    parser.add_argument("--only", type=str, default="",
                        help="comma-separated agent subset, e.g. random,dof_defensive")
    parser.add_argument("--no-curiosity", dest="curiosity", action="store_false",
                        default=True,
                        help="A/B: turn OFF the bonus for probing unmeasured "
                             "actions (env.config.CURIOSITY_ENABLED). Everything "
                             "else stays identical, so a difference is the "
                             "mechanism's own effect.")
    parser.add_argument("--false-claim", type=str, default="",
                        help="заведомо неверное утверждение в модель перед матчем, "
                             "KEY=VALUE[,KEY=VALUE…]; проверяет, что мир его "
                             "исправит (Axiom «реальность первична»). Пример: "
                             "--false-claim rules.citymindist=3.0")
    parser.add_argument("--dump-state", dest="dump_state", type=int, default=0,
                        metavar="N",
                        help="писать срез состояния мира на КАЖДОМ ходу до N-го: наши "
                             "города (размер, склад еды, surplus_food, недовольные), "
                             "наши юниты, видимые чужие юниты, НЕЗАВИСИМОЕ знание "
                             "клиента (контроллер: города/юниты/поселенцы/разбит/"
                             "состояние) и ПОЛНЫЙ текст сообщений мира. Нужен там, где "
                             "потеря города разбирается по записям, а не по догадке")
    parser.add_argument("--save-series", dest="save_series", action="store_true",
                        default=False,
                        help="also persist per-step DoF/entity/action series "
                             "(larger JSON, enables trajectory analysis)")
    parser.add_argument("--output", type=str, help="write per-episode metrics to JSON")
    parser.add_argument("--dump-candidates", dest="dump_candidates", type=int,
                        default=0, metavar="N",
                        help="напечатать кандидатов прогноза (вид, действие, "
                             "доф, срок, дисконт) за первые N ходов — для замера "
                             "порогов, а не для догадок")
    parser.add_argument("--sample-sites", dest="sample_sites", type=int, default=0,
                        metavar="N",
                        help="за первые N ходов оценить ВСЕ клетки окна вокруг наших "
                             "юнитов (та же формула `evaluate_site`) и дописать строки "
                             "в `site_sample.jsonl`. Нужно для честной (несмещённой) "
                             "оценки того, какие площадки на карте бывают: корпус "
                             "основанных городов к хорошим местам смещён")
    parser.add_argument("--sample-radius", dest="sample_radius", type=int, default=9,
                        help="радиус окна забора площадок (по умолчанию 9)")
    parser.add_argument("--ban-produce", dest="ban_produce", nargs="*", default=[],
                        metavar="ТИП",
                        help="запретить прогнозу ставить эти типы в очередь "
                             "(инструмент серии «состав против состава»: "
                             "например --ban-produce Warriors Settlers)")
    args, rest = parser.parse_known_args(argv)
    sys.argv = [sys.argv[0]] + rest
    return args


ARGS = _parse_cli(sys.argv[1:])

# Флаг «без ходов на клетки» обязан доходить и до ПРОГНОЗА: его кандидаты клеток строятся в
# `brain/forecast/options.py`, мимо общего фильтра решения. Прежде переменную ставил САМ общий
# фильтр, а в пути прогноза он не вызывается — и в прогоне с флагом оставались 9 отправок по
# клеткам (измерено: «изменение не подключено»). Ставим здесь, один раз при разборе аргументов.
if getattr(ARGS, "no_tile_actions", False):
    os.environ["DOF_NO_TILE_ACTIONS"] = "1"

import gymnasium
from civrealm.configs import fc_args
from civrealm.agents import RandomAgent, BaseAgent

from env import config as env_config
from env.config import AXIOM4_PENALTY_OPTIONS, CORE_DOF_SCALE, EPSILON
from env.entity_extractor import GameStateExtractor, as_dict, compute_total_dof_index
from env.entity_extractor import truthy  # пустые параметры = мир не примет
from env.experiments import note_choice
from env import food_gate
from env.wedged import is_wedged_family, is_wedged_here, record_success, record_wedged
from env.world_model import FALSE_CLAIM_MARKER, Provenance
from brain.generator.heuristics import ALL_STRATEGIES, DEFENSIVE, HeuristicGenerator
from metrics.tracker import MatchMetrics, agent_turns

# DOF-Core decision engine. The tournament must exercise the actual object of
# study: the Rust core owns the Axiom-3 veto and the Axiom-4 context-switch
# penalty for irreversible actions, and it declines to act when every option has
# a negative net delta (Decision Calculus §4).
try:
    from dof_core import CoreAction, CoreEntity, DOFCalculusCore

    HAVE_DOF_CORE = True
except Exception:  # noqa: BLE001 - Python fallback keeps the runner usable
    HAVE_DOF_CORE = False

# Slots: singleplayer/pbem 6000-6009, idle multiplayer pool 6300-6331.
MIN_PORT = 6000
MAX_PORT = 6331

#: Сколько секунд ждать один шаг, прежде чем считать, что стенд заклинило.
#: Измерено, что `irrigation` на речной равнине и `build_road` на орошённой
#: равнине не возвращают управление из `env.step` вообще — без этого таймера
#: матч умирает только по общему бюджету, и непонятно, какой выбор его убил.
STEP_TIMEOUT = 20


class MatchTimeout(Exception):
    """Raised when a single match exceeds its wall-clock budget."""


def _on_alarm(signum, frame):  # pragma: no cover - signal path
    raise MatchTimeout("match exceeded wall-clock budget")


# Backwards-compatible alias (older scripts imported MatchResult).
MatchResult = MatchMetrics


class NoOpAgent(BaseAgent):
    """Baseline that never issues an action."""

    def act(self, observations, info):
        return None


def allocate_port(wait: int = 120, bad_slots: set | None = None):
    """Ask civrealm for a free slot, or None if none appears in ``wait`` seconds.

    ``Ports.get()`` loops forever when no slot is free, so it is alarm-guarded.
    Slots are recycled by Publite2 after a game ends, so waiting is normal in a
    long run.

    ``bad_slots`` are ports that already failed a match in this process. CivRealm
    releases a slot when it has been idle for 30s even if its game never actually
    restarted, and such a slot hangs (`BeginTurnTimeout`); re-drawing it wastes a
    full match timeout, so failed slots are skipped. Drawing again is safe because
    ``Ports.get()`` marks the slot it just handed out as occupied.
    """
    try:
        from civrealm.freeciv.utils.port_utils import Ports
    except Exception:  # noqa: BLE001 - status endpoint unreachable
        return None

    def _alarm(signum, frame):
        raise MatchTimeout("no free slot")

    bad = bad_slots or set()
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(max(1, wait))
    try:
        for _ in range(8):
            port = Ports.get()
            if port not in bad:
                return port
        return None
    except (MatchTimeout, Exception):  # noqa: BLE001
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _same_class(cities: dict, cid, target: str) -> bool:
    """Один ли класс у текущей постановки города и у предлагаемой (§13.523).

    Штраф за смену берётся ТОЛЬКО при смене класса (`common/city.c:1906-1917`: внутри класса
    «There's never a penalty»), причём у ИИ на `normal` он не берётся вовсе
    (`server/citytools.c:3180`). Значит запрещать надо смену класса, а не любую смену.
    Род цели берём из `can_build_unit`/`can_build_improvement` записи города; не опознали —
    возвращаем False, то есть работаем по-прежнему (незнание не запрещает).
    """
    city = cities.get(str(cid)) or cities.get(cid)
    if not isinstance(city, dict):
        return False
    try:
        cur_kind = int(city.get("production_kind"))
    except (TypeError, ValueError):
        return False
    units = str(city.get("can_build_unit") or "")
    imps = str(city.get("can_build_improvement") or "")
    if units and target in units:
        new_kind = 6
    elif imps and target in imps:
        new_kind = 3
    else:
        return False
    return (cur_kind == 6) == (new_kind == 6)


def _hold_production_candidates(cands: list, obs: dict, type_names: dict | None) -> list:
    """Правило владельца §13.196 в ОБЩЕМ пути: запущенное производство идёт до конца.

    Почему здесь, а не только в прогнозе: измерено §13.205 — на пути без прогноза
    постановка менялась КАЖДЫЙ ход (`Granary ↔ Hanging Gardens`), потому что правило
    удержания жило лишь в одном решателе. Решение владельца: смена — только по
    исключительному поводу, иначе начатое доводится до конца.

    Текущее имя читается по РОДУ (`production_kind` + `production_value`), как читает
    встроенный ИИ (`daicity.c:1868/1915/1996`); таблица имён — общая, из
    `_production_names`. Если текущего предмета в предложении нет вовсе, город не
    фильтруется: иначе он остался бы без постановки вообще.
    """
    cities = (obs or {}).get("city") if isinstance(obs, dict) else None
    if not isinstance(cities, dict) or not cities or not type_names:
        return cands
    now: dict[str, str] = {}
    for cid, city in cities.items():
        if not isinstance(city, dict):
            continue
        try:
            name = (type_names or {}).get(int(city.get("production_value")))
        except (TypeError, ValueError):
            name = None
        if name:
            now[str(city.get("id", cid))] = str(name)
    if not now:
        return cands
    # Что город реально держит и что ему вообще предлагают сменить.
    offered_now: set[str] = set()
    for c in cands:
        action = _to_action(c)
        if action and str(action[0]) == "city" and str(action[2]).startswith("produce_"):
            offered_now.add(f"{action[1]}|{str(action[2])[len('produce_'):]}")
    held = {f"{cid}|{name}" for cid, name in now.items()}
    if os.environ.get("DOF_HOLD_DEBUG") == "1":
        # §13.655: печатаем, ЧТО правило видело. Без этого «отброшено 0» не отличает
        # «нечего фильтровать» от «предложение дошло пустым» (§13.618).
        print(f"  [удержание] держат {len(now)}, предложено смен {len(offered_now)}, "
              f"пар {len(held)}", flush=True)
    keep: list = []
    for c in cands:
        action = _to_action(c)
        if action is None:
            keep.append(c)
            continue
        ctrl, actor, name = action
        if ctrl != "city" or not str(name).startswith("produce_"):
            keep.append(c)
            continue
        want = f"{actor}|{str(name)[len('produce_'):]}"
        cur = now.get(str(actor))
        if cur is None or want in held or f"{actor}|{cur}" not in offered_now:
            keep.append(c)
            continue
        # §13.523: смена ВНУТРИ класса бесплатна — её запрещать нечего.
        if os.environ.get("DOF_HOLD_CLASS_ONLY", "1") != "0" and _same_class(
                cities, actor, str(name)[len("produce_"):]):
            keep.append(c)
            continue
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            # §13.477: прибор — почему кандидат на смену производства НЕ проходит фильтр.
            _key = f"держит «{cur}»"
            _PORDFILT[_key] = _PORDFILT.get(_key, 0) + 1
            if "Workers" in want:
                _k2 = "из них рабочих: " + _key
                _PORDFILT[_k2] = _PORDFILT.get(_k2, 0) + 1
    if os.environ.get("DOF_WORK_DEBUG") == "1" and _PORDFILT:
        print(f"  [фильтр-заказов] {_PORDFILT}", flush=True)
    return keep


def _hold_military_candidates(cands: list, obs: dict, my_id, military: set,
                              type_names: dict | None) -> list:
    """Нужда в войске — правило встроенного ИИ в ОБЩЕМ пути (§13.207).

    Замер, по которому это понадобилось: путь без прогноза строил 8–16 военных при
    населении 2–4, тогда как путь с прогнозом — 0, и разница была не в мире, а в том,
    что правило нужды жило только в прогнозе (§13.207).

    Правило то же самое и теми же чистыми функциями, что у прогноза
    (`brain/ai_default/military.py`): опасность = чужие, СПОСОБНЫЕ напасть и ДОЙТИ
    (`daimilitary.c:77`), защитник нужен при опасности и отсутствии защиты
    (`daicity.c:649/658`), и ровно столько, сколько покрывает опасность. Безвестные
    чужие считаются средним по известным (`spec_threat.mean_attack`), не нулём.
    """
    if not military:
        return cands
    city_fields = (obs or {}).get("city") if isinstance(obs, dict) else None
    if not isinstance(city_fields, dict) or not city_fields:
        return cands
    units = (obs or {}).get("unit") if isinstance(obs, dict) else None
    units = units if isinstance(units, dict) else {}
    try:
        from brain.ai_default import military as _ai_mil
        from env import spec_threat as _threat
    except Exception:  # noqa: BLE001
        return cands

    passports: dict[tuple[int, int], dict] = {}
    own_by_tile: dict[tuple[int, int], int] = {}
    for rec in units.values():
        if not isinstance(rec, dict) or rec.get("x") is None:
            continue
        tile = (int(rec.get("x")), int(rec.get("y")))
        passports[tile] = rec
        try:
            if int(rec.get("owner", my_id)) == int(my_id):
                own_by_tile[tile] = own_by_tile.get(tile, 0) + 1
        except (TypeError, ValueError):
            continue
    mean_att, _n = _threat.mean_attack(obs, my_id)
    mean_move, _m = _threat.mean_move_rate(obs, my_id)
    fill_attack = float(mean_att) if mean_att is not None else 1.0
    fill_move = float(mean_move) if mean_move is not None else 0.0

    have_military = 0
    for rec in units.values():
        if not isinstance(rec, dict):
            continue
        name = (rec.get("type_rule_name")
                or (type_names or {}).get(int(_num(rec.get("type"), -1))))
        if name and str(name) in military:
            have_military += 1

    need: dict[str, bool] = {}
    for cid, city in city_fields.items():
        if not isinstance(city, dict) or city.get("x") is None:
            continue
        cx, cy = int(city.get("x")), int(city.get("y"))
        threats = []
        # §13.421: та же ЕГО проверка опасности и здесь (`adv_is_player_dangerous`): без неё
        # угрозой считался любой видимый чужой юнит, и постановка уходила в военных.
        try:
            from env.diplomacy_from_save import dangerous_now as _dangerous_now2
            _allowed2 = _dangerous_now2(int(my_id))
        except Exception:  # noqa: BLE001
            _allowed2 = None
        for _owner, ux, uy in _threat.foreign_units_from_map(obs, my_id):
            if _allowed2 is not None and int(_num(_owner, -1)) not in _allowed2:
                continue
            rec = passports.get((int(ux), int(uy))) or {}
            threats.append(_ai_mil.Threat(
                attack_strength=_num(rec.get("type_attack_strength"), fill_attack),
                hp=_num(rec.get("type_hp"), 1.0),
                firepower=_num(rec.get("type_firepower"), 1.0),
                move_rate=_num(rec.get("type_move_rate"), fill_move),
                distance=int(max(abs(int(ux) - cx), abs(int(uy) - cy)))))
        danger = _ai_mil.city_danger(threats)
        wanted = _ai_mil.defenders_wanted(danger)
        need[str(city.get("id", cid))] = (_ai_mil.needs_defender(danger, own_by_tile.get((cx, cy), 0))
                                          and have_military < wanted)
    keep: list = []
    for c in cands:
        action = _to_action(c)
        if action is None:
            keep.append(c)
            continue
        ctrl, actor, name = action
        if (ctrl != "city" or not str(name).startswith("produce_")
                or str(name)[len("produce_"):] not in military
                or need.get(str(actor), True)):
            keep.append(c)
    return keep


def _his_danger(obs: dict, extractor) -> float:
    """Опасность города в его смысле: чужой юнит, видимый нами. Нет чужого — 0."""
    try:
        _units = getattr(extractor, "units", None) or {}
        _mine = getattr(extractor, "my_player_id", None)
        for _u in _units.values():
            _owner = _u.get("owner") if isinstance(_u, dict) else None
            if _owner is not None and _mine is not None and str(_owner) != str(_mine):
                return 1.0
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _city_defenders(env_getter, cid):
    """Число ЗАЩИТНИКОВ города — у контроллера, по городу-владельцу юнита (§13.438/§13.465).

    Возвращает None, если данных нет: «не знаю» отличается от нуля, и условие его вызова тогда не
    срабатывает — незнание не запрещает.
    """
    try:
        _ctl = getattr(getattr(env_getter(), "unwrapped", None), "civ_controller", None)
        _units = getattr(getattr(_ctl, "unit_ctrl", None), "units", None)
        if not isinstance(_units, dict) or cid is None:
            return None
        return sum(1 for _u in _units.values()
                   if isinstance(_u, dict) and str(_u.get("homecity", -1)) == str(cid))
    except Exception:  # noqa: BLE001
        return None


def _his_production_want(name: str, rec: dict, ctx, danger: float,
                         defenders: float | None = None,
                         urgency: float | None = None):
    """Хотелка его советников для этого имени производства (§13.366)."""
    try:
        from brain.ai_default import military_want as _mw
        _military = getattr(ctx, "military_names", None)
        if _military and str(name) in set(_military):
            _spec = getattr(ctx, "unit_spec", None)
            _stats = {}
            try:
                _stats = _spec(str(name)) or {} if callable(_spec) else {}
            except Exception:  # noqa: BLE001
                _stats = {}
            # §13.465: его УСЛОВИЕ ВЫЗОВА (`ai/default/daimilitary.c:1907-1925`) — защитник
            # рассматривается, только если `danger > 0` И `num_defenders <= urgency` (защитников
            # меньше, чем требует опасность). Если число защитников получить не удалось — «не знаю»,
            # и поведение прежнее, а не запрет: незнание не запрещает.
            _def = defenders
            if _def is None:
                # «Не знаю» и «ноль защитников» — РАЗНОЕ: если контроллера в контексте нет, число
                # неизвестно (None) и условие не срабатывает; ноль считается только тогда, когда
                # список юнитов действительно доступен, и в нём нет защитников этого города.
                try:
                    _ctl = getattr(ctx, "ctl", None)
                    _units = getattr(getattr(_ctl, "unit_ctrl", None), "units", None)
                    _cid = rec.get("id") if isinstance(rec, dict) else None
                    if _ctl is not None and isinstance(_units, dict) and _cid is not None:
                        _def = sum(1 for _u in _units.values()
                                   if isinstance(_u, dict)
                                   and str(_u.get("homecity", -1)) == str(_cid))
                except Exception:  # noqa: BLE001
                    _def = None
            _urg = urgency
            if _def is not None:
                if _urg is None:
                    try:
                        from brain.ai_default.military import defenders_wanted as _dw
                        _urg = float(_dw(danger))
                    except Exception:  # noqa: BLE001
                        _urg = None
                if _urg is not None and not (float(danger or 0.0) > 0.0
                                             and float(_def) <= float(_urg)):
                    return 0.0
            # Защитные роли берём из мира, если он их отдаёт; без роли желание 0 — как у него
            # для юнита без `L_DEFEND_GOOD`/`L_DEFEND_OK` (`daimilitary.c:1078-1081`).
            # §13.522: второе его условие (`ai/default/daimilitary.c:1907-1925`) — защитник
            # рассматривается только при `danger > 0` (вторая половина условия, `martial_value > 0`,
            # относится к наступающим юнитам, а роль наступающего мир не отдаёт). Без этого порога
            # мирный город с нулевой опасностью всё равно получал 4.5625 и перебивал поселенца.
            if float(danger or 0.0) <= 0.0 and os.environ.get("DOF_MIL_GATE") != "0":
                return 0.0
            _want = _mw.city_military_want(dict(_stats), danger, defend_good=False)
            # Слабый защитник (`defense_strength == 1`) при `urgency == 0`: желание ограничено
            # сверху — `MIN(49, danger)` при лечении в городе, иначе `MIN(25, danger)`.
            try:
                if _urg == 0 and float(_stats.get("defense_strength") or 0) == 1.0:
                    _cap = 49.0 if float(getattr(ctx, "hp_regen", 0.0) or 0.0) > 0.0 else 25.0
                    _want = min(_cap, float(danger or 0.0))
            except Exception:  # noqa: BLE001
                pass
            return _want
        _mw_name = str(name)
        if _mw_name in ("Settlers", "Founder", "Found city"):
            _fw = getattr(ctx, "founder_want", None)
            if callable(_fw):
                _w, _ = _fw(rec)
                return float(_w)
        if _mw_name in ("Workers", "Engineers"):
            _ww = getattr(ctx, "worker_want", None)
            if callable(_ww):
                _w, _ = _ww(rec)
                return float(_w)
    except Exception:  # noqa: BLE001
        return None
    return None


def _filters_trace() -> bool:
    """Включён ли след общих правил (§13.209)."""
    return os.environ.get("DOF_TRACE_FILTERS") == "1"


def _spec_at(table, idx):
    """Запись таблицы правил по номеру: она может быть и списком, и словарём.

    Измерено косвенно: чтение через `.get(idx)` на СПИСКЕ даёт AttributeError, исключение
    глоталось, и маска мира выглядела «отсутствующей» на каждом городе — то есть здоровый
    путь молча превращался в отказ от постановки.
    """
    if table is None:
        return None
    try:
        return table[idx]
    except (KeyError, IndexError, TypeError):
        return None


def _all_production_names(env_getter) -> set:
    """ВСЕ имена производства по правилам мира — юниты и постройки. Без запроса у мира."""
    out: set = set()
    try:
        rules = env_getter()
    except Exception:  # noqa: BLE001
        return out
    for _tbl in (getattr(rules, "unit_types", None), getattr(rules, "improvements", None)):
        if isinstance(_tbl, dict):
            _items = _tbl.values()
        elif isinstance(_tbl, (list, tuple)):
            _items = _tbl
        else:
            continue
        for _spec in _items:
            _nm = _spec.get("name") if isinstance(_spec, dict) else None
            if _nm:
                out.add(str(_nm))
    return out


def _world_production_names(env_getter, cid):
    """Маска постановки ИЗ МИРА: сырая запись города стенда и его же правила.

    Измерено (§13.215): в наблюдение стенда маска УЛУЧШЕНИЙ не попадает, поэтому наша картина
    города её не знает и кандидаты падали на весь каталог имён — мы предлагали городу
    `Marketplace`, `Library`, `Factory`, которых в его маске нет, стенд отвечал
    `Action produce_X of N is not valid`, приказ не применялся, а повтор не двигал матч
    (клин по общему таймауту). Маска при этом в мире ЕСТЬ (пакет 256) и стенд сам по ней
    проверяет приказ — значит брать её надо оттуда же, откуда берут её действия стенда.

    Возвращает множество имён того, что город может строить СЕЙЧАС (уже построенное
    исключено — стенд отказывает и в этом), или None, если мира под рукой нет: «незнание ≠
    запрет», тогда решение принимает цена по всему каталогу.
    """
    if env_getter is None or cid is None:
        return None
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        ccity = getattr(ctl, "city_ctrl", None)
        rules = getattr(ctl, "rule_ctrl", None)
        if ccity is None:
            return None
        rec = (getattr(ccity, "cities", {}) or {}).get(int(cid))
        if not isinstance(rec, dict):
            return None
        # `X or []` здесь нельзя: `improvements` — массив numpy, и `bool()` на нём срывается
        # («The truth value of an array with more than one element is ambiguous»). Именно это
        # и скрывало маску мира: исключение глоталось, и каждый город выглядел как «маски нет».
        held = rec.get("improvements")
        if held is None:
            held = []
        out: set[str] = set()
        for field, table in (("can_build_improvement", getattr(rules, "improvements", None)),
                             ("can_build_unit", getattr(rules, "unit_types", None))):
            mask = rec.get(field)
            if mask is None:
                continue
            # Маска приходит массивом numpy (`city_ctrl.handle_web_city_info_addition`
            # делает `np.array(byte_to_bit_array(...))`), и проверка «истинности» прямо на
            # элементе срывается: измерено — `ValueError: The truth value of an array with
            # more than one element is ambiguous`. Приводим к числу явно.
            if isinstance(mask, dict):
                pairs = list(mask.items())
            else:
                base = mask.ravel() if hasattr(mask, "ravel") else mask
                pairs = list(enumerate(base))
            for idx, flag in pairs:
                try:
                    if int(flag) == 0:
                        continue
                except (TypeError, ValueError):
                    continue
                if field == "can_build_improvement" and idx < len(held) and held[idx] == 1:
                    continue        # в городе уже есть — стенд такую постановку отвергает
                info = _spec_at(table, idx)
                name = (info or {}).get("name") if isinstance(info, dict) else None
                if name:
                    out.add(str(name))
        return out or None
    except Exception as exc:  # noqa: BLE001
        # Молчаливое «нет маски» уже один раз скрыло ошибку пути (измерено: «маски мира нет»
        # на каждом городе). Причину печатаем, чтобы это не повторялось незаметно.
        if _filters_trace():
            import traceback as _tb
            where = _tb.extract_tb(exc.__traceback__)[-1]
            print(f"  [постановка] маска мира не прочитана: {type(exc).__name__}: {exc} "
                  f"(строка {where.lineno}: {where.line})", flush=True)
        return None


def _my_units_classes(env_getter, my_id):
    """Классы и флаги НАШИХ юнитов — из мира (его правила плюс его же записи юнитов).

    Нужны военным семьям его оценки (`num_affected_units`, `daieffects.c:120`): постройка
    `Barracks` ценна ровно тем, что действует на наших наземных НЕневоенных. В нашем
    наблюдении ни класса, ни флагов нет, поэтому берём их там же, где их берёт стенд:
    `rule_ctrl.unit_types[id]['class']` → `rule_ctrl.unit_classes[id]`, плюс собственные
    флаги типа (именно по ним различается `NonMil`).
    """
    if env_getter is None:
        return ()
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        rules = getattr(ctl, "rule_ctrl", None)
        units = getattr(getattr(ctl, "unit_ctrl", None), "units", None) or {}
        classes = getattr(rules, "unit_classes", None) or {}
        utypes = getattr(rules, "unit_types", None) or {}
        out = []
        for _uid, unit in (units.items() if isinstance(units, dict) else ()):
            if not isinstance(unit, dict):
                continue
            owner = unit.get("owner")
            if my_id is not None and owner is not None and int(owner) != int(my_id):
                continue
            spec = utypes.get(unit.get("type")) if isinstance(utypes, dict) else None
            spec = spec if isinstance(spec, dict) else {}
            cls = classes.get(spec.get("class")) if isinstance(classes, dict) else None
            cls = cls if isinstance(cls, dict) else {}
            cls_name = str(cls.get("name") or "").split(":")[-1]
            flags: list[str] = []
            for source in (spec.get("flags"), cls.get("flags")):
                if isinstance(source, (list, tuple, set)):
                    flags.extend(str(f).split(":")[-1] for f in source)
            out.append((cls_name, tuple(flags)))
        return tuple(out)
    except Exception as exc:  # noqa: BLE001
        if _filters_trace():
            print(f"  [постановка] классы юнитов не прочитаны: {type(exc).__name__}: {exc}",
                  flush=True)
        return ()


#: Последний собранный контекст прогноза: в нём живёт дверь его чисел для клеток.
#: §13.336: «что город строит и с каким запасом щитов» — по городам. Пока запас растёт,
#: предмет держим и приказа не шлём (его правило), заново решаем только после завершения.
_LAST_PROD: dict = {}
#: §13.664 — ход, в который мы в последний раз отправили городу заказ производства.
#: Нужен, чтобы не повторять заказ: повтор стенд считает сменой предмета и списывает
#: накопленные щиты (§13.663 — город с 19 заказами не накопил ничего).
_LAST_ORDER_TURN: dict = {}
#: §13.348: ЦЕЛЬ поселенца — как его миссия `AIUNIT_BUILD_CITY` (`daisettler.c:1029-1054`):
#: он ставит поселенцу задачу с клеткой-целью и ведёт его туда, пока цель годна, и только по
#: прибытии основывает город. У нас цель пересчитывалась КАЖДЫЙ ход, а внутри цены площадки
#: сидит дорога (`amortize(total, PERFECTION*turns)`), поэтому «лучшая» переезжала на соседнюю
#: клетку и обратно: поселенец качался между двумя и не основывал вовсе (измерено §13.347).
_FOUND_TARGET: dict = {}
#: §13.395: сколько раз подряд шаг к удерживаемой цели не нашёлся. Цель бросаем не сразу:
#: сброс цели из-за одного недоступного шага и давал качание поселенцев (§13.394).
_FOUND_FAIL: dict = {}
#: §13.402: площадки, где мир ОТКАЗАЛ в основании этому поселенцу (`основать_здесь=False`).
#: Без этого поселенец приходил на отказную клетку, цель снималась, он выбирал её снова и
#: стоял (замер r790: 14–16 повторов на паре клеток, оснований за 45 ходов — ни одного роста).
_FOUND_BLACK: dict = {}

#: §13.339: проба «действует ли путь `ctrl_type=city` в этом стенде». Помним, какой ход по
#: клетке заказан и какими были выходы города; на следующем появлении города сравниваем.
_LAST_TILE_SENT: dict = {}

#: Ставится `_production_candidate` каждый ход и читается выбором без DoF.
_LAST_CTX = None
#: Наблюдение текущего решения — для оценки клеток города по правилам мира (§13.292).
_LAST_OBS = None


#: Работы клетки, которые выбирает ПЕРЕНОСЁННОЕ правило встроенного ИИ (13.288, 13.297).
#: Дороги включены после проверки связки процента по правилам (terrain.ruleset:119).
_PORT_WORK_NAMES = ("mine", "irrigation", "road", "build_road", "railroad", "build_railroad")


def _city_tile_diag(why: str) -> None:
    """Почему оценка клеток города по правилам промолчала — молчание обязано быть отличимо."""
    if os.environ.get("DOF_TILE_DEBUG") == "1":
        print(f"  [клетка-правила] молчит: {why}", flush=True)


def _land_work_want(obs: dict, map_obs: dict, offered: dict, pos) -> float:
    """ЕГО `best_impr` поселенца: лучшая работа, доступная ему СЕЙЧАС (`autoworkers.c:439`).

    Работы берутся из предложения мира (`build_road`, `mine`, `irrigation`, …) — то, что он может
    сделать на своей клетке немедленно. У него это обход всего радиуса города с маршрутизатором и
    оценкой `city_tile_value`; здесь — подмножество (та же арифметика, меньше охват; сказано
    в `brain/ai_default/worker_want.py`).
    """
    try:
        from brain.ai_default.tile_outputs import tile_outputs_from_rules
        from brain.ai_default.worker_want import best_improvement_want, tile_value
        from env.terrain_work import WORK_ACTION_EXTRA, tile_effect, tile_terrain_extras
        from env.terrain_work_times import TERRAIN_WORK_TIMES
    except Exception:  # noqa: BLE001
        return 0.0
    try:
        terrain, extras = tile_terrain_extras(map_obs, pos[0], pos[1])
    except Exception:  # noqa: BLE001
        return 0.0
    cur = tile_outputs_from_rules(terrain, extras)
    if cur is None:
        return 0.0
    _times = TERRAIN_WORK_TIMES.get(str(terrain).lower(), {}) or {}
    entries: list[tuple[float, float, int]] = []
    _vals: dict = {}
    for name, params in (as_dict(offered) or {}).items():
        if not truthy(params):
            continue
        _nm = str(name)
        extra = WORK_ACTION_EXTRA.get(_nm)
        if extra is None:
            continue            # смена террейна (`cultivate`) не оценена — не выдумываем
        delta = tile_effect(extra, terrain, extras, _vals)
        if delta is None:
            continue            # «не знаем» — не подставляем ноль как знание
        after = (float(cur[0]) + float(delta[0]), float(cur[1]) + float(delta[1]),
                 float(cur[2]) + float(delta[2]))
        _key = "road" if _nm == "build_road" else _nm
        delay = int(_times.get(_key) or 1)      # нет числа — 1 ход, наименьшее известное
        entries.append((tile_value(*cur), tile_value(*after), delay))
    return best_improvement_want(entries)


def _controller_cities(env_getter) -> dict:
    """СВОИ ГОРОДА ИЗ КОНТРОЛЛЕРА полными записями — второй канал (§13.357, §13.369)."""
    if env_getter is None:
        return {}
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        _cities = getattr(getattr(ctl, "city_ctrl", None), "cities", None)
        if not isinstance(_cities, dict):
            return {}
        return {str(k): (dict(v) if isinstance(v, dict) else v) for k, v in _cities.items()}
    except Exception:  # noqa: BLE001
        return {}


def _our_cities_from_controller(env_getter, obs: dict) -> set[tuple[int, int]]:
    """СВОИ ГОРОДА ИЗ КОНТРОЛЛЕРА (`city_ctrl.cities`) — второй канал, как у позиций юнитов §13.348.

    Зачем. Слой городов наблюдения бывает пуст в начале хода, и тогда проверки по городам
    (`citymindist`, отмена негодной цели, резерв мест) немы: измерено — 0 городов на всех замерах
    короткого прогона при живой столице. Контроллер — тот же мир, но его собственный канал.

    Индекс клетки переводится в координаты по форме карты: `index = x + y * xsize` (X — цилиндр),
    ровно как в `brain/forecast/live.py:117`. Свой `x`/`y` в записи, если он там есть, важнее индекса.
    """
    if env_getter is None:
        return set()
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        cities = getattr(getattr(ctl, "city_ctrl", None), "cities", None)
        if not isinstance(cities, dict) or not cities:
            return set()
        map_obs = as_dict((as_dict(obs) or {}).get("map")) or {}
        shape = getattr(map_obs.get("output"), "shape", None)
        w = int(shape[0]) if shape is not None and len(shape) >= 1 else 0
        out: set[tuple[int, int]] = set()
        for _cid, rec in cities.items():
            if not isinstance(rec, dict):
                continue
            try:
                if int(rec.get("owner", -1)) != 0:
                    continue            # чужие города — из наблюдения (мы видим их отдельно)
            except (TypeError, ValueError):
                continue
            x, y = rec.get("x"), rec.get("y")
            if x is None or y is None:
                idx = rec.get("tile")
                if idx is None or w <= 0:
                    continue
                x, y = int(idx) % w, int(idx) // w
            out.add((int(x), int(y)))
        return out
    except Exception:  # noqa: BLE001
        return set()


def _client_send_command(env_getter, command: str) -> bool:
    """Послать команду серверу каналом КЛИЕНТА (`ws_client.send_message`) — §13.372."""
    try:
        env = env_getter() if env_getter else None
        if env is None:
            return False
        objs = [env, getattr(env, "unwrapped", None)]
        for obj in list(objs):
            if obj is None:
                continue
            ctl = getattr(obj, "civ_controller", None)
            ws = getattr(obj, "ws_client", None) or getattr(ctl, "ws_client", None)
            send = getattr(ws, "send_message", None)
            if callable(send):
                send(command)
                print(f"  [команда-клиенту] {command!r} отправлена", flush=True)
                return True
    except Exception as _exc:  # noqa: BLE001
        print(f"  [команда-клиенту] не вышло: {type(_exc).__name__}: {_exc}", flush=True)
    print(f"  [команда-клиенту] клиент не найден для {command!r}", flush=True)
    return False


def _save_and_dump_cities(env_getter, username):
    """§13.375: читать ХОДОВОЙ сейв всю партию и печатать запись города как есть."""
    try:
        from env import city_from_save as _cfs
        from env.map_from_save import fetch_newest_save as _fetch
        _st = globals().setdefault("_CITY_SAVE_PROBE", {"tries": 0, "printed": False})
        _st["tries"] += 1
        if _st["tries"] > 200:
            return
        if env_getter and _st["tries"] % 4 == 1:
            try:
                _client_send_command(env_getter, "/save dofsave1")
            except Exception:  # noqa: BLE001
                pass
        text = _fetch(str(username))
        if not text:
            if _st["tries"] % 8 == 1:
                print(f"  [города-сейв] попытка {_st['tries']}: сейва ещё нет", flush=True)
            return
        sections = _cfs.city_sections(text)
        if _st["tries"] % 6 == 1 or (sections and not _st["printed"]):
            print(f"  [города-сейв] попытка {_st['tries']}: разделов городов {len(sections)}",
                  flush=True)
        if True:  # §13.376: перезаписываем ВСЕГДА — нужен самый поздний ходовой сейв
            try:
                with open("/tmp/dof_last_save.txt", "w", encoding="utf-8") as _f:
                    _f.write(text)
                _st["saved_text"] = True
                print(f"  [города-сейв] текст сейва сохранён: {len(text)} знаков", flush=True)
            except Exception:  # noqa: BLE001
                pass
        if not _st.get("raw") and text:
            _st["raw"] = True
            print("  [оглавление-сейва]", flush=True)
            print(_cfs.dump_structure(text), flush=True)
            print("  [раздел игрока]", flush=True)
            print(_cfs.dump_player_section(text, 70), flush=True)
        if sections and not _st["printed"]:
            _st["printed"] = True
            print("  [города-сейв] первая запись города:", flush=True)
            print({k: v for k, v in list(sections[0].items())[:30]}, flush=True)
    except Exception as _exc:  # noqa: BLE001
        print(f"  [города-сейв] проба упала: {type(_exc).__name__}: {_exc}", flush=True)
def _city_channels_probe(obs, avail, env_getter, extractor=None):
    """Прибор §13.369: что видно по городам в КАЖДОМ канале (наблюдение / контроллер / маски)."""
    try:
        _st = globals().setdefault("_CITY_CH_PROBE", {"n": 0})
        _st["n"] += 1
        if _st["n"] > 8:
            return
        _obs_city = (as_dict((as_dict(obs) or {}).get("city")) or {})
        _ctl_city = _controller_cities(env_getter)
        _avail_city = {}
        if isinstance(avail, dict):
            for _ctrl, _actors in avail.items():
                if str(_ctrl) in ("city", "city_ctrl") and isinstance(_actors, dict):
                    _avail_city[str(_ctrl)] = sum(len(a) if isinstance(a, dict) else 0
                                for a in _actors.values())
        _masks = []
        for _cid, _rec in list(_obs_city.items())[:3]:
            if not isinstance(_rec, dict):
                continue
            _m = []
            for _f in ("can_build_unit", "can_build_improvement"):
                _v = _rec.get(_f)
                if _v is None:
                    _m.append(_f.split("_")[-1] + "=нет")
                else:
                    try:
                        _m.append(_f.split("_")[-1] + f"={int(sum(1 for x in list(_v) if int(x) != 0))}")
                    except Exception:  # noqa: BLE001
                        _m.append(_f.split("_")[-1] + "=?")
            _masks.append(f"{_cid}({','.join(_m)})")
        print(f"  [каналы] ход-вызов {_st['n']}: наблюдение {len(_obs_city)} "
              f"{[str(k) for k in list(_obs_city)[:3]]}, контроллер {len(_ctl_city)} "
              f"{[str(k) for k in list(_ctl_city)[:3]]}, действия города {_avail_city}, "
              f"маски {_masks}", flush=True)
    except Exception as _exc:  # noqa: BLE001
        print(f"  [каналы] проба упала: {type(_exc).__name__}: {_exc}", flush=True)


def _maybe_learn_map_from_save(turn, every=10):
    """§13.363: наполнить память о карте сейвом сервера — то, что видит его `omniscience`."""
    try:
        from env import map_from_save as _mfs
        _name = str(fc_args.get("username") or "")
        if not _name:
            return None
        _state = globals().setdefault("_MAP_SAVE_STATE", {})
        _last = _state.get("turn")
        if _last is not None and turn is not None and int(turn) - int(_last) < int(every):
            return None
        _state["turn"] = turn
        _n = _mfs.load_from_save(_name)
        if _n:
            print(f"  [карта-сейв] память наполнена сейвом: известных клеток {_n}", flush=True)
        else:
            print("  [карта-сейв] сейва нет или пуст — оставляю память как есть", flush=True)
        return _n
    except Exception as _exc:  # noqa: BLE001
        print(f"  [карта-сейв] проба упала: {type(_exc).__name__}: {_exc}", flush=True)
        return None


def _mem_tiles(obs) -> int:
    """§13.407: сколько клеток карты мы знаем (память мира: сейв + наблюдение).

    Нужно, чтобы отличить «карта пуста» от «видно только ближний круг»: у ЕГО ИИ зрение полное
    (`omniscience = !has_handicap(H_MAP)`), у нас обзор идёт из наблюдения.
    """
    try:
        from env.world_memory import known as _known
        return len(_known())
    except Exception:  # noqa: BLE001
        return -1


def _founder_step(obs: dict, avail: dict, mindist: int | None = None, env_getter=None):
    """Поселенец идёт к лучшей площадке по ЕГО числам, а не основывает где стоит (§13.306).

    Возвращает `("unit", id, имя_шага)` или None. Вмешивается ТОЛЬКО тогда, когда поселенец
    стоит на площадке, которую его же правило считает голодной (`food_starvation`), и есть
    куда идти: город, основанный на такой площадке, умирает от голода на 2-м ходу, а сторона
    выбывает (измерено §13.305: «Famine destroys … entirely», `разбит=True`).

    Если идти некуда или мир не предлагает ни одного приближающего шага — НЕ мешаем: лучше
    город на плохой площадке, чем поселенец, который никогда не основывает.
    """
    unit_actions = as_dict(as_dict(avail).get("unit")) or {}
    if not unit_actions:
        return None
    # §13.351: ПРИБОР — принудительный шаг поселенца каждый ход (`DOF_FORCE_STEP=goto_4`).
    # Отделяет «наш ВЫБОР шага неверен» от «шаг не исполняется миром вовсе»: приказ один и
    # тот же, и по дампу видно, движется ли юнит. Не норматив, только измерение.
    _forced = os.environ.get("DOF_FORCE_STEP")
    if _forced:
        for _uid, _acts in unit_actions.items():
            _off = as_dict(_acts) or {}
            if not [n for n, p_ in _off.items()
                    if str(n).startswith(("build_city", "found_city")) and truthy(p_)]:
                continue
            if str(_forced) in {str(n) for n in _off}:
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [шаг-прибор] unit/{_uid}: {_forced}", flush=True)
                return ("unit", _uid, str(_forced))
        return None
    map_obs = as_dict(as_dict(obs).get("map")) or {}
    # §13.350: клетка-назначение шага обязана быть проходимой. Мир ПРЕДЛАГАЕТ шаг в воду,
    # а сам его не выполняет: поселенец 66-72 раза подряд получал один и тот же `goto_N`
    # и не сдвигался ни на клетку (измерено §13.348). Море берём из слоя террейна.
    _sea_words = ("ocean", "sea", "lake", "coast")

    def _blocked_step(x: int, y: int) -> bool:
        try:
            from env.terrain_work import tile_terrain_extras
            _nm, _ex = tile_terrain_extras(map_obs, int(x), int(y))
        except Exception:  # noqa: BLE001
            return False
        _nm = str(_nm).strip().lower().replace(" ", "_")
        return any(w in _nm for w in _sea_words)

    try:
        from brain.ai_default.founder_destination import (
            city_positions, goto_name_to, path_first_step, rank_sites, step_toward,
        )
        from env.food_gate import food_cost_of
        from env.site_eval import evaluate_site
    except Exception:  # noqa: BLE001
        return None
    # ── §13.358: форма карты и проходимость — для поиска ПУТИ (его маршрутизатор, `pf_map`).
    _shape = getattr((as_dict((as_dict(obs) or {}).get("map")) or {}).get("output"),
                     "shape", None)
    _passable = lambda _x, _y: not _blocked_step(_x, _y)   # noqa: E731
    # ── §13.353: МИНИМАЛЬНОЕ РАССТОЯНИЕ МЕЖДУ ГОРОДАМИ — из мира (считает вызывающий,
    # у него есть доступ к контроллеру). Мир отказывает в основании, если ближе `citymindist`
    # (`common/city.c:1445`), а наша оценка площадки этого не знала: поселенцы сгруживались,
    # каждый считал свою клетку лучшей, и город не появлялся.
    _mindist = int(mindist or 0)
    _mindist_src = "живое" if _mindist > 0 else "запасное"
    if _mindist <= 0:
        try:
            from env.rules_costs import CITYMINDIST_FALLBACK
            _mindist = int(CITYMINDIST_FALLBACK)
        except Exception:  # noqa: BLE001
            _mindist = 0
            _mindist_src = "неизвестно"
    # §13.357: два канала — наблюдение И контроллер. Слой наблюдения бывает пуст в начале хода.
    # §13.412: к известным городам добавляем площадки, где МЫ САМИ основали город в этой партии.
    # Замер r915: после основания на (9,11) другие поселенцы ещё 33 раза приходили в тот же
    # район и получали отказ — наш список городов от клиента отстаёт от мира, и ранжирование
    # предлагало клетки рядом с уже поставленным городом.
    _known_cities = (set(city_positions(obs)) | _our_cities_from_controller(env_getter, obs)
                     | set(globals().get("_FOUNDED_SITES") or set())
                     # §13.437: ГЛАВНОЕ — города из СЕЙВА по всем сторонам. Замер s1355 показал
                     # прямо: `[citymindist] 2 (источник: живое), городов известно 0` — наш список
                     # городов был ПУСТ (клиент отдаёт его с задержкой, контроллер тоже), поэтому
                     # проверка `citymindist_blocks` не отсекала НИЧЕГО и поселенцы шли на клетки
                     # вплотную к уже стоящему городу — а мир там основание запрещает (30 отказов,
                     # ни одного основания за партию). Мир считает `citymindist` по ВСЕМ городам
                     # карты, а не по нашим, поэтому берём все стороны.
                     | set(globals().get("_SAVE_CITIES") or set()))
    if os.environ.get("DOF_FOUND_DEBUG") == "1":
        _seen_turn = globals().setdefault("_MAP_LAYERS_SEEN", set())
        _seen_cnt = globals().setdefault("_MAP_LAYERS_CALLS", [0])
        _seen_cnt[0] += 1
        if _seen_cnt[0] <= 6:
            _mobs = as_dict((as_dict(obs) or {}).get("map")) or {}
            _info = {k: (type(v).__name__, getattr(v, "shape", len(v) if hasattr(v, "__len__") else "-"))
                     for k, v in list(_mobs.items())}
            from brain.forecast.live import revealed_tiles as _rv
            print(f"  [слои-карты] {sorted(_mobs.keys())}", flush=True)
            print(f"  [слои-карты] формы: {_info}", flush=True)
            _stat = _mobs.get("status")
            _st = _stat.tolist() if hasattr(_stat, "tolist") else _stat
            _known = (sum(1 for _col in _st for _v in _col if float(_v) >= 1.0)
                      if isinstance(_st, (list, tuple)) and _st else 0)
            _cs = sorted(_known_cities)[:1]
            _cx, _cy = (_cs[0] if _cs else (-1, -1))
            _sw = ""
            if _cs:
                try:
                    _sw = (f"status[x][y]={_st[_cx][_cy]}, status[y][x]={_st[_cy][_cx]}")
                except Exception as _e:  # noqa: BLE001
                    _sw = f"сверка упала: {type(_e).__name__}"
            _ter = _mobs.get("terrain")
            _tl = _ter.tolist() if hasattr(_ter, "tolist") else _ter
            _tvals = {}
            if isinstance(_tl, (list, tuple)) and _tl:
                for _col in _tl:
                    if not isinstance(_col, (list, tuple)):
                        continue
                    for _v in _col:
                        _tvals[_v] = _tvals.get(_v, 0) + 1
            _top = sorted(_tvals.items(), key=lambda kv: -kv[1])[:6]
            print(f"  [слои-карты] террейн: разные значения {len(_tvals)}, частые {_top}", flush=True)
            from env.world_memory import CALLS as _mcall, known as _mknown
            # §13.362: распределение состояния клеток (0 вне обзора, 1 известно-невидимо, 2 видно) —
            # показывает, отдаёт ли СЕРВЕР всю карту и что именно теряет клиент.
            try:
                _cnt = {0: 0, 1: 0, 2: 0, -1: 0}
                _ter_ok = {1: 0, 2: 0}
                for _x in range(len(_st) if isinstance(_st, (list, tuple)) else 0):
                    for _y in range(len(_st[_x])):
                        try:
                            _k = int(float(_st[_x][_y]))
                        except (TypeError, ValueError):
                            _k = -1
                        _cnt[_k] = _cnt.get(_k, 0) + 1
                        if _k in (1, 2):
                            try:
                                if float(_tl[_x][_y]) != 255:
                                    _ter_ok[_k] += 1
                            except (TypeError, ValueError, IndexError):
                                pass
                print(f"  [состояние клеток] вне обзора {_cnt.get(0, 0)}, известно-невидимо "
                            f"{_cnt.get(1, 0)} (с террейном {_ter_ok[1]}), видно {_cnt.get(2, 0)} "
                            f"(с террейном {_ter_ok[2]}), иных {_cnt.get(-1, 0)}", flush=True)
            except Exception as _exc:  # noqa: BLE001
                print(f"  [состояние клеток] проба упала: {type(_exc).__name__}: {_exc}", flush=True)
            # §13.362: ШТАТНЫЙ путь «игрок видит всю карту»: редактор сервера умеет снять туман
            # конкретному игроку (`server/edithand.c:1312`, посылки 190 «режим редактора» и 199
            # «снять туман игроку» — обе `cs` по `packets.def:2204/2214`). Пробуем каждый ход:
            # первая посылка может не пройти, пока игра не встала.
            if os.environ.get("DOF_REVEAL_MAP") == "1":
                try:
                    _pid_me = env_getter().get_playerid()
                    _ws = getattr(getattr(getattr(env_getter(), "unwrapped", None), "civ_controller", None),
                                 "ws_client", None)
                    if _ws is None:
                        print("  [карта-открыта] канала нет", flush=True)
                    else:
                        for _pkt in ({"pid": 190, "state": True},
                                      {"pid": 199, "player": int(_pid_me)}):
                            try:
                                _ws.send_request(_pkt)
                                print(f"  [карта-открыта] послал {_pkt}", flush=True)
                            except Exception as _exc2:  # noqa: BLE001
                                print(f"  [карта-открыта] {_pkt} упало: {type(_exc2).__name__}: {_exc2}",
                                      flush=True)
                except Exception as _exc:  # noqa: BLE001
                    print(f"  [карта-открыта] проба упала: {type(_exc).__name__}: {_exc}", flush=True)
            print(f"  [слои-карты] видимых сейчас {_mcall.get('live')}, "
                  f"в ПАМЯТИ {len(_mknown())} (по status живого {_known}), "
                  f"раскрытых по выходу {len(_rv(_mobs))}", flush=True)
    if os.environ.get("DOF_FOUND_DEBUG") == "1":
        _cities_raw = as_dict((as_dict(obs) or {}).get("city")) or {}
        _who = {}
        for _cid, _crec in _cities_raw.items():
            _r = as_dict(_crec) or {}
            _own = _r.get("owner")
            _who[_own] = _who.get(_own, 0) + 1
        _ctl_cities = _our_cities_from_controller(env_getter, obs)
        _obs_cities = set(city_positions(obs))
        print(f"  [слой-город] в наблюдении {len(_cities_raw)} городов, по владельцам {_who}; "
              f"наблюдение даёт {sorted(_obs_cities)[:3]}, контроллер {sorted(_ctl_cities)[:3]}, "
              f"всего известных {len(_known_cities)}", flush=True)
    # ── §13.355: ЕГО КАРТА ЗАНЯТОСТИ МЕСТ (`common/aicore/citymap.c`) и уход с задачи
    # основания освобождает место (`daitools.c:665-671`): если поселенца больше нет среди
    # способных действовать (основал город, погиб), его резерв снимается.
    from brain.ai_default.citymap import CityMap
    _cmap = globals().setdefault("_CITY_MAP", CityMap())
    # Освобождение — только когда поселенца НЕТ в наблюдении (основал город или погиб).
    # Проверка «нет в текущем меню» неверна: меню сжимается по ходу (60→48→36→21→10), и
    # резерв снимался у живого поселенца — измерено: пять поселенцев заняли ОДНО (17,14).
    for _key, _gt in list(_FOUND_TARGET.items()):
        _uid_gone = int(_key) if _key.lstrip("-").isdigit() else _key
        if _unit_pos(obs, _uid_gone) is None:
            _FOUND_TARGET.pop(_key, None)
            _cmap.free_city_spot(_gt[0], _gt[1], _uid_gone)
    if os.environ.get("DOF_FOUND_DEBUG") == "1":
        _seen_cm = globals().setdefault("_CM_SEEN", set())
        if _mindist_src not in _seen_cm:
            _seen_cm.add(_mindist_src)
            print(f"  [citymindist] {_mindist} (источник: {_mindist_src}), "
                  f"городов известно {len(_known_cities)}", flush=True)
    # §13.439: имена типов наших юнитов. В наблюдении типа нет (замер s1375: тип=None), поэтому
    # берём у контроллера — там же, где его читает перебор наших юнитов.
    _type_names: dict[str, str] = {}
    if env_getter is not None:
        try:
            _env_t = env_getter()
            _c_t = getattr(getattr(_env_t, "unwrapped", None), "civ_controller", None)
            _uts_t = getattr(getattr(_c_t, "rule_ctrl", None), "unit_types", None) or {}
            for _uid_t, _rec_t in (getattr(getattr(_c_t, "unit_ctrl", None), "units", None) or {}).items():
                if not isinstance(_rec_t, dict):
                    continue
                _spec_t = _uts_t.get(_rec_t.get("type")) if isinstance(_uts_t, dict) else None
                _type_names[str(_uid_t)] = str((_spec_t or {}).get("name") or _rec_t.get("type") or "")
        except Exception:  # noqa: BLE001
            _type_names = {}
    for uid, actions in unit_actions.items():
        offered = as_dict(actions) or {}
        # §13.439: ЕГО ПРАВИЛО МИССИИ относится к ПОСЕЛЕНЦУ, а не к любому юниту. Замер s1380
        # показал прямо в журнале, кого мы ведём основывать:
        #   unit/107 тип='Workers', unit/108 тип='Explorer', unit/106 тип='Workers'
        # — ни одного поселенца. Рабочие и разведчик не могут основать город (`build_city=False`
        # у мира — законный ответ), поэтому они «ждали площадку» всю партию, стояли без работы,
        # а наши поселенцы, если и были, в этом же цикле путались с ними; отсюда и 120 действий
        # в списке, и нулевой рост числа городов. Тип берём у контроллера: в наблюдении его нет
        # (замер s1375: тип=None).
        if _type_names:
            _tn = str(_type_names.get(str(uid)) or "")
            if "settler" not in _tn.lower():
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [не-поселенец] unit/{uid} (тип {_tn!r}) — правило основания к нему "
                          f"не применяется", flush=True)
                continue
        founding = [str(n) for n, params in offered.items()
                    if str(n).startswith(("build_city", "found_city")) and truthy(params)]
        # ── §13.349: ЕГО правило миссии (`daisettler.c:1036-1040`): если город ЗДЕСЬ основать
        # нельзя (`!city_can_be_built_here`), задача отменяется и поселенец идёт к лучшей
        # площадке. У нас вмешательство шло ТОЛЬКО при голодной площадке, поэтому поселенец,
        # вставший там, где основывать нельзя (например, ближе положенного к своему городу),
        # стоял 148 ходов и не делал НИЧЕГО: общего пути кандидат не даётся, а правило молчало.
        can_found_here = bool(founding)
        pos = _unit_pos(obs, uid)
        if pos is None:
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid}: позиции в наблюдении нет", flush=True)
            continue
        try:
            site = evaluate_site(map_obs, pos[0], pos[1],
                                 vals={"FOOD_COST": food_cost_of(obs)})
        except Exception as _exc:  # noqa: BLE001
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid}: оценка площадки упала "
                      f"({type(_exc).__name__})", flush=True)
            continue
        # ── §13.322: что выбрало бы ЕГО правило — основать здесь или идти к лучшей
        # достижимой площадке (`daisettler.c:1113-1140`). ТОЛЬКО ЗАМЕР: решений не меняет,
        # поэтому идёт до проверки голода и включается отдельным ключом.
        # §13.410: площадки ищем по ВСЕЙ известной карте (память мира: сейв + наблюдение), а не
        # по туманному обзору. У его ИИ зрение полное (`omniscience`); наш прежний перебор шёл
        # по 6-21 клетке вокруг юнита (замер §13.408).
        _rev = None
        try:
            from brain.forecast.live import revealed_tiles as _rev_tiles
            from env.world_memory import known as _wm_known
            _rev = set(_rev_tiles((obs or {}).get("map"))) | set(_wm_known())
        except Exception:  # noqa: BLE001
            _rev = None
        if os.environ.get("DOF_FOUND_DEBUG") == "1":
            _seen = globals().setdefault("_FOUND_DEBUG_SEEN", set())
            if (uid, tuple(pos)) not in _seen:
                _seen.add((uid, tuple(pos)))
                try:
                    _all = rank_sites(obs, exclude=city_positions(obs), reference=tuple(pos),
                                      cities=_known_cities, mindist=_mindist,
                                      reserved=_cmap, revealed=_rev)
                except Exception:  # noqa: BLE001
                    _all = []
                _here = next((c for c in _all
                              if (int(c[0]), int(c[1])) == tuple(pos)), None)
                _best = _all[0] if _all else None
                if _best is None:
                    print(f"  [основание] unit/{uid} на {tuple(pos)}: ДОСТИЖИМЫХ ПЛОЩАДОК НЕТ "
                          f"(здесь основывать {'можно' if can_found_here else 'НЕЛЬЗЯ'})", flush=True)
                if _best is not None:
                    _same = (int(_best[0]), int(_best[1])) == tuple(pos)
                    _h = ("—" if _here is None
                          else f"total {_here[2]:.1f}, want {_here[3]:.1f}")
                    print(f"  [основание] unit/{uid} на {tuple(pos)} (здесь: {_h}) | "
                          f"лучшая достижимая {(_best[0], _best[1])} "
                          f"(total {_best[2]:.1f}, want {_best[3]:.1f}) → его правило: "
                          f"{'основать здесь' if _same else 'ИДТИ'}", flush=True)
        # ── ЕГО правило выбора задачи (`daisettler.c:1113-1140`): поселенец идёт к лучшей
        # ДОСТИЖИМОЙ площадке, если её ценность — уже с вычетом дороги — выше того, что даёт
        # основание здесь. «Основать где стою» у него не отдельное правило, а частный случай.
        # Измерено (§13.323): на 45 ходах его правило уходит в 6 случаях из 8, и выигрыш
        # переживает стоимость пути (380.2 против 348.5; 541.8 против 469.7; 469.8 против 421.2),
        # а мы основывали на месте и получали землю с 8 щитами на 21 клетку.
        try:
            # §13.413: отказные клетки ЭТОГО поселенца исключаем из поиска, а не только из
            # «основать здесь». Замер r930: у unit/118 и unit/120 ВСЕ их площадки (3-4) попали в
            # чёрный список, и наш перебор снова выбирал лучшую из отказных — поселенец ходил по
            # кругу. Мир отказал в клетке — это факт о мире (его `cityresult_fill` её не берёт),
            # значит и наше ранжирование её не предлагает.
            _black = set((globals().get("_FOUND_BLACK") or {}).get(uid) or set())
            ranked_all = rank_sites(obs, exclude=city_positions(obs) | _black,
                                    reference=tuple(pos), settler_shield_cost=0.0,
                                    cities=_known_cities, mindist=_mindist,
                                    reserved=_cmap, revealed=_rev)
        except Exception:  # noqa: BLE001
            ranked_all = []
        _black = _FOUND_BLACK.get(str(uid)) or set()
        if _black and ranked_all:
            # §13.402: отказные клетки этого поселенца площадками не считаем (его `daisettler.c`
            # отменяет задачу, если основать на цели нельзя). Если чёрный список съел всё —
            # оставляем как есть: пусть лучше попробует, чем стоит.
            _kept = [c for c in ranked_all if (int(c[0]), int(c[1])) not in _black]
            if _kept:
                ranked_all = _kept
            else:
                # §13.414: все площадки ЭТОГО поселенца уже отвергнуты миром. Прежде мы брали
                # лучшую из отказных и снова шли туда — замер r940: 72 отказа за партию, все
                # приходятся на повторные заходы в отказные клетки. Мир отказал — не идём туда
                # снова: пусть лучше постоит, чем жжёт ходы в заведомо бесплодной поездке.
                ranked_all = []
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [чёрный-список] unit/{uid}: все площадки отказные ({len(_black)}) — "
                          f"никуда не иду (мир отверг их все)", flush=True)
        if not ranked_all:
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                # §13.407: почему площадок нет — иначе не отличить «карта пустая» от «всё
                # отсечено правилами». Считаем видимые клетки, наши города, резерв и citymindist.
                _vis = 0
                try:
                    _mp = as_dict((obs or {}).get("map")) or {}
                    for _k, _v in _mp.items():
                        if str(_k) in ("width", "height", "x", "y") and not hasattr(_v, "shape"):
                            continue
                        if hasattr(_v, "shape") and len(getattr(_v, "shape", ())) >= 2:
                            _vis += int(_v.shape[0]) * int(_v.shape[1])
                            break
                except Exception:  # noqa: BLE001
                    _vis = -1
                print(f"  [пропуск] unit/{uid} на {tuple(pos)}: достижимых площадок нет "
                      f"(видимых клеток {_vis}, наших городов {len(_known_cities or [])}, "
                      f"citymindist {_mindist}, резерв занят {len(getattr(_cmap, '_spots', {}) or {})}, "
                      f"в памяти карты {_mem_tiles(obs)})",
                      flush=True)
            continue                      # некуда идти — не мешаем основанию
        here = next((c for c in ranked_all
                     if (int(c[0]), int(c[1])) == tuple(pos)), None)
        best = ranked_all[0]
        on_best = (int(best[0]), int(best[1])) == tuple(pos)
        starved = bool(getattr(site, "starved_food", False)
                       or getattr(site, "starved_shield", False))
        # ── §13.356: ЕГО ВЫБОР (`daisettler.c:1121-1134`): ценность площадки против ценности
        # работы на земле. `result->result > best_impr` — идём основывать; иначе, если работа
        # есть (`best_impr > 0`), он становится AUT_AUTO_SETTLER и работает на земле.
        _city_want = float(best[3])                                   # его `result->result`
        _impr_want = _land_work_want(obs, map_obs, offered, pos)       # его `best_impr`
        _city_wins = _city_want > _impr_want
        if os.environ.get("DOF_FOUND_DEBUG") == "1":
            _h_now = _FOUND_TARGET.get(str(uid))
            print(f"  [поселенец-ход] unit/{uid} на {tuple(pos)} "
                  f"{'цель ' + str(_h_now) if _h_now else 'цели нет'}; "
                  f"основать_здесь={can_found_here}, голоден={starved}; город {_city_want:.1f} "
                  f"против работы {_impr_want:.1f} → "
                  f"{'ГОРОД' if _city_wins else 'земля (его AUT_AUTO_SETTLER)'}", flush=True)
        if not _city_wins:
            # Земля важнее площадки: его `else if (best_impr > 0)` — работаем на земле и снимаем
            # задачу основания (`dai_unit_new_task` освобождает и место, `daitools.c:665-671`).
            _was = _FOUND_TARGET.pop(str(uid), None)
            if _was is not None:
                _cmap.free_city_spot(_was[0], _was[1], uid)
            continue
        if on_best and can_found_here:
            # ── ЕГО `dai_do_build_city` (`daisettler.c:1053-1070`): пришли на место и можно —
            # ОСНОВЫВАЕМ САМИ. Прежде здесь стояло «основывает общий путь», и это было ИЗМЕРЕНО
            # как потеря: у поселенца верхним кандидатом общего пути шли работы на земле
            # (`build_road=2.0`, `cultivate=2.0`), основание не посылалось вовсе — 18 поселенцев
            # за 150 ходов и 5 приказов `build_city`.
            _prev = _FOUND_TARGET.pop(str(uid), None)
            if _prev is not None:
                _cmap.free_city_spot(_prev[0], _prev[1], uid)
            if founding:
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [основание] unit/{uid} на {tuple(pos)}: основать_здесь "
                          f"(город {_city_want:.1f} > работы {_impr_want:.1f}) — приказ "
                          f"{founding[0]} (его dai_do_build_city)", flush=True)
                return ("unit", uid, founding[0])
            continue
        if can_found_here and not starved and here is not None \
                and float(best[3]) <= float(here[2]):
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid} на {tuple(pos)}: лучшая {tuple(best[:2])} "
                      f"не окупает дорогу ({float(best[3]):.1f} <= {float(here[2]):.1f})",
                      flush=True)
            continue                      # лучше, но не настолько: дорога съедает выигрыш
        ranked = [c for c in ranked_all if (int(c[0]), int(c[1])) != tuple(pos)]
        # §13.581: прибор. Показывает ТОП-3 площадки по рангу (с расстоянием) и 3 САМЫЕ БЛИЖНИЕ.
        # Вопрос опровержимый: есть ли законная площадка ближе 4 клеток, которую агент игнорирует.
        # Под флагом, поведение по умолчанию не трогает.
        if os.environ.get("DOF_FOUND_DEBUG") == "1" and ranked:
            try:
                _d = lambda c: max(abs(int(c[0]) - int(pos[0])), abs(int(c[1]) - int(pos[1])))
                _r3 = ranked[:3]
                _n3 = sorted(ranked, key=_d)[:3]
                print(f"  [площадки] unit/{uid} в {tuple(pos)}: "
                      f"ранг {[(int(c[0]), int(c[1])) for c in _r3]} близость {[_d(c) for c in _r3]} | "
                      f"ближайшие {[(int(c[0]), int(c[1])) for c in _n3]} близость {[_d(c) for c in _n3]} | "
                      f"всего {len(ranked)}", flush=True)
            except Exception:  # noqa: BLE001
                pass
        gotos = [str(n) for n, params in offered.items()
                 if str(n).startswith("goto_") and truthy(params)]
        # ── §13.348: ДЕРЖИМ цель, как его миссия (`daisettler.c:1029-1054`): пока цель годна,
        # ведём поселенца к НЕЙ, а не к пересчитанной заново. По прибытии — не мешаем общему
        # пути основать (`build_city`), цель снимаем. Цель стала недостижимой — пересчитываем.
        _held = _FOUND_TARGET.get(str(uid))
        if _held is not None and _known_cities:
            # ── ЕГО ОТМЕНА (`daisettler.c:1040-1045`): если основывать в цели УЖЕ нельзя
            # (появился город ближе положенного — `citymindist_prevents_city_on_tile`,
            # `common/city.c:1445`), задача снимается и место освобождается. Измерено (`cmp1`):
            # поселенец пришёл в (16,33), где мир отказывает (`основать_здесь=False`) — цель была
            # выбрана до появления столицы и держалась, поэтому основание не срабатывало.
            from brain.ai_default.founder_destination import citymindist_blocks as _blocks
            if _blocks(_held[0], _held[1], _known_cities, _mindist):
                _FOUND_TARGET.pop(str(uid), None)
                _cmap.free_city_spot(_held[0], _held[1], uid)
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [отмена] unit/{uid}: цель {_held} стала негодной "
                          f"(город ближе citymindist) — ищем заново", flush=True)
                _held = None
        if _held is not None:
            if (int(pos[0]), int(pos[1])) == _held:
                _FOUND_TARGET.pop(str(uid), None)
                _cmap.free_city_spot(_held[0], _held[1], uid)   # пришли: место отдаём городу
                if can_found_here and founding:
                    # §13.412: помним своё основание сразу — список городов от клиента отстаёт,
                    # и без этой памяти другие поселенцы шли в тот же район и получали отказ.
                    globals().setdefault("_FOUNDED_SITES", set()).add((int(pos[0]), int(pos[1])))
                    if os.environ.get("DOF_FOUND_DEBUG") == "1":
                        print(f"  [основание] unit/{uid} пришёл на {tuple(pos)}: приказ "
                              f"{founding[0]} (его dai_do_build_city)", flush=True)
                    return ("unit", uid, founding[0])
                # §13.402: мир отказал в основании на этой клетке — запоминаем её за этим
                # поселенцем, чтобы он не выбрал её снова (без этого стоял тут весь прогон).
                _key = (int(pos[0]), int(pos[1]))
                # §13.416: мир отвечает `build_city=False` и тогда, когда у поселенца просто
                # кончился ход (действие требует очков движения), — а не только когда клетка
                # негодна. Замер r970: 24 отказные клетки — все на хорошей земле (трава, равнина,
                # лес, холмы), ни одной из `NoCities`. Прежде мы с первого отказа писали клетку
                # в чёрный список и больше туда не шли. Теперь пишем только после ВТОРОГО отказа
                # на той же клетке: первый — «попробуй ещё раз следующим ходом».
                _avail = offered.get("build_city")
                if not _avail:
                    # §13.435: ПРЕЖДЕ ВСЕГО показываем, ЧТО мир вообще предлагает этому поселенцу
                    # на этой клетке. Замер s1355: четверо поселенцев стояли на своих площадках
                    # («основать_здесь=True», решение «ГОРОД»), а мир ни разу не предложил
                    # основание — 30 отказов и НИ ОДНОГО основания за партию, у нас остался всего
                    # один город. Без полного списка предложенного нельзя отличить «кончился ход»
                    # от «эта клетка миру не годится», а лечение у этих двух причин разное.
                    # §13.436: ПРИБОР (`DOF_FORCE_FOUND=1`) — послать основание ПО ИМЕНИ, даже
                    # если клиент помечает его негодным. Замер s1360: у поселенцев на площадках
                    # `build_city` в списке предложенного ЕСТЬ, но со значением «нельзя», а очки
                    # движения из наблюдения не читаются (`None`) — то есть «кончился ход» и
                    # «клетка негодна» различить пока нельзя, и поселенец ждёт вечно (30 отказов,
                    # ни одного основания за партию, у нас 1 город против 6).
                    # Прибор отделяет «наш ВЫБОР неверен» от «приказ не проходит у мира»: стоит
                    # один ход, отказ виден в `[отказ-основания]`.
                    if os.environ.get("DOF_FORCE_FOUND") == "1":
                        if os.environ.get("DOF_FOUND_DEBUG") == "1":
                            print(f"  [основание-прибор] unit/{uid} на {tuple(pos)}: посылаю "
                                  f"build_city по имени, хотя клиент отвечает "
                                  f"build_city={_avail!r}", flush=True)
                        return ("unit", uid, "build_city")
                    if os.environ.get("DOF_FOUND_DEBUG") == "1":
                        try:
                            _keys = sorted(str(k) for k in offered)
                            _moves = None
                            _utype = None
                            # §13.438: КОГО мы ведём основывать. В списке предложенного у этих
                            # юнитов 120 действий (`airbase`, `airlift`, `attack_0…N`) — столько
                            # у поселенца быть не может. Печатаем собственный тип юнита из
                            # наблюдения: если это не поселенец, то он и ждёт не того.
                            try:
                                # §13.438: в наблюдении типа нет (замер s1375: тип=None),
                                # поэтому берём его у контроллера — там же, где его читает
                                # перебор наших юнитов (civ_controller.unit_ctrl.units).
                                _env2 = env_getter() if env_getter else None
                                _c2 = getattr(getattr(_env2, "unwrapped", None), "civ_controller", None)
                                _uc = getattr(_c2, "unit_ctrl", None)
                                _us2 = getattr(_uc, "units", None) or {}
                                _rule2 = getattr(_c2, "rule_ctrl", None)
                                _uts = getattr(_rule2, "unit_types", None) or {}
                                _rec2 = _us2.get(str(uid)) or _us2.get(uid) or {}
                                if isinstance(_rec2, dict):
                                    _t2 = _rec2.get("type")
                                    _spec2 = _uts.get(_t2) if isinstance(_uts, dict) else None
                                    _utype = (_spec2 or {}).get("name") if isinstance(_spec2, dict) else _t2
                                    _moves = _rec2.get("moves_left", _rec2.get("moves"))
                            except Exception:  # noqa: BLE001
                                pass
                            _us = obs.get("units")
                            if _moves is None and isinstance(_us, list):
                                for _u in _us:
                                    if str(_u.get("id")) == str(uid):
                                        _moves = _u.get("moves_left")
                                        _utype = _utype or _u.get("type")
                                        break
                            print(f"  [отказ-основания] unit/{uid} на {tuple(pos)}: мир НЕ предлагает "
                                  f"основание; тип={_utype!r}, build_city={_avail!r}, очки={_moves}, "
                                  f"всего {len(_keys)}: {_keys}", flush=True)
                        except Exception:  # noqa: BLE001
                            pass
                    # §13.424: мир не ПРЕДЛАГАЕТ основание вовсе — это не отказ клетки, а
                    # «сейчас нельзя» (у поселенца кончились очки движения: замер r970 — все 24
                    # «отказные» клетки были на хорошей земле). Прежде и такой ход увеличивал
                    # счётчик отказов, и площадка уходила в чёрный список на втором же ходу —
                    # отсюда «все площадки отказные» 85 раз за партию и стоящие поселенцы.
                    _cnt = globals().setdefault("_FOUND_REFUSALS", {})
                    _per = _cnt.setdefault(str(uid), {})
                    _per[_key] = 0
                    if os.environ.get("DOF_FOUND_DEBUG") == "1":
                        print(f"  [отказ-основания] unit/{uid} на {tuple(pos)}: мир не предлагает "
                              f"основание сейчас (build_city={_avail}) — жду на этой же клетке, "
                              f"цель НЕ снимаю (движение)", flush=True)
                    # §13.429: цель НЕ снимаем. Прежде здесь стоял `_FOUND_TARGET.pop`, и поселенец
                    # терял цель, выбирал заново (часто другую площадку) и уходил — за партию
                    # s1210 было 7 случаев «основать_здесь=True» и всего 2 основания. Достаточно
                    # подождать: в следующем ходу очки движения есть, и основание пройдёт.
                    continue
                _cnt = globals().setdefault("_FOUND_REFUSALS", {})
                _per = _cnt.setdefault(str(uid), {})
                _per[_key] = int(_per.get(_key, 0)) + 1
                if _per[_key] < 2:
                    if os.environ.get("DOF_FOUND_DEBUG") == "1":
                        print(f"  [отказ-основания] unit/{uid} на {tuple(pos)}: мир не даёт основать "
                              f"здесь (build_city={offered.get('build_city')}) — пробую снова "
                              f"следующим ходом (отказ {_per[_key]})", flush=True)
                    _FOUND_TARGET.pop(str(uid), None)
                    continue
                _FOUND_BLACK.setdefault(str(uid), set()).add(_key)
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    # §13.414: печатаем ПРИЧИНУ со стороны мира, а не только своё решение:
                    # предлагает ли мир основание (`build_city`) на этой клетке прямо сейчас.
                    print(f"  [отказ-основания] unit/{uid} на {tuple(pos)}: мир не даёт основать "
                          f"здесь (build_city={offered.get('build_city')}) "
                          f"— клетка в чёрный список, ищем другую", flush=True)
                continue
            # ── §13.358: ЕГО ПУТЬ (`dai_unit_goto`, `daitools.c:242-291`) — идём по кратчайшему
            # пути, а не одним жадным шагом: жадный упирался в воду/тупик и стоял (§13.348).
            _step_held = None
            _nx = path_first_step(tuple(pos), _held, _passable, shape=_shape)
            if _nx is not None:
                _nm = goto_name_to(tuple(pos), _nx)
                if _nm is not None and (not gotos or _nm in gotos):
                    _step_held = _nm
            if _step_held is None:
                _step_held = step_toward(tuple(pos), _held, offered=gotos or None,
                                         blocked=_blocked_step)
            if _step_held is None and gotos:
                # §13.395: цель НЕ сбрасываем из-за одного недоступного шага — именно это давало
                # качание (§13.394: площадка (25,9) → (24,9) и обратно). Его поселенец идёт к
                # `task->target` (`daitasks.c`, `dai_unit_new_task`), а не пересчитывает лучшую
                # соседнюю площадку каждый ход. Берём любой ПРЕДЛОЖЕННЫЙ мир ход, который
                # уменьшает расстояние до удерживаемой цели.
                try:
                    from brain.ai_default.founder_destination import (
                        _wrap as _wrap_of, goto_name as _goto_name_of)
                    _cur_d = max(abs(int(_held[0]) - int(pos[0])),
                                 abs(int(_held[1]) - int(pos[1])))
                    _best_step, _best_d = None, _cur_d
                    for _dx in (-1, 0, 1):
                        for _dy in (-1, 0, 1):
                            if _dx == 0 and _dy == 0:
                                continue
                            _nm2 = _goto_name_of(_dx, _dy)
                            if _nm2 is None or _nm2 not in gotos:
                                continue
                            _nx2 = _wrap_of(int(pos[0]) + _dx, int(pos[1]) + _dy, _shape)
                            if _nx2 is None:
                                continue
                            _d2 = max(abs(int(_held[0]) - int(_nx2[0])),
                                      abs(int(_held[1]) - int(_nx2[1])))
                            if _d2 < _best_d:
                                _best_d, _best_step = _d2, _nm2
                    _step_held = _best_step
                except Exception:  # noqa: BLE001
                    _step_held = None
            if _step_held is not None:
                _FOUND_FAIL.pop(str(uid), None)
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [поселенец] unit/{uid}: держу цель {_held} (его миссия) "
                          f"→ шаг {_step_held}", flush=True)
                return ("unit", uid, _step_held)
            # Шага нет вовсе. Держим цель ещё несколько ходов: путь может открыться (юнит
            # освободит клетку, откроется берег), а сброс цели возвращает качание.
            if _held is not None and (int(_held[0]), int(_held[1])) == (int(pos[0]), int(pos[1])):
                # §13.430: мы СТОИМ на удерживаемой площадке — «шага нет» здесь не неудача, а
                # ожидание: мир не даёт основание без очков движения. Прежде этот случай считался
                # неудачей и на третьем ходу цель сбрасывалась — поселенец выбирал заново и
                # уходил. Замер s1215: 200 «основать_здесь=False» и только 5 «True»; два
                # поселенца за партию так и не основали город.
                _FOUND_FAIL.pop(str(uid), None)
                continue
            _n_fail = _FOUND_FAIL.get(str(uid), 0) + 1
            _FOUND_FAIL[str(uid)] = _n_fail
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [поселенец] unit/{uid}: шага к цели {_held} нет "
                      f"(попытка {_n_fail} из 3) — цель держу", flush=True)
            if _n_fail <= 3:
                continue
            _FOUND_FAIL.pop(str(uid), None)
            _FOUND_TARGET.pop(str(uid), None)
            _cmap.free_city_spot(_held[0], _held[1], uid)   # цель недостижима — место свободно
        # Берётся ПЕРВАЯ площадка, к которой мир предлагает законный шаг. Измерено: без
        # этого поселенец 11 раз подряд выбирал шаг к воде, не сдвигался и не основывал
        # город вовсе — цена площадки без достижимости вредна.
        step = None
        target = None
        for cand in ranked:
            # ЕГО `pf_map`: площадка годится, только если до неё ЕСТЬ путь, а не только
            # направление. Жадный шаг вёл к воде и в тупики — поселенцы не доходили.
            _cx, _cy = int(cand[0]), int(cand[1])
            _nx = path_first_step(tuple(pos), (_cx, _cy), _passable, shape=_shape)
            if _nx is None:
                continue
            _nm = goto_name_to(tuple(pos), _nx)
            if _nm is not None and _nm in gotos:
                step, target = _nm, cand
                break
            step = step_toward(tuple(pos), (_cx, _cy), offered=gotos or None,
                               blocked=_blocked_step)
            if step is not None:
                target = cand
                break
        if step is None or target is None:
            continue
        _FOUND_TARGET[str(uid)] = (int(target[0]), int(target[1]))   # §13.348: держим до прибытия
        # ── ЕГО ЗАНЯТИЕ МЕСТА: место города (`daitools.c:708`) и клетка первого жителя
        # (`daisettler.c:1139`). Другие поселенцы это место площадкой уже не считают
        # (`city_desirability`, `:715-719`).
        _cmap.reserve_city_spot(int(target[0]), int(target[1]), uid)
        try:
            from env.food_gate import food_cost_of as _fco
            _bt = evaluate_site(map_obs, int(target[0]), int(target[1]),
                                vals={"FOOD_COST": _fco(obs)})
            if getattr(_bt, "best_other_x", -1) >= 0:
                _cmap.reserve_tile(int(_bt.best_other_x), int(_bt.best_other_y), uid)
        except Exception:  # noqa: BLE001
            pass
        if os.environ.get("DOF_FOUND_DEBUG") == "1":
            print(f"  [резерв] unit/{uid} занял место {(int(target[0]), int(target[1]))} "
                  f"(его citymap_reserve_city_spot, daitools.c:708)", flush=True)
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [поселенец] unit/{uid}: площадка {pos} голодная "
                  f"({getattr(site, 'reason', '')}) → иду к {target[:2]} (его total "
                  f"{target[2]:.1f}), шаг {step}", flush=True)
        return ("unit", uid, step)
    return None


def _city_tile_his_manager(obs: dict, avail: dict):
    """§13.432: расстановка жителей его управляющим — ОДНОЙ задачей, а не по одной клетке.

    Управляющий (`brain/ai_default/worker_manager.py`) считает желаемый набор клеток по его весам
    (размер 1 → еда 20 против щитов 5) и наименьшим избыткам, а мы отдаём ОДИН шаг пары
    «снять плохую → занять лучшую»: постановка жителя в клиенте действительна лишь при свободном
    горожанине (`city/city_actions.py:150`), поэтому снимаем первым, а займём следующим ходом.

    Снятие при этом разрешается стражем (§13.432 в `env/food_gate.py`) вместе с доказательством:
    каким станет избыток еды ПОСЛЕ обмена. Иначе правило F запрещало бы у города с нулевым
    избытком любой обмен, и город оставался бы на плохой клетке навсегда (§13.431).
    """
    try:
        from brain.ai_default.worker_manager import choose_arrangement
        from env.site_eval import tile_output
        from env import food_gate as _fg
    except Exception:  # noqa: BLE001
        return None
    map_obs = as_dict(as_dict(obs).get("map")) or {}
    city_actions = as_dict(as_dict(avail).get("city")) or {}
    cities = as_dict((obs or {}).get("city")) or {}
    _dbg = os.environ.get("DOF_TILE_DEBUG") == "1"
    if _dbg and city_actions:
        globals()["_MGR_DBG"] = globals().get("_MGR_DBG", 0) + 1
        if globals()["_MGR_DBG"] <= 3:
            print(f"  [расстановка-проба] городов в действиях {len(city_actions)}, "
                  f"записей городов {len(cities)}, ключи записей {list(cities)[:2]}", flush=True)
    for cid, actions in city_actions.items():
        names = {str(n): params for n, params in as_dict(actions).items()
                 if truthy(params) and str(n).startswith(("city_work_", "city_unwork_"))}
        if _dbg and globals()["_MGR_DBG"] <= 3:
            print(f"  [расстановка-проба] город {cid}: действий по клеткам {len(names)}, "
                  f"пример {list(names)[:2]}", flush=True)
        if not names:
            continue
        rec = None
        for _key in (cid, str(cid), int(cid) if str(cid).lstrip("-").isdigit() else None):
            if _key is not None and _key in cities:
                rec = cities[_key]
                break
        if not isinstance(rec, dict) or rec.get("x") is None or rec.get("y") is None:
            continue
        try:
            cx, cy = int(rec["x"]), int(rec["y"])
            size = float(rec.get("size") or 1.0)
        except (TypeError, ValueError):
            continue
        offs: dict[tuple[int, int], tuple[str, str]] = {}
        for _n in names:
            _off = _tile_offset_of(_n)
            if _off is None:
                continue
            offs[_off] = ("unwork" if _n.startswith("city_unwork_") else "work", _n)
        if not offs:
            continue
        worked = {o for o, (kind, _n) in offs.items() if kind == "unwork"}
        free = {o for o, (kind, _n) in offs.items() if kind == "work"}
        if not worked and not free:
            continue
        # §13.432: клиент предлагает `city_work_*` только при СВОБОДНОМ горожанине, поэтому
        # свободных клеток в списке нет вовсе (замер s1245: у обоих наших городов предложено
        # лишь по одному `city_unwork_*`). Но какие клетки станут свободны после снятия — мы
        # знаем: это весь радиус, кроме обрабатываемых. Их годность берём из карты, а не из
        # предложения, чтобы задачу можно было посчитать ЦЕЛИКОМ (как делает его управляющий).
        for _dx in range(-2, 3):
            for _dy in range(-2, 3):
                _o = (_dx, _dy)
                if _o in worked or _o in free:
                    continue
                try:
                    _yy = tile_output(map_obs, cx + _dx, cy + _dy)
                except Exception:  # noqa: BLE001
                    _yy = None
                if _yy is None:
                    continue
                if float(_yy[0]) <= 0.0 and float(_yy[1]) <= 0.0:
                    continue          # ни еды, ни щитов — держать такую клетку незачем
                free.add(_o)
        yields: dict[tuple[int, int], tuple[float, float, float]] = {}
        for o in worked | free | {(0, 0)}:
            try:
                _y = tile_output(map_obs, cx + o[0], cy + o[1])
            except Exception:  # noqa: BLE001
                _y = None
            if _y is None:
                continue
            yields[o] = (float(_y[0]), float(_y[1]), float(_y[2]))
        if len(yields) < 2:
            continue
        try:
            food_cost = float(_fg.food_cost_of(obs) or 2.0)
        except Exception:  # noqa: BLE001
            food_cost = 2.0
        if os.environ.get("DOF_BEST_ARRANGE") == "1":
            # §13.461: полный поиск с отсечением (CMA) вместо жадного перебора. Если годной
            # расстановки нет — НЕ выдумываем замену (у него `cmr->found_a_valid = FALSE`).
            plan = None
            try:
                from brain.ai_default.worker_manager import best_arrangement

                _cand = [o for o in list(worked) + list(free) if o != (0, 0)]
                _b = best_arrangement(yields, size=size, candidates=_cand, food_cost=food_cost,
                                      granary_full=False)
                if _b.get("feasible"):
                    _tot = [sum(float(yields.get(o, (0.0, 0.0, 0.0))[i]) for o in _b["chosen"])
                            for i in range(3)]
                    plan = {"chosen": _b["chosen"], "ok": True, "food": _tot[0], "shield": _tot[1],
                            "surplus": {"food": _b["surplus"]["food"],
                                        "shield": _b["surplus"]["shield"]}}
                    if _dbg and globals().get("_MGR_DBG", 0) <= 25:
                        print(f"  [расстановка-полная] город {cid}: размер {size:g}, "
                              f"набор {sorted(plan['chosen'])}, избыток "
                              f"{plan['surplus']['food']:+.1f}", flush=True)
            except Exception:  # noqa: BLE001
                plan = None
            if plan is None:
                continue
        else:
            plan = choose_arrangement(yields, size=size, worked=worked, free=free,
                                      food_cost=food_cost, granary_full=False)
        if _dbg and globals().get("_MGR_DBG", 0) <= 25:
            print(f"  [расстановка-проба] город {cid}: размер {size:g}, обрабатывает {sorted(worked)}, "
                  f"свободных посчитано {len(free)}, клеток с выходами {len(yields)}, "
                  f"набор {plan['chosen']}, еда {plan['food']:.1f} щиты {plan['shield']:.1f} "
                  f"избыток {plan['surplus']['food']:+.1f}, годится {plan['ok']}", flush=True)
        if not plan.get("ok"):
            continue
        chosen = set(plan["chosen"])
        surplus_after = float(plan["surplus"]["food"])
        # §13.516: СПЕРВА ЗАНЯТЬ, если горожанин свободен. Иначе сервер сам вернёт снятого
        # жителя на прежнюю клетку, и мы будем снимать одну и ту же клетку каждый ход
        # (измерено: 28 снятий против 7 постановок, клетка (1,0) снималась повторно).
        for o in sorted(chosen - worked):
            kind, name = offs.get(o, (None, None))
            if kind != "work":
                continue
            if os.environ.get("DOF_TILE_DEBUG") == "1":
                print(f"  [расстановка] город {cid} (размер {size:g}): занимаю {o} → {name} "
                      f"(§13.516: раньше снятия)", flush=True)
            return ("city", cid, name)
        # 1) Есть обрабатываемая клетка, которой не место в желаемом наборе — снимаем её.
        for o in sorted(worked - chosen):
            kind, name = offs[o]
            if kind != "unwork":
                continue
            _fg.allow_swap(cid, o, food_after=surplus_after, size=size, food_cost=food_cost)
            if os.environ.get("DOF_TILE_DEBUG") == "1":
                print(f"  [расстановка] город {cid} (размер {size:g}): снимаю {o} "
                      f"(еда после обмена {surplus_after:+.1f}, веса "
                      f"еда {plan['weights']['food']:g}/щиты {plan['weights']['shield']:g}) "
                      f"→ {name}", flush=True)
            return ("city", cid, name)
        # 2) Есть свободная клетка из желаемых и свободный горожанин — занимаем.
        for o in sorted(chosen - worked):
            kind, name = offs.get(o, (None, None))
            if kind != "work":
                continue
            if os.environ.get("DOF_TILE_DEBUG") == "1":
                print(f"  [расстановка] город {cid} (размер {size:g}): занимаю {o} → {name}",
                      flush=True)
            return ("city", cid, name)
    return None


def _tile_offset_of(name: str):
    """Смещение `(dx, dy)` из имени `city_<family>_<idx>_<dx>_<dy>`."""
    parts = str(name).split("_")
    try:
        return int(parts[-2]), int(parts[-1])
    except (TypeError, ValueError, IndexError):
        return None


def _city_tile_rescue(obs: dict, avail: dict):
    """Спасение ГОЛОДАЮЩЕГО города: у него годность идёт ПЕРЕД выгодой (§13.305).

    `common/aicore/cm.c:623` решает так: сначала `fitness.sufficient` (все статьи не ниже
    `minimal_surplus`), и только среди годных берётся `fitness.weighted`. Наш же отбор брал
    лишь ходы с ПОЛОЖИТЕЛЬНЫМ выигрышем (`if gain <= 0: break`) — поэтому ход, который убирает
    голод, но не даёт выигрыша по весам, отбрасывался, и город продолжал голодать
    (измерено: 4 наблюдения с излишком −1 при размере городов 1 и 2).

    Возвращает `(ctrl, actor, name)` — ход, улучшающий сальдо еды, или None.
    """
    city_actions = as_dict(as_dict(avail).get("city")) or {}
    cities = as_dict(as_dict(obs).get("city")) or {}
    map_obs = as_dict(as_dict(obs).get("map")) or {}
    try:
        from brain.ai_default.city_tiles import parse_city_tile_action
        from brain.ai_default.tile_outputs import tile_outputs_from_rules
        from env.terrain_work import tile_terrain_extras
    except Exception:  # noqa: BLE001
        return None
    best = None
    for cid, actions in city_actions.items():
        rec = None
        for _key in (cid, str(cid), int(cid) if str(cid).lstrip("-").isdigit() else None):
            if _key is not None and _key in cities:
                rec = cities[_key]
                break
        if not isinstance(rec, dict) or rec.get("x") is None or rec.get("y") is None:
            continue
        _raw = rec.get("surplus_food")
        if _raw is None:
            continue
        try:
            surplus = float(_raw)
        except (TypeError, ValueError):
            continue
        if surplus >= 0.0:
            continue          # город не голодает — спасать нечего
        cx, cy = int(rec["x"]), int(rec["y"])
        for name, params in as_dict(actions).items():
            name = str(name)
            if not (name.startswith("city_work_") or name.startswith("city_unwork_")) \
                    or not truthy(params):
                continue
            parsed = parse_city_tile_action(name)
            if parsed is None:
                continue
            try:
                terrain, extras = tile_terrain_extras(map_obs, cx + parsed[1], cy + parsed[2])
            except Exception:  # noqa: BLE001
                continue
            got = tile_outputs_from_rules(terrain, extras)
            if got is None:
                continue
            food = float(got[0])
            after = surplus - food if name.startswith("city_unwork_") else surplus + food
            if after <= surplus:
                continue      # сальдо не улучшается — это не спасение
            if best is None or after > best[0]:
                best = (after, cid, name, surplus)
    if best is None:
        return None
    after, cid, name, surplus = best
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        print(f"  [клетка-спасение] город {cid}: {name} — излишек {surplus:g} → {after:g} "
              f"(годность ПЕРЕД выгодой, cm.c:623)", flush=True)
    return ("city", cid, name)


def _city_tile_candidate(obs: dict, avail: dict):
    """Какое действие по клетке города отправить — по перенесённой оценке (§13.294).

    Мир предлагает до 21 клетки радиуса с непустыми параметрами (`city_work_*`), но короткий
    список генератора их не берёт: прирост DoF у постановки жителя почти нулевой. У его
    управляющего городом расстановка жителей — обязательная часть хода (`cm.c`), поэтому
    кандидат собирается напрямую из предложенного, а выбирает его перенесённое число.

    Возвращает `(ctrl, actor, action)` или None. None — если данных нет ИЛИ лучший ход был бы
    обратным к нашему же прошлому ходу по этой клетке (чередование измеренно вредит).
    """
    # §13.432: сперва — ЕГО управляющий городом: расстановка как одна задача (веса еда 20/щиты 5
    # при размере 1, наименьшие избытки еда 1, щиты 1). Прежде жителей никто не расставлял: в
    # предложенных действиях были только `city_unwork_*`, а правило F запрещало любое снятие у
    # города с нулевым избытком еды (замер §13.431: города размера 1 работали Forest с едой 1,
    # имея рядом свою же Grassland с едой 2, и потому не росли вовсе).
    def _city_used(_x):
        """§13.635: город этого действия уже отдал заказ в этом ходу?"""
        if os.environ.get("DOF_NO_ACTOR_REPEAT") != "1" or not _USED_ACTORS:
            return False
        return ((str("city"), str(_x).split("_")[-1]) in
                {(str(_c).split("_")[0], str(_a).split("_")[-1])
                 for _c, _a in (_USED_ACTORS[0] or ())})

    if os.environ.get("DOF_NO_WORKER_MANAGER") != "1":
        _mgr = _city_tile_his_manager(obs, avail)
        if _mgr is not None:
            _LAST_TILE_ACTION[str(_mgr[1])] = _mgr[2]
            # §13.635: эти два ранних возврата стоят ДО отбора (закрыт в §13.632) и минуют его
            # целиком. Если город уже действовал, возвращаем управление дальше, а не отдаём ход
            # ему же повторно (иначе `_turn_phase` закрывает ход, §13.612-13.634).
            if _city_used(_mgr[1]):
                print(f"        [§13.635] город {_mgr[1]} (упр. жителями) уже действовал — "
                      f"ищем другого", flush=True)
            else:
                return _mgr
    # Сперва — спасение голодающего города: годность ПЕРЕД выгодой (его порядок).
    # Только если спасать нечего, переходим к выбору по выигрышу.
    _rescue = _city_tile_rescue(obs, avail)
    if _rescue is not None:
        _LAST_TILE_ACTION[str(_rescue[1])] = _rescue[2]
        if _city_used(_rescue[1]):
            print(f"        [§13.635] город {_rescue[1]} (спасение) уже действовал — "
                  f"ищем другого", flush=True)
        else:
            return _rescue
    city_actions = as_dict(as_dict(avail).get("city")) or {}
    best = None
    for cid, actions in city_actions.items():
        names = [str(n) for n, params in as_dict(actions).items()
                 if str(n).startswith(("city_work_", "city_unwork_")) and truthy(params)]
        if not names:
            continue
        _pend = _LAST_TILE_SENT.pop(str(cid), None)
        if _pend is not None and os.environ.get("DOF_TILE_DEBUG") == "1":
            _now = None
            for _k, _v in as_dict((obs or {}).get("city")).items():
                if str(_k) == str(cid):
                    _now = _v
                    break
            _now = as_dict(_now) or {}
            def _g(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            print(f"  [проба-city] город {cid}: заказали {_pend['name']}; выходы города "
                  f"еда {_pend['food']}→{_g(_now.get('prod_food'))}, "
                  f"щиты {_pend['shield']}→{_g(_now.get('prod_shield'))}, "
                  f"торговля {_pend['trade']}→{_g(_now.get('prod_trade'))}", flush=True)
        cands = [{"ctrl_type": "city", "actor_id": cid, "action_name": n} for n in names]
        gains = _city_tile_gains_from_rules(cid, cands, obs=obs)
        if not gains:
            continue
        # Обратный ход к нашему же прошлому действию по той же клетке не отправляем.
        # Ключ хранится СТРОКОЙ, поэтому и читается строкой: измерено — при записи целым
        # защита от чередования не видела прошлого действия, и житель дёргался туда-обратно
        # 30 из 30 ходов (city_work_16_-1_2 ↔ city_unwork_16_-1_2).
        _prev = _LAST_TILE_ACTION.get(str(cid))
        _prev_bench = None
        if _prev:
            _prev_bench = (str(_prev)[len("city_unwork_"):]
                           if str(_prev).startswith("city_unwork_")
                           else str(_prev)[len("city_work_"):])
        for name in sorted(gains, key=lambda n: -gains[n]):
            gain = gains[name]
            if gain <= 0:
                break
            if _prev_bench is not None and name[len("city_unwork_"):] == _prev_bench \
                    and (name.startswith("city_unwork_") != str(_prev).startswith("city_unwork_")):
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [клетка-ход] {name} пропущено: обратный ход к {_prev}", flush=True)
                continue
            # §13.632: занятый актёр не берётся — иначе город, уже отдавший заказ в этом ходу,
            # выбирается снова, `_turn_phase` видит повтор и закрывает ход, а остальные города
            # заказов не получают. Измерено: 53 из 60 повторов идут ИМЕННО отсюда (§13.620),
            # и защита на возврате не помогала — город подхыватывала следующая ветвь (§13.622).
            # Поэтому исключаем не на возврате, а в ОТБОРЕ кандидата.
            if os.environ.get("DOF_NO_ACTOR_REPEAT") == "1" and _USED_ACTORS:
                _used_norm = {(str(_c).split("_")[0], str(_a).split("_")[-1])
                              for _c, _a in (_USED_ACTORS[0] or ())}
                if (str("city"), str(cid)) in _used_norm:
                    print(f"        [§13.632] город {cid} уже отдал заказ в этом ходу — "
                          f"берём другого", flush=True)
                    continue
            if best is None or gain > best[0]:
                # Ключ актёра сохраняем КАК ЕСТЬ: он приходит ЦЕЛЫМ, и подмена его строкой
                # ломает поиск по словарям ниже (измерено: `KeyError: '121'`, 0 ходов).
                best = (gain, cid, name)
            break
    if best is None:
        return None
    gain, cid, name = best
    _LAST_TILE_ACTION[str(cid)] = name
    if os.environ.get("DOF_TILE_DEBUG") == "1":
        # §13.339: проба пути `city`. Измеряем и «что заказали», и «что стало с выходами
        # города»: иначе «ход по клетке не применён» неотличимо от «применили не тот ход».
        _co = None
        for _k, _v in as_dict((obs or {}).get("city")).items():
            if str(_k) == str(cid):
                _co = _v
                break
        _co = as_dict(_co) or {}
        def _f(v):  # noqa: E306 — местный: `_num` здесь не в области видимости
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        _LAST_TILE_SENT[str(cid)] = {
            "name": name, "obs": _co,
            "food": _f(_co.get("prod_food")),
            "shield": _f(_co.get("prod_shield")),
            "trade": _f(_co.get("prod_trade"))}
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        print(f"  [клетка-ход] город {cid}: {name} (перенесённая оценка +{gain:.1f})", flush=True)
    return ("city", cid, name)


def _city_tile_gains_from_rules(city_id, cands, obs=None) -> dict:
    """Выигрыш постановки/снятия жителя по ПРАВИЛАМ мира — когда своих чисел нет (§13.292).

    Числа: выходы клетки из правил (`tile_outputs_from_rules`) и ценность перенесённым
    `city_tile_value` (`infracache.c:293`). Порядок «снять плохую → занять лучшую» — его:
    у клиента `city_work` недействителен без свободного горожанина
    (`city/city_actions.py:150`), поэтому снятие оправдано только лучшей свободной клеткой.

    Возвращает `{имя действия: выигрыш}`. Пустой словарь, если данных нет: молчание обязано
    быть отличимо от нуля.
    """
    obs = obs if isinstance(obs, dict) else _LAST_OBS
    if not isinstance(obs, dict):
        _city_tile_diag("нет наблюдения")
        return {}
    try:
        from brain.ai_default.city_tiles import (
            parse_city_tile_action, tile_value_from_rules, unwork_gain, work_gain,
            workable_offsets,
        )
        from env.terrain_work import tile_terrain_extras
    except Exception as _exc:  # noqa: BLE001
        _city_tile_diag(f"импорт упал: {_exc!r}")
        return {}

    _cities = as_dict(obs.get("city")) or {}
    # Ключи записи города приходят ЦЕЛЫМИ числами (измерено: ключи ['int']), а id из имени
    # действия — строкой. Ищем все три вида, иначе дверь чисел пустеет на ровном месте.
    rec = _cities.get(city_id)
    if rec is None:
        for _key in (str(city_id), int(city_id) if str(city_id).lstrip("-").isdigit() else None):
            if _key is not None and _key in _cities:
                rec = _cities[_key]
                break
    if not isinstance(rec, dict) or rec.get("x") is None or rec.get("y") is None:
        _city_tile_diag(f"город {city_id} не найден среди {list(_cities)[:6]} (ключи "
                        f"{[type(k).__name__ for k in list(_cities)[:3]]})")
        return {}
    cx, cy = int(rec["x"]), int(rec["y"])
    map_obs = as_dict(obs.get("map")) or {}

    # ── §13.316: ценность клетки — ЕГО ВЗВЕШЕННАЯ СУММА УПРАВЛЯЮЩЕГО (`cm.c`), а не мера
    # рабочего (`city_tile_value`, `infracache.c:293`). Это РАЗНЫЕ решения у него: клетки
    # жителей выбирает управляющий, клетку для улучшения — советник рабочих.
    # Измерено на числах живого пути: расстановки различаются в 32 из 48 наблюдений, и всякий
    # раз у управляющего излишек еды ВЫШЕ (суммарно +32). Причина видна в весах: на городе,
    # растущем до второго размера, у него пища весит 20 против 5 у щитов (`cityturn.c:325-341`),
    # а у меры рабочего 30 против 17 — поэтому она берёт щиты там, где он берёт еду.
    from brain.ai_default import city_manager as _cm

    def _f(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    _size = int(_f(rec.get("size"), 1) or 1)
    _stock = _f(rec.get("food_stock"), 0.0) or 0.0
    _granary_full = _stock >= float(_cm.granary_size(_size))
    _factor = float(_cm.food_factor(_size, _granary_full))
    _trade = _f(rec.get("prod_trade"), 0.0) or 0.0
    _sci_out, _gold_out = _f(rec.get("science")), _f(rec.get("gold"))
    if _trade > 0.0 and _sci_out is not None and _gold_out is not None:
        _sci_rate, _gold_rate = _sci_out / _trade, _gold_out / _trade
    else:
        _sci_rate = _gold_rate = 0.0

    def _outputs(dx: int, dy: int):
        """Выходы клетки по правилам и с её улучшениями — те же числа, что видит решение."""
        try:
            from brain.ai_default.tile_outputs import tile_outputs_from_rules
            terrain, extras = tile_terrain_extras(map_obs, cx + dx, cy + dy)
        except Exception:  # noqa: BLE001
            return None
        return tile_outputs_from_rules(terrain, extras)

    def _value(dx: int, dy: int):
        got = _outputs(dx, dy)
        if got is None:
            return None
        food, shield = float(got[0]), float(got[1])
        trade = float(got[2]) if len(got) > 2 else 0.0
        # Торговля делится ставками города — как в `dai_city_want`: роскошь веса не имеет.
        return _cm.score(food, shield, trade * _gold_rate, trade * _sci_rate,
                         _size, _granary_full)

    def _food(dx: int, dy: int):
        """ЕДА клетки по правилам — нужна для условия годности (см. ниже)."""
        got = _outputs(dx, dy)
        return None if got is None else float(got[0])

    # Какие клетки заняты: говорит сам стенд — он предлагает снятие именно с занятых.
    worked, free_offered = {}, {}
    for c in cands or ():
        if str(c.get("ctrl_type")) != "city" or str(c.get("actor_id")) != str(city_id):
            continue
        name = str(c.get("action_name") or "")
        parsed = parse_city_tile_action(name)
        if parsed is None:
            continue
        _idx, dx, dy = parsed
        if name.startswith("city_unwork_"):
            worked[name] = _value(dx, dy)
        elif name.startswith("city_work_"):
            free_offered[name] = _value(dx, dy)

    # Свободные клетки: городской радиус минус занятые. Радиус — правило движка
    # (`common/map.c:628`, `common/map.h:397`).
    taken = {(parse_city_tile_action(n)[1], parse_city_tile_action(n)[2]) for n in worked}
    free_values = [v for (dx, dy) in workable_offsets(rec.get("city_radius_sq"))
                   if (dx, dy) not in taken and (v := _value(dx, dy)) is not None]
    free_values += [v for v in free_offered.values() if v is not None]

    gains = {}
    for name, value in worked.items():
        gains[name] = unwork_gain(value, free_values)
    best_worked = max([v for v in worked.values() if v is not None], default=None)
    for name, value in free_offered.items():
        gains[name] = work_gain(value, best_worked)
    # ── ГОДНОСТЬ: ОН ОТБРАСЫВАЕТ ГОЛОДНЫЙ ВАРИАНТ ЦЕЛИКОМ, ДО СРАВНЕНИЯ ВЫГОДЫ ──
    #     `common/aicore/cm.c:623`:
    #       if (surplus[stat_index] < parameter->minimal_surplus[stat_index]) {
    #         fitness.sufficient = FALSE;
    #       }
    #     Без этого условия мы выбрали бы клетку со щитами и без еды: измерено — город
    #     погиб от голода («Famine destroys … entirely.»), потому что жителя сняли в
    #     специалиста, и еда стала нулевой. Веса без годности — половина его правила.
    # ── ГОДНОСТЬ ПО ЕГО ПОРОГУ И ЕГО ПОВТОР ПРИ НЕУДАЧЕ (§13.316) ──
    # Порог: `cityturn.c:346-350` — `minimal_surplus[O_FOOD]` равен 1, а при полной житнице 0.
    # Прежде мы отбрасывали только ГОЛОДНЫЕ варианты («излишек < 0»), то есть допускали
    # расстановку с излишком 0 там, где он требует 1, — а именно излишек 0 и означал застой.
    # Повтор: `cityturn.c:430-434` — если ни один вариант порог не проходит, он ПОВТОРЯЕТ с
    # ослабленными порогами (пища 0, щиты 0), а не оставляет город без решения.
    food_blocked = {}
    _surplus = rec.get("surplus_food")
    if _surplus is not None:
        try:
            _surplus = float(_surplus)
        except (TypeError, ValueError):
            _surplus = None
    if _surplus is not None:
        _after = {}
        for _name in list(gains):
            _parsed = parse_city_tile_action(_name)
            if _parsed is None:
                continue
            _f = _food(_parsed[1], _parsed[2])
            if _f is None:
                continue
            _after[_name] = _surplus - _f if _name.startswith("city_unwork_") else _surplus + _f
        _need = 0.0 if _granary_full else float(_cm.MIN_SURPLUS_FOOD)
        _kept = {n for n, v in _after.items() if v >= _need}
        _relaxed = False
        if not _kept and _after:
            # ЕГО ПОВТОР: пороги ослаблены до нуля — но голодный вариант не берём и здесь.
            _kept = {n for n, v in _after.items() if v >= 0.0}
            _relaxed = True
        for _name in list(gains):
            if _name in _after and _name not in _kept:
                food_blocked[_name] = _after[_name]
                gains.pop(_name)
        if (_food_blocked_seen := (food_blocked or _relaxed)) and os.environ.get(
                "DOF_TILE_DEBUG") == "1":
            print(f"  [клетка-годность] город {city_id}: порог {_need:g}"
                  f"{' → ПОВТОР с ослабленными (его `cityturn.c:430-434`)' if _relaxed else ''}; "
                  f"отброшено {len(food_blocked)} — "
                  f"{ {k: round(v, 1) for k, v in food_blocked.items()} } "
                  f"(при излишке {_surplus:g}, житница {'полна' if _granary_full else 'не полна'})",
                  flush=True)
    if not gains:
        _city_tile_diag(f"город {city_id}: все варианты клетки голодные — хода нет")
    if os.environ.get("DOF_TILE_DEBUG") == "1" and gains:
        print(f"  [клетка-правила] город {city_id}: занято {len(worked)}, свободно "
              f"{len(free_values)}; выигрыши "
              f"{ {k: round(v, 1) for k, v in gains.items()} }", flush=True)
    return gains


def _tile_score_of(ctx, ctrl_type, action_name, actor_id=None):
    """Δ веса ЕГО управляющего для перевода жителя — или `None`, если это не клетка.

    Шкалы не смешиваются: это число сравнивается ТОЛЬКО с числами того же рода (прирост
    взвешенной суммы), а не с опциями и не с приростом DoF.
    """
    if ctx is None or str(ctrl_type) != "city":
        return None
    name = str(action_name or "")
    if not (name.startswith("city_work_") or name.startswith("city_unwork_")):
        return None
    getter = getattr(ctx, "tile_scores", None)
    if getter is None:
        if os.environ.get("DOF_TILE_DEBUG") == "1":
            print(f"  [клетка-отладка] у контекста нет tile_scores (ctx={type(ctx).__name__})",
                  flush=True)
        return None
    # Id города берётся у АКТЁРА, а не из имени действия: измерено, что число в
    # `city_unwork_<n>_<dx>_<dy>` — не id города (`city_unwork_11_...` при наших городах
    # 121 и 126), а индекс клетки в постановке города; иначе дверь его чисел пустеет.
    if actor_id is None:
        return None
    try:
        rows = getter(str(actor_id))
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("DOF_TILE_DEBUG") == "1":
            print(f"  [клетка-отладка] {name}: его числа упали — "
                  f"{type(exc).__name__}: {exc}", flush=True)
        return None
    if os.environ.get("DOF_TILE_DEBUG") == "1":
        print(f"  [клетка-отладка] {name}: строк его чисел {len(rows or ())}; "
              f"контекст {type(ctx).__name__}", flush=True)
    for act, gain in rows or ():
        if str(act) == name:
            return float(gain)
    if os.environ.get("DOF_TILE_DEBUG") == "1":
        print(f"  [клетка-отладка] {name}: в его числах не значится (строк {len(rows or ())})",
              flush=True)
    return None


def _filters_name(name) -> str:
    """Имя текущего предмета для следа — как есть, без подстановок."""
    return repr(name)


def _is_wonder_name(name: str) -> bool:
    """Чудо ли это — по роду, прочитанному из правил мира.

    Мир различает роды (`Improvement`, `GreatWonder`, `SmallWonder`, `Special`), поэтому
    спрашиваем у мира, а не у списка имён: список имён чудо не выдаёт (измерено — `Colossus`
    попадал в кандидаты как обычная постройка).
    """
    try:
        from env.rules_costs import BUILDING_COST
        genus = str((BUILDING_COST.get(str(name)) or {}).get("genus") or "")
        return genus in ("GreatWonder", "SmallWonder")
    except Exception:  # noqa: BLE001
        return False


def _wonder_city_id(obs) -> object:
    """Город чудес — его правило (`server/advisors/advbuilding.c:195`).

    Дословно у него (`ai/default/daicity.c:1972`): «Only wonder city should build wonders!» —
    во ВСЕХ остальных городах желание строить чудо обнуляется (`building_want = 0`). Сам
    город чудес он выбирает по `value = pcity->surplus[O_SHIELD]` (вдвое меньше, если рядом
    океан; плюс «даунтаун» и города материка при носителе-помощнике; минус четверть при
    угрозе на материке).

    Из наблюдения читается ПЕРВОЕ слагаемое — щиты города; остальные требуют данных,
    которых у нас нет. Это названный пробел, а не подстановка нуля: отсутствие «даунтауна»
    не делает город чудес отсутствующим.
    """
    best_id, best_value = None, None
    for cid, rec in ((obs or {}).get("city") or {}).items():
        if not isinstance(rec, dict):
            continue
        value = float(rec.get("surplus_shield") or 0.0)
        if best_value is None or value > best_value:
            best_id, best_value = cid, value
    return best_id


def _whoami_probe(env_getter):
    """§13.381: кто мы для клиента и что у него в хранилище городов."""
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", env), "civ_controller", None)
        pc = getattr(ctl, "player_ctrl", None)
        cc = getattr(ctl, "city_ctrl", None)
        mine = getattr(pc, "my_player_id", None)
        pl = getattr(getattr(pc, "players", None), "get", None)
        me = None
        try:
            me = pl(mine) if callable(pl) else None
        except Exception:  # noqa: BLE001
            me = None
        cities = getattr(cc, "cities", None)
        print(f"  [кто-мы] my_player_id={mine!r}, наш игрок={str(me)[:80]!r}, город_ctrl городов={len(cities) if isinstance(cities, dict) else cities!r}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  [кто-мы] не вышло: {type(exc).__name__}: {exc}", flush=True)
def _my_index(env_getter) -> int:
    """Номер нашего игрока на сервере (`my_player_id` клиента); §13.383."""
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", env), "civ_controller", None)
        return int(getattr(getattr(ctl, "player_ctrl", None), "my_player_id", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0

def _founder_want_of(obs, rec, cities_xy, mindist: int = 2) -> float:
    """ЕГО `founder_want` для города (`ai/default/daisettler.c:1316`, `daicity.c`).

    Это ЛУЧШИЙ результат основания рядом с городом: он считает его как виртуальный поселенец в
    центре города и берёт максимум по площадкам. Условия отбора — его же: клетка должна
    допускать город (`city_can_be_built_here` → наша `terrain_allows_city`), не быть ближе
    `citymindist` к уже имеющимся городам и давать неотрицательный избыток еды (`food_surplus`).
    Ноль значит «этому городу идти некуда» — тогда поселенца он не заказывает.
    """
    try:
        cx, cy = int(rec.get("x")), int(rec.get("y"))
    except Exception:  # noqa: BLE001
        return 0.0
    best = 0.0
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            x, y = cx + dx, cy + dy
            try:
                from brain.ai_default.founder_destination import terrain_allows_city as _tac
                if not _tac(x, y):
                    continue
            except Exception:  # noqa: BLE001
                continue
            if any(max(abs(x - int(a)), abs(y - int(b))) < int(mindist)
                   for a, b in (cities_xy or ())):
                continue
            try:
                from env.site_eval import evaluate_site as _ev_site
                ev = _ev_site(obs, x, y, size=1)
            except Exception:  # noqa: BLE001
                continue
            if float(getattr(ev, "food_surplus", 0.0) or 0.0) <= 0.0:
                continue
            best = max(best, float(ev.food) + float(ev.shields) + float(ev.trade))
    return best


_FOUNDER_CACHE: dict = {}

#: Причины, по которым рабочий не нашёл работу (прибор `DOF_WORK_DEBUG=1`).
_WORK_DIAG: dict = {}

#: Почему кандидат на смену производства не прошёл фильтр (§13.477).
_PORDFILT: dict = {}


def _founder_want_cached(obs, rec, cities_xy, mindist: int, turn: int) -> float:
    """Желание поселенца С КЭШЕМ — как у него (`ai/default/daicity.c:926-936`).

    Он пересчитывает `contemplate_new_city` не каждый ход, а раз в
    `fc_rand(AI_CITY_RECALC_SPEED) + AI_CITY_RECALC_SPEED` ходов (`AI_CITY_RECALC_SPEED = 5`),
    и сам комментирует: «This means AI is not very opportunistic if there happens to open up spot
    for a new city». Мы пересчитывали каждый ход — то есть были оппортунистичнее его.
    """
    import random as _rnd
    cid = rec.get("id") if isinstance(rec, dict) else None
    slot = _FOUNDER_CACHE.get(cid)
    if slot is not None and int(turn) < int(slot[0]):
        return float(slot[1])
    want = float(_founder_want_of(obs, rec, cities_xy, mindist))
    _FOUNDER_CACHE[cid] = (int(turn) + _rnd.randrange(5) + 5, want)
    return want


    """ЕГО `founder_want` для города (`ai/default/daisettler.c:1316`, `daicity.c`).

    Это ЛУЧШИЙ результат основания рядом с городом: он считает его как виртуальный поселенец в
    центре города и берёт максимум по площадкам. Условия отбора — его же: клетка должна
    допускать город (`city_can_be_built_here` → наша `terrain_allows_city`), не быть ближе
    `citymindist` к уже имеющимся городам и давать неотрицательный избыток еды (`food_surplus`).
    Ноль значит «этому городу идти некуда» — тогда поселенца он не заказывает.
    """
    try:
        cx, cy = int(rec.get("x")), int(rec.get("y"))
    except Exception:  # noqa: BLE001
        return 0.0
    best = 0.0
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            x, y = cx + dx, cy + dy
            try:
                from brain.ai_default.founder_destination import terrain_allows_city as _tac
                if not _tac(x, y):
                    continue
            except Exception:  # noqa: BLE001
                continue
            if any(max(abs(x - int(a)), abs(y - int(b))) < int(mindist)
                   for a, b in (cities_xy or ())):
                continue
            try:
                from env.site_eval import evaluate_site as _ev_site
                ev = _ev_site(obs, x, y, size=1)
            except Exception:  # noqa: BLE001
                continue
            if float(getattr(ev, "food_surplus", 0.0) or 0.0) <= 0.0:
                continue
            best = max(best, float(ev.food) + float(ev.shields) + float(ev.trade))
    return best


def _city_size_of(rec: dict, save_fields: dict | None, cid) -> float | None:
    """Размер города: сперва из наблюдения, потом из сейва (§13.419)."""
    for _src in (rec, (save_fields or {}).get(str(cid)),
                 (save_fields or {}).get(str((rec or {}).get("id")))):
        if not isinstance(_src, dict):
            continue
        try:
            if _src.get("size") is not None:
                return float(_src["size"])
        except (TypeError, ValueError):
            continue
    return None


def _current_build_of(rec) -> str | None:
    """Имя текущей постановки города из сейва — для правила §13.196.

    Правило владельца: начатое производство доводится до конца. Проверка нужна в «аварийных»
    ветвях, которые возвращают заказ НАПРЯМУЮ, минуя `_hold_production_candidates` (строка 3861).
    Измерено §13.519: город менял постановку четыре раза за партию (Granary → Settlers → Granary),
    теряя вложенные щиты (22 → 9).
    """
    try:
        name = rec.get("currently_building_name") if isinstance(rec, dict) else None
    except Exception:  # noqa: BLE001
        return None
    return str(name) if name else None


def _first_legal_build(info: dict, cid, avoid: tuple[str, ...] = (),
                       size: float | None = None) -> str | None:
    """Первая законная постановка города, кроме запрещённых (§13.419).

    Берём ИМЕННО то, что мир предлагает городу (`info['available_actions']['city']`), — ничего не
    выдумываем. Предпочитаем `Coinage`: в маске стенда это единственная невоенная и не
    расходующая население постановка, а поселенца строить городу нельзя (см. §13.419).
    """
    try:
        acts = ((info or {}).get("available_actions") or {}).get("city") or {}
        one = acts.get(str(cid)) or acts.get(cid) or {}
        names = [str(k)[len("produce_"):] for k, v in dict(one).items()
                 if v and str(k).startswith("produce_")]
    except Exception:  # noqa: BLE001
        if os.environ.get("DOF_TABLE_DEBUG") == "1":
            print("  [таблица] город " + str(cid) + ", размер " + str(size) + " → " + str(None), flush=True)
        return None
    names = [n for n in names if n not in avoid]
    if not names:
        if os.environ.get("DOF_TABLE_DEBUG") == "1":
            print("  [таблица] город " + str(cid) + ", размер " + str(size) + " → " + str(None), flush=True)
        return None
    # §13.427: порядок предпочтения — КАК У НЕГО в середине партии. Замер сейва 60-го хода: его
    # города размера 1-3 строят City Walls (8 из 8 у игрока 1), Granary и Great Wall, и только
    # постройки. Прежде мы брали `Coinage` первым и не давали городу ни роста, ни защиты.
    # §13.445: порядок построек — ПО РАЗМЕРУ ГОРОДА, из наблюдения его очередей (§13.444, 100 ходов):
    #   размер 1: City Walls, Archers        размер 4: Library, Great Library, Caravan, City Walls
    #   размер 2: City Walls, Granary, …     размер 5: Pikemen, Caravan, Colosseum, City Walls, Temple
    #   размер 3: City Walls, Granary, …     размер 6+: Caravan, Diplomat, Marketplace, Library, Temple
    # Наш прежний набор (§13.427) я собрал из очередей 60-го хода и он зависит от хода: к 100-му у
    # него в очереди Colosseum, Caravan, Courthouse, а мы, исчерпав короткий список, уходили в
    # Phalanx и Coinage — город перестал работать на рост (замер s1455: он 13 городов размерами 4–8,
    # мы 7 городов размерами 1–5).
    _by_size = {
        1: ("City Walls", "Archers", "Barracks", "Granary", "Coinage"),
        2: ("City Walls", "Granary", "Workers", "Barracks", "Library", "Temple", "Marketplace",
            "Coinage"),
        3: ("City Walls", "Granary", "Workers", "Library", "Courthouse", "Temple", "Marketplace",
            "Barracks", "Coinage"),
        4: ("Library", "Caravan", "Workers", "City Walls", "Granary", "Barracks", "Marketplace",
            "Temple", "Coinage"),
        5: ("Caravan", "Colosseum", "Workers", "City Walls", "Temple", "Marketplace", "Library",
            "Granary", "Coinage"),
    }
    # §13.448: `Workers` добавлены по наблюдению его очередей (§13.445): у него рабочие — обычная
    # постройка городов размера 2–3 (Workers 5 на размере 2). Без рабочих у нас нет ни дорог
    # (торговля), ни ирригации (еда), то есть не запускается его цикл
    # «население → торговля → технологии → постройки → население» (§13.447).
    _size_now = size
    _prefs = list(_by_size.get(int(_size_now or 0)) or ()) if _size_now else []
    _prefs += ["City Walls", "Granary", "Workers", "Temple", "Marketplace", "Library", "Barracks",
               "Caravan", "Colosseum", "Courthouse", "Coinage"]
    # §13.577: `City Walls` стоит ПЕРВЫМ в списке предпочтений, а стоит 120 щитов. Замер на T60
    # (партия gg1): три наших города из пяти строили City Walls со щитами 2, 4 и 22 — при 2-4
    # щитах в ход это десятки ходов, то есть город заперт до конца партии и поселенца не даст.
    # Он в это же время доводит число городов с 8 до 12. Под флагом убираем City Walls из списка;
    # по умолчанию поведение прежнее, старое остаётся контрольной рукой A/B.
    if os.environ.get("DOF_NO_WALLS") == "1":
        _prefs = [p for p in _prefs if p != "City Walls"]
    # §13.606: вариант «Granary первой, City Walls на месте» (DOF_GRANARY_FIRST) проверен серией 7x60
    # и оказался ХУЖЕ снятия стен: рост 14 против 9, города 5 против 6, население 9 против 11.
    # Значит дело не в том, что City Wall занимает первое место в списке, а в том, что 120 щитов,
    # вложенных в стены, уходят из роста. Флаг убран, как и прочие отвергнутые (§13.562, §13.584).
    # §13.508 (проба, под прибором): ЕГО правило поселенца — город, у которого есть куда идти
    # (`founder_want > 0`), заказывает поселенца, а не монету и не казармы. Проверяем это прямой
    # вставкой поселенца в начало списка: у города размера 1 поселенец невозможен (§13.419).
    if os.environ.get("DOF_SETTLER_FIRST") == "1" and _size_now and float(_size_now) >= 2.0:
        _prefs = ["Settlers"] + _prefs
    for pref in _prefs:
        if pref in names:
            if pref == "Coinage" and os.environ.get("DOF_COINAGE_DEBUG") == "1":
                # §13.527: прибор — ПОЧЕМУ выбран простой. Без него ветвь приходилось угадывать.
                print("  [монета] город " + str(cid) + ", размер " + str(size)
                      + ", поселенец в предложении: " + ("да" if "Settlers" in names else "НЕТ")
                      + ", первые предпочтения: " + str(_prefs[:7]), flush=True)
            if os.environ.get("DOF_TABLE_DEBUG") == "1":
                print("  [таблица] город " + str(cid) + ", размер " + str(size) + " → " + str(pref), flush=True)
            return pref
    if os.environ.get("DOF_TABLE_DEBUG") == "1":
        print("  [таблица] город " + str(cid) + ", размер " + str(size) + " → " + str(names[0]), flush=True)
    return names[0]


def _order_city_production(env_getter, username, obs=None, info=None, dof_state=None,
                          extractor=None):
    """§13.385: заказ производства ГОРОДУ КЛИЕНТА (его же номером), а не номером из сейва.

    Номер города в сейве серверный (121 и т.п.); `env.step` ждёт номер города КЛИЕНТА
    (`city_ctrl.cities`). Поэтому берём города прямо у клиента и фильтруем по владельцу.
    """
    st = globals().setdefault("_CITY_ORDER", {"tried": 0})
    # §13.397: помним, каким городам заказ уже отдан В ЭТОМ ХОДУ. Сейв обновляется раз в ход,
    # поэтому без этой памяти один и тот же город получал заказ в каждой попытке, а прочие
    # города в это время отдавались прогнозу — он ставил им Barracks/Coinage/Phalanx, и
    # расширение вставало (замер r715: за 80 ходов основано 4 города против 9-10 у него).
    _ord_mem = globals().setdefault("_ORDERED_THIS_TURN", {})
    _turn_now = 0
    try:
        _turn_now = int((info or {}).get("turn") or 0) if isinstance(info, dict) else 0
    except (TypeError, ValueError):
        _turn_now = 0
    # §13.428: ход берём из СЕЙВА, а не только из наблюдения. Замер s1170: поле `turn` в
    # наблюдении приходило пустым, `_turn_now` не менялся, память `_ord_mem` не сбрасывалась —
    # и после первого же прохода НИ ОДИН город больше не получал заказа. Следствие в сейве
    # 60-го хода: основаны два города на 4-м ходу, оба строят `Coinage`, юнитов трое
    # (Explorer и два Workers), поселенцев нет вовсе. Это же объясняет, почему трасса очередей
    # обрывалась на 11-м ходу. Ход из сейва — та же мера, что и в трассе.
    if not _turn_now:
        try:
            from env.map_from_save import fetch_newest_save as _fs_t0
            _m0 = re.search(r"^turn=(\d+)", (_fs_t0(str(username or "")) or ""), re.M)
            if _m0:
                _turn_now = int(_m0.group(1))
        except Exception:  # noqa: BLE001
            pass
    if _ord_mem.get("turn") != _turn_now:
        _ord_mem.clear()
        _ord_mem["turn"] = _turn_now
        # §13.428: счётчик попыток тоже обнуляем на новом ходу. Прежде он рос за ВСЮ партию
        # (`>= 80` → `return None`), и после восьмидесятой попытки заказы прекращались навсегда.
        st["tried"] = 0
    if st["tried"] >= 80:  # §13.388: заказов много — городов и ходов больше
        return None
    try:
        env = env_getter()
        ctl = getattr(getattr(env, "unwrapped", env), "civ_controller", None)
        mine = int(getattr(getattr(ctl, "player_ctrl", None), "my_player_id", 0) or 0)
        cities = getattr(getattr(ctl, "city_ctrl", None), "cities", None)
        if not isinstance(cities, dict) or not cities:
            return None
        ours = {cid: rec for cid, rec in cities.items()
                if isinstance(rec, dict) and int(rec.get("owner", mine)) == mine}
        if not ours:
            return None
        # §13.417: прежде при шести и более городах стоял `return None` — и БОЛЬШЕ НИКАКИХ заказов.
        # Без заказа мир достраивает то, что стоит по умолчанию, а по умолчанию первым идёт военный
        # юнит: замер r980 — у нас 10 `Warriors` при 4 городах и размере 1.5, у сторон-ИИ военных 0.
        # `_settlers_wanted` ниже даёт 0 — поселенцев не заказываем),
        # чтобы ни один город не оставался без решения.
        # §13.418: отношения из свежего сейва — их требует ЕГО проверка опасности
        # (`adv_is_player_dangerous`, `server/advisors/advdata.c:1103`) перед перебором чужих
        # юнитов. Провайдер задаём на каждом ходу: сейв обновляется раз в ход.
        try:
            from env.diplomacy_from_save import set_provider as _set_dip
            from env.map_from_save import fetch_newest_save as _fns_d
            if username:
                def _dip_text(_u=str(username)):
                    return _fns_d(_u)
                _set_dip(_dip_text)
        except Exception:  # noqa: BLE001
            pass
        _save_build = {}
        # §13.433: избыток еды наших городов по сейву (нижняя оценка, без улучшений клеток).
        _save_surplus: dict[str, float] = {}
        try:
            # §13.420: КОГДА ЕГО ГОРОДА СТРОЯТ ПОСЕЛЕНЦЕВ — из сейва, по всем сторонам, каждые
            # 5 ходов. Без этого «подгонять порог роста» пришлось бы своим числом, а нужно ЕГО
            # отношением: при каком размере города у него уходит поселенец.
            if os.environ.get("DOF_AI_CITY_TRACE") == "1":
                from env.city_vector import parse_player_section as _pps_t
                from env.map_from_save import fetch_newest_save as _fs_t
                _tt = _fs_t(str(username or "")) if username else None
                _turn_t = int((info or {}).get("turn") or 0) if isinstance(info, dict) else 0
                if _tt:
                    _m_t = re.search(r"^turn=(\d+)", _tt, re.M)
                    if _m_t:
                        _turn_t = int(_m_t.group(1))
                if _tt:
                    _parts = []
                    for _pl in range(6):
                        try:
                            _cs_t = _pps_t(_tt, _pl)
                        except Exception:  # noqa: BLE001
                            continue
                        if not _cs_t:
                            continue
                        _b = {}
                        for _c_t in _cs_t.values():
                            _n_t = str(_c_t.get("currently_building_name") or "?")
                            _b.setdefault(_n_t, []).append(float(_c_t.get("size") or 0))
                        _parts.append(f"игрок {_pl}: городов {len(_cs_t)}, " + ", ".join(
                            f"{k}×{len(v)} (размеры {sorted(set(v))})"
                            for k, v in sorted(_b.items())))
                    if _parts:
                        _body_t = " | ".join(_parts)
                        _seen_t = globals().setdefault("_AI_CITY_TRACE_SEEN", set())
                        # §13.420: ключ — само содержимое (какие постановки при каких размерах),
                        # без номера хода: номер из сейва берётся из кэша и повторяется, из-за
                        # чего вся история, кроме первого показа, пропадала.
                        if _body_t not in _seen_t:
                            _seen_t.add(_body_t)
                            print(f"  [его-города] ход {_turn_t}: {_body_t}", flush=True)
            from env.city_vector import parse_player_section as _pps
            from env.map_from_save import fetch_newest_save as _fs
            _txt = _fs(str(username or "")) if username else None
            if _txt:
                _rows_save = _pps(_txt, mine)
                for _r in _rows_save.values():
                    _save_build[str(_r.get("id"))] = str(_r.get("currently_building_name") or "")
                # §13.433: ЕГО условие для поселенца — `pcity->surplus[O_FOOD] >=
                # utype_upkeep_cost(founder, pplayer, O_FOOD)` (`ai/default/daicity.c:560`), то есть
                # город может отдать поселенца, только если прокормит его. Считаем избыток еды по
                # ОБРАБОТАННЫМ клеткам из сейва (`worked0000…`) и правилам мира. Улучшений
                # (ирригация, шахты) сейв не хранит, поэтому это нижняя оценка — и мы её помечаем
                # как таковую: неизвестное не выдаём за ноль.
                try:
                    from env.map_from_save import parse_map_rows as _pmr
                    from brain.ai_default.tile_outputs import tile_outputs_from_rules as _tor
                    _terr_sv = _pmr(_txt)
                    _wk_sv: dict[str, list[tuple[int, int]]] = {}
                    for _mw in re.finditer(r'^worked(\d{4})="([^"]*)"$', _txt, re.M):
                        _yw = int(_mw.group(1))
                        for _xw, _vw in enumerate(_mw.group(2).split(',')):
                            if _vw not in ("-", ""):
                                _wk_sv.setdefault(_vw, []).append((_xw, _yw))
                    for _cw, _cells in _wk_sv.items():
                        _food_w = 0.0
                        _known_w = True
                        for _xw, _yw in _cells:
                            _ow = _tor(_terr_sv.get((_xw, _yw), "")) if (_xw, _yw) in _terr_sv else None
                            if _ow is None:
                                _known_w = False
                                continue
                            _food_w += float(_ow[0])
                        if not _known_w:
                            continue
                        _sz_w = float((_rows_save.get(_cw) or {}).get("size") or 1.0)
                        # §13.441: КЛЕТКА ГОРОДА считается всегда и бесплатно — её в `worked0000…`
                        # нет (проверено: у id127 избыток «−1.0» при растущей на +1 за ход пище,
                        # то есть мы теряли ровно выход центральной клетки). Его управляющий центр
                        # тоже берёт первым и бесплатно (§13.432, `chosen = [(0,0)] + …`).
                        _cx_w = (_rows_save.get(_cw) or {}).get("x")
                        _cy_w = (_rows_save.get(_cw) or {}).get("y")
                        if _cx_w is not None and _cy_w is not None:
                            _oc_w = _tor(_terr_sv.get((int(_cx_w), int(_cy_w)), "")) \
                                if (int(_cx_w), int(_cy_w)) in _terr_sv else None
                            if _oc_w is not None:
                                _food_w += float(_oc_w[0])
                            else:
                                _known_w = False
                        if _known_w:
                            _save_surplus[str(_cw)] = _food_w - 2.0 * _sz_w
                    # §13.437: города ВСЕХ сторон из сейва — с координатами. Мир считает
                    # `citymindist` по всем городам карты, а клиент отдаёт список с задержкой
                    # (замер s1355: «городов известно 0»), из-за чего поселенцы шли основывать
                    # вплотную к существующим городам и получали отказ.
                    _all_cities: set[tuple[int, int]] = set()
                    for _pl in range(0, 12):
                        try:
                            for _cc in _pps(_txt, _pl).values():
                                if _cc.get("x") is not None and _cc.get("y") is not None:
                                    _all_cities.add((int(_cc["x"]), int(_cc["y"])))
                        except Exception:  # noqa: BLE001
                            continue
                    if _all_cities:
                        globals()["_SAVE_CITIES"] = _all_cities
                    # §13.440: РОСТ — хронология размеров наших городов, запаса пищи и избытка
                    # по сейву. Без неё нельзя судить, почему город не дорастает до второго
                    # размера, а на нём держится право заказывать поселенца (§13.434). Печать —
                    # один раз на ход.
                    _mg = re.search(r'^turn=(\d+)', _txt, re.M)
                    _turn_g = _mg.group(1) if _mg else None
                    _seen_g = globals().setdefault("_GROWTH_SEEN", set())
                    if _turn_g is not None and _turn_g not in _seen_g:
                        _seen_g.add(_turn_g)
                        # §13.442: ИЗБЫОК ПО НАБЛЮДЕНИЮ. Замер s1420: запас пищи рос на +1 за ход,
                        # а наша формула печатала 2.0 — клетка города то попадает в `worked`, то
                        # нет, и мы считали её дважды. Поэтому избыток берём из фактического
                        # прироста запаса пищи (размер города при этом не менялся), а расчётную
                        # формулу оставляем запасным источником. Наблюдение — характеристика
                        # мира, и оно надёжнее нашей арифметики.
                        _prev_g = globals().setdefault("_FOOD_PREV", {})
                        for _cg, _rg in _rows_save.items():
                            try:
                                _fs = float(_rg.get("food_stock") or 0)
                                _sz = float(_rg.get("size") or 1)
                            except Exception:  # noqa: BLE001
                                continue
                            _pk = str(_cg)
                            _old = _prev_g.get(_pk)
                            if _old is not None and _old[0] != _sz:
                                _old = None          # город вырос: запас обнулился, прирост неверен
                            if _old is not None:
                                _delta = _fs - float(_old[1])
                                if -8.0 <= _delta <= 8.0 and abs(_delta - round(_delta)) < 1e-6:
                                    _save_surplus[_pk] = float(round(_delta))
                            _prev_g[_pk] = (_sz, _fs)
                    if os.environ.get("DOF_GROWTH_DEBUG") == "1":
                        if _turn_g is not None and _turn_g in _seen_g:
                            _seen_print = globals().setdefault("_GROWTH_PRINTED", set())
                            if _turn_g not in _seen_print:
                                _seen_print.add(_turn_g)
                                _parts_g = [f"id{_cg} разм{_rg.get('size')} пища{_rg.get('food_stock')} "
                                            f"избыток{_save_surplus.get(str(_cg), '?')} "
                                            f"строит{_rg.get('currently_building_name')}"
                                            for _cg, _rg in _rows_save.items()]
                                print(f"  [рост] ход {_turn_g}: " + " | ".join(_parts_g), flush=True)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            _save_build = {}
        # §13.403: поселенцев должен строить РОВНО ОДИН город, остальные — по ЕГО выбору
        # (`_production_candidate`). Прежде мы требовали поселенцев от КАЖДОГО города, пока
        # городов меньше цели: города не росли вовсе (замер: население 8.5 против 37, размер
        # 1-2, и у него же города строят City Walls/Great Wall, а не одних поселенцев).
        # §13.411: но при двух-трёх городах одного источника не хватает — расширение отстаёт
        # вдвое-втрое (замер r895: 2 города против 5). Поэтому источников столько же, сколько
        # не хватает до цели: меньше четырёх городов — двух, до шести — один, дальше ни одного.
        _n_cities = len(ours)
        if os.environ.get("DOF_FOUNDER_PER_CITY") != "1":
            # §13.425 ВЫКЛЮЧЕНО по умолчанию: замер s1135/s1140 — городов стало 2 вместо 3-6
            # (поселенцы из городов размера 2 снимают население, и город снова 1), счёт упал до
            # ×3.0/×2.4 при прежних ×2.2-×2.6. Причина в СКОРОСТИ выпуска поселенцев (у нас
            # 1.25 щита на город против 3.7-4.4), а не в том, сколько городов их заказывают:
            # пока город не выпускает поселенца быстро, второй источник только съедает рост.
            _settlers_wanted = 2 if _n_cities < 4 else (1 if _n_cities < 6 else 0)
        else:
            # §13.425: ЕГО правило вместо нашего счёта. У него поселенца заказывает КАЖДЫЙ
            # город, у которого `founder_want > 0` (есть куда идти) — замер `DOF_AI_CITY_TRACE`:
            # на 10-м ходу поселенцев строят ОБА его города. Наш счёт «два источника до четырёх
            # городов» (§13.411) был нашим изобретением и оставлял нас с 3-6 городами против
            # его 9-13. Здесь считаем число городов, у которых площадка рядом есть.
            _cities_xy = [(int(_r.get("x")), int(_r.get("y")))
                          for _r in ours.values() if _r.get("x") is not None]
            _mind5 = int(_world_citymindist(env_getter()) or 0) or 2
            _settlers_wanted = sum(
                1 for _r in ours.values()
                if _founder_want_cached(obs, _r, _cities_xy, _mind5, _turn_now) > 0.0)
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [поселенцы] городов {_n_cities}, из них с площадкой рядом "
                      f"{_settlers_wanted} (его founder_want)", flush=True)
        _settlers_now = sum(1 for _v in (_save_build or {}).values()
                            if str(_v).endswith("Settlers"))
        _any_settlers_now = _settlers_now >= _settlers_wanted
        # §13.389: ЕГО выбор производства — максимум хотелок советников (§13.364). Считаем
        # хотелку для каждого законного имени постановки и берём наибольшую.
        _ctx = None
        # §13.389/13.391: слой городов в наблюдении бывает пуст — подкладываем города КЛИЕНТА,
        # иначе контекст его выбора собрать нечем. И дополняем их числами ИЗ СЕЙВА: клиент не
        # даёт городу ни щитов/ход, ни координат, из-за чего его выбор видел только постройки
        # (замер §13.390: единственный вариант — `Barracks`).
        _save_fields = {}
        try:
            from env.city_vector import parse_player_section as _pps2
            from env.map_from_save import fetch_newest_save as _fs2
            _t2 = _fs2(str(username or "")) if username else None
            if _t2:
                for _r2 in _pps2(_t2, _my_index(env_getter)).values():
                    _save_fields[str(_r2.get("id"))] = _r2
        except Exception:  # noqa: BLE001
            _save_fields = {}
        try:
            if isinstance(obs, dict) and (_save_fields or ours):
                _city_layer = {str(_k): dict(_v) for _k, _v in (obs.get("city") or {}).items()
                               if isinstance(_v, dict)}
                for _k, _v in ours.items():
                    _city_layer.setdefault(str(_k), dict(_v))
                for _k, _v in list(_city_layer.items()):
                    _sv = _save_fields.get(str(_v.get("id", _k))) or {}
                    for _dst, _src in (("x", "x"), ("y", "y"),
                                       ("shield_stock", "shield_stock"),
                                       ("prod_shield", "last_turns_shield_surplus"),
                                       ("food_stock", "food_stock")):
                        if _v.get(_dst) is None and _sv.get(_src) is not None:
                            _v[_dst] = _sv.get(_src)
                _obs2 = dict(obs)
                _obs2["city"] = _city_layer
                obs = _obs2
        except Exception:  # noqa: BLE001
            pass
        if obs is not None and info is not None and dof_state is not None:
            try:
                from brain.forecast import live as _live
                _ctx = _live.build_context(obs, info, dof_state, extractor,
                    type_names=_production_names(env_getter()) or None,
                        military_names=_military_type_names(env_getter()) or None,
                        gold=_gold_of(obs, extractor))
            except Exception as _exc:  # noqa: BLE001
                print(f"  [заказ] контекст не собран: {type(_exc).__name__}: {_exc}", flush=True)
        for cid, rec in sorted(ours.items(), key=lambda kv: str(kv[0])):
            print("  [город-запись] " + str({k: (str(v)[:70]) for k, v in sorted(rec.items())
                  if k in ("owner", "size", "shield_stock", "prod_shield", "surplus_shield",
                            "production_value", "production_kind", "can_build_unit",
                            "can_build_improvement", "turn_last_built", "capital")}), flush=True)
            _names = _production_names(env_getter()) or {}
            _pv = rec.get("production_value")
            built = str(_names.get(int(_pv)) if isinstance(_pv, (int, float)) else _pv or "")
            st["tried"] += 1
            if _ctx is not None and getattr(_ctx, 'production_of', None) and len(ours) >= int(
                    os.environ.get("DOF_HIS_CHOICE_MIN", "1")):
                try:
                    _po = _ctx.production_of
                    _keys = [f'city_{cid}', f"city_{rec.get('id')}", str(cid)]  # только строки: у него ключ города — текст
                    _opt = None
                    for _k in _keys:
                        _one = _po(_k) if callable(_po) else (_po.get(_k) if hasattr(_po, 'get') else None)
                        if _one:
                            _opt = _one
                            break
                    if _opt:
                        # §13.559: КАРКАС выбора производства вместо нашего разбора списка.
                        # `_opt` — это ровно `[(имя, желание, срок)]` из `production_of`, то есть
                        # ЕГО шкала по каждому имени; адаптер раскладывает её по трём ведомствам
                        # (`advisor_adapter.split_options`), а `choose_build` решает порядком
                        # `daicity.c:250` и своими шкалами (`want_scales`). Старый разбор ниже
                        # остаётся контрольной рукой: он включается, когда флаг выключен.
                        if os.environ.get("DOF_CHOOSE_BUILD", "0") == "1":
                            try:
                                from brain.ai_default.advisor_adapter import (
                                    choose_from_options as _cfo)
                                _mil_cb = _military_type_names(env_getter()) or ()
                                _nm_cb, _want_cb = _cfo(_opt, rec, military_names=_mil_cb)
                                _first_cb = (_opt[0][0]
                                             if isinstance(_opt[0], (list, tuple)) else _opt[0])
                                if _nm_cb and _nm_cb != built:
                                    print(f"  [каркас] город {cid}: {_nm_cb!r} "
                                          f"желание {_want_cb:.3f}; старая ветвь взяла бы "
                                          f"{str(_first_cb)!r}", flush=True)
                                    return ('city', cid, f'produce_{_nm_cb}')
                                print(f"  [каркас] город {cid}: {_nm_cb!r} = {built!r} "
                                      f"(желание {_want_cb:.3f}) — очередь держим", flush=True)
                                return None
                            except Exception as _exc:  # noqa: BLE001
                                print(f"  [каркас] не посчитался, падаю на старую ветвь: "
                                      f"{type(_exc).__name__}: {_exc}", flush=True)
                        # §13.553: T12 оба города копили в Barracks (15 и 24 щита), а он город НЕ
                        # защищает — потом смена на поселенца рубила запас вдвое (24 -> 14).
                        # Казармы и монета выкидываются ВСЕГДА, независимо от защитников.
                        if os.environ.get("DOF_NO_MIL_SOFT", "1") != "0":
                            _soft = [o for o in _opt
                                     if str(o[0] if isinstance(o, (list, tuple)) else o)
                                     != "Barracks"]
                            if _soft:
                                _opt = _soft
                        # §13.538: у противников НОЛЬ военных юнитов, а `danger` за 100 ходов ни разу
                        # не поднимался выше нуля — а города строили Barracks просто потому, что
                        # в меню из 3-4 постановок это единственный «не монета». Военное из МЕНЮ
                        # убираем, когда войны нет: у встроенного ИИ защитник идёт от опасности,
                        # а не от скудости предложения.
                        if (os.environ.get("DOF_NO_MIL_MENU", "1") != "0"
                                and _city_defenders(env_getter, cid)):
                            try:
                                _mil = _military_type_names(env_getter()) or set()
                            except Exception:  # noqa: BLE001
                                _mil = set()
                            _civ = [o for o in _opt
                                    if str(o[0] if isinstance(o, (list, tuple)) else o) not in _mil
                                    # §13.538-правка: `Barracks` — ПОСТРОЙКА, а `_military_type_names`
                                    # перечисляет только юнитов; фильтр её не ловил (94 заказа за 60 ходов).
                                    and str(o[0] if isinstance(o, (list, tuple)) else o) not in ("Barracks", "Coinage")]
                            _coin = [o for o in _opt
                                     if str(o[0] if isinstance(o, (list, tuple)) else o) == "Coinage"]
                            # §13.538c: если мирного в меню не осталось (город размера 1 без
                            # поселенца), берём монету, а не казармы: казармы — это щиты в никуда.
                            if _civ:
                                _opt = _civ
                            elif _coin:
                                _opt = _coin
                        # §13.552: поселенец съедает жителя и роняет город до размера 1 — на T60 три
                        # наших города стояли на размере 1 с запасом еды 13-19, то есть крутили
                        # поселенцев вместо роста (у него города 2-3). До размера 3 поселенца не берём,
                        # если есть альтернатива: сначала город должен подрасти.
                        # §13.561: НО замер темпа основания (§13.560) показал, что города у нас
                        # почти все 1-2, и гейт <=2 глушит поселенцев почти во всех городах: мы
                        # основали 5 городов против его 9 в ТОМ ЖЕ окне ходов (1-2 ... 51-52).
                        # Под флагом опускаем гейт до <=1 — город размера 2 поселенца брать может.
                        # По умолчанию поведение прежнее; старое — контрольная рука A/B.
                        try:
                            _szc = float(rec.get("size")) if rec.get("size") is not None else None
                        except (TypeError, ValueError):
                            _szc = None
                        if _szc is not None and _szc <= 2.0:
                            _grow = [o for o in _opt
                                     if str(o[0] if isinstance(o, (list, tuple)) else o) != "Settlers"]
                            if _grow:
                                _opt = _grow
                        # §13.555: город размера 1 НЕ МОЖЕТ выпустить поселенца (некого отдавать),
                        # а заказ остаётся с прошлого размера: в замере он накопил 68 щитов при цене 40.
                        # Снимаем принудительно, даже если альтернативы в ранжированном списке нет.
                        if (os.environ.get("DOF_SIZE1_COIN", "0") != "0"
                                and _szc is not None and _szc <= 1.0
                                and str(built) == "Settlers"):
                            _coin = [o for o in _opt
                                     if str(o[0] if isinstance(o, (list, tuple)) else o) == "Coinage"]
                            if _coin:
                                _opt = _coin
                        _first = _opt[0]
                        _nm = str(_first[0] if isinstance(_first, (list, tuple)) else _first)
                        print(f"  [заказ] его выбор города {cid}: {_nm!r} (первые 3: {str(_opt[:3])[:120]})", flush=True)
                    if not globals().get('_OPT_DUMP'):
                        globals()['_OPT_DUMP'] = True
                        print(f"  [опции] все его варианты: {str(_opt)[:400]}", flush=True)
                        print(f"  [опции] не оценено у него: {str(getattr(_ctx, 'unpriced', None))[:200]}", flush=True)
                        _recs = getattr(_ctx, 'state', None)
                        print(f"  [опции] запись города как её видит он: "
                              f"{str({k: rec.get(k) for k in ('prod_shield','shield_stock','surplus_food','production_value','production_kind','size','x','y')})}", flush=True)
                        if _nm and _nm != built:
                            return ('city', cid, f'produce_{_nm}')
                        return None
                except Exception as _exc:  # noqa: BLE001
                    print(f"  [заказ] его выбор не прочёлся: {type(_exc).__name__}: {_exc}", flush=True)
                
            if False:
                try:
                    _acts2 = ((info.get('available_actions') or {}).get('city') or {})
                    _acts2 = _acts2.get(str(cid)) or _acts2.get(cid) or {}
                    _legal2 = [str(k)[len('produce_'):] for k, v in dict(_acts2).items()
                            if v and str(k).startswith('produce_')]
                    _dgr = _his_danger(obs, extractor)
                    _w = {}
                    for _n in _legal2:
                        _val = _his_production_want(_n, rec, _ctx, _dgr,
                                                defenders=_city_defenders(env_getter, rec.get("id")))
                        if _val is not None:
                            _w[_n] = float(_val)
                    if _w:
                        # §13.547: тот же фильтр военного, что и в ветви «его выбор». Без него
                        # город качался Coinage -> Barracks -> Coinage и не производил ничего:
                        # одна ветвь казармы убирала, другая ставила обратно.
                        if (os.environ.get("DOF_NO_MIL_MENU", "1") != "0"
                                and _city_defenders(env_getter, cid)):
                            try:
                                _milf = set(_military_type_names(env_getter()) or set()) | {"Barracks", "Coinage"}
                            except Exception:  # noqa: BLE001
                                _milf = {"Barracks"}
                            _w2 = {k: v for k, v in _w.items() if str(k) not in _milf}
                            if _w2:
                                _w = _w2
                        _best2 = max(_w, key=_w.get)
                        print(f"  [заказ] его хотелки города {cid}: " +
                            ', '.join(f'{k}={v:.3f}' for k, v in sorted(_w.items(), key=lambda kv: -kv[1])[:5]), flush=True)
                        if _best2 != built:
                            print(f"  [заказ] → produce_{_best2} (в очереди было {built!r})", flush=True)
                            return ('city', cid, f'produce_{_best2}')
                        print(f"  [заказ] город {cid}: его выбор совпал с очередью ({built!r}) — не трогаю", flush=True)
                        return None
                except Exception as _exc:  # noqa: BLE001
                    print(f"  [заказ] его хотелки не посчитались: {type(_exc).__name__}: {_exc}", flush=True)
            built = _save_build.get(str(cid), built)
            if _ord_mem.get(str(cid)):
                continue   # §13.397: этому городу заказ уже отдан в этом ходу
            print(f"  [заказ] город клиента {cid}: по сейву строит {built!r} (номер {rec.get('production_value')}), щитов/ход {rec.get('prod_shield')}, щитов {rec.get('shield_stock')}",
                  flush=True)
            # §13.426: ЕГО экономика смены постановки — теряется ПОЛОВИНА вложенных щитов
            # (`common/city.c:1917`: «Penalize 50% of the production»). Мы же меняли заказ при
            # каждом удобном случае, и щиты городов уходили в никуда. Замер s1140: к 60-му ходу
            # 2 города — при том что на город мы выходим ВЫШЕ его городов (щиты 2.50 против
            # 1.00-2.67, клеток 3.5 против 3.2, потолок площадки 9.0 против 8.8-9.3). Меняем
            # постановку, только если вложено не больше двух ходов — либо если очередь военная,
            # а опасных сторон нет вовсе (§13.423: тогда снятие того стоит).
            _stock6 = float(rec.get("shield_stock") or 0.0)
            _per6 = float(rec.get("prod_shield") or 0.0) or 1.0
            _cur_mil6 = str(built) in {str(_x) for _x in (_military_type_names(env_getter()) or ())}
            _danger6 = None
            try:
                from env.diplomacy_from_save import dangerous_now as _dn6
                _danger6 = _dn6(int(mine))
            except Exception:  # noqa: BLE001
                _danger6 = None
            _mil_no_danger6 = _cur_mil6 and _danger6 is not None and not _danger6
            if _stock6 > 2.0 * _per6 and not _mil_no_danger6:
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [заказ] город {cid}: вложено {_stock6:g} щитов при {_per6:g} в ход — "
                          f"постановку {built!r} НЕ меняем (смена теряет половину)", flush=True)
                continue
            if built.endswith("Settlers") or built == "Settlers":
                # §13.419: ЕГО запрет — поселенца не заказывают там, где город не может отдать
                # население: `pop_cost >= city_size_get(pcity)` (`daicity.c:788`, «We don't like
                # disbanding the city as a side effect»). Замер s1010: три наших города на 80-м
                # ходу ВСЕ размера 1 (у сторон-ИИ 2.17-2.33) — город, строящий поселенца при
                # размере 1, не растёт НИКОГДА, и такой заказ надо не «дожимать», а снимать.
                _sz1 = _city_size_of(rec, _save_fields, cid)
                _sur1 = _save_surplus.get(str(cid))
                # §13.434: ЕГО оба условия вместе, а не по отдельности:
                #   (1) `daicity.c:788` — поселенца берём не там, где `pop_cost >= city_size`,
                #       то есть город размера 1 поселенца НЕ заказывает (иначе оба наших города
                #       садятся в Settlers, ни один не растёт, и расширение кончается — это и
                #       видел замер трассы s1335: мы замерли на 2 городах с 11-го хода, он
                #       основывал 3-й, 4-й, 5-й каждые ~10 ходов);
                #   (2) `daicity.c:560` — избыток еды должен покрывать содержание поселенца.
                if (_sz1 is not None and _sz1 <= 1.0
                        and (os.environ.get("DOF_NO_HOLD_ALT") == "1"
                             or _current_build_of(rec) in (None, "Settlers"))
                        and os.environ.get("DOF_NO_SIZE_RULE") != "1"):
                    # §13.427: правило СНОВА ВКЛЮЧЕНО. Замер середины партии (сейв 60-го хода)
                    # снял противоречие §13.420: у его сторон города размера 1 строят City Walls
                    # (8 городов из 8 у игрока 1!), Granary и Great Wall, и НИ ОДИН его город
                    # поселенцев не строит — поселенцы у него были только в самой первой
                    # очереди. Наши же два города размера 1 к 60-му ходу всё ещё строят
                    # поселенцев и потому не растут (у него размеры 2-3, у нас 1).
                    # §13.565: эта ветка берёт ПЕРВУЮ законную постановку, а ею у города размера <=1
                    # оказывается Barracks — 30 щитов, то есть ~15 ходов при 2 щитах/ход. По
                    # траектории §13.563 именно тут теряются ходы 1-30. Под флагом убираем Barracks
                    # из кандидатов; по умолчанию поведение прежнее, старое — контроль A/B.
                    _av2 = (("Settlers", "Barracks") if os.environ.get("DOF_NO_BARRACKS_SZ1") == "1"
                            else ("Settlers",))
                    _alt2 = _first_legal_build(info, cid, avoid=_av2, size=_sz1)
                    if _alt2:
                        _ord_mem[str(cid)] = _alt2
                        print(f"  [заказ] город {cid} размера {_sz1:g} не может строить поселенца "
                              f"→ { _alt2!r} (его daicity.c:788)", flush=True)
                        return ("city", cid, f"produce_{_alt2}")
                # §13.396: этот город УЖЕ строит нужное — заказ отдаём следующему. Прежде здесь
                # стоял `return None`, и заказ всегда доставался первому по номеру городу, а
                # остальные (замер r695: основаны на 23, 29, 37 ходах) дожимали `Warriors`.
                continue
            if _any_settlers_now:
                # §13.423: но если город стоит на ВОЕННОМ и опасных сторон нет вовсе — заказ
                # снимаем: без этого города, чья очередь оказалась `Warriors`, так и дожимали
                # военных, пока мы расширялись. Замер s1085: 7 `Warriors`, рождённых на ходах
                # 27-41, при том что к 60-му ходу опасных сторон нет ни одной.
                try:
                    from env.diplomacy_from_save import dangerous_now as _dn3
                    _danger3 = _dn3(int(mine))
                except Exception:  # noqa: BLE001
                    _danger3 = None
                _mils3 = {str(_x) for _x in (_military_type_names(env_getter()) or ())}
                if _danger3 is not None and not _danger3 and built in _mils3:
                    _alt4 = _first_legal_build(info, cid, avoid=tuple(_mils3) + ("Barracks",),
                                              size=locals().get("_sz2"))
                    if _alt4:
                        _ord_mem[str(cid)] = _alt4
                        print(f"  [заказ] город {cid} строит военного {built!r} без опасных сторон "
                              f"→ {_alt4!r} (его adv_is_player_dangerous)", flush=True)
                        return ("city", cid, f"produce_{_alt4}")
                # §13.403: поселенцев уже строит другой город — этот город отдаём ЕГО выбору
                # (постановка прогноза ниже), иначе все города до цели роста строят только
                # поселенцев и не растут (население 8.5 против 37 у него).
                continue
            try:
                _av = (info.get("available_actions") or {}).get("city") or {}
                _acts = _av.get(str(cid)) or _av.get(cid)
                _legal = [k for k, v in (_acts or {}).items() if v] if isinstance(_acts, dict) else _acts
                print(f"  [заказ] законные действия города: {str(_legal)[:200]}", flush=True)
            except Exception as _exc:  # noqa: BLE001
                print(f"  [заказ] действия города не прочесть: {_exc}", flush=True)
            # §13.386: его же порядок — сначала защита города, потом поселенец. Без защитника город
            # забирают соседи: в серии §13.377-13.385 города росли до 6-7 и падали до 1-2.
            units = getattr(getattr(ctl, 'unit_ctrl', None), 'units', None) or {}
            _guard = 0
            for _urec in (units.values() if isinstance(units, dict) else []):
                if not isinstance(_urec, dict):
                    continue
                if int(_urec.get('homecity', -1) or -1) == int(cid) if str(cid).isdigit() else False:
                    _guard += 1
            _danger_now = 0.0
            # §13.393: опасность — ЕГО числом (`brain/ai_default/danger.py:assess_danger`:
            # чужой юнит, способный дойти и напасть), а не моим «виден чужой юнит». Замер
            # r670: при бинарном признаке мы кончаем партию с 11.5 военных против его 0.5.
            try:
                from brain.ai_default.danger import assess_danger as _assess
                _rec_d = dict(rec)
                _sv_d = _save_fields.get(str(rec.get("id"))) or {}
                for _d_dst, _d_src in (("x", "x"), ("y", "y")):
                    if _rec_d.get(_d_dst) is None and _sv_d.get(_d_src) is not None:
                        _rec_d[_d_dst] = _sv_d.get(_d_src)
                _d_info = _assess(_rec_d, obs, _my_index(env_getter)) or {}
                _danger_now = float(_d_info.get("danger") or 0.0)
            except Exception:  # noqa: BLE001
                _danger_now = _his_danger(obs, extractor) if obs is not None else 0.0
            if len(ours) >= 6 and _danger_now > 0 and _guard < 1:
                # §13.387: войско выбираем ЕГО правилом — по силам юнита из правил мира
                # (`defense_desirability`, `daimilitary.c`), среди законных постановок города.
                try:
                    from brain.ai_default.military_want import defense_desirability as _dd
                    from brain.ai_default.unit_stats import load_units as _lu
                    _units = _lu()
                    _acts = ((info.get('available_actions') or {}).get('city') or {})
                    _acts = _acts.get(str(cid)) or _acts.get(cid) or {}
                    _names = [str(k)[len('produce_'):] for k, v in dict(_acts).items()
                            if v and str(k).startswith('produce_')]
                    _mil = [n for n in _names if n in _units and (float(_units[n].get('attack') or 0)
                            + float(_units[n].get('defense') or 0)) > 0]
                    if not _mil:
                        _mil = [n for n in ('Phalanx', 'Archers', 'Warriors') if n in _units]
                    if _mil:
                        _best = max(_mil, key=lambda n: _dd(_units[n]))
                        print(f"  [заказ] город {cid}: войска нет, по силам лучший {_best!r} "
                            f"(желание {_dd(_units[_best]):.3f}, из {sorted(_mil)})", flush=True)
                        return ('city', cid, f'produce_{_best}')
                except Exception as _exc:  # noqa: BLE001
                    print(f"  [заказ] выбор войска не вышел: {type(_exc).__name__}: {_exc}", flush=True)
                print(f"  [заказ] у города {cid} нет своего войска → produce_Warriors", flush=True)
                _ord_mem[str(cid)] = "Warriors"
                return ('city', cid, 'produce_Warriors')
            _sz2 = _city_size_of(rec, _save_fields, cid)
            _sur2 = _save_surplus.get(str(cid))
            # §13.434: см. пояснение выше — его ДВА условия вместе (размер больше содержания И
            # избыток еды покрывает содержание поселенца).
            if (_sz2 is not None and _sz2 <= 1.0
                    and (os.environ.get("DOF_NO_HOLD_ALT") == "1"
                             or _current_build_of(rec) in (None, "Settlers"))
                    and os.environ.get("DOF_NO_SIZE_RULE") != "1"):
                # §13.427: см. пояснение выше — правило снова включено по умолчанию
                # (`DOF_NO_SIZE_RULE=1` выключает для честного A/B).
                # §13.419: то же правило и для НАШЕЙ постановки — городу размера 1 поселенца не
                # заказываем (он не может отдать население: `daicity.c:788`).
                _av3 = (("Settlers", "Barracks") if os.environ.get("DOF_NO_BARRACKS_SZ1") == "1"
                        else ("Settlers",))
                _alt3 = _first_legal_build(info, cid, avoid=_av3, size=_sz2)
                if _alt3:
                    _ord_mem[str(cid)] = _alt3
                    print(f"  [заказ] город {cid} размера {_sz2:g} не может строить поселенца "
                          f"→ {_alt3!r} (его daicity.c:788)", flush=True)
                    return ("city", cid, f"produce_{_alt3}")
                continue
            print(f"  [заказ] город {cid} защищён → produce_Settlers", flush=True)
            _ord_mem[str(cid)] = "Settlers"
            return ("city", cid, "produce_Settlers")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  [заказ] не вышло: {type(exc).__name__}: {exc}", flush=True)
        return None


def _order_settlers_from_save(env_getter, username):
    """§13.378: заказ производства городу по записям ходового сейва.

    Города до клиента не доходят (§13.369), а стенд действий постановки не предлагает,
    поэтому действие синтезируем сами: ("city", <id>, "produce_Settlers"). Города берём
    из вектора `c={}` сейва (§13.376). Пробуем малое число раз: если сервер откажет,
    повторять вредно (заказ города может подвесить партию).
    """
    st = globals().setdefault("_SETTLER_ORDER", {"tried": 0, "sent": 0})
    if st["tried"] >= 3:
        return None
    try:
        from env.city_vector import parse_player_section as _parse_player_section
        from env.map_from_save import fetch_newest_save as _fetch_save
        _uname = str(username or "")
        text = _fetch_save(_uname) if _uname else None
        print(f"  [заказ] сейв прочитан: {len(text) if text else 0} знаков", flush=True)
        if not text:
            return None
        _idx = _my_index(env_getter)
        _un = None
        for _ln in text.splitlines()[:4000]:
            if _ln.startswith("username="):
                _un = _ln.split("=", 1)[1].strip().strip(chr(34))
        print(f"  [заказ] наш номер игрока {_idx}, в сейве раздел 0 = {_un!r}", flush=True)
        cities = _parse_player_section(text, _idx)
        if len(cities) >= 3:

            print(f"  [заказ] городов уже {len(cities)} — заказ поселенца не нужен", flush=True)
            st["tried"] = 3
            return None
        for cid, rec in sorted(cities.items()):
            built = str(rec.get("currently_building_name") or "")
            if built == "Settlers":
                print(f"  [заказ] город {cid} {rec.get("name")!r} уже строит Settlers", flush=True)
                return None
            st["tried"] += 1
            print(f"  [заказ] город {cid} {rec.get("name")!r}: щиты {rec.get("shield_stock")}, щитов/ход {rec.get("last_turns_shield_surplus")}, строит {built!r} → заказываю produce_Settlers", flush=True)
            return ("city", str(cid), "produce_Settlers")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  [заказ] не вышло: {type(exc).__name__}: {exc}", flush=True)
        return None
def _production_candidate(obs: dict, info: dict, dof_state, extractor,
                          type_names, military_names, gold, avail=None,
                          env_getter=None) -> dict | None:
    """Постановка города — ЕГО числами, без оценки DoF (§13.210).

    Почему это нужно в общем пути: стенд действия постановки городу НЕ предлагает вовсе
    (измерено §13.209 — единственное городовое действие `city_unwork_*`), поэтому до сих
    пор постановку ставил ТОЛЬКО прогноз. Путь без прогноза очередь не ставил, она
    додерживала `Warriors`, и сервер достраивал его снова: 8–16 военных при населении 2–4
    (§13.207). Здесь берём ЕГО выбор (`live.build_context(...).production_of`, то есть его
    правило `daicity.c:1860` с его весами) и синтезируем действие `produce_<имя>`;
    сравнение — той же мерой, что у поиска (ценность с дисконтом `γ^срок`), своих
    коэффициентов не вводим.

    Если лучший выбор совпадает с тем, что уже стоит в очереди, кандидата нет: запущенное
    идёт до конца (правило владельца §13.196).
    """
    if _filters_trace():
        print("  [постановка] вызов: строю выбор постановки", flush=True)
    try:
        from brain.forecast import live as _live
        from brain.forecast.search import FORECAST_GAMMA as _gamma
    except Exception as _exc:  # noqa: BLE001
        if _filters_trace():
            print(f"  [постановка] импорт прогноза упал: {type(_exc).__name__}: {_exc}", flush=True)
        return None
    try:
        ctx = _live.build_context(obs, info, dof_state, extractor,
                                  type_names=type_names or None,
                                  military_names=military_names or None, gold=gold)
    except Exception as _exc:  # noqa: BLE001
        if _filters_trace():
            print(f"  [постановка] сбор контекста упал: {type(_exc).__name__}: {_exc}", flush=True)
        return None
    if ctx is None or getattr(ctx, "production_of", None) is None:
        if _filters_trace():
            print("  [постановка] контекст не собран или выбор закрыт — пропуск", flush=True)
        return None
    global _LAST_CTX, _LAST_OBS
    _LAST_CTX = ctx
    # §13.292: наблюдение нужно, чтобы оценить клетки города правилами мира, когда свои
    # числа пусты. Держим его рядом с контекстом — там же, где живёт всё остальное.
    _LAST_OBS = obs
    # §13.360: ЧЕМ ЕГО ПРАВИЛО МЕРИТ ПОСТАНОВКУ. Без этих двух чисел спор «почему войско, а не
    # поселенец» не решается: нужен и выбор правила по городу, и цены типов в той же мере.
    if os.environ.get("DOF_CHOICE_DEBUG") == "1":
        try:
            _po = getattr(ctx, "production_of", None) or {}
            _tp = getattr(ctx, "type_price_of", None) or {}
            _rows = []
            for _cid in list(((obs or {}).get("city") or {}).keys())[:2]:
                _rec = None
                try:
                    _rec = (_po(_cid) if callable(_po)
                            else (_po.get(_cid) if isinstance(_po, dict) else None))
                except Exception as _exc2:  # noqa: BLE001
                    _rec = f"<{type(_exc2).__name__}: {_exc2}>"
                _rows.append(f"город {_cid}: выбор {str(_rec)[:70]!r}")
            def _price(_nm):
                try:
                    return (_tp(_nm) if callable(_tp)
                            else (_tp.get(_nm) if isinstance(_tp, dict) else None))
                except Exception as _exc3:  # noqa: BLE001
                    return f"<{type(_exc3).__name__}>"
            print("  [выбор-производства] " + "; ".join(_rows)
                  + f" | цены: Settlers {_price('Settlers')}, Warriors {_price('Warriors')}",
                  flush=True)
        except Exception as _exc:  # noqa: BLE001
            print(f"  [выбор-производства] проба упала: {type(_exc).__name__}: {_exc}", flush=True)
    cities = (obs or {}).get("city") or {}
    if not cities:
        # §13.377: оба канала по городам пусты (§13.369) — берём города из ХОДОВОГО СЕЙВА
        # (§13.376: вектор `c={}` в разделе игрока) и переносим имена полей сейва в те,
        # которых ждёт выбор производства.
        try:
            from env.city_vector import parse_city_vectors as _parse_cities
            from env.map_from_save import fetch_newest_save as _fetch_save
            _uname = str(fc_args.get("username") or "")
            _txt = _fetch_save(_uname) if _uname else None
            if _txt:
                _saved = _parse_cities(_txt, username=_uname)
                _inv = {}
                try:
                    for _val, _nm in (type_names or {}).items():
                        _inv[str(_nm)] = _val
                except Exception:  # noqa: BLE001
                    _inv = {}
                for _cid, _rec in _saved.items():
                    _built = str(_rec.get("currently_building_name") or "") or None
                    cities[str(_cid)] = {
                        "id": _rec.get("id", _cid),
                        "x": _rec.get("x"), "y": _rec.get("y"),
                        "name": _rec.get("name"),
                        "size": _rec.get("size"),
                        "shield_stock": _rec.get("shield_stock"),
                        "prod_shield": _rec.get("last_turns_shield_surplus"),
                        "production_value": _inv.get(_built) if _built else None,
                        "production_kind": _rec.get("currently_building_kind"),
                        "surplus_food": _rec.get("surplus_food"),
                        "_from_save": True,
                    }
                if cities and _filters_trace():
                    print(f"  [города-сейв] городов из ходового сейва: {len(cities)}", flush=True)
        except Exception as _exc:  # noqa: BLE001
            if _filters_trace():
                print(f"  [города-сейв] не вышло: {type(_exc).__name__}: {_exc}", flush=True)
    # §13.369: слой городов наблюдения бывает пуст — пробуем живой контроллер
    if not cities:
        try:
            cities = _controller_cities(env_getter) or cities
        except Exception:  # noqa: BLE001
            pass
    wonder_city = _wonder_city_id(obs)
    for cid, rec in cities.items():
        if _filters_trace() and isinstance(rec, dict):
            print(f"  [§13.691 рост] город {cid}: size={rec.get('size')} "
                  f"еда+={rec.get('surplus_food')} склад_еды={rec.get('food_stock')} "
                  f"щиты={rec.get('shield_stock')} строит={str(rec.get('currently_building_name'))!r}",
                  flush=True)
        if not isinstance(rec, dict):
            continue
        # §13.212 (указание 1): кандидаты берём из МАСОК САМОГО ГОРОДА, а не из предложения
        # стенда: постановку стенд не предлагает вовсе (§13.209), а маски он публикует и по
        # ним же проверяет приказ. Функция та же, что у прогноза, — правило одно.
        try:
            allowed = _live._allowed_production_types(rec, type_names)
        except Exception:  # noqa: BLE001
            allowed = None
        # §13.215: маска улучшений в наблюдение не попадает — берём её ИЗ МИРА. Это точнее
        # каталога: мир говорит не «имя существует», а «город построит это сейчас».
        world = _world_production_names(env_getter, cid)
        if world:
            if _filters_trace():
                print(f"  [постановка] город {cid}: маска МИРА — {len(world)} предметов: "
                      f"{sorted(world)[:12]}", flush=True)
                if isinstance(rec, dict):
                    _grow = {k: rec.get(k) for k in ("size", "surplus_food", "food_stock",
                                                     "prod_food", "prod_shield", "shield_stock",
                                                     "ppl_unhappy", "ppl_content")}
                    print(f"  [§13.691 рост] город {cid}: {_grow} | строит "
                          f"{str(rec.get('currently_building_name'))!r} | клеток "
                          f"{len(rec.get('worked') or ())}", flush=True)
            allowed = world
        else:
            # Маски мира нет — ЗАКАЗ НЕ ОТПРАВЛЯЕМ. Здесь «незнание ≠ запрет» уступает
            # измеренной цене ошибки: заказ по имени из своего каталога стоит не нуля, а
            # клина (матч умирает), и повторить его нельзя. Пусть очередь идёт как идёт —
            # это честнее, чем гадать именем, которое мир может прочесть иначе.
            if _filters_trace():
                print(f"  [постановка] город {cid}: маски мира нет — постановку не ставим",
                      flush=True)
            continue
        if allowed is None:
            # Масок нет — это «незнание», а не запрет (правило проекта: «незнание ≠
            # отсутствие возможностей»). Тогда берём ВЕСЬ каталог имён: отбор сделает цена —
            # без цены тип не предлагается, а выдумывать её мы не будем.
            allowed = {str(n) for n in (type_names or {}).values() if n}
        if not allowed:
            continue
        try:
            current = (type_names or {}).get(int(rec.get("production_value")))
        except (TypeError, ValueError):
            current = None
        # §13.336 (перенос, буквально): его ИИ НЕ меняет уже начатое производство, пока предмет
        # ещё можно строить. `server/cityturn.c:2330-2353`, `choose_build_target`:
        #   «Try building the same thing again. Repeat building doesn't require a call to
        #    change_build_target, so just return.»
        # и `ai/default/daicity.c:256-261`: «Don't change existing productions unless we have to.»
        # У нас совет (сборщик цен) звался КАЖДЫЙ ход, и город дёргался: приказ на поселенца
        # (40 щитов) жил 5 ходов и выбивался нашим же следующим, щиты уходили на дешёвого воина
        # (10) — отсюда `units_built=9` при `military_units=9` и стопка 16 воинов (измерено).
        # `allowed` — это маска МИРА (`_world_production_names`), то есть «город построит это
        # СЕЙЧАС»; она и есть его `can_city_build_*_now`.
        shields = float(rec.get("prod_shield") or 0.0)
        if shields <= 0.0:
            continue
        stock = float(rec.get("shield_stock") or 0.0)
        # §13.335: СЫРЫЕ числа очереди печатаются ДО решения (ниже), а щиты и выход города
        # читаются ЗДЕСЬ: правило удержания (§13.336) сравнивает запас, и раньше `stock`
        # вычислялся НИЖЕ него — порядок был бы неверен, если бы правило вообще срабатывало.
        # §13.340: ПРИБОР — принудительный приказ одному городу каждый ход (`DOF_FORCE_PROD=<Имя>`).
        # Нужен, чтобы отделить «канал не принимает» от «наш выбор не тот»: приказ идёт ровно один
        # и тот же, и по сырой очереди видно, применился ли он. Не нормативный, только измерение.
        _force = os.environ.get("DOF_FORCE_PROD")
        # `DOF_FORCE_EVERY=<N>` — посылать принудительный приказ только каждый N-й ход:
        # постоянный приказ и одиночный дали РАЗНЫЙ исход по улучшениям (0 из 22 против
        # 2 из 3), и это надо различить, а не выбирать удобное.
        _every = int(os.environ.get("DOF_FORCE_EVERY") or 0)
        _turn_now = int(info.get("turn") or 0)
        _send_now = (not _every) or (_turn_now % _every == 0)
        if _force and _send_now and any(str(_force) == str(a) for a in allowed):
            if _filters_trace():
                print(f"  [приказ-прибор] ход {info.get('turn')}: город {cid}: "
                      f"produce_{_force} (в очереди было {_filters_name(current)})", flush=True)
            return {"ctrl_type": "city", "actor_id": cid,
                    "action_name": f"produce_{_force}",
                    "current_name": str(current) if current else None,
                    "_committed": (str(_force), float(stock))}
        _prev = _LAST_PROD.get(str(cid))
        if os.environ.get("DOF_HOLD_TRACE") == "1":
            # §13.639: прибор печатает ВСЕ условия удержания, а не только когда оно сработало.
            # Иначе «правило не держит» неотличимо от «условия не совпали».
            print(f"  [держание] город {cid}: строит={current!r} "
                  f"помним={(str(_prev[0]) if _prev else None)!r} "
                  f"щиты={stock:.0f} помним_щиты={(float(_prev[1]) if _prev else -1):.0f} "
                  f"в_маске={(str(current) in {str(a) for a in allowed}) if current else None}",
                  flush=True)
        if (current and _prev and str(_prev[0]) == str(current) and stock >= float(_prev[1])
                and any(str(current) == str(a) for a in allowed)):
            if _filters_trace():
                print(f"  [постановка] город {cid}: строит {current!r}, щитов {stock:.0f} "
                      f"(было {float(_prev[1]):.0f}) — накопление идёт, приказа не шлём", flush=True)
            _LAST_PROD[str(cid)] = (str(current), stock)
            continue
        # §13.335/13.336: СЫРЫЕ числа очереди — то, что уходит в пакет `packet_city_change`
        # (`city_actions.py:383`). Печатаем ДО решения: иначе выключатель приказов (`DOF_NO_PROD`,
        # для измерения «а что если мы молчим») скрывает как раз то, что надо видеть.
        if _filters_trace():
            _raw = {k: rec.get(k) for k in ("production_kind", "production_value",
                                            "shield_stock", "did_buy")}
            print(f"  [очередь-сырое] ход {info.get('turn')}: город {cid}: {_raw}", flush=True)
        if os.environ.get("DOF_NO_PROD") == "1":
            # Измерение «а что если мы молчим»: нужен, чтобы отличить «приказ не применяется»
            # от «стенд сам меняет предмет». Нормативным этот выключатель не является.
            if _filters_trace():
                print(f"  [постановка] город {cid}: DOF_NO_PROD=1 — приказ не шлём (измерение)",
                      flush=True)
            continue
        if current and _prev and str(_prev[0]) == str(current) and stock < float(_prev[1]):
            if _filters_trace():
                print(f"  [постановка] город {cid}: щиты упали {float(_prev[1]):.0f}→{stock:.0f} — "
                      f"{current!r} завершён, решаем заново", flush=True)
        # Предохранитель 1: ставим только то, что СТЕНД СЕЙЧАС ПРЕДЛАГАЕТ городу.
        # Синтезированный приказ по имени, которого нет в списке законных, вешает контроллер:
        # измерено — `timeout: wedged on city/produce_Library at turn 1`, и то же с
        # `produce_Factory`. Список — из наблюдения, а не из маск: маски говорят «может»,
        # предложение — «принимается сейчас».
        offered: set[str] = set()
        if isinstance(avail, dict):
            for ctrl, actors in avail.items():
                if str(ctrl) not in ("city", "city_ctrl") or not isinstance(actors, dict):
                    continue
                for actor_id, acts in actors.items():
                    if str(actor_id) not in (str(cid), str(rec.get("id"))):
                        continue
                    if isinstance(acts, dict):
                        offered.update(str(a) for a in acts.keys())
        # §13.367 (указание владельца): СБОР не фильтруем. Если мир сейчас не перечислил имена
        # для города, берём ВСЁ, что город может строить — из его же записи и правил
        # (`_world_production_names`: `can_build_unit` + `can_build_improvement`). Отсев —
        # только на этапе решения (клины, род, нужда, хотелки §13.365/13.366).
        if not offered:
            try:
                _may = _world_production_names(env_getter, cid)
                if _may:
                    offered = {str(_x) for _x in _may}
                    if _filters_trace():
                        print(f"  [сбор] город {cid}: мир не перечислил имена — беру всё, что город "
                            f"может строить: {len(offered)}", flush=True)
            except Exception as _exc:  # noqa: BLE001
                if _filters_trace():
                    print(f"  [сбор] город {cid}: список возможного не получен: "
                        f"{type(_exc).__name__}: {_exc}", flush=True)
        # Предохранитель 2: клины уважаем — но ТОЛЬКО там, где отказ подтверждён.
        # §13.346: голый `is_wedged` считает отказы и НЕ смотрит успехи. Измерено:
        # `city/produce_Settlers` имел 6 отказов (партии, кончившиеся по таймауту) и
        # 9 успехов — и всё равно резался. Цена: поселенец не оценивался вовсе
        # (строки `[желание]` за партию НОЛЬ), очередь 100 ходов клепала воинов
        # серверным умолчанием, а к 134-му ходу мы потеряли город.
        # Правило из скилла: семейный запрет — только если НИ РАЗУ не вышло
        # (`is_wedged_family`), плюс запрет ИМЕННО В ЭТОЙ КЛЕТКЕ (`is_wedged_here`).
        try:
            from env.wedged import is_wedged_family as _is_wedged_family
            from env.wedged import is_wedged_here as _is_wedged_here
        except Exception:  # noqa: BLE001
            def _is_wedged_family(_ctrl, _name):  # type: ignore[misc]
                return False

            def _is_wedged_here(_ctrl, _name, _pos):  # type: ignore[misc]
                return False

        def _is_wedged(ctrl_type: str, action_name: str, pos=None) -> bool:
            """Резать имя только по подтверждённому отказу: семейно (0 успехов) или здесь."""
            if _is_wedged_family(ctrl_type, action_name):
                return True
            if pos is None:
                return False
            return _is_wedged_here(ctrl_type, action_name, pos)
        # «Стенд сказал» и «сведений нет» — разные вещи. Если список предложений вообще не
        # опубликован (оффлайн, тест, пустое наблюдение), это НЕ запрет: незнание ≠ запрет.
        offer_known = isinstance(avail, dict) and bool(avail)
        # Классы и флаги наших юнитов — из мира: без них его военные эффекты (ветеранство,
        # восстановление) не оцениваются, и `Barracks` выходит нулём, хотя войска уже стоят.
        units = _my_units_classes(env_getter, getattr(extractor, "my_player_id", None))
        if _filters_trace():
            print(f"  [постановка] город {cid}: наших юнитов для его военных эффектов "
                  f"{len(units)}", flush=True)
        if _filters_trace():
            # §13.368 (указание владельца): имена производства придумываем САМИ. Мир не обязан их
            # перечислять: берём то, что город может строить по его же записи и правилам, а если и
            # этого нет — весь каталог правил (юниты + постройки). Отсев — только при решении.
            _names = set(offered) if offered else set()
            if not _names:
                try:
                    _names = {str(x) for x in (_world_production_names(env_getter, cid) or set())}
                except Exception:  # noqa: BLE001
                    _names = set()
            if not _names:
                _names = _all_production_names(env_getter)
            if _filters_trace():
                print(f"  [сбор] город {cid}: имён к рассмотрению {len(_names)}"
                    f" (мир назвал {len(offered)})", flush=True)
            names_sorted = sorted(_names)
            print(f"  [постановка] город {cid}: стенд предлагает {len(names_sorted)} "
                  f"предметов: {names_sorted[:14]}", flush=True)
        best: tuple[float, str, int] | None = None
        scored: list[tuple[float, str, int]] = []
        # §13.559: строки для КАРКАСА выбора постановки (`advisor_adapter` → `choose_build`).
        # Сырое желание по имени собирается ДО всякой меры: каркас раскладывает его по трём
        # ведомствам и применяет свои шкалы. Ветвь ниже остаётся контрольной рукой A/B.
        _cb_on = os.environ.get("DOF_CHOOSE_BUILD", "0") == "1"
        _cb_rows: list[tuple[str, "float | None", int]] = []
        for name in sorted(allowed):
            action_name = f"produce_{name}"
            # Фильтр «есть ли в предложении стенда» здесь БОЛЕЕ НЕ применяется: измерено, что
            # предложение НЕ служит признаком законности — оно содержало 207 предметов, среди
            # них `produce_Offshore Platform`, которого город строить не может, и стенд на нём
            # же и клинил (`wedged on city/produce_Offshore Platform at turn 1`). Признак
            # законности — маска МИРА (§13.215), по которой стенд сам проверяет приказ; она и
            # задаёт `allowed` выше.
            _city_pos = None
            try:
                if rec.get("x") is not None and rec.get("y") is not None:
                    _city_pos = (int(rec.get("x")), int(rec.get("y")))
            except (TypeError, ValueError):
                _city_pos = None
            if _is_wedged("city", action_name, _city_pos):
                if _filters_trace():
                    print(f"  [постановка] {name}: режется реестром клинов "
                          f"(подтверждённый отказ, успехов нет) — пропуск", flush=True)
                continue          # это имя уже клинило матч (реестр `env/wedged.py`)
            if _is_wonder_name(name) and str(cid) != str(wonder_city):
                # «Only wonder city should build wonders!» Его правило, не наше.
                if _filters_trace():
                    print(f"  [постановка] {name}: чудо — строит только город чудес "
                          f"({wonder_city}), а это {cid}", flush=True)
                continue
            got = None
            if getattr(ctx, "type_price_of", None) is not None:
                try:
                    got = ctx.type_price_of(str(name), rec, units, obs)
                except Exception as _exc:  # noqa: BLE001
                    got = None
                    if _filters_trace():
                        print(f"  [постановка] {name}: цена не получена — "
                              f"{type(_exc).__name__}: {_exc}", flush=True)
            if got is None:
                continue
            options, cost = float(got[0]), float(got[1])
            own_stock = stock if (current is None or str(current) == str(name)) else 0.0
            turns = max(1, int(math.ceil(max(0.0, cost - own_stock) / shields)))
            value = options * (_gamma ** turns)
            # §13.366: ЕГО выбор производства, а не наша мера. Его `domestic_advisor_choose_build`
            # (`ai/default/daidomestic.c:489-620`) сравнивает ХОТЕЛКИ своих советников и берёт
            # максимум (`adv_better_choice`), а наша мера (`type_price`) сравнивала ценность за щит —
            # из-за этого воин (4.5625, 10 щитов) перебивал поселенца (3.8125, 40 щитов) (§13.360).
            # §13.559: под флагом каркаса сырое желание по имени нужно ВСЕГДА — оно и есть вход
            # трёх советников (`advisor_adapter.split_options`). Старая мера (`type_price`) не
            # выбрасывается: она остаётся контрольной рукой, когда флаг выключен.
            _his = None
            if _cb_on or os.environ.get("DOF_HIS_PRODUCTION") == "1":
                _his = _his_production_want(str(name), rec, ctx, _his_danger(obs, extractor))
                if _his is not None:
                    if _filters_trace():
                        print(f"  [его-выбор] {name}: его хотелка {_his:.4f}"
                            f" (наша мера была {value:.4f} за {turns} ход.)", flush=True)
                    value = float(_his)
            scored.append((value, str(name), turns))
            # §13.559: КАРКАСУ нужна хотелка ПО ИМЕНИ до дисконта — это `options` из цены типа
            # (`type_price_of`), ЕГО шкала опций. Она есть у ВСЕХ имён (поселенец/рабочий — через
            # свои формулы желания, постройки — через `improvement_value`), тогда как
            # `_his_production_want` покрывает лишь три рода. Прежде здесь стоял `_his`, и у
            # внутреннего ведомства не было ни одного имени — каркас всякий раз падал на ветвь A/B
            # (измерено: 18 строк «его желаний нет ни по одному имени»).
            _cb_rows.append((str(name), float(options), turns))
            # §13.633: город, УЖЕ отдавший заказ в этом ходу, не получает второй. После исключения
            # в `_city_tile_candidate` (§13.632: 169 срабатываний) повтор не исчез — значит заказ
            # городу отдаёт ещё и эта ветвь. Проверка через `locals()`: имя города в этой области
            # видимости не подтверждено чтением, и падать на NameError в прогоне нельзя.
            _cid_now = locals().get("cid")
            if (os.environ.get("DOF_NO_ACTOR_REPEAT") == "1" and _USED_ACTORS
                    and _cid_now is not None
                    and (str("city"), str(_cid_now).split("_")[-1]) in
                    {(str(_c).split("_")[0], str(_a).split("_")[-1])
                     for _c, _a in (_USED_ACTORS[0] or ())}):
                print(f"        [§13.633] город {_cid_now} уже отдал заказ — производства не даём",
                      flush=True)
                continue
            if best is None or value > best[0]:
                best = (value, str(name), turns)
        if best is None:
            if _filters_trace():
                print(f"  [постановка] город {cid}: маски дали {len(allowed)} типов, "
                      f"ни один не оценён — постановку не меняем", flush=True)
            continue
        # §13.559: КАРКАС выбора производства (`brain/ai_default/build_choice.py`, порядок
        # `daicity.c:250`) вместо нашей меры. Ветвь выше — контрольная рука A/B: она уже
        # выбрала `best` своей мерой (`type_price`), и мы её не выбрасываем, а лишь
        # перекрываем решением каркаса, когда он есть чем решать.
        if _cb_on and _cb_rows:
            try:
                from brain.ai_default.advisor_adapter import choose_from_options as _cfo
                # Советникам нужны ТОЛЬКО имена с его желанием: строка без желания (None) —
                # это «его числа нет», и подставлять туда 0.0 значило бы выдумать за него.
                _cb_use = [(n, w, t) for n, w, t in _cb_rows if w is not None]
                if _cb_use:
                    _mil_names = _military_type_names(env_getter()) or ()
                    _nm_cb, _want_cb = _cfo(_cb_use, rec, military_names=_mil_names)
                    # Предохранитель: каркас обязан вернуть имя ИЗ ЗАКОННЫХ (`allowed`), иначе
                    # приказ по имени, которого мир не принимает, вешает контроллер (§13.367).
                    if _nm_cb and _nm_cb in allowed:
                        if _filters_trace():
                            print(f"  [каркас] город {cid}: {_nm_cb!r} желание {_want_cb:.4f}; "
                                  f"наша мера взяла бы {best[1]!r} ({best[0]:.4f})", flush=True)
                        _t_cb = next((t for n, w, t in _cb_rows if n == _nm_cb), best[2])
                        best = (float(_want_cb), str(_nm_cb), _t_cb)
                    elif _filters_trace():
                        print(f"  [каркас] город {cid}: имя {_nm_cb!r} не из законных — "
                              f"оставляю ветвь A/B ({best[1]!r})", flush=True)
                elif _filters_trace():
                    print(f"  [каркас] город {cid}: его желаний нет ни по одному имени — "
                          f"оставляю ветвь A/B ({best[1]!r})", flush=True)
            except Exception as _exc:  # noqa: BLE001
                if _filters_trace():
                    print(f"  [каркас] город {cid}: не посчитался ({type(_exc).__name__}: "
                          f"{_exc}) — оставляю ветвь A/B ({best[1]!r})", flush=True)
        if _filters_trace():
            # §13.335: сырые числа очереди — чтобы отличить «приказ не применён» от
            # «имя предмета прочитано неверно». `production_kind/value` — то, что
            # уходит в пакет `packet_city_change` (`city_actions.py:383`).
            _top = sorted(scored, key=lambda r: r[0], reverse=True)[:5]
            print(f"  [постановка] город {cid}: маски {len(allowed)} типов; оценено "
                  f"{len(scored)}; лучший {best[1]} (ценность {best[0]:.3f} за {best[2]} ход.); "
                  f"в очереди {current!r}; верх: "
                  + ", ".join(f"{n} {v:.2f}/{t}х" for v, n, t in _top), flush=True)
        if current and best[1] == str(current):
            continue          # повода менять нет: запущенное идёт до конца (§13.196)
        # §13.684: ВЫВОД ГОРОДА ИЗ ПРОСТОЯ — единственный рычаг, выведенный из картины захода.
        # Измерено (§13.683): среда сама ставит и стирает предмет, и оставляет наши города в `Coinage`
        # по 8 ходов подряд (T=52-60, два города). `Coinage` кассирует щиты в золото: щиты при нём равны
        # 0 и НЕ копятся. Значит вмешательство именно в такой город НИЧЕГО не стоит (терять нечего) и
        # выводит город из простоя. Правило: заказываем, ТОЛЬКО если город кассирует/пуст; чужой
        # строящийся предмет не трогаем (его смена стоила бы накопленного).
        if os.environ.get("DOF_UNIDLE") == "1":
            _cur_u = str(current).strip() if current else None
            _idling = _cur_u is None or _cur_u.lower() in ("coinage", "none", "")
            if os.environ.get("DOF_UNIDLE_DEBUG") == "1":
                _tv = None
                for _src in (info, obs):
                    if isinstance(_src, dict):
                        for _k in ("turn", "game_turn", "turn_number", "step"):
                            if _src.get(_k) is not None:
                                _tv = _src.get(_k)
                                break
                    if _tv is not None:
                        break
                print(f"  [§13.684] ход {_tv if _tv is not None else '?'} город {cid}: "
                      f"в городе {_cur_u!r} щиты {float(stock):.0f} -> "
                      f"{'ЗАКАЗЫВАЮ (простой)' if _idling else 'не трогаю (среда строит)'}", flush=True)
            if not _idling:
                continue
        # §13.679: НЕ ВМЕШИВАТЬСЯ В ЦИКЛ, КОТОРЫЙ ВЕДЁТ СРЕДА.
        # Измерено: в городе в 45 % наблюдений стоит НЕ наш предмет (§13.673), и после завершения
        # постройки предмет ставит среда (18 из 23 завершений, §13.677), а очередь навязать нельзя —
        # в пространстве действий есть только смена предмета (§13.678). Значит наш заказ равносилен
        # СМЕНЕ предмета среды, а смена списывает накопленные щиты (до 26, §13.654). Правило: если в
        # городе НЕ наш предмет — не трогаем; свой предмет подтверждаем только после его завершения
        # (когда щиты упали ниже памятного запаса).
        if os.environ.get("DOF_HANDS_OFF") == "1":
            _cur_h = str(current) if current else None
            _mine_h = str(_prev[0]) if _prev is not None else None
            if _cur_h is None or _cur_h != _mine_h:
                if os.environ.get("DOF_HANDS_OFF_DEBUG") == "1":
                    print(f"  [§13.679] город {cid}: в городе {_cur_h!r}, наш предмет {_mine_h!r} "
                          f"— не вмешиваюсь (щиты {float(stock):.0f})", flush=True)
                continue
            if os.environ.get("DOF_HANDS_OFF_DEBUG") == "1":
                print(f"  [§13.679] город {cid}: в городе наш предмет {_cur_h!r} — подтверждаю заказ "
                      f"(щиты {float(stock):.0f}, помним_щиты {float(_prev[1]):.0f})", flush=True)
        # §13.664: не повторять заказ тому же городу. Сравниваем со СВОЕЙ памятью, а не
        # с очередью: очередь нашего предмета не удерживает (§13.646-13.648), поэтому
        # правило выше не срабатывало ни разу, а повтор заказа обнуляет щиты (§13.663).
        if os.environ.get("DOF_SKIP_SAME_ORDER") == "1" and _prev is not None:
            _ord_turn = _LAST_ORDER_TURN.get(str(cid))
            _turn_here = int(info.get("turn") or 0)
            _same_item = str(_prev[0]) == str(best[1])
            _accumulating = float(stock) >= float(_prev[1])
            # §13.665: условие «заказ был В ПРОШЛОМ ходу» УБРАНО — измерено (cb21.log):
            # совпадений 6, из них «недавно» всего 1. Наши повторные заказы идут с
            # промежутком в 2+ хода (заказ в 6-м, повтор в 8-м), и такой повтор всё
            # равно стирает накопленное: в §13.663 один заказ на 23-м ходу снёс 35 щитов.
            if os.environ.get("DOF_SKIP_DEBUG") == "1":
                print(f"  [§13.664] город {cid}: выбор {best[1]!r} помним {str(_prev[0])!r} "
                      f"щиты {float(stock):.0f} помним_щиты {float(_prev[1]):.0f} "
                      f"заказ_был_в_ходу {_ord_turn} ход {_turn_here} "
                      f"тот_же={_same_item} копит={_accumulating}", flush=True)
            if _same_item and _accumulating:
                if os.environ.get("DOF_SKIP_DEBUG") == "1":
                    print(f"  [§13.664] город {cid}: НЕ повторяю {best[1]!r} "
                          f"(заказ ушёл в ходу {_ord_turn}, щиты растут) в_очереди {current!r}",
                          flush=True)
                _LAST_ORDER_TURN[str(cid)] = _turn_here
                continue
        return {"ctrl_type": "city", "actor_id": cid,
                "action_name": f"produce_{best[1]}",
                "current_name": str(current) if current else None,
                # §13.336: помним ЧТО И С КАКИМ ЗАПАСОМ ЩИТОВ мы поставили. Пока щиты растут,
                # город держит предмет (его правило «don't change existing productions unless we
                # have to», `daicity.c:256-261`); заново решаем только когда постройка
                # завершилась — падение запаса, что и есть его `city_built_last_turn`.
                "_committed": (str(best[1]), float(stock)),
                "projected_dof_delta": {}, "is_reversible": True}
    return None


def _port_diag(why: str, extra) -> None:
    """Почему перенос работы промолчал — молчание обязано быть отличимо от данных."""
    if os.environ.get("DOF_TRACE_FILTERS") != "1":
        return
    print(f"  [работа-перенос] молчит: {why}" + (f" ({extra})" if extra is not None else ""),
          flush=True)


def _port_work_choice_for(actor, candidates, obs, dof_state, avail=None):
    """Работа, которую выбрал бы встроенный ИИ на клетке этого юнита (§13.288).

    Возвращает имя работы или None, если данных не хватает (тогда правило молчит).
    """
    try:
        from brain.ai_default.worker_choice import choose_tile_work, work_options_from_rules
        from env.terrain_output import server_tile_outputs
        from env.terrain_work import tile_terrain_extras
    except Exception:  # noqa: BLE001
        return None

    positions = getattr(dof_state, "positions", None) or {}
    pos = positions.get(str(actor)) or positions.get(f"unit_{actor}")
    if not pos:
        _port_diag(f"нет позиции юнита {actor}", len(positions))
        return None
    try:
        x, y = int(pos[0]), int(pos[1])
    except (TypeError, ValueError, IndexError):
        return None

    map_obs = obs.get("map") if isinstance(obs, dict) else None
    if not isinstance(map_obs, dict):
        _port_diag("нет карты в наблюдении", None)
        return None
    try:
        terrain, _extras_here = tile_terrain_extras(map_obs, x, y)
    except Exception:  # noqa: BLE001
        return None
    if not terrain:
        return None
    # Клиент присылает ОТОБРАЖАЕМОЕ имя террейна (Grassland), а правила мира записаны
    # служебными ключами (grassland). Приводим к ключу правил один раз здесь, чтобы ни одна
    # таблица не искалась по имени, которого в правилах нет.
    terrain = str(terrain).strip().lower().replace(" ", "_")

    city_actions = {}
    try:
        source = avail if avail is not None else ((obs.get("avail") or {}) if isinstance(obs, dict) else {})
        city_actions = (source or {}).get("city") or {}
    except Exception:  # noqa: BLE001
        city_actions = {}
    outputs_by_city = {}
    try:
        outputs_by_city = server_tile_outputs(city_actions, x, y)
    except Exception:  # noqa: BLE001
        outputs_by_city = {}
    if outputs_by_city:
        outputs = next(iter(outputs_by_city.values()))
    else:
        # Город сообщает выходы только своих клеток, а рабочий часто стоит ВНЕ радиуса
        # (измерено: 6 обращений подряд). Основа выходов — свойство террейна и лежит в
        # правилах мира, поэтому берём её оттуда, а не из наблюдения и не нулём.
        # Выходы = основа террейна ПЛЮС уже имеющиеся улучшения клетки (экстры приходят в
        # том же слое, что и террейн). Без этого работа на уже улучшенной клетке выглядела бы
        # выгоднее, чем она есть: прирост считался бы от чистой основы.
        from brain.ai_default.tile_outputs import tile_outputs_from_rules

        outputs = tile_outputs_from_rules(terrain, _extras_here)
        if outputs is None:
            _port_diag(f"нет основы выходов для террейна {terrain}", None)
            return None
        _port_diag(f"клетка вне радиуса — правила: {terrain} {tuple(_extras_here)} "
                   f"→ {tuple(outputs)}", None)

    offered = []
    for c in candidates:
        act = _to_action(c)
        if act and str(act[0]) == "unit" and str(act[1]) == str(actor):
            offered.append(str(act[2]))
    options = work_options_from_rules(str(terrain), tuple(outputs), offered)
    if not options:
        _port_diag(f"правил нет для {terrain} {outputs} из {offered}", None)
        return None
    try:
        choice = choose_tile_work([((x, y), tuple(outputs), options)])
    except Exception:  # noqa: BLE001
        return None
    return choice.activity or None


def _worker_dest_step(actor: str, cands: list, obs: dict, dof_state, avail=None) -> str | None:
    """Шаг рабочего к клетке, где работа даёт прирост (§13.451).

    Зачем: §13.450 показала, что цепочка работ исправна, но рассматривает ТУ клетку, на которой
    рабочий стоит. Если работы на ней нет, встроенный ИИ ведёт рабочего туда, где она есть. Здесь
    ровно это: из клеток в радиусе выбирается клетка с наибольшим ДИСКОНТИРОВАННЫМ выигрышем работы
    (`amortize`), и рабочему возвращается имя хода `goto_*` в её сторону.

    Включается только прибором `DOF_WORK_MOVE=1`: новая ветка решения не должна менять поведение
    полосы до отдельного прогона. Ценности не выдумываются — они берутся из правил мира (выходы
    террейна с уже имеющимися улучшениями) и коэффициентов его управляющего городом.
    """
    if os.environ.get("DOF_WORK_DEBUG") == "1":
        print(f"  [работа-вход] вызван для {actor}, DOF_WORK_MOVE={os.environ.get('DOF_WORK_MOVE')}", flush=True)
    if os.environ.get("DOF_WORK_MOVE") != "1":
        return None
    try:
        from brain.ai_default.founder_destination import goto_name_to, path_first_step
        from brain.ai_default.tile_outputs import tile_outputs_from_rules
        from brain.ai_default.worker_choice import work_options_from_rules
        from brain.ai_default.worker_destination import best_work_tile
        from brain.ai_default.worker_manager import factors, tile_value
        from env.terrain_work import tile_terrain_extras
    except Exception:  # noqa: BLE001
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3433", flush=True)
        return None

    positions = getattr(dof_state, "positions", None) or {}
    pos = positions.get(str(actor)) or positions.get(f"unit_{actor}")
    if not pos:
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-нет-позиции] " + str(actor) + ": записей в positions "
                  + str(len(positions)) + ", пример ключей " + str(list(positions)[:4]),
                  flush=True)
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3442", flush=True)
        return None
    try:
        px, py = int(pos[0]), int(pos[1])
    except Exception:  # noqa: BLE001
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3446", flush=True)
        return None

    map_obs = obs.get("map") if isinstance(obs, dict) else None
    rules = obs.get("rules") if isinstance(obs, dict) else None
    if not isinstance(map_obs, dict) or not isinstance(rules, dict):
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3451", flush=True)
        return None
    try:
        xs, ys = int(rules.get("xsize") or 0), int(rules.get("ysize") or 0)
    except Exception:  # noqa: BLE001
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3455", flush=True)
        return None
    if xs <= 0 or ys <= 0:
        if os.environ.get("DOF_WORK_DEBUG") == "1":
            print("  [работа-обрыв] строка 3457", flush=True)
        return None

    weights = factors(1.0)

    def _outputs(tile):
        tx, ty = tile
        try:
            ter, extras = tile_terrain_extras(map_obs, tx, ty)
        except Exception:  # noqa: BLE001
            if os.environ.get("DOF_WORK_DEBUG") == "1":
                print("  [работа-обрыв] строка 3466", flush=True)
            return None
        if not ter:
            if os.environ.get("DOF_WORK_DEBUG") == "1":
                print("  [работа-обрыв] строка 3468", flush=True)
            return None
        ter = str(ter).strip().lower().replace(" ", "_")
        outs = tile_outputs_from_rules(ter, extras)
        if outs is None:
            return None
        return ter, tuple(outs)

    _wd = _WORK_DIAG if os.environ.get("DOF_WORK_DEBUG") == "1" else None

    def _wdc(reason):
        if _wd is not None:
            _wd[reason] = _wd.get(reason, 0) + 1

    def options_for(tile):
        """{работа: выигрыш} для клетки — из правил мира, без выдуманных значений."""
        got = _outputs(tile)
        if got is None:
            _wdc("выходов клетки нет (террейн/эффекты неизвестны)")
            return None
        ter, old = got
        try:
            raw = work_options_from_rules(ter, old, _PORT_WORK_NAMES)
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            _wdc("правила не предлагают работ для этого террейна")
            return None
        base = float(tile_value(old[0], old[1], old[2], weights))
        out = {}
        for name, (new_outs, delay) in raw.items():
            gain = float(tile_value(new_outs[0], new_outs[1], new_outs[2], weights)) - base
            if gain <= 0.0:
                continue
            out[name] = _amortize_gain(gain, int(delay))
        return out or None

    tiles = [(x, y) for x in range(max(0, px - 4), min(xs, px + 5))
             for y in range(max(0, py - 4), min(ys, py + 5))]
    try:
        target = best_work_tile(worker_pos=(px, py), tiles=tiles, options_for=options_for,
                                gain_of=lambda opts: max(opts.values()), radius=4)
    except Exception:  # noqa: BLE001
        return None
    if not target:
        _wdc("годной цели нет: все приросты <= 0")
        if _wd is not None and len(_wd) > 3:
            _wd = None  # печатаем сводку один раз, чтобы не залить журнал
        print(f"  [работа-клетки] причин: {_WORK_DIAG}", flush=True)
        return None

    step = goto_name_to((px, py), target)
    if step is None:
        return None
    have = {str(_to_action(c)[2]) for c in cands
            if _to_action(c) and str(_to_action(c)[0]) == "unit"
            and str(_to_action(c)[1]) == str(actor)}
    if step in have:
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [работа-цель] unit/{actor}: иду на {target} шагом {step}", flush=True)
        return step
    return None


def _amortize_gain(gain: float, delay: int) -> float:
    """`amortize` из его `advtools.c` (MORT = 24) — выигрыш работы с учётом срока."""
    try:
        from brain.ai_default.worker_choice import amortize
        return float(amortize(gain, delay))
    except Exception:  # noqa: BLE001
        return gain


def _prefer_port_work_choice(cands: list, obs: dict, dof_state, avail=None) -> list:
    """Оставить выбранную ИМ работу среди предложенных работ КАЖДОГО юнита (§13.288).

    Измерено за этот заход: работу клетки выбирал счёт совпадений со списком предпочтений
    (`_preference_score`), поэтому шли шахта и дорога, а город стоял на размере 1 при
    излишке еды 0 (13.280). Теперь работу выбирает ЕГО правило.
    """
    by_actor: dict = {}
    for c in cands:
        act = _to_action(c)
        if not act or str(act[0]) != "unit":
            continue
        name = str(act[2])
        if name in _PORT_WORK_NAMES:
            by_actor.setdefault(str(act[1]), []).append(name)
    if not by_actor:
        return cands

    keep: dict = {}
    for actor in by_actor:
        chosen = _port_work_choice_for(actor, cands, obs, dof_state, avail)
        if chosen:
            keep[actor] = chosen
    # §13.451: если работы на текущей клетке нет — вести рабочего туда, где она есть.
    move_keep: dict = {}
    for actor in by_actor:
        if keep.get(actor):
            continue
        try:
            step = _worker_dest_step(actor, cands, obs, dof_state, avail)
        except Exception:  # noqa: BLE001
            step = None
        if step:
            move_keep[actor] = step
    if not keep and not move_keep:
        return cands

    out = []
    for c in cands:
        act = _to_action(c)
        if not act:
            out.append(c)
            continue
        ctrl, actor, name = str(act[0]), str(act[1]), str(act[2])
        chosen = keep.get(actor)
        if ctrl == "unit" and chosen and name in _PORT_WORK_NAMES and name != chosen:
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [работа-перенос] unit/{actor}: {name} отложено — его правило "
                      f"выбрало {chosen}", flush=True)
            continue
        step = move_keep.get(actor)
        if ctrl == "unit" and step and name.startswith("goto_") and name != step:
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [работа-цель] unit/{actor}: {name} отложено — иду шагом {step}",
                      flush=True)
            continue
        out.append(c)
    if not out:
        return cands
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # След связывает отбор с исходом: видно, что осталось ПОСЛЕ правила, а не только что
        # оно отложило. Без этого «отложено» и «отправлено» в одном ходу выглядят как
        # противоречие, хотя могут быть разными решениями.
        _left = sorted({str(_to_action(c)[2]) for c in out
                        if _to_action(c) and str(_to_action(c)[2]) in ("mine", "irrigation")})
        _picked = ", ".join(f"{a}->{w}" for a, w in sorted(keep.items()))
        print(f"  [работа-перенос] выбор: {_picked}; осталось работ: {_left}", flush=True)
    return out


def _is_action_wedged(ctrl: str, name: str, position) -> bool:
    """Заклинивало ли уже это действие — по правилу §13.274.

    Семейно режем БЕЗНАДЁЖНОЕ (отказов >= 2 и ни одного успеха), исправное — только в той
    клетке, где оно уже падало. Измерено на живом реестре: `unit/plant` — 26 отказов,
    0 успехов (резать), `unit/build_city` — 3 отказа, 37 успехов (играть; семейный запрет
    убил бы основание города).
    """
    try:
        if is_wedged_family(ctrl, name):
            return True
    except Exception:  # noqa: BLE001
        return False
    if position is None:
        return False
    try:
        # Падало ли ИМЕННО ЗДЕСЬ. Не `is_wedged(context=...)`: он складывает с устаревшими
        # семейными отказами и резал `build_city` в новых клетках — 176 исключений за прогон.
        return bool(is_wedged_here(ctrl, name, position))
    except Exception:  # noqa: BLE001
        return False


_UNWORK_SENT: dict = {}


def _drop_repeated_unwork(cands: list, info: dict | None) -> list:
    """§13.571: одно и то же снятие работы с клетки уходило 29-45 раз подряд.

    Прибор вскрыл, что `city_unwork` — это 40-45 % ВСЕХ отправок, а один и тот же кандидат
    (`city_unwork_20_2_1`) подавался 45 раз. В реестре сторожей (`wedged_actions.json`) семейства
    `city/city_unwork` нет, поэтому штатный `_drop_wedged_candidates` его не ловит.

    Под флагом `DOF_NO_UNWORK_REPEAT=1` не берём кандидата, если ровно он же уходил на прошлом
    ходу. По умолчанию поведение прежнее — старое остаётся контрольной рукой A/B.
    """
    if os.environ.get("DOF_NO_UNWORK_REPEAT") != "1":
        return cands
    turn = info.get("turn") if isinstance(info, dict) else None
    out = []
    _dropped = 0
    for c in cands:
        nm = str(c.get("action_name") or "")
        if nm.startswith("city_unwork"):
            key = (str(c.get("actor_id")), nm)
            _prev = _UNWORK_SENT.get(key)
            # §13.572-правка: повтор идёт ЧЕРЕЗ ХОД, а не внутри хода. Первая версия сравнивала
            # номер хода на равенство (`== turn`) и потому не могла сработать ни разу: внутри
            # одного хода тот же кандидат не подаётся дважды. Серия nu это подтвердила — доля
            # `city_unwork` осталась 44 % (была 40-45 %), повторы до 44 раз на партию.
            # Считаем повтором подачу на этом или на ПРОШЛОМ ходу; допуск в один ход закрывает
            # и возможную ошибку на единицу между `info["turn"]` и номером при отправке.
            if _prev is not None and (turn is None or _prev >= turn - 1):
                _dropped += 1
                continue
        out.append(c)
    # §13.574: прибор ДОКЛАДЫВАЕТ, что точка правки вообще исполняется. Три захода подряд
    # правки стояли на неисполняемых путях; без этой строки «фильтр не сработал» и «фильтр
    # не вызывался» снова неразличимы. Убрать, когда версия закроется.
    print(f"  [фильтр unwork] ход {turn}: кандидатов {len(cands)}, повторов снято {_dropped}",
          flush=True)
    return out


def _drop_wedged_candidates(cands: list, dof_state) -> list:
    """Выкинуть кандидатов, о которых известно, что стенд на них заклинивает.

    Живьём экономическая рука залипала на втором ходу в КАЖДОЙ партии (`unit/plant`),
    потому что путь юнитов реестр не спрашивал вовсе: сыграно 1 ход из 20, счёт 0.7
    против 5.7 у экспансиониста.
    """
    positions = getattr(dof_state, "positions", None) or {}
    out = []
    for c in cands:
        act = _to_action(c)
        if not act:
            out.append(c)
            continue
        ctrl = str(act[0])
        actor = str(act[1]) if len(act) >= 2 else ""
        name = str(act[2]) if len(act) >= 3 else ""
        position = positions.get(actor) or positions.get(f"{ctrl}_{actor}")
        if _is_action_wedged(ctrl, name, position):
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"  [клин] {ctrl}/{name} — известно, что заклинивает; исключено",
                      flush=True)
            continue
        out.append(c)
    return out


# ── §13.311: выбор ТЕХНОЛОГИИ — его argmax, а не плоское совпадение со списком ──
#
# Измерено: за прогон предлагалось НЕСКОЛЬКО технологий (`research_tech_Alphabet_`,
# `research_tech_Advanced Flight_`, `research_tech_Amphibious Warfare_`), и все получали
# одинаковое предпочтение 1.0 — какая исследуется, решал порядок, а не ценность. У него это
# `ai_choose_tech` (`daitech.c`): берётся технология с наибольшим `tech_want`, который есть
# прирост оценки ГОРОДОВ от открываемых ею построек, × 14/8.

_TECH_ACTION_PREFIXES = ("research_tech_", "set_tech_goal_")


def _tech_action_name(action_name) -> str | None:
    """`research_tech_Advanced Flight_` → `Advanced Flight` — имя технологии МИРА."""
    name = str(action_name or "")
    for prefix in _TECH_ACTION_PREFIXES:
        if name.startswith(prefix):
            tech = name[len(prefix):].strip().rstrip("_").strip()
            return tech or None
    return None


def _cand_action_name(cand) -> str:
    act = _to_action(cand)
    return str(act[2]) if act else ""


def _tech_named(cands) -> int:
    """Сколько кандидатов называют технологию — чтобы «не сработало» отличать от «нечего решать»."""
    return sum(1 for c in cands if _tech_action_name(_cand_action_name(c)) is not None)


def _tech_values(obs: dict, extractor, action_names) -> dict[str, float]:
    """Хотение технологии по его числу: прирост оценки НАШИХ городов × 14/8.

    Пропуск данных честен: технология, открывающая пустое (нет номера постройки в фактах
    мира), получает ноль — это и есть его счёт для неё, а не выдуманная оценка.
    """
    try:
        from brain.ai_default.effects import city_want as _his_city_want
        from brain.ai_default.tech import city_want_with, tech_want_total
        from env.entity_extractor import city_options
    except Exception:  # noqa: BLE001
        return {}
    model = getattr(extractor, "model", None)
    my_id = getattr(extractor, "my_player_id", None)
    cities = as_dict(as_dict(obs).get("city"))
    mine = [rec for rec in cities.values()
            if isinstance(rec, dict) and (my_id is None or rec.get("owner") == my_id)]
    if not mine:
        return {}
    out: dict[str, float] = {}
    for action_name in action_names:
        tech = _tech_action_name(action_name)
        if tech is None or tech in out:
            continue
        pairs = []
        for rec in mine:
            try:
                before = float(city_options(rec, model=model))
                after = float(city_want_with(city_options, rec, tech, model=model))
            except Exception:  # noqa: BLE001
                continue
            pairs.append((before, after))
        if pairs:
            out[tech] = float(tech_want_total(pairs))
    return out


def _prefer_port_tech_choice(cands: list, obs: dict, extractor) -> list:
    """Оставить в каждой семье технологии ту, что выбрал бы он (§13.311).

    Семьи разделены намеренно: `research_tech` меняет исследование, `set_tech_goal` — только
    указание, и у него это разные решения. Сравнивать хотение технологии с хотением постановки
    города на одной шкале НЕЛЬЗЯ: у него между ними нет общего коэффициента.
    """
    from brain.ai_default.tech import keep_best_tech
    values = _tech_values(obs, extractor, [_cand_action_name(c) for c in cands])
    if not values:
        return cands
    out = cands
    for prefix in _TECH_ACTION_PREFIXES:
        out = keep_best_tech(
            out, name_of=_cand_action_name,
            value_of=lambda c, _v=values: _v.get(_tech_action_name(_cand_action_name(c))),
            family_prefix=prefix)
    if os.environ.get("DOF_TRACE_FILTERS") == "1" and _tech_named(cands) >= 2:
        print(f"  [технология] его числа: "
              f"{ {k: round(v, 2) for k, v in sorted(values.items())} } → оставлено "
              f"{[ _cand_action_name(c) for c in out if _tech_action_name(_cand_action_name(c)) is not None ]}",
              flush=True)
    return out


def _count_kinds(cands: list, where: str) -> None:
    """§13.657: печатает, ЧТО за кандидаты пришли, а не только когда правило сработало (§13.618).

    Два счётчика: `produce_*` (заказы производства) и клеточные (`city_work`/`city_unwork`).
    """
    if os.environ.get("DOF_GEN_DEBUG") != "1":
        return
    names = []
    for c in cands or ():
        try:
            a = _to_action(c)
            names.append(str(a[2]) if a else "")
        except Exception:
            names.append("")
    prod = sum(1 for n in names if n.startswith("produce_"))
    work = sum(1 for n in names if n.startswith("city_work"))
    unwork = sum(1 for n in names if n.startswith("city_unwork"))
    print(f"  [генератор:{where}] всего {len(names)}, produce {prod}, "
          f"city_work {work}, city_unwork {unwork}", flush=True)


def _hold_busy_city(cands: list, obs: dict | None) -> list:
    """§13.658: у города, где постановка УЖЕ идёт, альтернатив не предлагаем.

    Признак наблюдаемый и уже используется на этом пути: непустой `turns_to_prod_complete`
    значит «мир считает производство идущим». Действующее правило удержания требует, чтобы
    текущий предмет был среди предложенных (измерено §13.656: «предложено смен 0»), поэтому
    не срабатывает; здесь сравнение имён не нужно вовсе. Решение владельца §13.196.
    """
    if os.environ.get("DOF_HOLD_BUSY") != "1":
        return cands
    cities = (obs or {}).get("city") if isinstance(obs, dict) else None
    if not isinstance(cities, dict) or not cities:
        return cands
    busy = set()
    for cid, rec in cities.items():
        if isinstance(rec, dict) and rec.get("turns_to_prod_complete") is not None:
            busy.add(str(rec.get("id", cid)))
    out = []
    dropped = 0
    for c in cands:
        a = _to_action(c)
        if (a and str(a[0]) == "city" and str(a[2]).startswith("produce_")
                and str(a[1]) in busy):
            dropped += 1
            continue
        out.append(c)
    # Печать ЧТО посмотрел, а не только когда сработало (§13.618).
    if os.environ.get("DOF_HOLD_BUSY_DEBUG") == "1":
        print(f"  [занятость] в работе {len(busy)}, снято {dropped}, "
              f"было {len(cands)}, стало {len(out)}", flush=True)
    return out


def _apply_common_rules(cands: list, obs: dict, extractor, env_getter,
                        avail=None) -> list:
    """ОБЩИЕ правила, обязательные для любого решателя (§13.206–13.208).

    Собрано в одно место, чтобы ни один путь не оказался без правила: пока правила
    (удержание постановки, нужда в войске) жили внутри прогноза, путь без прогноза
    строил 8–16 военных при населении 2–4 и менял постановку каждый ход.

    При `DOF_TRACE_FILTERS=1` печатает, СКОЛЬКО кандидатов отбросило каждое правило —
    чтобы «правило внесено» проверялось замером, а не чтением кода.
    """
    if env_getter is None:
        return cands
    try:
        type_names = _production_names(env_getter())
    except Exception:  # noqa: BLE001
        return cands
    before = len(cands)
    held = _hold_production_candidates(cands, obs, type_names)
    held = _hold_busy_city(held, obs)
    try:
        military = _military_type_names(env_getter())
    except Exception:  # noqa: BLE001
        military = set()
    kept = _hold_military_candidates(
        held, obs, getattr(extractor, "my_player_id", None), military, type_names)
    # §13.311: ЧТО исследовать — решает его `ai_choose_tech`, а не порядок предложения.
    # Стоит здесь, в теле общей функции, потому что её зовут оба пути: правило, живущее
    # только в одном, уже пять раз оказывалось неработающим (13.273/13.280/13.286/13.301/13.308).
    kept = _prefer_port_tech_choice(kept, obs, extractor)
    _count_kinds(cands, "вход правил")
    if getattr(ARGS, "no_tile_actions", False):
        # Флаг обязан доходить и до ПРОГНОЗА: его кандидаты клеток строятся в
        # `brain/forecast/options.py`, мимо общего фильтра (измерено: с флагом в прогоне
        # оставались 8 отправок по клеткам — «изменение не подключено»).
        os.environ.setdefault("DOF_NO_TILE_ACTIONS", "1")
        _tile_free = []
        for _c in kept:
            _act = _to_action(_c)
            _nm = str(_act[2]) if _act else ""
            if _nm.startswith(("city_work_", "city_unwork_")):
                continue
            _tile_free.append(_c)
        if _tile_free or not kept:
            kept = _tile_free
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        city_ish = [c for c in cands
                    if str((_to_action(c) or ("", "", ""))[2]).startswith("produce_")]
        print(f"  [правила] кандидатов {before} → удержание {len(held)} → войско {len(kept)}; "
              f"постановок было {len(city_ish)}, "
              f"отброшено удержанием {len(city_ish) - len([c for c in held if str((_to_action(c) or ('','',''))[2]).startswith('produce_')])}, "
              f"войском {len([c for c in held if str((_to_action(c) or ('','',''))[2]).startswith('produce_')]) - len([c for c in kept if str((_to_action(c) or ('','',''))[2]).startswith('produce_')])}; "
              f"военных типов {len(military)}; род кандидатов "
              f"{sorted({str((_to_action(c) or ('?','',''))[0]) for c in cands})}; "
              f"стенд предложил городу "
              f"{sum(len(v) for k, v in (avail or {}).items() if str(k) in ('city', 'city_ctrl') and isinstance(v, dict))}; "
              f"все имена с 'produc' в предложении "
              f"{[str(a) for v in (avail or {}).values() if isinstance(v, dict) for acts in v.values() if isinstance(acts, dict) for a in acts.keys() if 'produc' in str(a)][:5]}; "
              f"действий у города всего "
              f"{[str(a) for v in (avail or {}).values() if isinstance(v, dict) for acts in v.values() if isinstance(acts, dict) for a in acts.keys() if str(a).startswith('city_')][:5]}; "
              f"имена городовых кандидатов "
              f"{[str((_to_action(c) or ('','',''))[2]) for c in cands if str((_to_action(c) or ('','',''))[0]) == 'city'][:3]}"
              f" / в предложении стенда "
              f"{[str(k) for v in (avail or {}).values() if isinstance(v, dict) for a in v.values() if isinstance(a, dict) for k in a.keys()][:6]}",
              flush=True)
    return kept


def _to_action(candidate: dict):
    """Candidate -> the (ctrl_type, actor_id, action_name) tuple env.step wants.

    Uses the structured fields: actor ids and action names may contain
    underscores and spaces, and actor ids may be ints or strings.
    """
    ctrl_type = candidate.get('ctrl_type')
    actor_id = candidate.get('actor_id')
    action_name = candidate.get('action_name')
    if ctrl_type is None or actor_id is None or action_name is None:
        return None
    return (ctrl_type, actor_id, action_name)


def _core_entities(state) -> list:
    """SystemStateMatrix → Rust core entity list.

    The core carries `current_dof` in the DOF-SPEC [0, 1] field range (its
    `apply_action` clamps at 1.0), while the extractor works in options. Every
    value the core sees is therefore divided by one shared reference, so the
    ordering and the sign of every net delta are identical to the option-space
    computation (Σ ln(x/c) = Σ ln(x) − n·ln c, and n is the same on both sides of
    every comparison the bridge makes).
    """
    return [
        CoreEntity(
            entity_id=e.entity_id,
            current_dof=min(1.0, e.dof_count / CORE_DOF_SCALE),
            is_collapse_source=e.is_collapse_source,
            is_reversible=e.time_to_collapse_mks > 1e14,
        )
        for e in state.entities.values()
    ]


def _core_actions(candidates: list[dict]) -> list:
    """DOF candidates → Rust core action list (deltas in the core's own units)."""
    return [
        CoreAction(
            action_id=c["option_id"],
            description=c.get("description", ""),
            dof_delta=[(k, v / CORE_DOF_SCALE)
                       for k, v in c.get("projected_dof_delta", {}).items()],
            is_reversible=bool(c.get("is_reversible", True)),
            duration_turns=1.0,
        )
        for c in candidates
    ]


def _frozen_probe(obs: dict, my_player_id) -> list[str]:
    """Факты о точке замерзания — чтобы «нет кандидатов» перестало быть симптомом.

    Печатается только когда ядро отказалось от всех кандидатов. Отвечает на три
    вопроса, без которых любые формулы для скрытых клеток — гадание:

    1. **что за юнит** (тип, носитель населения или нет, запас хода);
    2. **сколько тумана в его достижимой зоне** (нераскрытые клетки в квадрате
       радиуса `move_rate`) — это и есть «незнание», ради которого стоило бы идти;
    3. **что говорит оценка площадки на месте и на лучшей достижимой**: годна ли,
       какая еда/щиты/торговля, какова доля скрытых клеток в её рабочей зоне.

    Ничего не меняет и не пишет: только читает наблюдение теми же функциями, что и
    агент, поэтому меряет именно то, чем агент руководствуется.
    """
    lines: list[str] = []
    try:
        from env.entity_extractor import is_population_carrier, num, spec_field
        from env.site_eval import evaluate_site, in_bounds, tile_output
    except Exception:  # noqa: BLE001
        return lines
    units = as_dict(as_dict(obs).get('unit'))
    map_obs = as_dict(as_dict(obs).get('map'))
    vals = {}
    if 'rules.food_cost' in (as_dict(obs).get('rules') or {}):
        vals['FOOD_COST'] = float(as_dict(obs).get('rules')['food_cost'])
    for unit_id, u in units.items():
        if not isinstance(u, dict):
            continue
        owner = u.get('owner', my_player_id)
        try:
            if int(owner) != int(my_player_id):
                continue
        except (TypeError, ValueError):
            continue
        x, y = u.get('x'), u.get('y')
        if x is None or y is None:
            continue
        x, y = int(x), int(y)
        kind = str(spec_field(u, 'rule_name', '') or '?')
        carrier = bool(is_population_carrier(u))
        reach = max(1, int(num(spec_field(u, 'move_rate', 1), 1)))
        hidden = known = 0
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                try:
                    if not in_bounds(map_obs, x + dx, y + dy):
                        continue     # за краем карты: ни раскрытой, ни скрытой
                    if tile_output(map_obs, x + dx, y + dy)[3]:
                        known += 1
                    else:
                        hidden += 1
                except Exception:  # noqa: BLE001
                    pass
        try:
            here = evaluate_site(map_obs, x, y, size=1, vals=vals)
            site_txt = (f"площадка здесь: годна={here.viable}, "
                        f"еда={here.food:.1f} (гейт {here.gate_food:.1f}/"
                        f"верх {here.gate_food_high:.1f}), "
                        f"щиты={here.shields:.1f}, торговля={here.trade:.1f}, "
                        f"скрытых в зоне {here.unknown_ratio:.0%} [{here.reason}]")
        except Exception as exc:  # noqa: BLE001
            site_txt = f"площадка здесь: ошибка {type(exc).__name__}"
        lines.append(f"[замер] {kind} (unit_{unit_id}) на ({x},{y}) ход={reach} "
                     f"носитель={carrier} скрытых/раскрытых в достижимой зоне "
                     f"{hidden}/{known}; {site_txt}")
    return lines


_CANDIDATE_DUMPS: list = []
# Номер игры в серии: срезы из одной серии пишутся в ОДИН файл, и без номера
# игры строки разных матчей смешиваются — «город исчез на 3-м ходу» становится
# неразличимо с «город исчез на 3-м ходу другой игры».
_EPISODE_IDX: list = [0]
# Действия, выбранные ЗА ход: срез состояния без них не отличает «мир сам забрал
# город» от «наш же выбор его и погубил» — а это ровно разница между K1 и K5.
_TURN_ACTIONS: dict = {}
#: Правило F (§10.30): что отсечено за матч и сколько раз не нашлось записи города.
_GATE_FILTERED: list = [0]
_GATE_NO_CITY: list = [0]
_GATE_REASONS: list = []
#: Сколько раз в сообщениях мира встретился признак боя (§10.33: «нападает»).
_COMBAT_MESSAGES: list = [0]
#: Вердикт Правила F по ушедшему действию: (ctrl, actor, name) -> текст вердикта.
_ACTION_VERDICT: dict = {}
_BUY_DIAG_PRINTED: list = []
_TECH_NUMBERS_SEEN: list = []


def _state_dump_path() -> str:
    """Куда писать срезы: рядом с --output, иначе в /tmp."""
    out = getattr(ARGS, "output", None)
    return f"{out}.state.jsonl" if out else "/tmp/dof_state_dump.jsonl"


def _world_citymindist(env) -> int:
    """`citymindist` из САМОГО МИРА (`rule_ctrl.game_info`), иначе 0.

    Это характеристика мира (указание владельца: цену достаточно узнать один раз у мира),
    поэтому спрашиваем сервер, а не задаём число сами.
    """
    try:
        gi = getattr(getattr(_controller_of(env), "rule_ctrl", None), "game_info", None)
        if isinstance(gi, dict) and gi.get("citymindist") is not None:
            return int(gi["citymindist"])
    except Exception:  # noqa: BLE001
        return 0
    return 0


def _controller_of(env):
    ctrl = getattr(env, "civ_controller", None)
    if ctrl is None:
        inner = getattr(env, "unwrapped", None)
        ctrl = getattr(inner, "civ_controller", None) if inner is not None else None
    return ctrl


def _plain(value):
    """Привести значение мира к обычным типам: numpy-массив → список.

    ЖИВОЕ наблюдение отдаёт `map.output` массивом, а не списком списков, и на этом
    прибор уже падал: `array or []` бросает `ValueError` («truth value … ambiguous»).
    Булевых проверок на значениях мира быть не должно вовсе.
    """
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # noqa: BLE001
            return value
    return value


def _tile_out(obs: dict, x, y):
    """Выход клетки по (x, y) в ОБЕИХ ориентациях: измеряем, а не угадываем.

    В сохранённых фикстурах `map.output[x][y]` (78 × 52), но на ЖИВЫХ наблюдениях
    прибор вернул `None` — значит, ориентация (или наличие раздела) там иная.
    Поэтому пишем оба прочтения: `xy` и `yx`, вместе с размерами массива.
    """
    mp = (obs or {}).get("map")
    if not isinstance(mp, dict):
        return {"размеры": None, "выход_xy": None, "выход_yx": None}
    out = _plain(mp.get("output"))
    ter = _plain(mp.get("terrain"))
    if out is None:
        out = []
    if ter is None:
        ter = []
    row = {"размеры": [len(out),
                       len(out[0]) if out and hasattr(out[0], "__len__") else None]}
    for name, (a, b) in (("xy", (x, y)), ("yx", (y, x))):
        try:
            row[f"выход_{name}"] = out[a][b]
            row[f"террейн_{name}"] = ter[a][b]
        except Exception:  # noqa: BLE001
            row[f"выход_{name}"] = None
    return row


def _city_workable_tiles(obs: dict, rec: dict) -> list:
    """Клетки в радиусе города с ЕДОЙ/ЩИТАМИ/ТОРГОВЛЕЙ по нашему читателю карты.

    Зачем в срезе. Расстановку жителей у него выбирает управляющий по взвешенной сумме
    (`cm.c`), а наш путь меряет клетку мерой рабочего (`infracache.c`). Чтобы решить, менять ли
    путь, нужен замер на ОДНИХ И ТЕХ ЖЕ числах — тех, что видит живой путь (`site_eval.tile_output`,
    а не `окно_клеток`, где порядок чисел не подтверждён).
    """
    from brain.ai_default.city_tiles import workable_offsets
    from brain.ai_default.tile_outputs import tile_outputs_from_rules
    from env.terrain_work import tile_terrain_extras
    mp = (obs or {}).get("map")
    if not isinstance(mp, dict):
        return []
    try:
        cx, cy = int(rec.get("x")), int(rec.get("y"))
    except (TypeError, ValueError):
        return []
    out = []
    for dx, dy in workable_offsets(5):
        # Центр города обрабатывается БЕЗ жителя («свободно обрабатываемая клетка» у него же,
        # `is_free_worked_index` в `cm.c:1944`). Выбрасывать его нельзя: без него сумма выходов
        # города ниже фактической, и любой замер по такому срезу сравнивает не то.
        is_center = (dx == 0 and dy == 0)
        try:
            # ЧИСЛА — ПО ПРАВИЛАМ И С УЛУЧШЕНИЯМИ, как их считает живой путь. `map.output` —
            # только база: на ней орошённый луг неотличим от неорошённого, и замер по ней
            # сравнивает не то, что видит решение (моя ошибка, поймана сравнением с фактом:
            # «расстановки дают излишек 1» против фактических 2).
            terrain, extras = tile_terrain_extras(mp, cx + dx, cy + dy)
            outs = tile_outputs_from_rules(terrain, extras)
        except Exception:  # noqa: BLE001
            continue
        if not outs:
            continue
        food, shield = outs[0], outs[1]
        trade = outs[2] if len(outs) > 2 else 0.0
        known = True
        out.append({"dx": int(dx), "dy": int(dy), "food": float(food),
                    "shield": float(shield), "trade": float(trade),
                    "known": bool(known), "center": bool(is_center)})
    return out


def _city_window(obs: dict, cx, cy, r: int = 2):
    """Выходы клеток вокруг города в ОБЕИХ ориентациях, по смещениям.

    Нужно ровно для цены действий `city_work/city_unwork`: имя действия даёт
    смещение `(dx, dy)`, а цена — выход ИМЕННО той клетки. Ориентация на живых
    данных ещё не подтверждена, поэтому пишем оба прочтения.
    """
    mp = (obs or {}).get("map")
    if not isinstance(mp, dict) or cx is None or cy is None:
        return None
    out = _plain(mp.get("output"))
    if not isinstance(out, list):
        return None
    win = {}
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            xy = yx = None
            try:
                xy = out[cx + dx][cy + dy]
            except Exception:  # noqa: BLE001
                pass
            try:
                yx = out[cy + dy][cx + dx]
            except Exception:  # noqa: BLE001
                pass
            win[f"{dx},{dy}"] = {"xy": xy, "yx": yx}
    return win


def _dump_state(env, obs, info, extractor, turn: int, port=None) -> None:
    """Срез мира на ходу: наши города/юниты, видимые чужие, знание клиента, сообщения.

    Зачем: вопрос «почему сторона теряет город на 2–5-м ходу» без этого среза
    решается догадкой, а догадка уже один раз дала неверный вывод (захват города
    ИИ при `enemy_units_seen_max = 0`). Здесь видно ровно то, чем мир это
    объясняет: состояние города до потери, кто был рядом, что говорит
    НЕЗАВИСИМОЕ знание клиента, и что написал сам сервер в `game.messages`.
    """
    my_id = getattr(extractor, "my_player_id", None)
    obs = obs or {}
    city_recs = as_dict(obs.get("city")) or {}
    unit_recs = as_dict(obs.get("unit")) or {}
    my_cities, my_units, foreign_cities, foreign_units = [], [], [], []
    for cid, rec in city_recs.items():
        if not isinstance(rec, dict):
            continue
        row = {"id": cid, "owner": rec.get("owner"), "x": rec.get("x"),
               "y": rec.get("y"), "size": rec.get("size"),
               "food_stock": rec.get("food_stock"),
               "surplus_food": rec.get("surplus_food"),
               "prod_food": rec.get("prod_food"),
               "ppl_unhappy": rec.get("ppl_unhappy"),
               "turns_to_prod": rec.get("turns_to_prod_complete"),
               "production_value": rec.get("production_value"),
               "клетка_центра": _tile_out(obs, rec.get("x"), rec.get("y")),
               # Выходы клеток города: если мир их публикует (civrealm читает
               # `pcity['output_food'][idx]`), то арифметику еды можно взять
               # напрямую, а не выводить из дельт между ходами.
               # §13.328: срез обязан нести ВСЕ числа, которые публикует мир, а не
               # выбранные нами: иначе «щиты/ход None» — наша пустота, а не его ноль.
               "прочие_поля": {k: _plain(rec[k]) for k in rec
                               if k not in ("x", "y", "owner", "size", "food_stock",
                                            "surplus_food", "prod_food", "ppl_unhappy",
                                            "turns_to_prod_complete", "production_value")},
               "ключи_записи": sorted(rec.keys()),
               "окно_клеток": _city_window(obs, rec.get("x"), rec.get("y")),
               "рабочие_клетки": _city_workable_tiles(obs, rec),
               "выходы_массивами": {
                   k: _plain(rec[k]) for k in rec
                   if (isinstance(rec.get(k), (list, tuple))
                       or hasattr(rec.get(k), "tolist"))
                   and any(s in k for s in
                           ("output", "tile", "worked", "food", "specialist"))}}
        (my_cities if rec.get("owner") == my_id else foreign_cities).append(row)
    for uid, rec in unit_recs.items():
        if not isinstance(rec, dict):
            continue
        row = {"id": uid, "owner": rec.get("owner"),
               "type": rec.get("type_rule_name"), "x": rec.get("x"),
               "y": rec.get("y"), "moves": rec.get("moves_left"),
               "клетка": _tile_out(obs, rec.get("x"), rec.get("y"))}
        (my_units if rec.get("owner") == my_id else foreign_units).append(row)
    ctrl_info: dict = {}
    ctrl = _controller_of(env)
    if ctrl is not None:
        probes = [
            ("разбит", lambda: bool(ctrl.my_player_is_defeated())),
            ("городов_контроллер",
             lambda: len(ctrl.city_ctrl.get_cities_by_player_id(my_id))),
            ("юнитов_контроллер", lambda: len(ctrl.unit_ctrl.units)),
            ("есть_юниты", lambda: bool(ctrl.unit_ctrl.have_units())),
            ("есть_поселенцы",
             lambda: bool(ctrl.unit_ctrl.my_units_have_type("Settlers"))),
            ("состояние_клиента", lambda: ctrl.clstate.client_state()),
            ("игра_окончена", lambda: bool(ctrl.game_is_over)),
            ("игра_завершена", lambda: bool(ctrl.game_is_end)),
            ("ход_контроллера", lambda: ctrl.turn_manager.turn),
        ]
        for name, fn in probes:
            try:
                ctrl_info[name] = fn()
            except Exception as exc:  # noqa: BLE001 - диагностика не рушит матч
                ctrl_info[name] = f"ошибка:{type(exc).__name__}"
    player_rec = as_dict(as_dict(obs.get("player")).get(str(my_id))) or {}
    game_rec = as_dict(obs.get("game")) or {}
    actions = as_dict(info.get("available_actions")) or {}
    row = {
        "эпизод": _EPISODE_IDX[0],
        "порт": port,
        "ветвь": "прогноз" if ARGS.forecast else "ВЫКЛ",
        "turn": (info or {}).get("turn"),
        "turn_played": turn,
        "obs_entities": len(city_recs) + len(unit_recs),
        "n_city_recs": len(city_recs),
        "n_unit_recs": len(unit_recs),
        "my_cities": my_cities,
        "my_units": my_units,
        "foreign_cities": foreign_cities,
        "foreign_units": foreign_units,
        "is_alive": player_rec.get("is_alive"),
        "score": player_rec.get("score"),
        "gold": player_rec.get("gold"),
        "offered": {k: (len(v) if isinstance(v, dict) else v)
                    for k, v in actions.items()},
        "действия_за_ход": _TURN_ACTIONS.get(turn) or [],
        "messages": game_rec.get("messages"),
        "food_cost": (as_dict(obs.get("rules")) or {}).get("food_cost"),
        "celebratesize": (as_dict(obs.get("rules")) or {}).get("celebratesize"),
        "controller": ctrl_info,
    }
    try:
        with open(_state_dump_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - запись среза не должна рушить матч
        pass
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # §13.290: сколько клеток обрабатывает каждый свой город. Мир помечает клетку полем
        # `worked` = id города (`civrealm/.../map/tile.py:63`). Город размера 1 обязан
        # обрабатывать центр И клетку горожанина: если обработана одна — горожане не
        # расставлены, и дело не в ценах и не в работах.
        try:
            _worked_layer = (as_dict(obs.get("map")) or {}).get("worked")
            _counts = {}
            if _worked_layer is not None:
                import numpy as np

                _wa = np.asarray(_worked_layer)
                _ids = [c.get("id") for c in my_cities]
                for _cid in _ids:
                    if _cid is None:
                        continue
                    _counts[_cid] = int((_wa == _cid).sum())
            _sizes = {c.get("id"): c.get("size") for c in my_cities}
            _layer_keys = sorted((as_dict(obs.get("map")) or {}).keys())
            print(f"      [обработка] свои города: "
                  f"{[(cid, f'размер {_sizes.get(cid)}', f'клеток {n}') for cid, n in _counts.items()]}"
                  f"{'(нет клеток) ' if not _counts else ''}слои карты: {_layer_keys}",
                  flush=True)
        except Exception as _exc:  # noqa: BLE001 - диагностика не должна рушить матч
            print(f"      [обработка] не измерена: {_exc!r}", flush=True)
    print(f"      [состояние {row['turn']}] сущ={row['obs_entities']} "
          f"(город {len(city_recs)}, юнит {len(unit_recs)}) "
          f"свои города={[(c.get('x'), c.get('y'), c.get('size'), c.get('surplus_food')) for c in my_cities]} "
          f"свои юниты={[(u.get('type'), u.get('x'), u.get('y')) for u in my_units]} "
          f"чужих видно={len(foreign_units)} "
          f"жив={row['is_alive']} счёт={row['score']} "
          f"контроллер: городов={ctrl_info.get('городов_контроллер')} "
          f"юнитов={ctrl_info.get('юнитов_контроллер')} "
          f"поселенцы={ctrl_info.get('есть_поселенцы')} "
          f"разбит={ctrl_info.get('разбит')} "
          f"состояние={ctrl_info.get('состояние_клиента')} "
          f"действия={row['действия_за_ход']} "
          f"сообщения={str(row['messages'])[-200:]!r}", flush=True)


def _unit_pos(obs, unit_id):
    """Позиция юнита по его id: нужна для `join_city`, где в имени действия города нет."""
    units = as_dict((obs or {}).get("unit"))
    for key in (unit_id, str(unit_id)):
        rec = units.get(key)
        if isinstance(rec, dict):
            try:
                return int(rec.get("x")), int(rec.get("y"))
            except (TypeError, ValueError):
                return None
    return None


def _food_gate_filter(cands, obs, extractor, turn=None) -> list:
    """Правило F (§10.30) для ПРЕЖНЕГО пути: отсечь еду-небезопасные действия.

    Отсечение идёт ДО ядра, а не вето после выбора: вето оставило бы сторону без
    хода в тот ход, когда безопасная альтернатива была (ядро выбрало бы её).
    Действие, для которого в наблюдении нет записи города-цели, НЕ запрещается —
    правило работает по факту мира; такие случаи считаются отдельно, чтобы
    «не видно города» не выглядело как «безопасно».
    """
    if not getattr(env_config, "FOOD_GATE_ENABLED", True):
        return list(cands)
    from env.food_gate import city_at, city_by_id, denies
    my_id = getattr(extractor, "my_player_id", None)
    kept: list = []
    for cand in cands:
        name = str(cand.get("action_name", ""))
        if not (name.startswith("city_unwork_")
                or name.startswith("city_change_specialist")
                or name == "join_city"):
            kept.append(cand)
            continue
        city = None
        if str(cand.get("ctrl_type", "")) == "city":
            city = city_by_id(obs, cand.get("actor_id"))
        elif name == "join_city":
            pos = _unit_pos(obs, cand.get("actor_id"))
            if pos is not None:
                city = city_at(obs, pos[0], pos[1])
        if not isinstance(city, dict) or city.get("owner") != my_id:
            _GATE_NO_CITY[0] += 1
            kept.append(cand)
            continue
        deny, why = denies(name, city=city, obs=obs, turn=turn)
        if deny:
            _GATE_FILTERED[0] += 1
            if why not in _GATE_REASONS and len(_GATE_REASONS) < 6:
                _GATE_REASONS.append(why)
            continue
        # Вердикт едет ВМЕСТЕ с кандидатом: без этого «протечку» (ушло действие,
        # которое правило обязано было запретить) нельзя отличить от законного хода —
        # состояние внутри хода меняется, и сверка по началу хода врёт.
        try:
            cand["food_gate"] = (f"разрешено: surplus={city.get('surplus_food')} "
                                 f"проверено правилом F")
        except Exception:  # noqa: BLE001
            pass
        kept.append(cand)
    return kept


def _remember_verdict(action, verdict) -> None:
    """Запомнить вердикт Правила F для действия, которое сейчас уйдёт на сервер.

    Действие попадает в запись хода ВМЕСТЕ со своим вердиктом: тогда «протечка»
    видна как «в записи стоит запрет», а не выясняется сверкой по началу хода.
    """
    if verdict and action:
        try:
            _ACTION_VERDICT[(str(action[0]), str(action[1]), str(action[2]))] = str(verdict)
        except Exception:  # noqa: BLE001
            pass


def _verdict_of(action) -> str:
    if not action:
        return ""
    try:
        return _ACTION_VERDICT.get((str(action[0]), str(action[1]), str(action[2])), "")
    except Exception:  # noqa: BLE001
        return ""


def _dump_index_composition(obs, extraction, extractor) -> None:
    """Состав общего индекса DoF: кто сколько даёт и что удерживает сток (§10.34, V3).

    Зачем числа: производство юнита даёт индексу `+ln(опций)` ≈ +1.5, а сток за
    содержание (`UNIT_UPKEEP_SINK_W` × upkeep) при весе 0.05 почти ничего. Без этого
    среза «беговая дорожка производства» — догадка; с ним видно, чем именно она
    уравновешена (или не уравновешена).
    """
    my_id = getattr(extractor, "my_player_id", None)
    state = getattr(extraction, "state", None)
    entities = getattr(state, "entities", None) or {}
    units_obs = as_dict((obs or {}).get("unit")) or {}
    cities_obs = as_dict((obs or {}).get("city")) or {}
    own_units = {f"unit_{k}" for k, v in units_obs.items()
                 if isinstance(v, dict) and v.get("owner") == my_id}
    own_cities = {f"city_{k}" for k, v in cities_obs.items()
                  if isinstance(v, dict) and v.get("owner") == my_id}
    sums: dict[str, float] = {"свои юниты": 0.0, "свои города": 0.0,
                              "чужие юниты": 0.0, "чужие города": 0.0,
                              "технологии": 0.0, "прочее": 0.0}
    for ent_id, ent in entities.items():
        if getattr(ent, "is_collapse_source", False) or not getattr(ent, "dof_known", True):
            continue
        value = math.log(max(float(getattr(ent, "dof_options", 0.0) or 0.0), EPSILON))
        if ent_id in own_units:
            key = "свои юниты"
        elif ent_id in own_cities:
            key = "свои города"
        elif ent_id.startswith("unit_"):
            key = "чужие юниты"
        elif ent_id.startswith("city_"):
            key = "чужие города"
        elif ent_id.startswith(("tech_", "technology_")):
            key = "технологии"
        else:
            key = "прочее"
        sums[key] += value
    upkeep_sum = 0.0
    upkeep_units = 0
    for rec in units_obs.values():
        if not isinstance(rec, dict):
            continue
        u = (float(rec.get("upkeep_food") or 0) + float(rec.get("upkeep_gold") or 0)
             + float(rec.get("upkeep_shield") or 0))
        upkeep_sum += u
        if u > 0:
            upkeep_units += 1
    sink = float(getattr(state, "dof_sink", 0.0) or 0.0)
    parts = getattr(extractor, "_last_sink_parts", None) or {}
    total = sum(sums.values()) - sink
    own_unit_count = sum(1 for v in units_obs.values()
                         if isinstance(v, dict) and v.get("owner") == my_id)
    prices = parts.get("prices") or {}
    price_text = (", ".join(f"{k} {v:.3f}" for k, v in sorted(prices.items()))
                  if prices else "запасной вес 0.05 (города в наблюдении нет)")
    print(f"      [индекс DoF] состав: " +
          ", ".join(f"{k} {v:+.2f}" for k, v in sums.items() if abs(v) > 1e-9) +
          f"; сток {sink:.2f} (содержание {float(parts.get('upkeep', 0.0)):.2f}, "
          f"задержка населения {float(parts.get('delay', 0.0)):.2f})"
          f"; цены из формулы города: {price_text}"
          f"; итог {total:.2f}; своих юнитов {own_unit_count}, "
          f"с содержанием>0 {upkeep_units}, сумма содержания {upkeep_sum:.0f}",
          flush=True)


def _dump_foreign_entities(obs, extraction, extractor) -> None:
    """Срез ЧУЖИХ сущностей в общем DoF: входят ли, сколько дают, кто помечен коллапсом.

    Вопрос Andy: чужие объекты и юниты должны входить в расчёт ОБЩЕГО DoF системы, а
    «источником коллапса» должен становиться лишь тот чужой юнит, который
    НЕПОСРЕДСТВЕННО НАПАДАЕТ. Без этого среза оба утверждения — вера: извлечение
    строится по всем записям наблюдения (фильтра владельца в коде нет), но вклад чужих
    сущностей в индекс и признак коллапса нигде не печатались.
    """
    my_id = getattr(extractor, "my_player_id", None)
    entities = getattr(getattr(extraction, "state", None), "entities", None) or {}
    # Бой или захват в сообщениях мира: без этого «нападает» нечем подтвердить —
    # наш счётчик боевых действий фиксирует только НАШИ бои.
    messages = str(((as_dict((obs or {}).get("game")) or {}).get("messages")) or "")
    combat_hits = [w for w in ("attacked", "destroyed", "captured", "Annihilated",
                               "killed", "razed", "sacked", "bombard")
                   if w in messages]
    if combat_hits:
        _COMBAT_MESSAGES[0] += 1
        print(f"      [бой в сообщениях {_COMBAT_MESSAGES[0]}] слова {combat_hits}: "
              f"{messages[-220:]!r}", flush=True)
    foreign_ids = []
    for unit_id, rec in (as_dict((obs or {}).get("unit")) or {}).items():
        if isinstance(rec, dict) and rec.get("owner") != my_id:
            foreign_ids.append(f"unit_{unit_id}")
    for city_id, rec in (as_dict((obs or {}).get("city")) or {}).items():
        if isinstance(rec, dict) and rec.get("owner") != my_id:
            foreign_ids.append(f"city_{city_id}")
    present, absent, ctx = [], [], []
    if not foreign_ids:
        return                      # нечего мерить: чужих записей в наблюдении нет
    for ent_id in foreign_ids:
        ent = entities.get(ent_id)
        if ent is None:
            absent.append(ent_id)
            continue
        options = float(getattr(ent, "dof_options", 0.0) or 0.0)
        present.append((ent_id, options,
                        bool(getattr(ent, "is_collapse_source", False)),
                        bool(getattr(ent, "dof_known", True))))
    own_unit_city = sum(
        1 for ent_id in entities
        if ent_id.startswith(("unit_", "city_")) and ent_id not in set(foreign_ids))
    foreign_share = sum(math.log(max(o, EPSILON)) for _i, o, _c, _k in present
                        if o > 0)
    own_share = sum(
        math.log(max(float(getattr(e, "dof_options", 0.0) or 0.0), EPSILON))
        for ent_id, e in entities.items()
        if ent_id.startswith(("unit_", "city_")) and ent_id not in set(foreign_ids)
        and getattr(e, "dof_known", True) and not getattr(e, "is_collapse_source", False))
    print(f"      [чужое в DoF] чужих записей {len(foreign_ids)}, из них сущностей "
          f"{len(present)}, не стало сущностью {len(absent)}; своих сущностей "
          f"юнит/город {own_unit_city}; вклад чужих в индекс "
          f"{foreign_share:+.3f} против своих {own_share:+.3f}", flush=True)
    for ent_id, options, collapse, known in present[:6]:
        print(f"        {ent_id}: опций {options:.2f}, "
              f"источник коллапса={collapse}, известно={known}", flush=True)
    if absent[:3]:
        print(f"        НЕ в сущностях: {absent[:3]}", flush=True)


def _dump_fog_distance(obs, extractor) -> None:
    """До ближайшей НЕРАСКРЫТОЙ клетки от каждого своего юнита (§10.41).

    Зачем число: замер §10.40 показал, что дело не в переоценённом производстве, а в
    том, что остальные семейства стоят около нуля. Ценность разведки измерена раньше
    (разрыв Дженсена = INFO_GAP_FLOOR_OPTIONS опций за раскрытую клетку), но она
    применима, только если туман РЯДОМ: иначе шаг к нему стоит больше, чем даёт.
    Здесь видно, сколько шагов до тумана на самом деле.
    """
    mp = (obs or {}).get("map")
    if not isinstance(mp, dict):
        return
    terrain = _plain(mp.get("terrain"))
    if not isinstance(terrain, list) or not terrain:
        return
    my_id = getattr(extractor, "my_player_id", None)
    units = as_dict((obs or {}).get("unit")) or {}
    distances = []
    for rec in units.values():
        if not isinstance(rec, dict) or rec.get("owner") != my_id:
            continue
        try:
            ux, uy = int(rec.get("x")), int(rec.get("y"))
        except (TypeError, ValueError):
            continue
        best = None
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                d = max(abs(dx), abs(dy))
                if best is not None and d >= best:
                    continue
                try:
                    cell = terrain[(ux + dx) % len(terrain)][uy + dy]
                except Exception:  # noqa: BLE001
                    continue
                if cell == 255:
                    best = d
        if best is not None:
            distances.append(best)
    if distances:
        from env.config import INFO_GAP_FLOOR_OPTIONS
        print(f"      [туман] шагов до ближайшей нераскрытой клетки: {distances} "
              f"(медиана {sorted(distances)[len(distances)//2]}); "
              f"ценность одного раскрытия {INFO_GAP_FLOOR_OPTIONS} опции", flush=True)


def _print_food_gate_summary() -> None:
    """Что правило F отсекло за матч — иначе «правило работает» остаётся верой.

    Здесь же журнал РЕШЕНИЙ правила пишется в `<output>.gate.jsonl`: без чисел на
    момент решения «протечку» нельзя отличить от законного хода (состояние внутри
    хода меняется от действия к действию).
    """
    report = food_gate.denial_report()
    decisions = food_gate.decision_log()
    print(f"  правило F (еда необратима): решений проверено {len(decisions)}, "
          f"запрещено {report.get('total', 0)} "
          f"(по семействам: {report.get('counts') or 'нет'}), "
          f"из них отсечено в ПРЕЖНЕМ пути {_GATE_FILTERED[0]} "
          f"(остальные — в прогнозе, там цена считается его формулой), "
          f"без записи города {_GATE_NO_CITY[0]}", flush=True)
    for line in (report.get("examples") or [])[:4]:
        print(f"    пример запрета: {line}", flush=True)
    for why in _GATE_REASONS[:2]:
        print(f"    причина: {why}", flush=True)
    out = getattr(ARGS, "output", None)
    if out and decisions:
        try:
            with open(f"{out}.gate.jsonl", "a", encoding="utf-8") as fh:
                for d in decisions:
                    fh.write(json.dumps({"эпизод": _EPISODE_IDX[0],
                                         "ветвь": "прогноз" if ARGS.forecast else "ВЫКЛ",
                                         **d}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - запись журнала не должна рушить серию
            pass


def _write_learn_record(obs, extractor, metrics) -> None:
    """Срез склада фактов за игру — кривая самообучения (DOF_CALIBRATION §10.32).

    Без этой записи «модель обучается» остаётся верой. Записывается по каждому матчу:

    * **покрытие** — сколько СВОИХ типов юнитов склад уже знает (стоимость);
    * **точность** — совпадает ли память склада с живым `type_build_cost` (и примеры
      расхождений с числами);
    * **поправки** — сколько пар «утверждено ≠ замерено» модель получила за матч;
    * **решения** — сколько действий сделано и какой счёт, чтобы видеть, даёт ли
      память что-то поведению.

    Заодно склад пополняется живыми числами: это и есть обучение (одна запись —
    и мера, и наблюдение).
    """
    my_id = getattr(extractor, "my_player_id", None)
    live: dict[str, float] = {}
    for rec in (as_dict((obs or {}).get("unit")) or {}).values():
        if not isinstance(rec, dict) or rec.get("owner") != my_id:
            continue
        name = str(rec.get("type_rule_name") or rec.get("rule_name") or "")
        try:
            cost = float(rec.get("type_build_cost"))
        except (TypeError, ValueError):
            continue
        if name and cost > 0.0:
            live.setdefault(name, cost)
    store = None
    try:
        from env.measured_facts import MeasuredFacts
        store = MeasuredFacts()
    except Exception:  # noqa: BLE001
        store = None
    known, unknown, mismatch = [], [], []
    for name, cost in sorted(live.items()):
        stored = None
        if store is not None:
            try:
                stored = store.cost(name)
            except Exception:  # noqa: BLE001
                stored = None
        if stored is None:
            unknown.append(name)
        else:
            known.append(name)
            if abs(float(stored) - cost) > 1e-6:
                mismatch.append(f"{name}: склад {stored:g} ≠ мир {cost:g}")
        try:
            if store is not None:
                store.observe_type(name, cost=cost, kind="unit",
                                   source="learn-record")
        except Exception:  # noqa: BLE001
            pass
    if store is not None:
        try:
            store.save()
        except Exception:  # noqa: BLE001
            pass
    row = {
        "эпизод": _EPISODE_IDX[0],
        "ветвь": "прогноз" if ARGS.forecast else "ВЫКЛ",
        "порт": getattr(metrics, "port", None),
        "ходов": getattr(metrics, "turns_played", None) or getattr(metrics, "turns", None),
        "склад_путь": os.environ.get("DOF_MEASURED_FACTS") or "measured_facts.json",
        "свои_типы": sorted(live),
        "живые_стоимости": {k: live[k] for k in sorted(live)},
        "покрытие_известно": known,
        "покрытие_неизвестно": unknown,
        "точность_совпало": len(known) - len(mismatch),
        "точность_расхождения": mismatch,
        "поправок_ключей": len(getattr(metrics, "corrected_keys", []) or []),
        "поправки": (getattr(metrics, "correction_log", []) or [])[:3],
        "решений": getattr(metrics, "decisions", None),
        "решений_на_ход": getattr(metrics, "decisions_per_turn_mean", None),
        "счёт": getattr(metrics, "score_cum", None),
    }
    out = getattr(ARGS, "output", None)
    if not out:
        return
    try:
        with open(f"{out}.learn.jsonl", "a", encoding="utf-8") as fh:
            # `default=str` обязателен: в `correction_log` попадают не-JSON-объекты, и
            # без него запись молча падала ЦЕЛИКОМ (измерено: файл создавался пустым,
            # 80 игр данных остались только в логе). Ошибку больше НЕ глотаем молча.
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  [обучение] запись среза не удалась: {type(exc).__name__}: {exc}",
              flush=True)
    print(f"  [обучение] эпизод {row['эпизод']}: склад знает {len(known)} из "
          f"{len(live)} своих типов, расхождений {len(mismatch)}, "
          f"поправок {row['поправок_ключей']}"
          + (f"; НЕ знает: {unknown}" if unknown else ""), flush=True)


def _dump_candidates(ctx, info) -> None:
    """Напечатать ЧИСЛА кандидатов прогноза: вид, действие, ΔDoF, срок, дисконт.

    Зачем: вопрос «почему исследование редко выбирается» без этих чисел решается
    догадкой. Здесь видно ровно то, из чего поиск выбирает: `add_entity` даёт
    Δ = ln(опции), срок уходит в дисконт γ^срок, а необратимость снимает штраф.
    Печатается до `ARGS.dump_candidates` ходов, одна запись на ход (прогноз
    вызывается за ход дважды — второй раз это конец хода).
    """
    if not ARGS.dump_candidates:
        return
    turn = (info or {}).get("turn")
    if len(_CANDIDATE_DUMPS) >= ARGS.dump_candidates:
        return
    if _CANDIDATE_DUMPS and _CANDIDATE_DUMPS[-1] == turn:
        return
    _CANDIDATE_DUMPS.append(turn)
    try:
        from brain.forecast.options import candidates
        from brain.forecast.search import FORECAST_GAMMA, IRREVERSIBLE_PENALTY
        cands = candidates(ctx.state, ctx.vals)
    except Exception as exc:  # noqa: BLE001
        print(f"        [кандидаты] сбой: {type(exc).__name__}: {exc}", flush=True)
        return
    rows = []
    for cand in cands:
        penalty = 0.0 if cand.effect.reversible else IRREVERSIBLE_PENALTY
        discounted = (cand.effect.delta - penalty) * (FORECAST_GAMMA ** cand.effect.delay)
        rows.append((discounted, cand))
    rows.sort(key=lambda kv: kv[0], reverse=True)
    print(f"        [кандидаты] ход {turn}: всего {len(cands)} "
          f"(по видам: " + ", ".join(
              f"{k} {sum(1 for _c in cands if _c.kind == k)}"
              for k in sorted({c.kind for c in cands})) + ")", flush=True)
    # ── ПОЧЕМУ НЕТ ДВИЖЕНИЯ (§10.34) ────────────────────────────────────────
    # Сервер предлагает по 8 шагов каждому юниту, а в кандидатах движения нет:
    # различаем «шагов не предложено» и «наш фильтр отбросил по ценности».
    try:
        from brain.forecast.options import move_diag
        md = move_diag() or {}
        if md:
            print(f"        [движение] единиц {md.get('единиц')}, предложено "
                  f"шагов {md.get('предложено_шагов')}, отброшено по ценности "
                  f"{md.get('отброшено_по_ценности')}, оставлено "
                  f"{md.get('оставлено')} (после фильтра меню "
                  f"{md.get('оставлено_после_фильтра')}), единиц без шагов "
                  f"{md.get('без_шагов')}, ценность на месте "
                  f"{md.get('текущая_ценность')}", flush=True)
            for step in (md.get("шаги") or [])[:3]:
                print(f"          шаг: {step.get('юнит')} → {step.get('куда')}: "
                      f"ценность {step.get('ценность')}, раскрытие "
                      f"{step.get('раскрытие')}, на месте {step.get('на_месте')}, "
                      f"пройдёт по ценности {step.get('пройдёт_по_ценности')}, "
                      f"с раскрытием {step.get('пройдёт_с_раскрытием')}", flush=True)
            # ── КТО ВЫИГРЫВАЕТ РАНЖИРОВАНИЕ ────────────────────────────────
            # «Кандидат есть, но не выбран» — это про порядок, а не про фильтр.
            # Печатаем ключи ранжирования верхних кандидатов: у движения немедленная
            # дельта нулевая (клетка раскрыта), у производства — ln(опций) нового
            # юнита; если разница только в этом, причина названа числом.
            try:
                from brain.forecast.search import (FORECAST_GAMMA,
                                                   IRREVERSIBLE_PENALTY,
                                                   _rank_key)
                ranked = sorted(
                    cands,
                    key=lambda c: _rank_key(c, ctx.state, ctx.vals, 1.0,
                                            FORECAST_GAMMA, 3),
                    reverse=True)
                preview = []
                for c in ranked[:4]:
                    key = _rank_key(c, ctx.state, ctx.vals, 1.0, FORECAST_GAMMA, 3)
                    preview.append(f"{c.kind}:{c.action[2]}"
                                   f"(дельта {c.effect.delta:+.3f}, ключ {key:+.3f})")
                print(f"        [ранжирование] " + "; ".join(preview), flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"        [ранжирование] сбой: {type(exc).__name__}: {exc}",
                      flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"        [движение] сбой замера: {type(exc).__name__}: {exc}",
              flush=True)
    # ── ПЕРЕПИСЬ МЕНЮ ЮНИТА ─────────────────────────────────────────────────
    # Без неё «в кандидатах нет движения» неотличимо от «сервер не предлагал
    # шагов»: первое — дефект нашего провода, второе — свойство мира. Печатаем
    # СЫРЫЕ имена годных действий по нашим юнитам (сколько всего, сколько из них
    # `goto_*`) — числами, а не догадкой.
    try:
        offered_unit = as_dict(as_dict(info.get("available_actions")).get("unit"))
        ours = list(getattr(ctx.state, "positions", {}) or {})
        census = []
        for unit_id in ours[:4]:
            bare = str(unit_id).split("_", 1)[1] if "_" in str(unit_id) else str(unit_id)
            acts = None
            for key, value in offered_unit.items():
                if str(key) == str(bare):
                    acts = as_dict(value)
                    break
            names = [n for n, ok in (acts or {}).items() if ok]
            goto = [n for n in names if n.startswith("goto")]
            census.append(f"{unit_id}: годных {len(names)} (шагов {len(goto)})"
                          + (f" → {names[:6]}" if names else ""))
        print(f"        [меню юнита] {'; '.join(census) or 'наших юнитов в меню нет'}",
              flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"        [меню юнита] сбой переписи: {type(exc).__name__}: {exc}",
              flush=True)
    # Печатаем верх списка И, отдельно, все исследования/улучшения — даже если они
    # в самом низу: вопрос «почему наука не выбирается» требует её ЧИСЕЛ, а не
    # отсутствия в топе.
    shown = rows[:8]
    for row in rows[8:]:
        if row[1].kind in ("research", "improve", "buy"):
            shown.append(row)
    for discounted, cand in shown:
        # Для появления/исследования дельта = ln(опции) — печатаем и сами опции,
        # чтобы порог считался по числам мира, а не по логарифмам.
        options = ""
        if cand.kind in ("produce", "research"):
            options = f" опций={math.exp(cand.effect.delta):.2f}"
        elif cand.kind == "improve":
            options = f" прирост_города={(cand.extra or {}).get('gain')}"
        elif cand.kind == "buy":
            options = (f" предмет={(cand.extra or {}).get('type')} "
                       f"опций={(cand.extra or {}).get('options')} "
                       f"золото={(cand.extra or {}).get('gold')}")
        print(f"          {cand.kind:8s} {cand.action[0]}/{cand.action[1]}/"
              f"{cand.action[2]} Δ={cand.effect.delta:+.4f}"
              f" срок={cand.effect.delay}{options}"
              f" дисконт={discounted:+.4f}", flush=True)


def _dump_tech_numbers(obs, extractor, info) -> None:
    """ЧИСЛА технологии — даже когда кандидата на неё нет вовсе.

    Без этой строки «почему наука не выбирается» решается догадкой. Здесь видно
    каждое слагаемое: стоимость, накопленное, торговля, ставка, наука за ход по
    ИЗМЕРЕННОМУ драйверу, срок и открываемый набор. Отдельно называется причина,
    по которой семейство пусто, — а их две и они разные: «наука/ход = 0» (миру
    нечем исследовать) и «срок не публикуется» (цена неизвестна).
    """
    if not ARGS.dump_candidates:
        return
    turn = (info or {}).get("turn")
    if _TECH_NUMBERS_SEEN and _TECH_NUMBERS_SEEN[-1] == turn:
        return
    _TECH_NUMBERS_SEEN.append(turn)
    try:
        from brain.forecast.live import _player_record
        my_id = getattr(extractor, "my_player_id", None)
        player = _player_record(obs, my_id)

        def number(value):
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                return 0.0

        cost = number(player.get("researching_cost"))
        done = number(player.get("bulbs_researched"))
        rate = number(player.get("science"))
        trade = 0.0
        for city in (obs.get("city") or {}).values():
            if not isinstance(city, dict):
                continue
            try:
                if int(city.get("owner", my_id)) != int(my_id):
                    continue
            except (TypeError, ValueError):
                continue
            trade += number(city.get("prod_trade"))
        per_turn = round(trade * rate / 100.0)
        current = player.get("researching")
        turns = (max(1, int(math.ceil(max(0.0, cost - done) / per_turn)))
                 if per_turn > 0 and cost > 0 else None)
        unlocked = None
        try:
            from brain.forecast.live import _record_by_id
            from env.entity_extractor import tech_options
            record = _record_by_id(obs.get("tech"), current)
            if record:
                base = number((getattr(extractor, "model", None).values()
                               if getattr(extractor, "model", None) else {})
                              .get("TECH_BASE_OPTIONS"))
                unlocked = float(tech_options(
                    record, as_known=True,
                    model=getattr(extractor, "model", None))) - base
                if unlocked <= 0.0:
                    # Ловушка «пустая запись»: если технологии приписан ноль
                    # открываемого, надо видеть, ЧТО это за запись, иначе
                    # «наука не оценивается» остаётся догадкой.
                    print(f"          запись найдена, но открываемого 0: "
                          f"имя={record.get('name')!r} "
                          f"юнитов={len(record.get('sup_units') or [])} "
                          f"улучшений={len(record.get('sup_improvements') or [])} "
                          f"полей={sorted(record.keys())[:8]}", flush=True)
            else:
                layer = obs.get("tech") or {}
                keys = [str(k) for k in list(layer.keys())[:12]]
                print(f"          запись технологии {current!r} НЕ НАЙДЕНА; "
                      f"ключи слоя ({len(layer)}): {keys}", flush=True)
        except Exception:  # noqa: BLE001
            unlocked = None
        value = None
        if unlocked and unlocked > 0 and turns:
            value = math.log(unlocked) * (0.8 ** turns)
        print(f"        [технология] ход {turn}: исследуется {current!r} "
              f"стоимость={cost:.0f} накоплено={done:.0f} торговля={trade:.0f} "
              f"ставка={rate:.0f}% наука/ход={per_turn} срок={turns if turns else '—'}"
              f" открывает={('%.2f' % unlocked) if unlocked else '—'} опций "
              f"вклад_в_индекс={('%.4f' % value) if value else '—'}", flush=True)
        if per_turn <= 0:
            print("          причина: наука за ход = 0 (миру нечем исследовать) — "
                  "цена технологии не публикуется, и это не «недооценка»", flush=True)
        elif turns is None:
            print("          причина: стоимость технологии неизвестна из наблюдения",
                  flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"        [технология] сбой диагностики: {type(exc).__name__}: {exc}",
              flush=True)


def _improvement_names(env) -> dict:
    """Таблица «индекс постройки → имя» из правил КЛИЕНТА.

    Нужна потому, что постройки города приходят в наблюдении БИТОВОЙ МАСКОЙ без имён,
    а по имени только и можно узнать, что город построил водопровод (предел роста 8 → 12)
    или канализацию (сверх 12). Индексы берём списком по id, как у типов юнитов: словарь
    `improvements` бывает неполным, и тогда нужная постройка просто отсутствует.
    """
    out: dict = {}
    try:
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        rules = getattr(ctl, "rule_ctrl", None)
        names = getattr(rules, "improvements_list", None) or []
        for iid, name in enumerate(list(names)):
            if name:
                out[int(iid)] = str(name)
        for iid, spec in dict(getattr(rules, "improvements", None) or {}).items():
            name = spec.get("name") if isinstance(spec, dict) else None
            if name:
                try:
                    out.setdefault(int(iid), str(name))
                except (TypeError, ValueError):
                    continue
        if not out:
            total = int((getattr(rules, "ruleset_control", None) or {})
                        .get("num_impr_types") or 0)
            for iid in range(total):
                spec = (getattr(rules, "improvements", None) or {}).get(iid)
                if isinstance(spec, dict) and spec.get("name"):
                    out[int(iid)] = str(spec["name"])
    except Exception:  # noqa: BLE001
        return {}
    return out


#: След перечня военных типов: сколько имён пришло за партию (§13.192).
#: Гадать, почему ворота военного типа не срабатывают, нельзя — их надо измерить.
_MILITARY_TRACE: list = []


def _military_type_names(env) -> set:
    """Типы юнитов с наступательной силой — из правил КЛИЕНТА.

    Нужно для переноса их правила опасности (§13.161): военные типы предлагаются
    городу только по нужде. Силу берём у самих правил (`attack_strength`), а не из
    списка имён: список имён — наша догадка, а сила — свойство мира.

    Ошибка здесь раньше возвращала ПУСТОЕ множество молча, а пустое множество делает
    ворота военного типа бездейственными: и прежнее правило, и перенос ничего не меняли
    бы, а выглядело бы это как «эффекта нет». Теперь причина записывается в след.
    """
    out: set = set()
    reason = ""
    try:
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        rules = getattr(ctl, "rule_ctrl", None)
        all_types = dict(getattr(rules, "unit_types", None) or {})
        for _tid, spec in all_types.items():
            if not isinstance(spec, dict):
                continue
            name = spec.get("name")
            try:
                attack = float(spec.get("attack_strength") or 0)
            except (TypeError, ValueError):
                attack = 0.0
            if name and attack > 0.0:
                out.add(str(name))
        if not all_types:
            reason = "правила типов не получены (unit_types пуст)"
        elif not out:
            reason = "у типов нет attack_strength>0 — или поле названо иначе"
    except Exception as exc:  # noqa: BLE001
        _MILITARY_TRACE.append({"n": -1, "reason": f"{type(exc).__name__}: {exc}"})
        return set()
    _MILITARY_TRACE.append({"n": len(out), "reason": reason,
                            "sample": sorted(out)[:4]})
    return out


def _print_military_trace() -> None:
    """Печатает, сколько военных типов реально пришло из правил клиента."""
    if not _MILITARY_TRACE:
        return
    last = _MILITARY_TRACE[-1]
    print(f"\n  военные типы из правил: {last['n']}"
          f"{'  [' + last['reason'] + ']' if last.get('reason') else ''}"
          f"{'  например: ' + ', '.join(last['sample']) if last.get('sample') else ''}",
          flush=True)


def _publish_improvement_names(extractor, env) -> int:
    """Опубликовать имена построек фактами `improvement.<индекс>.name`.

    Мир этого не публикует (битовая маска), правила клиента — публикуют. Без имён
    предел роста остаётся базовым (8), и водопровод не получает цены: он бы поднимал
    предел, о котором формулы не знают.
    """
    names = _improvement_names(env)
    # §13.601: печать карты «номер -> имя постройки». Нужна, чтобы расшифровать битовую маску
    # `improvements` в сейве (биты 7, 12, 21, 37). Под флагом, поведение по умолчанию не трогает.
    if os.environ.get("DOF_IMPROV_MAP") == "1":
        print("  [карта-построек] " + " | ".join(f"{i}={n}" for i, n in sorted(names.items())),
              flush=True)
    for iid, name in sorted(names.items()):
        extractor.model.observe(f'improvement.{iid}.name', name, 0,
                                source=Provenance.RULESET,
                                evidence=f'improvement id {iid} from the client rules')
    return len(names)


def _unit_type_names(env) -> dict:
    """Таблица «id типа юнита → имя» из правил КЛИЕНТА.

    Нужна, чтобы опознать предмет в очереди города (`production_kind`/`production_value`)
    и тем самым оценить покупку. Берём СПИСОК по id (`unit_types_list[id] = name`) — он
    заполняется по индексу; словарь `unit_types` оказался неполным (52 записи при
    `production_value = 71`, то есть предмет в нём просто отсутствовал). Если имени нет —
    покупку прогноз не предложит: угадывать цену предмета нельзя.
    """
    out: dict = {}
    try:
        ctl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        rules = getattr(ctl, "rule_ctrl", None)
        # СДВИГ: в наблюдении `production_value` юнита увеличен на число типов улучшений
        # (`city/city_state.py`: `production_value += num_impr_types` для VUT_UTYPE).
        # Без него предмет не опознавался вовсе (id 68/71 при таблице в 52 записи).
        shift = 0
        try:
            shift = int((getattr(rules, "ruleset_control", None) or {})
                        .get("num_impr_types") or 0)
        except (TypeError, ValueError):
            shift = 0
        names = getattr(rules, "unit_types_list", None) or []
        for tid, name in enumerate(list(names)):
            if name:
                out[int(tid) + shift] = str(name)
        for tid, spec in dict(getattr(rules, "unit_types", None) or {}).items():
            name = spec.get("name") if isinstance(spec, dict) else None
            if name:
                try:
                    out.setdefault(int(tid) + shift, str(name))
                except (TypeError, ValueError):
                    continue
    except Exception:  # noqa: BLE001
        return {}
    return out


def _production_names(env) -> dict:
    """Таблица «production_value наблюдения → имя» по РОДУ постановки.

    Согласовано с кодом встроенного ИИ: он читает предмет очереди парой
    (`pcity->production.kind`, `pcity->production.value`) — род и значение вместе
    (`ai/default/daicity.c:1868/1915/1996`). Одна таблица имён без рода неверна, и
    это измерено: `production_value=71` разбиралось как юнит №3 «Warriors», тогда как
    стенд публикует УЛУЧШЕНИЯ без сдвига, а ЮНИТЫ со сдвигом на число улучшений
    (`city/city_state.py:91-92`: `production_value += num_impr_types` для VUT_UTYPE).

    Проверка числами мира (`classic/`): улучшений **68**, юнитов **52**, и порядок
    юнитов `[unit_settlers] → [unit_worker] → [unit_engineers] → [unit_warriors]`,
    то есть `71 − 68 = 3 = warriors`. Чтение было ВЕРНЫМ; не хватало второй половины —
    улучшений: при их роде в таблице юнитов имени нет вовсе, и предмет очереди
    назывался «ничем», из-за чего хранитель постановки (§13.196) не удерживал её.

    Ключи не пересекаются, пока сдвиг равен числу улучшений: 0…67 — улучшения,
    68…119 — юниты. Если сдвига нет (правила не отдали `num_impr_types`), таблица
    улучшений строится первой и юнит НЕ перекрывает её (`setdefault`).
    """
    out: dict = dict(_improvement_names(env) or {})
    for key, name in (_unit_type_names(env) or {}).items():
        out.setdefault(int(key), str(name))
    return out


def _gold_of(obs, extractor) -> float:
    """Золото игрока — по ЗАПИСИ игрока, а не по ключу словаря (ловушка §5.2f/13)."""
    try:
        from brain.forecast.live import _player_record
        rec = _player_record(obs, getattr(extractor, "my_player_id", None)) or {}
        return float(rec.get("gold") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _forecast_decide(obs, info, dof, extractor, avail, *, type_names=None,
                     military_names=None,
                     gold=None) -> tuple[bool, tuple | None]:
    """Прогноз решает ход: `(взял_ли_решение, действие)`.

    Различать «прогноз решил не действовать» и «прогноз недоступен» обязательно:
    первое — законный исход DOF-Core (нет строгого улучшения), и подменять его
    прежним путём нельзя; второе — сбой, и тогда работает прежний путь.
    """
    if not ARGS.forecast:
        return False, None
    # Отдельное решение рабочего (§13.259): как у встроенного ИИ, работа по клетке не соревнуется
    # с ходом и производством города. Признак печатается — иначе «работы не было» и «решение не
    # подключено» неразличимы.
    if getattr(ARGS, "worker_work", True):
        try:
            from brain.forecast import live as _flive  # локально: модуль импортируют и в других местах
            _ww = _flive.worker_work_choice(obs, info, extractor,
                                            getattr(extractor, "my_player_id", None))
        except Exception as _exc:  # noqa: BLE001 - не рушим матч диагностикой
            _ww = None
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"        [рабочий] сбой решения: {type(_exc).__name__}: {_exc}", flush=True)
        if _ww is not None:
            _FORECAST_STATS["worker_work"] = _FORECAST_STATS.get("worker_work", 0) + 1
            try:
                _wtn = int((info or {}).get("turn") or (info or {}).get("turn_played") or -1)
            except (TypeError, ValueError):
                _wtn = -1
            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                print(f"        [прогноз] отправляю (ход {_wtn}) работа: {_ww[2]} "
                      f"(актёр {_ww[1]})", flush=True)
            return True, _ww
    if os.environ.get("DOF_TRACE_UNITS") == "1":
        # Покадровый состав: без него нельзя ответить, достраивается ли предмет
        # (например `Settlers`) и что делает вышедший поселенец. Дамп состояния для
        # этого непригоден — он повторяет первый ход во всех кадрах (измерено, §13.230).
        try:
            _tn = int((info or {}).get("turn") or (info or {}).get("turn_played") or -1)
        except (TypeError, ValueError):
            _tn = -1
        if _tn not in _UNIT_TRACE_TURNS:
            _UNIT_TRACE_TURNS.add(_tn)
            _my_id = getattr(extractor, "my_player_id", None)
            _counts: dict[str, int] = {}
            # Путь поселенцев — для объявленного замера (§13.244). Объявлять ДО цикла:
            # первая редакция стояла после него, и прогоны падали `UnboundLocalError`
            # (поймал привратник годности серии, §13.245).
            _walk: list[str] = []
            _units_seen = 0
            for _ukey, _u in as_dict(obs.get("unit")).items():
                if not isinstance(_u, dict):
                    continue
                _units_seen += 1
                if _my_id is not None and _u.get("owner") is not None \
                        and str(_u.get("owner")) != str(_my_id):
                    continue
                _tname = str(_u.get("type_rule_name") or _u.get("type") or "?")
                _counts[_tname] = _counts.get(_tname, 0) + 1
                if "Settler" in _tname or "Engineer" in _tname or "Worker" in _tname:
                    # Рабочие добавлены §13.255: без них не видно, предлагает ли стенд работу
                    # (`irrigate`/`mine`/`build_road`) и что мы из этого выбираем.
                    # Объявленный замер (§13.244-13.246): ПОСТРОЕННЫЙ поселенец стоит на месте.
                    # Нужен не только путь, но и РЕШЕНИЕ: что предлагал стенд и что выбрали —
                    # иначе «хода нет» и «хода не было в предложении» неразличимы.
                    _m = re.search(r"(\d+)$", str(_ukey))
                    _uid = int(_m.group(1)) if _m else None
                    _off_unit = ((info or {}).get("available_actions", {}) or {}).get("unit", {}) or {}
                    _acts = (_off_unit.get(_uid) if _uid is not None else None)
                    if _acts is None and _uid is not None:
                        _acts = _off_unit.get(str(_uid))
                    _acts = _acts or {}
                    _act_names = (sorted(_acts)[:8] if isinstance(_acts, dict)
                                  else [str(x) for x in (_acts or [])][:8])
                    _all_names = sorted(_acts) if isinstance(_acts, dict) else []
                    _interesting = [n for n in _all_names
                                    if any(k in str(n) for k in ("goto", "found", "build",
                                                                 "city", "fortify", "irrigate",
                                                                 "mine", "road"))]
                    # Работы по клетке — отдельным перечнем (§13.255): общий список режется
                    # по алфавиту, и `irrigate`/`mine` в первые десять не попадают.
                    _works = [n for n in _all_names
                              if any(k in str(n) for k in ("irrigate", "mine", "road",
                                                           "cultivate", "plant", "fortif"))]
                    _walk.append(f"{_tname}#{_uid}@{_u.get('x')},{_u.get('y')} "
                                 f"предложено {len(_all_names)}, ходовых "
                                 f"{len(_interesting)}: {_interesting[:10]} "
                                 f"работы {len(_works)}: {_works[:8]}")
            _cities = [c for c in as_dict(obs.get("city")).values()
                       if isinstance(c, dict)
                       and (_my_id is None or str(c.get("owner")) == str(_my_id))]
            _queue = []
            for _c in _cities:
                _qname = (type_names or {}).get(int(_c.get("production_value") or -1))
                _cma = _c.get("cma_enabled")
                _qname = f"{_qname}[упр.{_cma}]" if _cma is not None else _qname
                _queue.append(f"{_c.get('id')}:{_qname or _c.get('production_value')}"
                              f"(разм.{_c.get('size')},ед.+{_c.get('surplus_food')},"
                              f"запас еды {_c.get('food_stock')}, житница "
                              f"{_c.get('granary_size')}/{_c.get('granary_turns')}, "
                              f"рост через {_c.get('growth_in')}, "
                              f"до готовности {_c.get('turns_to_prod_complete')})")
            print(f"        [наши юниты] ход {_tn}: городов {len(_cities)} | юниты всего "
                  f"{_units_seen}, наших {sum(_counts.values())} "
                  f"{dict(sorted(_counts.items()))} | очередь {_queue}"
                  + (f" | путь {_walk}" if _walk else ""), flush=True)
    try:
        from brain.forecast import choose
        from brain.forecast.live import _player_record, build_context

        _tile_first = None
        ctx = build_context(obs, info, dof, extractor,
                            exclude_actors=set(_USED_ACTORS[0])
                            if _USED_ACTORS else None,
                            type_names=type_names,
                            military_names=military_names, gold=gold)
        if getattr(ARGS, "tile_every_turn", False):
            # Приказ по клетке живёт ОДИН ход — управляющий сервера перекрывает его на
            # следующем обновлении города (§13.234), но именно наш приказ даёт прирост еды, а
            # раскладка мира даёт ноль (§13.235: без приказов 0–1 город против 2–3). Значит
            # приказ надо подавать КАЖДЫЙ ход, а не только когда мир оставил жителя без работы.
            try:
                # Города и клетки живут в `vals` (Valuations), а не в самом контексте:
                # `ctx.city_ids` такого поля нет — ветвь падала 126 раз и не исполнялась
                # вовсе (измерено следом: `AttributeError: 'LiveContext' object has no
                # attribute 'city_ids'`). «Эффекта нет» и «ветвь не исполняется» снова
                # оказались неразличимы без следа.
                _vals = getattr(ctx, "vals", None)
                for _cid in ((_vals.city_ids() if _vals is not None else []) or []):
                    for _a, _g in ((_vals.tiles(_cid) if _vals is not None else []) or []):
                        if _g and float(_g) > 0 and (_tile_first is None
                                                     or float(_g) > _tile_first[1]):
                            _tile_first = (("city", _cid, str(_a)), float(_g))
            except Exception as _exc:  # noqa: BLE001 - не рушим матч диагностикой
                print(f"        [клетка каждый ход] сбой: {type(_exc).__name__}: {_exc}",
                      flush=True)
                _tile_first = None
            if _tile_first is not None:
                _wire_t = _to_wire_action(_tile_first[0], avail)
                if _wire_t is not None:
                    if os.environ.get("DOF_TRACE_FILTERS") == "1":
                        print(f"        [клетка каждый ход] {_tile_first[0][2]} "
                              f"(город {_tile_first[0][1]}, прирост {_tile_first[1]:.2f})",
                              flush=True)
                    _FORECAST_STATS["tile_every_turn"] = (
                        _FORECAST_STATS.get("tile_every_turn", 0) + 1)
                    return True, _wire_t
        if ARGS.dump_candidates and len(_BUY_DIAG_PRINTED) < 4:
            rec = {}
            for city in (obs.get("city") or {}).values():
                if isinstance(city, dict) and city.get("id") is not None:
                    rec = city
                    break
            if rec.get("id") is not None:
                # Печатаем не на первом решении (города ещё нет), а на первом, где он есть.
                _BUY_DIAG_PRINTED.append(True)
                offered_city = {}
                for key, acts in ((info.get("available_actions") or {})
                                  .get("city") or {}).items():
                    if str(key) == str(rec.get("id")):
                        offered_city = acts if isinstance(acts, dict) else {}
                print(f"        [покупка] таблица типов: {len(type_names or {})}; "
                      f"город: {rec.get('id')}, род={rec.get('production_kind')}, "
                      f"значение={rec.get('production_value')}, "
                      f"срок={rec.get('turns_to_prod_complete')}, "
                      f"buy_cost={rec.get('buy_cost')}, "
                      f"золото={_gold_of(obs, extractor)}; "
                      f"предложение покупки={offered_city.get('city_buy_production')!r}; "
                      f"имя типа={(type_names or {}).get(rec.get('production_value'))!r}",
                      flush=True)
        _watch_tech(ctx, obs, info)
        _dump_candidates(ctx, info)
        _dump_tech_numbers(obs, extractor, info)
        if ARGS.ban_produce:
            # Серия «состав против состава»: прогноз тот же, меняется ТОЛЬКО набор
            # типов, которые он вправе ставить в очередь. Никакой другой разницы
            # между ветвями быть не должно, иначе сравнение состава ничего не значит.
            banned = {str(name) for name in ARGS.ban_produce}
            _orig_productions = ctx.vals.productions
            _orig_improvements = ctx.vals.improvements

            def _filter(call, city, _b=banned):
                return [item for item in call(city) if str(item[0]) not in _b]

            ctx.vals.productions = (
                lambda city, _p=_orig_productions: _filter(_p, city))
            ctx.vals.improvements = (
                lambda city, _i=_orig_improvements: _filter(_i, city))
            # Замер внутри агента (`probe_offers`) заполняется побочным эффектом
            # исходного `productions`, поэтому запрещённые типы могли бы вернуться
            # через замер — и ветвь «с запретом» поставила бы запрещённое. Убираем.
            for _name in list(getattr(ctx, "probe_offers", {}) or {}):
                if str(_name) in banned:
                    ctx.probe_offers.pop(_name, None)
        _learn_type_cost(ctx, obs)      # вторая половина прошлого замера
        if (not _FORECAST_NOTES_PRINTED or ARGS.trace) and ctx.notes:
            _FORECAST_NOTES_PRINTED.append(True)
            for note in ctx.notes:
                print(f"        [прогноз] {note}", flush=True)
        choice = choose(ctx.state, ctx.vals)
    except Exception as exc:  # noqa: BLE001 - сбой прогноза не должен ломать матч
        _FORECAST_ERRORS.append(f"{type(exc).__name__}: {exc}")
        if len(_FORECAST_ERRORS) <= 3:
            print(f"        [прогноз] сбой: {type(exc).__name__}: {exc}", flush=True)
        return False, None

    _FORECAST_STATS["decisions"] += 1
    if choice.action is None:
        # Замер спрашивается ПЕРВЫМ — и именно тогда, когда кандидатов нет вовсе:
        # город предлагает только неоцениваемые типы, и потратить ход на замер
        # единственный способ выйти из круга «не знаем цену → не строим → не узнаём».
        probe = _probe_decision(ctx, extractor, info)
        if probe is not None and ARGS.ban_produce:
            # Запрет ветви обязан действовать и на замерный ход. Иначе «ветвь без
            # Warriors» ставила бы Warriors через пустой ход, и запрет переставал
            # быть единственным различием между ветвями (измерено: в логе ветви
            # запрета замер выбирал `city/131/produce_Warriors`).
            _pn = str(probe[2])
            _banned = {str(_n) for _n in ARGS.ban_produce}
            if (_pn.startswith("produce_")
                    and _pn[len("produce_"):] in _banned):
                _PENDING_PROBE.clear()
                _PROBE_TARGET.clear()
                probe = None
        if probe is not None:
            # Действие, которого сервер НЕ предлагает, роняет эпизод: словарь
            # действий сервера не содержит такого актёра, и `env.step` падает
            # `KeyError: '131'` в base_action.get_action (измерено, тот же прогон).
            # Поэтому замер проходит ту же проверку по меню, что и обычный выбор.
            _wire_probe = _to_wire_action(probe, avail)
            if _wire_probe is None:
                _PENDING_PROBE.clear()
                _PROBE_TARGET.clear()
                _FORECAST_STATS["probe_unmappable"] = (
                    _FORECAST_STATS.get("probe_unmappable", 0) + 1)
                if _FORECAST_STATS["probe_unmappable"] <= 3:
                    print(f"        [прогноз] замер {probe} сервер не предлагает "
                          f"— не отправлен", flush=True)
                probe = None
        if probe is not None:
            _FORECAST_STATS["probes"] += 1
            if _FORECAST_STATS["probes"] <= 3:
                print(f"        [прогноз] пустой ход потрачен на замер: "
                      f"{probe[0]}/{probe[1]}/{probe[2]}", flush=True)
            return True, _wire_probe
        if not choice.candidate_kinds:
            # Это НЕ отказ от действия, а конец хода: кандидатов нет, потому что
            # все актёры этого хода уже решили (или в мире действительно нечего
            # делать). Смешивать эти два факта нельзя — «отказ 30» перестаёт
            # отличаться от «инструмент не работал».
            _FORECAST_STATS["idle"] += 1
            return True, None
        _FORECAST_STATS["declined"] += 1
        _tally_reason(choice.reason)
        return True, None
    wire = _to_wire_action(choice.action, avail)
    if wire is None:
        # Прогноз назвал действие, которого сервер не предлагает: не подменяем его
        # другим и не «додумываем» — ход закрывается без действия.
        _FORECAST_STATS["unmappable"] += 1
        if _FORECAST_STATS["unmappable"] <= 3:
            print(f"        [прогноз] выбрал {choice.action}, но сервер такого "
                  f"не предлагает — ход без действия", flush=True)
        return True, None
    # Удержание решения по КЛЕТКЕ: обратный ход к нашему же прошлому действию не отправляем.
    # Иначе житель снимается и ставится обратно каждый ход: прирост еды +2 → +0, город
    # перестаёт расти, а производство сбрасывает щиты. Обратный ход — не «новое решение»
    # (новое решение это ДРУГАЯ клетка), поэтому отказ здесь не мешает переназначению.
    if isinstance(wire, tuple) and len(wire) >= 3 and str(wire[0]) == "city":
        _nm = str(wire[2])
        if _nm.startswith("city_work_") or _nm.startswith("city_unwork_"):
            _bench = _nm[len("city_unwork_"):] if _nm.startswith("city_unwork_") \
                else _nm[len("city_work_"):]
            _prev = _LAST_TILE_ACTION.get(str(wire[1]))
            if _prev:
                _prev_bench = (_prev[len("city_unwork_"):]
                               if str(_prev).startswith("city_unwork_")
                               else str(_prev)[len("city_work_"):])
                if _prev_bench == _bench and (
                        (str(_prev).startswith("city_unwork_") != _nm.startswith("city_unwork_"))):
                    if os.environ.get("DOF_TRACE_FILTERS") == "1":
                        print(f"        [прогноз] отказ от обратного хода по клетке "
                              f"{wire[1]}/{_nm} — только что было {_prev}", flush=True)
                    _FORECAST_STATS["tile_hold"] = _FORECAST_STATS.get("tile_hold", 0) + 1
                    return True, None
            _LAST_TILE_ACTION[str(wire[1])] = _nm
    _FORECAST_STATS["acted"] += 1
    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # У основного пути следа отправок НЕ БЫЛО (§13.228: за 31 ход «прогноз» 5 раз, а что
        # он отправлял — не видно), тогда как у режима без DoF след есть. Без этого «эффекта
        # нет» и «изменение не подключено» неразличимы.
        if isinstance(wire, tuple) and len(wire) >= 3:
            _shown = f"{wire[0]}/{wire[2]} (актёр {wire[1]})"
        else:
            _shown = str(wire)
        try:
            _sn_tn = int((info or {}).get("turn") or (info or {}).get("turn_played") or -1)
        except (TypeError, ValueError):
            _sn_tn = -1
        print(f"        [прогноз] отправляю (ход {_sn_tn}) {_shown}", flush=True)
    return True, wire


def _to_wire_action(action: tuple[str, str, str], avail: dict) -> tuple | None:
    """Перевести выбор прогноза в действие, которое сервер СЕЙЧАС предлагает.

    Прогноз мыслит сущностями и целями; провод знает только свои имена. Поэтому
    выбор сопоставляется с предложенным набором, и если соответствия нет — лучше
    не действовать, чем сделать не то.
    """
    ctrl, actor, name = action
    unit_actions = as_dict(as_dict(avail).get("unit"))
    city_actions = as_dict(as_dict(avail).get("city"))
    tech_actions = as_dict(as_dict(avail).get("tech"))
    if os.environ.get("DOF_TECH_DEBUG") == "1":
        # §13.542: мир вообще не предлагает смену исследования? Печатаем РАЗДЕЛЫ и размер.
        print("  [исследование] разделы мира: " + str(sorted((avail or {}).keys()))
              + ", tech-действий: " + str(len(tech_actions)), flush=True)

    def offered_actor(pool: dict, entity_id: str) -> tuple[object, dict] | None:
        bare = entity_id.split("_", 1)[1] if "_" in entity_id else entity_id
        for key, actions in pool.items():
            if str(key) == str(bare):
                return key, as_dict(actions)
        return None

    if ctrl == "unit":
        found = offered_actor(unit_actions, actor)
        if found is None:
            return None
        key, actions = found
        if name.startswith("goto"):
            # `goto_<dir8>` — шаг в конкретном направлении: подставить другой
            # значит увести юнита не туда, куда прогноз считал ценность. Поэтому
            # берётся ИМЕННО выбранное имя; если сервер его не предлагает — ход
            # закрывается без действия (как и любое несопоставимое действие).
            if actions.get(name):
                return ("unit", key, name)
            return None
        if actions.get(name):
            return ("unit", key, name)
        return None

    if ctrl == "city":
        found = offered_actor(city_actions, actor)
        if found is None:
            return None
        key, actions = found
        for cand_name, params in actions.items():
            if cand_name == name or (name.startswith("produce_")
                                     and cand_name == name):
                if params:
                    return ("city", key, cand_name)
        return None

    if ctrl == "tech":
        cur = tech_actions.get("cur_player")
        for cand_name, params in (cur if isinstance(cur, dict) else {}).items():
            if cand_name.startswith("research_tech") and params:
                return ("tech", "cur_player", cand_name)
        return None

    return None


#: Диагностика прогноза: сколько решений он принял и сколько отклонил.
# Ходы, по которым покадровый след состава уже напечатан (по одному на ход).
_UNIT_TRACE_TURNS: set = set()

# Последнее действие по клетке, ОТПРАВЛЕННОЕ нами, по городам: `{город: имя действия}`.
# Нужна, чтобы город не дёргал жителя туда-обратно (измерено §13.232: `city_unwork_18_1_2`
# и `city_work_18_1_2` чередуются каждый ход, прирост еды становится +0, мир отдаёт
# «рост через 1000000000 turns», а счётчик производства сбрасывается).
_LAST_TILE_ACTION: dict = {}

#: Что мы уже сказали управляющему по каждому городу: `{город: (размер, требуемая еда)}`.
_CMA_SENT: dict = {}

#: Городской управляющий СЕРВЕРА (проверено дважды: packets.js:75 и разбор enum):
#: PACKET_WEB_CMA_SET = 257, PACKET_WEB_CMA_CLEAR = 258. Форма запроса — как в самом клиенте
#: (`javascript/cma.js:115`): {"pid": 257, "id": <город>, "cm_parameter": {...}}.
_CMA_SET_PID = 257
_CMA_CLEAR_PID = 258


def _city_manager_params(size: int, food_surplus: int,
                         granary_is_full: bool = False) -> dict:
    """Требования управляющему: числа мира (`set_default_city_manager`, cityturn.c:313-360).

    Порядок выходов у мира: food, shield, trade, gold, luxury, science. Еда — как у него
    (20 при размере 1, 15 при 2..notradesize, 10 выше), щиты 5, торговля и роскошь 0,
    золото 2, наука 2.

    Требование по еде — ЕГО значение (`minimal_surplus[O_FOOD] = 1`), а не строже. Проба
    поднять его до 2 измерена и отброшена (§13.243): мир отдаёт признак `cma_enabled`
    истинным ровно тогда, когда у города ЕСТЬ параметр (`server/citytools.c:2694-2699`),
    а невыполнимое требование он не смягчает — отвергает параметр ЦЕЛИКОМ. С требованием 2
    флаг в одной партии был False 36 раз из 36 при 79 отправках и без единого сбоя, тогда как
    с его значением 1 — True 25 раз из 26. Выдумывать вместо его числа здесь нечего.
    """
    from brain.ai_default.city_manager import food_factor as _his_food_factor

    return {
        "minimal_surplus": [(0 if granary_is_full else int(food_surplus)), 1, 0,
                            -2147483647, 0, 0],
        "max_growth": False,
        "require_happy": False,
        "allow_disorder": False,
        "allow_specialists": True,
        "factor": [_his_food_factor(size, granary_is_full), 5, 0, 2, 0, 2],
        "happy_factor": 0,
    }


def _send_city_manager(env_getter, obs, extractor) -> int:
    """Отправить управляющему наши требования по каждому своему городу. Возвращает число отправок.

    Отправляем только при СМЕНЕ размера города или требуемой еды: незачем повторять одно и то
    же каждый ход. Мир отдаёт структуру наружу (`server/citytools.c:2696` копирует
    `pcity->cm_parameter` в веб-пакет), то есть проверка «дошло ли» возможна — но пока её нет,
    считаем отправленное, а не «поставленное».
    """
    try:
        env = env_getter()
        ctrl = getattr(getattr(env, "unwrapped", None), "civ_controller", None)
        ws = getattr(ctrl, "ws_client", None)
        if ws is None:
            print("        [управляющий] соединения нет — не отправлено", flush=True)
            return 0
        my_id = getattr(extractor, "my_player_id", None)
        sent = 0
        for rec in as_dict(obs.get("city")).values():
            if not isinstance(rec, dict):
                continue
            if my_id is not None and rec.get("owner") is not None \
                    and str(rec.get("owner")) != str(my_id):
                continue
            cid = rec.get("id")
            size = int(rec.get("size") or 1)
            # Его число, а не наше (§13.243): более строгое требование мир отвергает целиком.
            # Ветка «житница полна» — из записи города, а не догадкой (§13.253).
            req = 1
            _gran, _stock = rec.get("granary_size"), rec.get("food_stock")
            full = (_gran is not None and _stock is not None
                    and float(_stock) >= float(_gran))
            key = (size, req, full)
            # Мир СНИМАЕТ настройку управляющего: измерено (§13.240) — `cma_enabled` стал True
            # сразу после отправки и вернулся в False на следующем ходу у города 121. Пока
            # признак виден и он False, отправляем снова; если признак недоступен (None),
            # работаем по памяти о размере и требовании.
            if cid is None:
                continue
            said = _CMA_SENT.get(str(cid))
            if rec.get("cma_enabled") is False:
                pass  # мир снял — возвращаем, даже если мы это уже говорили
            elif said == key:
                continue
            ws.send_request({"pid": _CMA_SET_PID, "id": int(cid),
                             "cm_parameter": _city_manager_params(size, req, full)})
            _CMA_SENT[str(cid)] = key
            sent += 1
        if sent and os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"        [управляющий] требования отправлены городам: {sent}", flush=True)
        return sent
    except Exception as exc:  # noqa: BLE001 - не рушим матч диагностикой
        print(f"        [управляющий] сбой: {type(exc).__name__}: {exc}", flush=True)
        return 0

_FORECAST_STATS: dict[str, int] = {"decisions": 0, "acted": 0, "declined": 0,
                                   "unmappable": 0, "probes": 0, "idle": 0}
_FORECAST_ERRORS: list[str] = []
#: примечания прогноза печатаются один раз за матч (цена раскрытия, немеренные типы)
_FORECAST_NOTES_PRINTED: list[bool] = []
#: Замер (проба), который предстоит засчитать: [семейство, модель]. Заполняется,
#: когда прогноз отказывается действовать и вместо пустого хода идёт замер.
_PENDING_PROBE: list = []
#: Тип, который мы ПОСТАВИЛИ замером: [имя]. На следующем ходу из записи города
#: читается стоимость этого типа (`shield_stock / prod_process`). Имя держим мы,
#: потому что запись города несёт только номер вида производства, а не имя.
_PROBE_TARGET: list = []
#: (ctrl, актёр) решения, уже принятые в ЭТОМ ходу — прогноз обязан их видеть,
#: иначе предлагает ход тому, кто уже решил, и счётчики расходятся с проводом.
_USED_ACTORS: list = []
#: След науки: (ход, технология, стоимость, накоплено, наука городов) — для проверки
#: ВЫВЕДЕННОГО срока технологии фактом. Проверка идёт в живом прогоне, а не отдельным
#: скриптом: отдельный скрипт должен сам занимать державу, и без этого наблюдение
#: пусто (проверено — пусто).
_TECH_TRACE: list = []


def _watch_tech(ctx, obs, info=None) -> None:
    """Записать строку следа науки: прогресс и кандидаты на его драйвер.

    Срок технологии нужен (наука и технологии — сильные умножители DoF), но вывести
    его не удалось: прогресс рос `+0,+0,+1,…` при `bulbs` городов 3 и
    `player.science` 60, то есть ни одна из очевидных величин не подошла. Значит
    драйвер надо УСТАНОВИТЬ — и кандидаты объявлены ДО данных, чтобы не подогнать
    формулу под результат:

      1. floor(Σ торговля городов × ставка науки %)
      2. Σ bulbs городов (как публикуется)
      3. player['science']
      4. Σ торговля городов (без ставки)

    Ходы, на которых технология завершилась (прогресс сбрасывается), из сверки
    исключаются — иначе сброс выглядел бы как «формула не сошлась».
    """
    from brain.forecast.live import _player_record

    # ОДНА запись на ход: прогноз вызывается дважды за ход (второй вызов — конец
    # хода), и дубли превращали сверку в мусор: пары одинаковых строк давали рост 0,
    # а «совпало» считалось на выдуманных парах (первый замер так и испортился).
    turn_key = (info or {}).get("turn") if isinstance(info, dict) else None
    if turn_key is None:
        turn_key = len(_TECH_TRACE) + 1
    if _TECH_TRACE and _TECH_TRACE[-1].get("key") == turn_key:
        return

    player = _player_record(obs, getattr(ctx, "my_id", 0))
    cities = []
    for city in (obs.get("city") or {}).values():
        if not isinstance(city, dict):
            continue
        try:
            if int(city.get("owner", ctx.my_id)) != int(ctx.my_id):
                continue
        except (TypeError, ValueError):
            continue

        def number(key):
            try:
                return float(city.get(key) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        cities.append({"size": number("size"), "trade": number("prod_trade"),
                       "gold": number("prod_gold"), "bulbs": number("bulbs"),
                       "food": number("prod_food"), "shield": number("prod_shield")})
    _TECH_TRACE.append({
        "key": turn_key,
        "turn": len(_TECH_TRACE) + 1,
        "researching": player.get("researching"),
        "cost": player.get("researching_cost"),
        "progress": player.get("bulbs_researched"),
        "science": player.get("science"),
        "luxury": player.get("luxury"),
        "gold": player.get("gold"),
        "cities": cities,
    })


def _tech_candidates(row: dict) -> dict[str, float]:
    """Значения кандидатов за ход — по числам этого хода.

    Первый замер (24 хода, торговля 1, ставка 60) дал: рост +1 в каждом ходу, и
    «Σ торговля» совпала 24 из 24, а `bulbs` городов (3), `player.science` (60) и
    `floor(торговля × ставка%)` (0) — нет. Ловушка, которую надо снять: при
    торговле 1 с любым округлением вверх те же числа даёт и `ceil(торговля ×
    ставка%)` = ceil(0.6) = 1. Различить их можно только там, где торговля ≥ 2,
    поэтому варианты с округлением объявлены ЗАРАНЕЕ, а не подобраны после данных.
    """
    trade = sum(c["trade"] for c in row["cities"])
    bulbs = sum(c["bulbs"] for c in row["cities"])
    rate = float(row.get("science") or 0.0)
    return {
        "Σ торговля": trade,
        "floor(торговля × ставка%)": math.floor(trade * rate / 100.0),
        "ceil(торговля × ставка%)": math.ceil(trade * rate / 100.0),
        "round(торговля × ставка%)": round(trade * rate / 100.0),
        "Σ bulbs городов": bulbs,
        "player.science": rate,
    }


def _print_tech_trace() -> None:
    """Сверка кандидатов на драйвер науки с фактическим ростом прогресса."""
    rows = [r for r in _TECH_TRACE if r.get("progress") is not None]
    if len(rows) < 3:
        print("\n  наука: следа мало — драйвер не установлен", flush=True)
        return
    print("\n  наука: сверка кандидатов с ростом bulbs_researched", flush=True)
    checks: dict[str, list[bool]] = {}
    used = 0
    for prev, cur in zip(rows, rows[1:]):
        if prev.get("researching") != cur.get("researching"):
            continue                      # технология сменилась: прогресс сброшен
        delta = float(cur["progress"]) - float(prev["progress"])
        if delta < 0:
            continue
        used += 1
        for name, value in _tech_candidates(cur).items():
            checks.setdefault(name, []).append(abs(value - delta) < 1e-9)
        if used <= 6:
            city_trade = sum(c["trade"] for c in cur["cities"])
            city_bulbs = sum(c["bulbs"] for c in cur["cities"])
            print(f"    ход {cur['turn']}: рост {delta:+g}; торговля городов "
                  f"{city_trade:g}, bulbs городов {city_bulbs:g}, "
                  f"ставка {cur.get('science')}", flush=True)
    print(f"    сверено ходов: {used}", flush=True)
    for name, results in checks.items():
        matched = sum(1 for r in results if r)
        print(f"    кандидат «{name}»: совпал на {matched} из {len(results)}", flush=True)

    # Проверка срока ЦЕЛИКОМ: предсказанный ход завершения против фактического.
    # Берём первый ход, где стоимость УЖЕ публикуется: на первом ходу матча
    # исследования может ещё не быть, и тогда `cost` пуст (на этом проверка уже
    # терялась — срок молча не с чем было сверять).
    start_row = next((r for r in rows if r.get("cost") is not None), None)
    per_turn = _tech_candidates(rows[0])["round(торговля × ставка%)"]
    if start_row is not None and per_turn > 0:
        left = max(0.0, float(start_row["cost"]) - float(start_row.get("progress") or 0))
        predicted = int(start_row["turn"]) + int(math.ceil(left / per_turn))
        actual = next((r["turn"] for r in rows
                       if r.get("researching") != start_row.get("researching")), None)
        print(f"    срок технологии {start_row.get('researching')}: предсказано "
              f"завершение на ходу {predicted}, факт — "
              f"{('на ходу ' + str(actual)) if actual is not None else 'в матче не завершилась'}",
              flush=True)


def _learn_type_cost(ctx, obs) -> None:
    """Прочитать срок поставленного замера и записать стоимость типа в склад.

    Это вторая половина замера: постановка (в `_probe_decision`) плюс чтение числа у
    мира. Без второй половины замер — просто потраченный ход.

    Ограничение названо прямо: запись города не называет тип, поэтому стоимость
    приписывается тому типу, который мы поставили. Если город успел переключиться,
    склад получит расхождение и скажет «не знаем» — не «среднее».
    """
    target = _PROBE_TARGET[0] if _PROBE_TARGET else None
    if not target:
        return
    facts = getattr(ctx, "facts", None)
    if facts is None:
        return
    from env.measured_facts import cost_from_city

    for record in (as_dict(obs.get("city")) or {}).values():
        cost = cost_from_city(record)
        if cost is None:
            continue
        _PROBE_TARGET.clear()
        try:
            wrote = facts.observe_type(target, cost=cost, source="probe-in-agent")
            if wrote:
                facts.save()
                print(f"        [прогноз] замер состоялся: {target} — стоимость "
                      f"{cost:.1f}", flush=True)
        except Exception:  # noqa: BLE001
            pass
        return


def _probe_decision(ctx, extractor, info) -> tuple | None:
    """Ход на замер вместо пустого хода — под тем же бюджетом, что и любопытство.

    Почему это вообще нужно агенту, а не только мерному скрипту: стоимость типа
    нельзя вывести из наблюдения (её измеряют, поставив производство и прочитав
    `prod_process`/`shield_stock`), а опции типа узнаются лишь тогда, когда юнит
    появится живьём. Пока цены нет, тип не предлагается — и получается круг «не
    знаем → не строим → не узнаём». Если ход иначе пуст, потратить его на замер
    единственный способ круг разорвать.

    Бюджет тот же, что у неизмеренных действий проекта: `exploration_budget`,
    три попытки на семейство. Порядок типов — по алфавиту, чтобы прогон был
    воспроизводим.
    """
    model = getattr(extractor, "model", None)
    offers = getattr(ctx, "probe_offers", None) or {}
    if model is None or not offers:
        return None
    from env.experiments import exploration_budget, family_of

    for type_name in sorted(offers):
        ctrl, actor, action = offers[type_name]
        family = family_of(action)
        attempts = int(getattr(model, "experiment_attempts", {}).get(family, 0))
        if exploration_budget(attempts) <= 0.0:
            continue
        _PENDING_PROBE[:] = [family, model]
        _PROBE_TARGET[:] = [type_name]
        return (ctrl, actor, action)
    return None


def _note_probe_taken() -> None:
    """Засчитать замер: действие действительно ушло на сервер."""
    if not _PENDING_PROBE:
        return
    family, model = _PENDING_PROBE[0], _PENDING_PROBE[1]
    _PENDING_PROBE.clear()
    try:
        model.record_experiment(family, turn=0)
    except Exception:  # noqa: BLE001
        pass
#: почему прогноз отказался. Без разбора причин «отказ 25» неотличим от «прогноз
#: сломан»: причина — часть результата, а не отладка.
_FORECAST_REASONS: dict[str, int] = {}


def _tally_reason(reason: str) -> None:
    """Свести причину отказа к сопоставимому виду (числа в причине разные)."""
    text = (reason or "?").strip()
    low = text.lower()
    if "строгого улучшения" in low or "нет улучшения" in low:
        # Состав кандидатов сохраняем: «нет улучшения» и «нет кандидатов» —
        # разные факты, и различать их надо в отчёте, а не догадкой.
        tail = text.split("кандидаты:", 1)[-1].strip() if "кандидаты:" in text else "?"
        key = f"нет строгого улучшения (кандидаты: {tail[:60]})"
    elif "вето" in low:
        key = "вето (аксиома 3/4)"
    elif "необратим" in low:
        key = "необратимость"
    elif "нет кандидат" in low or "нечего" in low:
        key = "нет ни одного кандидата"
    else:
        key = text[:70]
    _FORECAST_REASONS[key] = _FORECAST_REASONS.get(key, 0) + 1


def _print_forecast_summary() -> None:
    print(f"\n  прогноз: решений {_FORECAST_STATS['decisions']} "
          f"(выдано действий {_FORECAST_STATS['acted']}, отказов "
          f"{_FORECAST_STATS['declined']}, из них на замер "
          f"{_FORECAST_STATS['probes']}, конец хода (кандидатов нет) "
          f"{_FORECAST_STATS['idle']}, не сопоставлено "
          f"{_FORECAST_STATS['unmappable']}), сбоев "
          f"{len(_FORECAST_ERRORS)}", flush=True)
    if _FORECAST_REASONS:
        top = sorted(_FORECAST_REASONS.items(), key=lambda kv: -kv[1])[:5]
        for reason, count in top:
            print(f"    отказ ×{count}: {reason}", flush=True)
    if _FORECAST_ERRORS:
        print(f"  прогноз, первые сбои: {_FORECAST_ERRORS[:3]}", flush=True)


def build_agent(agent_type: str, extractor: GameStateExtractor,
                lookahead: int = 3, context_switch_penalty: float = 0.5,
                max_candidates: int = 8, trace: bool = False,
                env_getter=None):
    """Create the agent for a given agent_type.

    ``lookahead`` / ``context_switch_penalty`` configure the DOF-Core engine;
    ``max_candidates`` caps how many branches each decision is evaluated over
    (the core's lookahead cost grows roughly as ``candidates ** horizon``).
    """
    if agent_type == "no-op":
        return NoOpAgent()
    if agent_type == "random":
        return RandomAgent()

    if agent_type.startswith("dof_"):
        strategy_name = agent_type[len("dof_"):]
        strategy = next(
            (s for s in ALL_STRATEGIES if s.name == strategy_name), DEFENSIVE
        )
        gen = HeuristicGenerator(strategy=strategy)
        gen.max_candidates = max_candidates
        core = (
            DOFCalculusCore(
                lookahead_horizon=lookahead,
                # The penalty is configured in options (the unit every delta is
                # projected in) and converted into the core's own scale, so it
                # stays comparable with the deltas it is weighed against.
                context_switch_penalty=context_switch_penalty / CORE_DOF_SCALE,
            )
            if HAVE_DOF_CORE else None
        )

        class DofAgent(BaseAgent):
            def act(self, obs, info):
                # Имена построек — один раз, как только доступны правила клиента:
                # без них предел роста города остаётся базовым и водопровод немой.
                # §13.329: требования управляющему отправляются ЗДЕСЬ — в начале хода, а не
                # после ветки `--no-dof`. Измерено: ветка `no_dof` возвращает ход изнутри
                # себя, поэтому вызов ниже неё был мёртв на ВСЕХ приёмочных прогонах:
                # `act` вызван 24 раза за 8 ходов, а вызов не сработал ни разу.
                if getattr(ARGS, "city_manager", False):
                    _sent_cm = _send_city_manager(env_getter, obs, extractor)
                    if os.environ.get("DOF_CM_DEBUG") == "1":
                        print(f"        [управляющий-вызов] отправок {_sent_cm}", flush=True)

                # §13.340: НЕПРЕРЫВНЫЙ след очереди по нашим городам — каждый ход, независимо от
                # того, дозвал ли ход до выбора производства. Без него замер «применился ли приказ»
                # опирался на редкие строки (1–6 за партию), и пар «приказ ↔ очередь» не набиралось.
                if os.environ.get("DOF_FOUND_DEBUG") == "1":
                    print(f"  [слой-город-ход] ход {info.get('turn')}: в наблюдении "
                          f"{len(as_dict((obs or {}).get('city')) or {})} городов", flush=True)
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    for _cid, _rec in (as_dict((obs or {}).get("city")) or {}).items():
                        _r = as_dict(_rec) or {}
                        print(f"  [очередь-ход] ход {info.get('turn')}: город {_cid}: "
                              f"kind={_r.get('production_kind')}, "
                              f"value={_r.get('production_value')}, "
                              f"stock={_r.get('shield_stock')}", flush=True)

                if not getattr(self, "_impr_published", False) and env_getter is not None:
                    try:
                        if _publish_improvement_names(extractor, env_getter()):
                            self._impr_published = True
                    except Exception:  # noqa: BLE001
                        self._impr_published = True
                dof = extractor.extract(obs, info, info.get("turn", 0))
                avail = info.get("available_actions", {})
                if os.environ.get("DOF_CHOICE_DEBUG") == "1":
                    _u = as_dict(as_dict(avail).get("unit"))
                    _c = as_dict(as_dict(avail).get("city"))
                    _nu = sum(1 for a in _u.values() for n, p_ in as_dict(a).items() if truthy(p_))
                    _nc = sum(1 for a in _c.values() for n, p_ in as_dict(a).items() if truthy(p_))
                    print(f"  [ход-вход] ход {info.get('turn')}: юнитных актёров {len(_u)} "
                          f"(действий {_nu}), городовых {len(_c)} (действий {_nc})", flush=True)

                # ПРОГНОЗ: перебор вариантов с перевыводом возможностей в будущем
                # состоянии (brain/forecast). Он решает ход; прежний путь ниже
                # остаётся как fallback на случай сбоя прогноза, а не как
                # альтернативное мнение: два решателя одновременно — это не
                # сравнение, а неопределённость.
                if getattr(ARGS, "no_dof", False):
                    # §13.204 (указание владельца): «сначала наш агент играет не хуже
                    # встроенного с ВЫКЛЮЧЕННЫМ DoF». Ни прогноза, ни индекса, ни вето
                    # ядра — выбор только предпочтением стратегии
                    # (`HeuristicGenerator._preference_score`). Нужен, чтобы отделить
                    # САМУ ИГРУ (основание городов, рост, производство) от наших
                    # надстроек: пока игра не идёт не хуже его, индекс накладывать не на что.
                    _raw_cands = gen.generate_candidates(dof.state, avail)
                    _count_kinds(_raw_cands, "выход генератора")
                    if os.environ.get("DOF_TILE_DEBUG") == "1":
                        # §13.292: где теряется постановка жителя. Считаем клеточные действия
                        # НА ВЫХОДЕ генератора (до наших правил): если их нет уже здесь, виноват
                        # картограф, а не правила.
                        _rw = [str((_to_action(c) or ("", "", ""))[2]) for c in _raw_cands]
                        print(f"  [генератор] всего {len(_raw_cands)}, city_work "
                              f"{sum(1 for n in _rw if n.startswith('city_work_'))}, city_unwork "
                              f"{sum(1 for n in _rw if n.startswith('city_unwork_'))}", flush=True)
                    descore = _apply_common_rules(
                        _raw_cands, obs, extractor,
                        env_getter, avail)
                    # §13.288: работу клетки выбирает ПЕРЕНОСЁННОЕ правило встроенного ИИ,
                    # а не счёт совпадений со списком. На ОБЩЕМ пути: у решения рабочего
                    # был свой гейт (`if not ARGS.forecast`), и при --no-dof оно не
                    # вызывалось вовсе — четвёртый случай одного дефекта (13.286).
                    descore = _prefer_port_work_choice(descore, obs, dof.state, avail)
                    # §13.274: клин — ИЗМЕРЕННЫЙ факт, и он обязан отсекать действие
                    # ЛЮБОГО рода. Без этого `unit/plant` ставился снова и залипал.
                    descore = _drop_wedged_candidates(descore, dof.state)
                    # §13.571: повтор того же снятия работы с клетки (40-45 % отправок, до 45 раз).
                    descore = _drop_repeated_unwork(descore, info)
                    # ── ПРАВИЛО F НА ПУТИ БЕЗ DoF (§13.308) ──
                    # Измерено: собственный отчёт правила говорил «решений проверено 0», а на
                    # этом пути оно стояло НИЖЕ выбора и другого списка. Следствие: `join_city`
                    # уходил в город размера 2 с излишком −1 (голодающий) — поселенец пропадал
                    # вместо нового города, и расширение не шло. Отсечение обязано быть ДО выбора:
                    # иначе безопасная альтернатива (выйти и основать) не рассматривается.
                    descore = _food_gate_filter(descore, obs, extractor, info.get("turn"))
                    # §13.210: постановку в городе ставим МЫ — стенд этого действия не
                    # предлагает вовсе (§13.209), и без него очередь додерживала Warriors.
                    # §13.294: ход по клетке города — ПЕРВЫМ. Измерено (13.293): короткий
                    # список генератора не берёт `city_work_*` (нулевой прирост DoF), поэтому
                    # освобождённого горожанина поставить нечем и город стоит на размере 1.
                    # §13.306: поселенец сперва идёт к годной площадке. Его ИИ не
                    # основывает город там, где юнит оказался (`daisettler.c`), а ведёт
                    # его к лучшей площадке — без этого город гибнет от голода.
                    # §13.348: ОТСТАВАНИЕ позиции — замер в одном ходу: наблюдение против
                    # живого контроллера. Правило берёт позицию из `obs["unit"]`, дамп — тоже,
                    # но после `env.step`; если контроллер показывает ту же клетку, что дамп,
                    # значит отстаёт НАБЛЮДЕНИЕ, и шаг считается от покинутой клетки.
                    if os.environ.get("DOF_FOUND_DEBUG") == "1":
                        try:
                            _obs_pos = []
                            for _k, _v in (as_dict((obs or {}).get("unit")) or {}).items():
                                _v = as_dict(_v) or {}
                                if str(_v.get("type_rule_name")) == "Settlers":
                                    _obs_pos.append((_k, _v.get("x"), _v.get("y")))
                            # Карта владельцев — ТРЕТИЙ канал (после `obs["unit"]` и контроллера):
                            # если поселенец виден на карте НЕ там, где в наблюдении, значит
                            # отстаёт наблюдение, и шаг считается от покинутой клетки.
                            _live = []
                            _mid = getattr(extractor, "my_player_id", None)
                            _grid = as_dict((as_dict((obs or {}).get("map")) or {}).get("unit_owner"))
                            _mine_tiles = []
                            if isinstance(_grid, (list, tuple)) and _mid is not None:
                                for _x, _col in enumerate(_grid):
                                    if not isinstance(_col, (list, tuple)):
                                        continue
                                    for _y, _v in enumerate(_col):
                                        try:
                                            if _v is not None and int(_v) == int(_mid):
                                                _mine_tiles.append((_x, _y))
                                        except (TypeError, ValueError):
                                            continue
                            _live = _mine_tiles
                            if not getattr(_founder_step, "_probe_done", False) and env_getter is not None:
                                _founder_step._probe_done = True
                                _ws = (as_dict((as_dict((obs or {}).get("map")) or {})
                                               .get("unit_owner")) or {})
                                _keys = list(_ws)[:3]
                                print(f"  [слой] unit_owner: тип {type(_ws).__name__}, "
                                      f"ключей {len(_ws)}, первые {_keys!r}", flush=True)
                                for _k in _keys[:1]:
                                    _v = _ws[_k]
                                    print(f"     [{_k!r}] тип {type(_v).__name__} "
                                          f"значение {str(_v)[:80]!r}", flush=True)
                                _c = _controller_of(env_getter())
                                # §13.357: пробник ГОРОДОВ контроллера — тем же способом, каким
                                # §13.348 нашли позиции юнитов. Слой городов наблюдения бывает
                                # пуст, а свои города нужны для citymindist и резерва мест.
                                _cs = getattr(getattr(_c, "city_ctrl", None), "cities", None)
                                if isinstance(_cs, dict) and _cs:
                                    _ck, _cv = next(iter(_cs.items()))
                                    print(f"  [контроллер] cities[{_ck!r}]: тип {type(_cv).__name__}, "
                                          f"значение {str(_cv)[:110]!r}", flush=True)
                                    print(f"  [контроллер] cities: всего {len(_cs)}", flush=True)
                                _us = getattr(getattr(_c, "unit_ctrl", None), "units", None)
                                if isinstance(_us, dict) and _us:
                                    _k0, _u0 = next(iter(_us.items()))
                                    print(f"  [контроллер] units[{_k0!r}]: тип {type(_u0).__name__}, "
                                          f"значение {str(_u0)[:100]!r}", flush=True)
                        except Exception as _exc:  # noqa: BLE001
                            print(f"  [позиции] ошибка: {type(_exc).__name__}: {_exc}", flush=True)
                    if os.environ.get("DOF_WHOAMI") == "1" and int(str(info.get("turn", 0) or 0)) % 5 == 1:
                        _whoami_probe(env_getter)
                    if os.environ.get("DOF_UNIT_DEBUG") == "1":
                        # §13.401: прибор «что мир предлагает нашим юнитам» — иначе не отличить
                        # «работник не действует» от «миру нечего предложить работнику».
                        try:
                            _ua = as_dict(as_dict((info or {}).get("available_actions")).get("unit")) or {}
                            print(f"  [юнит-предложение] ход {info.get('turn')}: "
                                  f"{str(_ua)[:400]}", flush=True)
                        except Exception:  # noqa: BLE001
                            pass
                    if os.environ.get("DOF_ORDER_SETTLERS") == "1":
                        _order = _order_city_production(env_getter, fc_args.get("username"), obs, info, dof.state, extractor)
                        if _order is not None:
                            return _order
                    if os.environ.get("DOF_CITY_FROM_SAVE") == "1":
                        _save_and_dump_cities(env_getter, fc_args.get("username"))
                    if os.environ.get("DOF_CITY_DEBUG") == "1":
                        _city_channels_probe(obs, avail, env_getter, extractor)
                    if os.environ.get("DOF_MAP_FROM_SAVE") == "1":
                        # §13.409: вместе с обучением карты из сейва разрешаем оценку клетки по
                        # террейну сейва (в библиотеке она выключена, чтобы не тянуть память
                        # чужой партии в тестах и в прогонах без карты из сейва).
                        os.environ.setdefault("DOF_SITE_FROM_SAVE", "1")
                        _maybe_learn_map_from_save(
                            info.get("turn") if isinstance(info, dict) else None)
                    _founder = _founder_step(obs, avail,
                                             mindist=_world_citymindist(env_getter()),
                                             env_getter=env_getter)
                    if _founder is not None:
                        return _founder
                    _tile_pick = _city_tile_candidate(obs, avail)
                    # §13.575: этот путь возвращает действие НАПРЯМУЮ, минуя `descore`, — поэтому
                    # фильтр повторов §13.572 его не видел, и оттуда шли повторные `city_unwork`
                    # (одно и то же действие до 45 раз за партию). Прибор §13.574 подтвердил, что
                    # фильтр на `descore` исполняется (187 вызовов) и повторы там снимает —
                    # значит остаток шёл именно здесь.
                    if (os.environ.get("DOF_NO_UNWORK_REPEAT") == "1"
                            and _tile_pick is not None
                            and str(_tile_pick[2]).startswith("city_unwork")):
                        _k = (str(_tile_pick[1]), str(_tile_pick[2]))
                        _prev_u = _UNWORK_SENT.get(_k)
                        _now_turn = int((info or {}).get("turn") or 0) if isinstance(info, dict) else 0
                        if _prev_u is not None and _prev_u >= _now_turn - 1:
                            print(f"  [фильтр unwork] ход {_now_turn}: снят повтор "
                                  f"{_tile_pick[2]} (последний раз ход {_prev_u})", flush=True)
                            _tile_pick = None
                    if _tile_pick is not None:
                        # §13.615: измерено — главная ветвь ПОВТОРА (25 из 54), актёры city 122/128.
                        # Возврат идёт НАПРЯМУЮ, мимо `offered`/`excluded` (options.py:352), поэтому
                        # город, уже действовавший в этом ходу, выбирается снова, `_turn_phase`
                        # видит повтор актёра и закрывает ход — остальные города заказов не получают.
                        # Тот же класс, что §13.575 (`_city_tile_candidate` мимо `descore`).
                        # §13.617: сравнение нормализует ИМЯ КОНТРОЛЛЕРА до префикса — у внутреннего
                        # кандидата ctrl это `city_work`/`city_unwork`, а ключ повтора в проводе
                        # `('city', 142)`. Именно на этом защита молчала в §13.616 (0 срабатываний).
                        _pk = (str(_tile_pick[0]).split("_")[0], str(_tile_pick[1]).split("_")[-1])
                        if (os.environ.get("DOF_NO_ACTOR_REPEAT") == "1" and _USED_ACTORS
                                and _pk in {(str(_c).split("_")[0], str(_a).split("_")[-1])
                                            for _c, _a in (_USED_ACTORS[0] or ())}):
                            print(f"        [§13.615] актёр {_pk} уже действовал в этом ходу "
                                  f"-> ищем другого", flush=True)
                            _tile_pick = None
                        else:
                            return _tile_pick
                    _prod = _production_candidate(
                        obs, info, dof.state, extractor,
                        _production_names(env_getter())
                        if env_getter is not None else None,
                        _military_type_names(env_getter())
                        if env_getter is not None else None,
                        _gold_of(obs, extractor), avail, env_getter)
                    if _prod is not None:
                        # §13.336: отправка заказа — это и есть наше решение. Помним его,
                        # иначе правило «держать начатое» не срабатывает НИ РАЗУ (измерено:
                        # 8 приказов подряд, 0 удержаний — память никто не заполнял).
                        _com = _prod.get("_committed")
                        if _com:
                            # §13.644: прибор в САМОЙ точке рождения заказа — печатает и смену, и очередь.
                            if os.environ.get("DOF_ORDER_TRACE") == "1":
                                _prev_com = _LAST_PROD.get(str(_prod.get("actor_id")))
                                _flip = bool(_prev_com and str(_prev_com[0]) != str(_com[0]))
                                print(f"  [смена-заказа] ход {info.get('turn')} город {_prod.get('actor_id')}: "
                                      f"было {(_prev_com[0] if _prev_com else None)!r} стало {_com[0]!r} "
                                      f"щиты {_com[1] if len(_com) > 1 else '?'} смена={_flip} "
                                      f"в_очереди {_prod.get('current_name')!r}", flush=True)
                            _LAST_PROD[str(_prod.get("actor_id"))] = _com
                            # §13.664: помним ХОД заказа — по нему решается, повтор это или смена.
                            _LAST_ORDER_TURN[str(_prod.get("actor_id"))] = int(info.get("turn") or 0)
                        if os.environ.get("DOF_TRACE_FILTERS") == "1":
                            print(f"  [постановка] ход {info.get('turn')}: отправляю "
                                  f"{_prod['action_name']} городу {_prod['actor_id']} "
                                  f"(в очереди было {_prod.get('current_name')!r})", flush=True)
                        # §13.339: ЧТО НЕСЁТ САМО ДЕЙСТВИЕ СРЕДЫ. Наш приказ уходит по имени,
                        # а номер предмета подставляет среда; если её номер не тот, что ждёт
                        # сервер, приказ молча пропадает — и никакой строки об ошибке не будет.
                        try:
                            _env = env_getter()
                            _tm = getattr(getattr(getattr(_env, "unwrapped", None),
                                                  "civ_controller", None),
                                          "turn_manager", None)
                            _obj = _tm._get_action_object(("city", _prod["actor_id"],
                                                           _prod["action_name"]))
                            _ub = None
                            try:
                                _ub = (getattr(_tm, "_turn_state", None) or {}).get("num_impr_types")
                            except Exception:  # noqa: BLE001
                                _ub = None
                            print(f"  [действие-среды] {_prod['action_name']}: "
                                  f"тип={type(_obj).__name__}, "
                                  f"prod_kind={getattr(_obj, 'prod_kind', None)}, "
                                  f"prod_value={getattr(_obj, 'prod_value', None)}, "
                                  f"имя={getattr(_obj, 'prod_name', None)}, "
                                  f"годно={_obj.is_action_valid() if _obj else None}", flush=True)
                        except Exception as _exc:  # noqa: BLE001
                            print(f"  [действие-среды] не прочитано: {type(_exc).__name__}: {_exc}",
                                  flush=True)
                        return _to_action(_prod)
                    # Жителя переставляет ЕГО управляющий (`server/cityturn.c:313`):
                    # строгое улучшение взвешенной суммы. Замер: до этого у клеток в режиме
                    # без DoF оценки не было ВООБЩЕ, и жители переставлялись порядком
                    # короткого списка (перетасовка 2–6 за игру).
                    _best_tile = None
                    if os.environ.get("DOF_TILE_DEBUG") == "1":
                        _tiles_in = [c.get("action_name") for c in descore
                                     if str(c.get("action_name") or "").startswith(("city_work_", "city_unwork_"))]
                        # §13.292: сырые действия города с параметрами. Вопрос, который это
                        # решает: `city_work` отброшен НАМИ (пустые параметры = по нашему
                        # правилу «сервер не примет») или его вовсе нет среди предложенных.
                        _raw_city = as_dict(as_dict(avail).get("city")) or {}
                        for _cid, _acts in list(_raw_city.items())[:1]:
                            _pairs = [(str(_n), bool(_pp) if not hasattr(_pp, "shape")
                                       else bool(getattr(_pp, "size", 0)))
                                      for _n, _pp in list(as_dict(_acts).items())]
                            print(f"  [город-сырые-действия] актёр {_cid}: {_pairs}", flush=True)
                        print(f"  [клетка-отладка] кандидатов {len(descore)}, из них клеток "
                              f"{len(_tiles_in)}: {_tiles_in[:6]}; контекст "
                              f"{'есть' if _LAST_CTX is not None else 'НЕТ'}", flush=True)
                    _rule_gains: dict = {}
                    _tile_cities = sorted({
                        str(c.get("actor_id")) for c in descore
                        if str(c.get("ctrl_type")) == "city"
                        and str(c.get("action_name") or "").startswith(
                            ("city_work_", "city_unwork_"))})
                    for _cid in _tile_cities:
                        _rule_gains.update(_city_tile_gains_from_rules(_cid, descore))
                    for _cand in descore:
                        _gain = _tile_score_of(_LAST_CTX, _cand.get("ctrl_type"),
                                               _cand.get("action_name"),
                                               _cand.get("actor_id"))
                        if _gain is None or _gain <= 0.0:
                            # §13.292: своих чисел на клетку города нет вовсе (измерено:
                            # «строк 0»). Тогда ценность клетки берётся перенесённым числом
                            # по правилам мира, а выигрыш — по порядку «снять плохую →
                            # занять лучшую», тоже его.
                            _rule_gain = _rule_gains.get(str(_cand.get("action_name") or ""))
                            if _rule_gain:
                                _gain = _rule_gain
                        if _gain is None or _gain <= 0.0:
                            continue
                        if _best_tile is None or _gain > _best_tile[0]:
                            _best_tile = (_gain, _cand)
                    if _best_tile is not None:
                        _wire = _to_action(_best_tile[1])
                        if _wire is not None:
                            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                                print(f"  [без DoF] житель: {_wire[2] if isinstance(_wire, tuple) and len(_wire) > 2 else _wire} "
                                      f"прирост веса управляющего {_best_tile[0]:+.1f}", flush=True)
                            return _wire
                    if os.environ.get("DOF_CHOICE_DEBUG") == "1":
                        # §13.354: вопрос «основание проиграло или его не было в списке».
                        # Без этого следа оба случая неразличимы, а лечатся они по-разному.
                        _bc = [c for c in descore
                               if str(c.get("action_name") or "").startswith(
                                   ("build_city", "found_city"))]
                        _scored = sorted(descore, key=gen._preference_score, reverse=True)[:4]
                        # Меню САМОГО МИРА (до генератора): без него «нет основания в списке»
                        # неотличимо от «мир его не предлагал».
                        _menu = 0
                        for _a, _acts in as_dict(as_dict(avail).get("unit")).items():
                            for _n, _pp in as_dict(_acts).items():
                                if str(_n).startswith(("build_city", "found_city")) and truthy(_pp):
                                    _menu += 1
                        _raw_bc = sum(
                            1 for c in _raw_cands
                            if str(c.get("action_name") or "").startswith(
                                ("build_city", "found_city")))
                        print(f"  [выбор-ход] ход {info.get('turn')}: мир предлагает оснований "
                              f"{_menu}, у генератора {_raw_bc}, кандидатов {len(descore)}, "
                              f"после наших правил {len(_bc)}; верх: "
                              + ", ".join(
                                  f"{c.get('ctrl_type')}/{c.get('action_name')}"
                                  f"={gen._preference_score(c):.1f}"
                                  for c in _scored)
                              or "  [выбор-ход] кандидатов нет", flush=True)
                    if descore:
                        _pick = max(descore,
                                    key=lambda c: (gen._preference_score(c),
                                                   sum(c.get("projected_dof_delta", {}).values()),
                                                   c.get("is_reversible", True)))
                        _wire = _to_action(_pick)
                        if _wire is not None:
                            if os.environ.get("DOF_TRACE_FILTERS") == "1":
                                # `_to_action` отдаёт КОРТЕЖ (имя, полезная нагрузка), а не
                                # словарь: обращение через `.get` уже один раз уронило прогон
                                # (`AttributeError: 'tuple' object has no attribute 'get'`,
                                # 0 ходов, ошибка в отчёте). Печатаем форму, а не поле.
                                # Кортеж стенда: (род контроллера, имя действия, полезная
                                # нагрузка). Раньше печатался только род — «unit», «city» —
                                # и по такому следу нельзя было понять, ЧТО мы делаем.
                                # Форма кортежа стенда: (род, НОМЕР актёра, имя действия).
                                # Второй элемент — номер, а не имя: по нему состав действий не
                                # читается (проверено замером: «unit/118», «city/127»), поэтому
                                # печатаем третий.
                                if isinstance(_wire, tuple) and len(_wire) >= 3:
                                    _name = f"{_wire[0]}/{_wire[2]} (актёр {_wire[1]})"
                                else:
                                    _name = getattr(_wire, "action_name", _wire)
                                print(f"  [без DoF] ход {info.get('turn')}: отправляю {_name} (кандидатов "
                                      f"{len(descore)}, предпочтение "
                                      f"{gen._preference_score(_pick):.3f})", flush=True)
                            if not getattr(self, "_nodof_said", False):
                                self._nodof_said = True
                                print("        [без DoF] выбор только предпочтением стратегии"
                                      "; индекс, прогноз и вето ядра выключены (§13.204)",
                                      flush=True)
                            return _wire
                    # Строгость режима: если предпочтение не выбрало ничего, ход всё
                    # равно не пропускается (§13.203), но идёт он ОБРАТИМЫМ действием
                    # из предложенных, а НЕ через прогноз: иначе «без DoF» мерился бы
                    # вместе с DoF, и базовая линия владельца была бы не базовой.
                    _fall = [c for c in descore if c.get("is_reversible")] or descore
                    if _fall:
                        _wire = _to_action(max(_fall, key=gen._preference_score))
                        if _wire is not None:
                            return _wire
                    return None

                if getattr(ARGS, "city_manager", False):
                    _send_city_manager(env_getter, obs, extractor)
                decided, wire = _forecast_decide(
                    obs, info, dof, extractor, avail,
                    type_names=(_production_names(env_getter())
                                if env_getter is not None else None),
                    military_names=(_military_type_names(env_getter())
                                    if env_getter is not None else None),
                    gold=lambda: _gold_of(obs, extractor))
                if decided:
                    if wire is not None:
                        return wire
                    # §13.203: ход НЕ ПРОПУСКАЕТСЯ. Прогноз осмотрел всё и не нашёл
                    # действия с положительным приростом — но мир не останавливается, а
                    # мера у нас ОТНОСИТЕЛЬНАЯ: пропущенный ход стоит всей позиции.
                    # Берём лучшее ОБРАТИМОЕ действие из предложенных (обратимое вложение
                    # не сжигает опции, Axiom 3), при равенстве — шаг (`goto`), то есть
                    # раскрытие тумана: без него годная площадка не появится никогда.
                    # У встроенного ИИ такого простоя нет вовсе: его поселенец всегда
                    # идёт к лучшей из известных целей (`ai/default/daisettler.c`).
                    _forced = [c for c in gen.generate_candidates(dof.state, avail)
                               if c.get("is_reversible")]
                    if _forced:
                        def _rank(c):
                            _d = sum(c.get("projected_dof_delta", {}).values())
                            _move = str(c.get("action_name", "")).startswith("goto")
                            # Положительный прирост решает сам за себя; при неположительном
                            # предпочитается ШАГ (`goto`) — раскрытие тумана, потому что
                            # «постоять» (+0.000, `keep_activity`) не меняет мира вовсе,
                            # а без раскрытия годная площадка не появится.
                            return (True, _d, _move) if _d > 0.0 else (False, _move, _d)
                        _best = max(_forced, key=_rank)
                        self._forced = getattr(self, "_forced", 0) + 1
                        if self._forced <= 5 or self._forced % 25 == 0:
                            print(f"        [вынужденный ход {self._forced}] "
                                  f"{_best.get('action_name')} "
                                  f"(прирост {sum(_best.get('projected_dof_delta', {}).values()):+.3f}, "
                                  f"обратимое — простой стоил бы позиции)", flush=True)
                        return _to_action(_best)

                cands = _apply_common_rules(
                    gen.generate_candidates(dof.state, avail), obs, extractor, env_getter, avail)
                if ARGS.ban_produce and cands:
                    # Тот же инструмент для ПРЕЖНЕГО пути (серия A: «обратный запрет»).
                    # Запрет действует только на постановку в очередь и только у того
                    # типа, что назван: всё остальное (движение, работы, основание,
                    # наука) остаётся нетронутым, иначе различие между ветвями было бы
                    # не одним, а двумя.
                    _banned = {str(_n) for _n in ARGS.ban_produce}
                    cands = [
                        c for c in cands
                        if not (str(c.get("action_name", "")).startswith("produce_")
                                and str(c.get("action_name"))[len("produce_"):] in _banned)
                    ]
                # Правило F (§10.30): еду-небезопасные действия отсекаются ДО ядра.
                cands = _food_gate_filter(cands, obs, extractor, info.get("turn"))
                if not cands:
                    # Самоотчёт: сервер предложил действия, а кандидатов ноль.
                    # Без этого «0 решений за матч» не отличить от вето ядра —
                    # измерено на живом стенде: сторона получала 9 действий
                    # каждый ход и не выбирала ни одного 30 ходов подряд.
                    self._no_cands = getattr(self, "_no_cands", 0) + 1
                    if self._no_cands <= 5 or self._no_cands % 25 == 0:
                        offered = {c: (len(m) if hasattr(m, "__len__") else "?")
                                   for c, m in (avail or {}).items()}
                        try:
                            n_ent = len(dof.state.entities)
                        except Exception:  # noqa: BLE001
                            n_ent = "?"
                        print(f"        [нет-кандидатов {self._no_cands}] "
                              f"ход={info.get('turn')} сущностей={n_ent} "
                              f"предложено по контроллерам={offered}", flush=True)
                        if self._no_cands <= 3:
                            for line in _frozen_probe(obs, getattr(extractor, "my_player_id", None)):
                                print("        " + line, flush=True)
                    return None

                if trace and cands:
                    preview = " ".join(
                        f"{c['action_name']}({sum(c['projected_dof_delta'].values()):+.2f}"
                        f"{',rev' if c['is_reversible'] else ',IRR'})"
                        for c in cands[:6]
                    )
                    print(f"        candidates: {preview}", flush=True)

                if core is None:
                    # Python fallback: same objective, no Rust veto.
                    best = gen.select_best(cands, dof.state)
                    if best:
                        wire = _to_action(best)
                        _remember_verdict(wire, best.get("food_gate"))
                        return wire
                    return None

                decision = core.select_best(_core_entities(dof.state), _core_actions(cands))
                if decision.chosen_action_id is None or decision.net_delta <= 0:
                    # DOF-SPEC Decision Calculus §4: select a path only if its
                    # projected gain STRICTLY exceeds the transition cost
                    # (NetDelta > 0). Accepting net_delta == 0 let the agent spend
                    # whole games on measured-neutral actions (irrigation/road on
                    # one unit, forever) because a zero-gain option was always
                    # available and the core only declined on negative deltas.
                    if trace and decision.chosen_action_id is not None:
                        print(f"        declined {decision.chosen_action_id} "
                              f"(net_delta={decision.net_delta:+.3f} <= 0)", flush=True)
                    # Тот же самоотчёт, но для второй причины: кандидаты были,
                    # ядро отказалось. Печатаем всегда (редко): иначе причина
                    # «0 решений» снова станет неразличимой.
                    self._vetoed = getattr(self, "_vetoed", 0) + 1
                    if self._vetoed <= 5 or self._vetoed % 25 == 0:
                        print(f"        [вето ядра {self._vetoed}] кандидатов "
                              f"{len(cands)}, выбор={decision.chosen_action_id}, "
                              f"net_delta={decision.net_delta:+.3f}", flush=True)
                        if self._vetoed <= 2:
                            # Раз в игру — полные факты о точке отказа: какие юниты,
                            # сколько тумана в их достижимой зоне, что говорит
                            # оценка площадки. Без этого формула для скрытых клеток
                            # опиралась бы на догадку.
                            for line in _frozen_probe(obs, getattr(extractor, "my_player_id", None)):
                                print("        " + line, flush=True)
                    return None

                for cand in cands:
                    if cand["option_id"] == decision.chosen_action_id:
                        wire = _to_action(cand)
                        _remember_verdict(wire, cand.get("food_gate"))
                        return wire
                return None

        return DofAgent()

    return RandomAgent()


def _turn_phase(action, used_actors: set, decisions_this_turn: int,
                max_decisions: int) -> tuple[str, tuple | None]:
    """Decide whether to act or to end the turn.

    CivRealm ends a turn **only** when the action handed to ``env.step`` is
    ``None`` (``civ_controller.perform_action``); a real action never advances
    the turn. Without this bookkeeping an agent that always finds something to do
    plays the whole match inside turn 1 and the AI opponents never move — which
    made a no-op baseline look like the strongest strategy.

    Returns ``("act", key)`` or ``("end_turn", None)``.
    """
    _tet = os.environ.get("DOF_TURN_END_TRACE") == "1"
    if action is None:
        if _tet:
            print(f"  [конец-хода-причина] None (решений {decisions_this_turn})", flush=True)
        return "end_turn", None
    if decisions_this_turn >= max_decisions:
        if _tet:
            print(f"  [конец-хода-причина] потолок max_decisions={max_decisions}", flush=True)
        return "end_turn", None

    key = (action[0], action[1])
    if key in used_actors:
        # One decision per actor per turn (civrealm's own convention): without
        # this, a reversible action with a positive-looking projection is
        # repeated forever inside a single turn.
        # §13.611: эта ветвь — подозреваемый №1 в пределе «2 решения за ход».
        # Прибор печатает и ЧИСЛО уже занятых актёров: если оно 2 при 4 городах,
        # значит решатель выбирает первый город по своему порядку и ход гаснет,
        # не дойдя до остальных.
        if _tet:
            print(f"  [конец-хода-причина] ПОВТОР АКТЁРА {key} "
                  f"(решений {decisions_this_turn}, занято актёров {len(used_actors)})", flush=True)
        return "end_turn", None
    return "act", key


def _start_footprint(obs: dict) -> tuple[str, dict]:
    """Отпечаток СТАРТА: где мы появились и что видно с этой точки.

    Почему не «отпечаток карты». На 1-м ходу разведано 9 клеток из 4056, а
    неразведанные помечены 255 — то есть слой террейна почти постоянный, и
    осреднение по блокам даёт одинаковый хэш у РАЗНЫХ миров. Именно так и вышло:
    «одинаковый отпечаток» у двух слотов оказался артефактом вырожденного
    инструмента, а не совпадением карт.

    Измерено: три прогона на ОДНОМ слоте дали три разных старта ((7,43),
    (21,11), (42,29)). Значит, каждый матч — своя среда, и «пара по слоту» не
    существует: сравнивать можно только распределения по многим матчам.
    Отпечаток старта фиксирует это: по нему видно, действительно ли две выборки
    сделаны из одного места, а не предположительно.

    `DOF_DUMP_MAP` кладёт слои на диск для разбора.
    """
    layer_map = as_dict(obs.get('map')) or {}
    dump = os.environ.get("DOF_DUMP_MAP", "")
    digest = hashlib.sha1()
    info: dict[str, Any] = {"revealed": 0, "start": None}
    try:
        import numpy as np
        terrain = layer_map.get('terrain')
        output = layer_map.get('output')
        if output is not None:
            arr_out = np.ascontiguousarray(output)
            if dump:
                np.save(f"{dump}.output.npy", arr_out)
            # Разведано там, где выход ненулевой (у нераскрытой клетки выход 0).
            mask = arr_out.sum(axis=2) > 0
            ys, xs = np.nonzero(mask)
            info["revealed"] = int(mask.sum())
            if len(ys):
                info["start"] = [int(round(ys.mean())), int(round(xs.mean()))]
            digest.update(mask.tobytes())
            digest.update(arr_out[mask].tobytes())
        if terrain is not None:
            arr_t = np.ascontiguousarray(terrain)
            if dump:
                np.save(f"{dump}.terrain.npy", arr_t)
            digest.update(arr_t.shape.__repr__().encode())
            if info["revealed"]:
                digest.update(arr_t[mask].tobytes())
    except Exception:  # noqa: BLE001 - отпечаток не стоит падения матча
        digest.update(repr(sorted(layer_map)).encode())
    if dump:
        try:
            with open(f"{dump}.fingerprint", "w") as fh:
                json.dump({"start_footprint": digest.hexdigest()[:12], **info},
                          fh, ensure_ascii=False)
        except OSError:
            pass
    return digest.hexdigest()[:12], info


def _count_actions(obs: dict) -> int:
    """Сколько действий сервер предложил — ВНИМАНИЕ: считать надо по `info`.

    Оставлено как напоминание о пойманной ошибке: `available_actions` приходят в
    `info` (`env.step` → `civ_controller.get_info_and_observation`), а в `obs` этого
    ключа нет. Счёт по `obs` давал ноль ВСЕГДА, из-за чего «сервер предложил
    ни одного» выглядело фактом о сервере, а было фактом об измерении.
    Для настоящего счёта используйте `info['available_actions']`.
    """
    avail = as_dict(obs.get('available_actions')) or {}
    count = 0
    for ctrl_map in avail.values():
        for actor_map in as_dict(ctrl_map).values():
            for value in as_dict(actor_map).values():
                try:
                    if bool(value):
                        count += 1
                except Exception:  # noqa: BLE001 - numpy-скаляр и т.п.
                    count += 1
    return count


def _parse_false_claims(spec: str) -> list[tuple[str, float]]:
    """`rules.citymindist=3.0,rules.food_cost=4` → [(key, 3.0), (key, 4.0)]."""
    out: list[tuple[str, float]] = []
    for item in str(spec or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, _, raw = item.partition("=")
        try:
            out.append((key.strip(), float(raw)))
        except ValueError:
            print(f"  [warn] не разобрал неверное утверждение: {item}", flush=True)
    return out


def _encounter_gap(obs: dict, my_player_id) -> tuple[int | None, int, int] | None:
    """Расстояние до ближайшей ЧУЖОЙ сущности: (min, чужих юнитов, наших юнитов).

    Зачем отдельная функция. Турнир, в котором противники не сходятся, не
    проверяет взаимодействие — а именно так и было в прежних дуэлях: старты
    стояли на 36–43 клетки (карта 78×52), и за 25–50 ходов стороны не видели друг
    друга вовсе. Поэтому контакт нужно ИЗМЕРЯТЬ.

    Метрика — Чебышёв на цилиндре: X замыкается (карта 78 в ширину), Y — нет.
    Это «сколько шагов по прямой», а не манхэттен: юнит ходит по восьми
    направлениям. `None` в первом элементе означает «чужих не видно вовсе» —
    это НЕ то же самое, что большое расстояние: туман не равен дали.
    """
    try:
        units = as_dict(as_dict(obs).get('unit'))
        cities = as_dict(as_dict(obs).get('city'))
    except Exception:  # noqa: BLE001
        return None
    shape = None
    try:
        rules = as_dict(as_dict(obs).get('rules'))
        xs, ys = rules.get('xsize'), rules.get('ysize')
        if xs and ys:
            shape = (int(xs), int(ys))
    except Exception:  # noqa: BLE001
        shape = None
    mine: list[tuple[int, int]] = []
    theirs: list[tuple[int, int]] = []
    for pool in (units, cities):
        for rec in pool.values():
            if not isinstance(rec, dict):
                continue
            x, y = rec.get('x'), rec.get('y')
            if x is None or y is None:
                continue
            owner = rec.get('owner', my_player_id)
            try:
                same = int(owner) == int(my_player_id)
            except (TypeError, ValueError):
                continue
            try:
                point = (int(x), int(y))
            except (TypeError, ValueError):
                continue
            (mine if same else theirs).append(point)
    if not theirs:
        return (None, 0, len(mine))
    best: int | None = None
    width = shape[0] if shape else None
    for mx, my in mine:
        for tx, ty in theirs:
            dx = abs(mx - tx)
            if width:
                dx = min(dx, width - dx)          # X замыкается
            dist = max(dx, abs(my - ty))          # Чебышёв: 8 направлений
            if best is None or dist < best:
                best = dist
    return (best, len(theirs), len(mine))


def _is_combat_action(action_name: str) -> bool:
    """Боевое действие — взаимодействие, а не только близость."""
    text = str(action_name).lower()
    return any(word in text for word in
               ("attack", "capture", "conquer", "bombard", "nuke", "kill"))


#: Ходы, с которых забор площадок уже сделан (одна строка на ход на матч).
_SITE_SAMPLE_SEEN: set = set()


def _sample_sites(obs: dict, turn: int, radius: int, my_player_id) -> int:
    """Оценить ВСЕ клетки окна вокруг наших юнитов и дописать строки в корпус.

    Зачем именно окно целиком. Ошибку оценки площадки нельзя мерить по основанным
    городам: такая выборка смещена к хорошим местам (в корпусе `site_outcomes`
    именно так и было). Здесь оцениваются и раскрытые клетки, и туман — той же
    формулой `evaluate_site`, которой руководствуется агент. В игру ничего не
    отправляется: только чтение наблюдения.

    Возвращает число дописанных строк.
    """
    if turn in _SITE_SAMPLE_SEEN:
        return 0
    map_obs = as_dict(as_dict(obs).get('map'))
    layer = map_obs.get('output')          # СЛОЙ — массив, а не словарь
    shape = getattr(layer, 'shape', None)
    rules = as_dict(as_dict(obs).get('rules'))
    try:
        xsize, ysize = int(rules.get('xsize') or 0), int(rules.get('ysize') or 0)
    except (TypeError, ValueError):
        xsize, ysize = 0, 0
    if (not xsize or not ysize) and shape and len(shape) >= 2:
        # Размер берём из формы слоя карты: ключи `rules` есть не всегда, а слой
        # приходит всегда (та же легенда, что в замерах: terrain/output — массивы).
        xsize, ysize = int(shape[0]), int(shape[1])
    if not (xsize and ysize):
        print("      [забор площадок] нет размера карты — забор пропущен", flush=True)
        return 0
    ours: list[tuple[int, int]] = []
    for rec in as_dict(as_dict(obs).get('unit')).values():
        if not isinstance(rec, dict):
            continue
        try:
            if int(rec.get('owner', my_player_id)) != int(my_player_id):
                continue
            ours.append((int(rec.get('x')), int(rec.get('y'))))
        except (TypeError, ValueError):
            continue
    if not ours:
        print("      [забор площадок] наших юнитов не видно — забор пропущен", flush=True)
        return 0
    from env.site_eval import evaluate_site
    from env.world_model import default_model
    values = dict(default_model().values())
    x0, y0 = ours[0]
    tag = os.environ.get("DOF_RUN_TAG", "")
    written = 0
    with open("site_sample.jsonl", "a", encoding="utf-8") as fh:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = (x0 + dx) % xsize, y0 + dy
                if not 0 <= y < ysize:
                    continue
                try:
                    site = evaluate_site(map_obs, x, y, size=1, vals=values)
                except Exception:  # noqa: BLE001
                    continue
                hidden = None
                try:
                    # Легенда (проверена на стенде): туман — это output (0,0,0) и
                    # террейн-сентайнел; поэтому «скрыта» определяем по выходу.
                    cell = map_obs.get("output")
                    hidden = not any(float(v) for v in list(cell[x][y])[:3])
                except Exception:  # noqa: BLE001
                    hidden = None
                fh.write(json.dumps({
                    "tag": tag, "turn": int(turn), "x": int(x), "y": int(y),
                    "hidden": hidden, "gate_food": float(site.gate_food),
                    "gate_food_high": float(site.gate_food_high),
                    "known_tiles": int(site.known_tiles),
                    "total_tiles": int(site.total_tiles),
                    "site_food": float(getattr(site, "food", 0.0)),
                    "site_shields": float(getattr(site, "shields", 0.0)),
                    "site_trade": float(getattr(site, "trade", 0.0)),
                    "viable": bool(site.viable),
                    "gate": float(values.get("SITE_MIN_FOOD", 6.0)),
                }, ensure_ascii=False) + "\n")
                written += 1
    _SITE_SAMPLE_SEEN.add(turn)
    print(f"      [забор площадок] ход {turn}: клеток окна {written} "
          f"(радиус {radius}, от {x0},{y0}) → site_sample.jsonl", flush=True)
    return written


def _action_record(action, obs) -> dict[str, Any]:
    if action is None:
        return {}
    ctrl, actor = str(action[0]), str(action[1])
    records = as_dict(as_dict(obs).get(ctrl))
    prefix = f"{ctrl}_"
    actor_key = actor[len(prefix):] if actor.startswith(prefix) else actor
    keys = (actor, actor_key, f"{ctrl}_{actor_key}")
    record = next((records[key] for key in keys if key in records), None)
    if record is None:
        try:
            record = records.get(int(actor_key))
        except ValueError:
            return {}
    return as_dict(record)


def _action_position_context(action, obs) -> dict[str, Any]:
    record = _action_record(action, obs)
    try:
        position = [int(record["x"]), int(record["y"])]
    except (KeyError, TypeError, ValueError):
        return {}
    context = {"position": position}
    unit_type = record.get("type_rule_name") or record.get("rule_name")
    if unit_type:
        context["unit_type"] = str(unit_type)
    return context


def _record_wedge(metrics: MatchMetrics, action, turn: int,
                  action_context=None) -> None:
    """Записать timeout вместе с местом, не распространяя его вслепую на карту."""
    if action is None:
        return
    ctrl, name = str(action[0]), str(action[2])
    metrics.wedge_action = {"ctrl_type": ctrl, "action_name": name, "turn": turn}
    context = {"agent": metrics.agent_name, **(action_context or {})}
    try:
        record_wedged(ctrl, name, turn=turn, context=context)
    except OSError as exc:  # pragma: no cover - диск, а не логика
        print(f"  [warn] не записал клинч {ctrl}/{name}: {exc}", flush=True)


def _record_step_success(metrics: MatchMetrics, action, turn: int,
                         action_context=None) -> None:
    """A returned env.step rehabilitates only the same controller position."""
    if action is None:
        return
    ctrl, name = str(action[0]), str(action[2])
    context = dict(action_context or {})
    if not context.get("position"):
        return
    context["agent"] = metrics.agent_name
    try:
        record_success(ctrl, name, turn=turn, context=context)
    except OSError as exc:  # pragma: no cover - диск, а не логика
        print(f"  [warn] не записал успех {ctrl}/{name}: {exc}", flush=True)


def run_match(agent_type: str, turns: int = 30, port: int = 6001,
              timeout: int = 240, seed: int | None = None,
              include_series: bool = False, max_decisions_per_turn: int = 20,
              lookahead: int = 3, context_switch_penalty: float = 0.5,
              max_candidates: int = 8, pace: float = 0.0, trace: bool = False,
              curiosity: bool = True,
              false_claims: list[tuple[str, float]] | None = None,
              ) -> MatchMetrics:
    """Play one game on ``port`` and return its metrics, one record per turn.

    ``turns`` counts *game turns*, not decisions: within a turn the agent may
    issue several decisions (one per actor), then the turn is ended explicitly by
    stepping ``None``.

    ``seed`` is handed to ``env.reset`` which sets the Freeciv map/game/agent
    seeds, so distinct seeds produce distinct scenarios.
    """
    metrics = MatchMetrics(agent_name=agent_type, include_series=include_series)
    # Номер попытки: срезы состояния (--dump-state) из одной серии лежат в одном
    # файле, и без этого номера строки разных матчей неразличимы.
    _EPISODE_IDX[0] += 1
    metrics.curiosity = curiosity
    metrics.port = port
    _SITE_SAMPLE_SEEN.clear()      # забор площадок — заново на каждый матч
    # Метка для корпуса сверок площадок: строки должны различаться по агентам,
    # иначе «прогноз против факта» смешает города всех вариантов в одну кучу.
    os.environ["DOF_RUN_TAG"] = f"{agent_type}{'' if curiosity else '/no-curiosity'}"
    # The A/B switch: read at every bonus call, so it takes effect per match.
    env_config.CURIOSITY_ENABLED = curiosity
    # Правило F: выключатель читается на каждом матче, поэтому контрольная ветвь
    # (`--no-food-gate`) идёт по тому же коду, а не по другой сборке.
    env_config.FOOD_GATE_ENABLED = bool(getattr(ARGS, "food_gate", True))
    food_gate.reset_log()
    _GATE_FILTERED[0] = 0
    _GATE_NO_CITY[0] = 0
    _GATE_REASONS.clear()
    _ACTION_VERDICT.clear()
    _CANDIDATE_DUMPS.clear()   # срезы кандидатов — «первые N ходов ЭТОЙ игры»
    _TURN_ACTIONS.clear()      # иначе список действий хода N накапливает прошлые игры
    _COMBAT_MESSAGES[0] = 0
    extractor = GameStateExtractor(my_player_id=0)
    env = None

    # Deliberately wrong claims, if the caller asked for them: the point is to make
    # the world correct something, because on live data it mostly *adds* facts
    # rather than contradicting them — so the correction branch would never be
    # exercised and "reality is primary" would stay an untested belief.
    for key, value in (false_claims or []):
        extractor.model.plant_false_claim(key, value, note="внедрено раннером")
        metrics.false_claims.append(f"{key}={value}")

    signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.time() + timeout
    signal.alarm(timeout)
    try:
        agent = build_agent(agent_type, extractor, lookahead,
                            context_switch_penalty, max_candidates, trace,
                            env_getter=lambda: env)

        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port, seed=seed)
        # Which civilisation the env is playing is decided when the game is
        # created, NOT by the agent — hardcoding player 0 silently made every
        # own-civilisation test fail (garrison counts, the founding estimate, and
        # therefore whether expansion looked like a gain at all).
        try:
            extractor.my_player_id = env.get_playerid()
        except Exception:  # noqa: BLE001 - the id is optional context, not a blocker
            pass
        metrics.seed = seed
        metrics.engine = "rust-core" if HAVE_DOF_CORE else "python"

        # Состав мира: каких игроков видит ЭТА сторона. Внешне «мой игрок не даёт
        # действий» и «я в другой игре, чем партнёр» неразличимы — 0 решений за 50
        # ходов в обоих случаях. Имена игроков их различают: в одной игре обе
        # стороны видят один и тот же список.
        try:
            players = as_dict(obs.get('player')) or {}
            names = sorted(str(rec.get('name')) for rec in players.values()
                           if isinstance(rec, dict))
            if os.environ.get("DOF_PLAYERS_DEBUG") == "1":
                for _pid, _rec in sorted(players.items()):
                    if not isinstance(_rec, dict):
                        continue
                    _num = {k: _rec[k] for k in _rec
                            if isinstance(_rec[k], (int, float)) and not isinstance(_rec[k], bool)}
                    print(f"  [игрок {_pid}] имя={_rec.get('name')!r} числа={_num}", flush=True)
            print(f"  [состав] сторона видит игроков: {names} "
                  f"(мой player_id={getattr(extractor, 'my_player_id', None)})",
                  flush=True)
        except Exception:  # noqa: BLE001 - диагностика не должна ломать матч
            pass

        turns_played = 0
        decisions_this_turn = 0
        used_actors: set = set()
        done = False
        # ДУЭЛЬ: в одной игре несколько игроков, поэтому ход завершается не нашим
        # `None`, а суммой фаз. Наш `None` закрывает только свою фазу, и считать
        # его ходом значит раздуть счётчик и пересчитывать метрики по устаревшему
        # наблюдению. Поэтому в дуэли ход считается по ГЛОБАЛЬНОМУ счётчику.
        duel = bool(ARGS.duel)
        last_global_turn = info.get("turn")

        while not done and turns_played < turns:
            if pace:
                time.sleep(pace)
            # Every step is bounded. A step that never returns is not a slow stand,
            # it is a wedge: knowing WHICH pick wedged it is the whole point, and
            # the global match timeout alone cannot tell us that.
            stepped = False
            try:
                remaining = max(1.0, deadline - time.time())
                step_budget = min(STEP_TIMEOUT, remaining)
                signal.setitimer(signal.ITIMER_REAL, step_budget)
                # Действия приходят в `info`, а не в `obs`: счёт по `obs` мерил не
                # то (ключ `available_actions` там отсутствует, поэтому «пусто»
                # получалось всегда). Меру переносим туда, где лежит источник —
                # и печатаем и наличие ключа в наблюдении, чтобы это не вернулось.
                info_actions = as_dict(info.get("available_actions")) or {}
                n_offered = sum(len(as_dict(v)) for v in info_actions.values()
                                if isinstance(v, dict))
                if n_offered == 0:
                    # Not (necessarily) a defect: with no action left to offer the
                    # loop ends the turn, and that is how a turn normally closes.
                    # A defect is zero actions for the WHOLE match; this counter is
                    # context for reading that, not a verdict by itself.
                    metrics.empty_action_turns += 1
                    if (metrics.empty_action_turns <= 5
                            or metrics.empty_action_turns % 25 == 0):
                        offered = {c: (len(as_dict(v)) if isinstance(v, dict) else v)
                                   for c, v in info_actions.items()}
                        print(f"      [пусто {metrics.empty_action_turns}] ход "
                              f"{turns_played + 1}: сервер предложил "
                              f"контроллеры {offered or 'ни одного'} "
                              f"(в наблюдении ключ available_actions: "
                              f"{'available_actions' in (obs or {})})", flush=True)
                _USED_ACTORS[:] = [set(used_actors)]   # ДО решения: прогноз смотрит
                # §13.609: прибор — какая ВЕТВЬ решателя закрывает ход. Ход кончается на `None`
                # (строка ниже), и медиана «2 решения за ход» — следствие того, что решатель
                # возвращает None раньше, чем обошёл города. Прибор запоминает строку возврата
                # внутри `act`; под флагом, по умолчанию поведение не трогает.
                if os.environ.get("DOF_NONE_TRACE") == "1":
                    import sys as _sys
                    _ret_lines: list[int] = []

                    def _tr(frame, event, arg, _r=_ret_lines):
                        if event == "return":
                            _r.append(f"{frame.f_code.co_name}@{frame.f_code.co_filename.split('/')[-1]}:{frame.f_lineno}")
                        return _tr

                    _sys.settrace(_tr)
                    try:
                        action = agent.act(obs, info)
                    finally:
                        _sys.settrace(None)
                    if _ret_lines:
                        print(f"  [ветвь-решения] ход {turns_played + 1}: "
                              f"актёр={'None' if action is None else action[:2]} "
                              f"действие={(action[2] if action and len(action) > 2 else None)} "
                              f"кадры {_ret_lines[-1:]}", flush=True)
                else:
                    action = agent.act(obs, info)
                phase, key = _turn_phase(action, used_actors, decisions_this_turn,
                                         max_decisions_per_turn)

                if phase == "act":
                    used_actors.add(key)
                    decisions_this_turn += 1
                    end_turn = False
                    metrics.record_decision(turns_played + 1, action)
                    _TURN_ACTIONS.setdefault(turns_played + 1, []).append(
                        [str(p) for p in action[:3]] + [_verdict_of(action)])
                    if trace:
                        # Параметры действия печатаем: без них не отличить «отправили
                        # постановку» от «отправили её так, что сервер её отверг»
                        # (подозрение — сдвиг значения юнита, измеряется здесь).
                        _prm = action[3] if len(action) > 3 else None
                        print(f"      turn {turns_played + 1}: "
                              f"{action[0]}/{action[1]}/{action[2]}"
                              + (f" параметры={_prm!r}" if _prm is not None else ""),
                              flush=True)
                else:
                    end_turn = True
                    # Вторая половина замера: действия БЫЛИ предложены, а выбора
                    # не сделано. Это указывает на наш код (нет кандидатов или
                    # весь список отклонён ядром), а не на стенд — и раньше эти два
                    # случая были неразличимы.
                    if decisions_this_turn == 0 and n_offered > 0:
                        seen = getattr(metrics, "no_choice_turns", 0) + 1
                        metrics.no_choice_turns = seen
                        if seen <= 5 or seen % 25 == 0:
                            # Что именно предложено: без этого «нет кандидатов»
                            # неотличимо от «сервер не предложил производство».
                            parts = []
                            for ctrl, actors in info_actions.items():
                                if not isinstance(actors, dict):
                                    continue
                                total = sum(len(as_dict(a)) for a in actors.values())
                                valid = sum(1 for a in actors.values()
                                            for params in as_dict(a).values() if params)
                                parts.append(f"{ctrl} {valid}/{total}")
                            city_valid = []
                            for actor, acts in as_dict(info_actions.get("city")).items():
                                truthy = [name for name, params in as_dict(acts).items()
                                          if params and name.startswith("produce_")]
                                if truthy:
                                    city_valid.append(f"{actor}: {len(truthy)} "
                                                      f"produce → {truthy[:3]}")
                            print(f"      [выбор-пуст {seen}] ход {turns_played + 1}: "
                                  f"предложено действий {n_offered} "
                                  f"({'; '.join(parts)}), агент не выбрал ни одного; "
                                  f"годное производство: "
                                  f"{city_valid or 'НЕТ'}", flush=True)
                            # СЫРОЕ МЕНЮ ЮНИТА: без него «нет кандидатов движения»
                            # неотличимо от «сервер не предлагал шагов». Вопрос
                            # «почему сторона стоит» решается именно этим списком.
                            unit_valid = []
                            for actor, acts in as_dict(info_actions.get("unit")).items():
                                names = [name for name, params in as_dict(acts).items()
                                         if params]
                                if names:
                                    goto = [n for n in names if n.startswith("goto")]
                                    unit_valid.append(
                                        f"{actor}: {len(names)} годных, "
                                        f"шагов {len(goto)} → {names[:8]}")
                            print(f"      [меню юнита] {unit_valid or 'НЕТ ГОДНЫХ'}", flush=True)
                    # §13.354: СКОЛЬКО РЕШЕНИЙ МЫ ПРИНЯЛИ ЗА ХОД. Без этого числа «наша
                    # сторона ничего не делает» и «стенд не даёт действовать» неразличимы,
                    # а следы печатают только часть путей (ранний возврат правила поселенца
                    # мимо печати отправки).
                    if os.environ.get("DOF_CHOICE_DEBUG") == "1":
                        print(f"  [решений-за-ход] ход {turns_played + 1}: "
                              f"{decisions_this_turn} (актёров задействовано "
                              f"{len(used_actors)})", flush=True)
                    action = None  # stepping None is what ends the turn
                    decisions_this_turn = 0
                    used_actors = set()

                step_action_context = _action_position_context(action, obs)
                stepped = True  # from here a hang belongs to the chosen action
                # §13.571: запомнить ОТПРАВЛЕННОЕ снятие работы с клетки — фильтр повторов
                # (_drop_repeated_unwork) читает эту запись на следующем ходу.
                try:
                    if (os.environ.get("DOF_NO_UNWORK_REPEAT") == "1" and action is not None
                            and str(action[0]) == "city"
                            and str(action[2]).startswith("city_unwork")):
                        _UNWORK_SENT[(str(action[1]), str(action[2]))] = turns_played + 1
                except Exception:  # noqa: BLE001
                    pass
                if os.environ.get("DOF_TRACE_UNITS") == "1" and action is not None:
                    # §13.452: прибор ИМЕННО на отправку действия. Прежний канал `[прогноз]`
                    # в этих партиях не печатает ни строки, поэтому судить о работах по нему
                    # было нельзя. Здесь видно ровно то, что уходит клиенту — и в сыром виде
                    # тоже, потому что вид действия заранее не известен.
                    try:
                        print(f"  [отправка-юнита] ход {turns_played + 1}: {str(action)[:110]}",
                              flush=True)
                    except Exception:  # noqa: BLE001
                        pass
                if os.environ.get("DOF_STEP_DEBUG") == "1":
                    # §13.543: ЕДИНСТВЕННАЯ точка, через которую проходит ход. Прежние приборы
                    # стояли в неисполняемых копиях и молчали.
                    try:
                        _t = turns_played + 1
                    except Exception:  # noqa: BLE001
                        _t = "?"
                    print(f"  [шаг] ход {_t}: {str(action)[:160]}", flush=True)
                obs, reward, terminated, truncated, info = env.step(action)
                _record_step_success(metrics, action, turns_played + 1,
                                     step_action_context)
                # Замер засчитывается только ПОСЛЕ шага: отклонённое сервером
                # действие ничему не учит, и тратить на него бюджет любопытства
                # нельзя (то же правило, что для неизмеренных действий проекта).
                _note_probe_taken()
            except MatchTimeout as exc:
                if not stepped or step_budget < STEP_TIMEOUT - 1e-6:
                    # Either the match budget ran out, or the agent itself hung:
                    # neither names an action, so there is nothing to measure.
                    raise
                _record_wedge(metrics, action, turns_played + 1,
                              step_action_context)
                raise MatchTimeout(
                    f"wedged on {action[0]}/{action[2]} at turn "
                    f"{turns_played + 1}") from exc
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)

            done = bool(terminated or truncated)
            # Счёт игры: серверная величина, не выведенная из наблюдения. Это
            # единственная метрика исхода, на которой можно законно сравнивать
            # агента с бездействующим: пакеты наблюдения у них разные, а счёт
            # считает сервер по своим правилам для всех одинаково.
            metrics.record_score(turns_played + 1, reward)
            # ── ВСТРЕЧА СТОРОН: измеряем контакт каждый ход, а не предполагаем ──
            try:
                _enc = _encounter_gap(obs, getattr(extractor, "my_player_id", None))
                if _enc is not None:
                    metrics.note_encounter(turns_played + 1, _enc[0], _enc[1], _enc[2])
                    if (_enc[0] is not None and _enc[0] <= metrics.CONTACT_WITHIN
                            and not metrics.enemy_contact_turns[:-1]):
                        print(f"      [встреча] ход {turns_played + 1}: чужая "
                              f"сущность в {_enc[0]} шаг(ах), чужих видно {_enc[1]}",
                              flush=True)
            except Exception as exc:  # noqa: BLE001
                metrics.note_encounter(turns_played + 1, None)
                print(f"      [встреча] замер не удался: {type(exc).__name__}: {exc}",
                      flush=True)
            if action is not None and _is_combat_action(action[2]):
                metrics.note_combat(str(action[2]))
            # ── ЗАБОР ПЛОЩАДОК (несмещённая выборка, §10.27) ─────────────────
            if ARGS.sample_sites and turns_played < ARGS.sample_sites:
                try:
                    _sample_sites(obs, turns_played + 1, ARGS.sample_radius,
                                  getattr(extractor, "my_player_id", None))
                except Exception as exc:  # noqa: BLE001
                    print(f"      [забор площадок] сбой: {type(exc).__name__}: {exc}",
                          flush=True)
            # An experiment counts when the action was actually TAKEN, not when it
            # was chosen: a pick the server rejects teaches nothing, and the bonus
            # for probing must decay against real experience only.
            if action is not None and not end_turn:
                note_choice(extractor.model, str(action[0]), str(action[2]),
                            turn=turns_played + 1)

            global_turn = info.get("turn")
            turn_advanced = global_turn != last_global_turn
            if end_turn and duel and not turn_advanced:
                # Наша фаза закрыта, но ход двигает пара фаз. Ждём соперника: не
                # считаем это ходом и не пересчитываем метрики по устаревшему
                # наблюдению (иначе счётчик ходов и индекс растут «на пустом месте»).
                time.sleep(max(0.0, ARGS.duel_wait))
            elif end_turn:
                turns_played += 1
                last_global_turn = global_turn
                # Срез состояния — ДО извлечения: он должен попасть в запись и на
                # ходу поражения, когда наблюдение пусто, а извлекатель уже
                # уходит в ветку «пусто от клиента».
                if ARGS.dump_state and turns_played <= ARGS.dump_state:
                    try:
                        _dump_state(env, obs, info, extractor, turns_played, port)
                    except Exception as exc:  # noqa: BLE001
                        print(f"      [состояние] сбой среза: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                extraction = extractor.extract(obs, info, info.get("turn", turns_played))
                if ARGS.dump_state:
                    try:
                        _dump_foreign_entities(obs, extraction, extractor)
                        _dump_index_composition(obs, extraction, extractor)
                        _dump_fog_distance(obs, extractor)
                    except Exception as exc:  # noqa: BLE001
                        print(f"      [чужое в DoF] сбой среза: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                if not metrics.start_fingerprint:
                    # Captured on the first turn. Not "the map": at turn 1 only a
                    # handful of tiles are revealed, so what identifies a match is
                    # where we started, not a map we cannot see.
                    (metrics.start_fingerprint,
                     start_info) = _start_footprint(obs)
                    metrics.revealed_cells = start_info.get("revealed", 0)
                    metrics.start_xy = start_info.get("start")
                entities = extraction.state.entities
                # Состав по видам: без него «вклад агента против no-op» может
                # оказаться разницей не в игре, а в том, что планка видела мир иначе.
                kinds: dict[str, int] = {}
                for entity_id in entities:
                    kind = str(entity_id).split('_', 1)[0]
                    kinds[kind] = kinds.get(kind, 0) + 1
                for kind, count in kinds.items():
                    if count > metrics.entity_kinds_max.get(kind, 0):
                        metrics.entity_kinds_max[kind] = count
                non_collapse = [e for e in entities.values() if not e.is_collapse_source]
                dof_index = (
                    sum(e.current_dof for e in non_collapse) / len(non_collapse)
                    if non_collapse else 0.0
                )
                # One record per turn; the "action" is the end-turn marker, and the
                # per-decision reversibility accounting is kept in decisions_*.
                metrics.record_step(
                    turns_played,
                    dof_index,
                    len(entities),
                    None,
                    compute_total_dof_index(extraction.state),
                )
                if turns_played % 10 == 0:
                    index = compute_total_dof_index(extraction.state)
                    print(f" [turn {turns_played}/{turns} ent={len(entities)} "
                          f"idx={index:.2f}]", end="", flush=True)

        metrics.finished = True
        _print_food_gate_summary()
        if ARGS.forecast:
            # Итог прогноза: без него «0 решений» снова было бы неотличимо от
            # «прогноз не работал и всё делал fallback».
            _print_forecast_summary()
            _print_tech_trace()
            _print_military_trace()
    except MatchTimeout as exc:
        metrics.error = f"timeout: {exc}"
    except Exception as exc:  # noqa: BLE001 - report, never crash the tournament
        metrics.error = f"{type(exc).__name__}: {exc}"
        # Матч умер не по таймауту. Виновный выбор надо назвать — но НЕ любой ценой:
        # клин на невиновном действии хуже отсутствия записи, потому что навсегда
        # убирает законное действие. Поэтому пишем только те отказы, что похожи на
        # отказ стенда (`AssertionError` в контроллере, таймаут), и молчим про
        # ошибки нашего собственного аргумента (`KeyError`/`TypeError`/`NameError`) —
        # они означают, что чинить надо нас, а не вычёркивать действие.
        if isinstance(exc, (AssertionError, TimeoutError, OSError)):
            try:
                _record_wedge(metrics, locals().get("action"),
                              int(locals().get("turns_played", -1)) + 1)
            except Exception:  # noqa: BLE001
                pass
        # A one-line summary is what the report shows; the traceback is what
        # makes the failure fixable, so keep it right next to the match.
        print(traceback.format_exc(), file=sys.stderr, flush=True)
    finally:
        signal.alarm(0)
        # Knowledge gained is reported even when the match died: a wedged match
        # that still taught us a family's effect is not a total loss, and the A/B
        # needs the count to compare "learning" against "score".
        try:
            metrics.experiments_total = sum(extractor.model.experiment_attempts.values())
            metrics.pairs_total = sum(len(v) for v in extractor.model.pairs.values())
            metrics.experiment_families = dict(extractor.model.experiment_attempts)
            # Did the world correct us? Counted from the model's own log, so the
            # answer is a number, not an impression.
            verdicts: dict[str, int] = {}
            corrected: list[str] = []
            log: list[dict] = []
            for rec in extractor.model.reconciliations:
                # Our own injection is not a world correction: it *is* the record
                # whose prior was the honest value and whose observed value is the
                # lie we planted. Counting it would double the evidence.
                if FALSE_CLAIM_MARKER in (rec.evidence or ""):
                    continue
                verdicts[rec.verdict] = verdicts.get(rec.verdict, 0) + 1
                if rec.verdict == 'corrected':
                    if rec.key not in corrected:
                        corrected.append(rec.key)
                    log.append({'key': rec.key, 'turn': rec.turn,
                                'prior': rec.prior, 'observed': rec.observed,
                                'source': getattr(rec.source, 'value', str(rec.source))})
            metrics.reconciled = verdicts
            metrics.corrected_keys = corrected
            metrics.correction_log = log
        except AttributeError:  # pragma: no cover - модель без учёта пар
            pass
        if env is not None:
            # СОСТАВ СЧЁТА: сервер считает счёт суммой категорий (Population, Trade,
            # Production, Cities, Technologies, Military Service, Wonders, Research
            # Speed, Land/Settled Area, Literacy, Culture, Built Units, Killed Units,
            # Unit Losses, Units Used). Если различие между ветвями целиком лежит в
            # категории «военные/построенные юниты», то вывод «производство полезно»
            # верен ПО ОПРЕДЕЛЕНИЮ метрики, а не как свойство поведения. Поэтому
            # состав счёта читается у сервера и записывается в отчёт — до выводов.
            try:
                # `evaluate_game` возвращает четвёрку (players, tags, turns, evaluations);
                # нужен последний элемент: {имя_категории: {player_id: [значения по ходам]}}.
                res = env.evaluate_game()
                cats = res[3] if isinstance(res, tuple) and len(res) == 4 else res
                pid = env.get_playerid()
                final: dict[str, float] = {}
                for tag_name, per_player in (cats or {}).items():
                    series = per_player.get(pid) if isinstance(per_player, dict) else None
                    if series:
                        final[str(tag_name)] = float(series[-1])
                metrics.category_scores = final
                if final:
                    print(f"  [счёт по категориям] " + ", ".join(
                        f"{k}={v:.0f}" for k, v in sorted(final.items())), flush=True)
                # §13.332: ЭТАЛОН НА СВОЁМ СТЕНДЕ. Мир публикует счёт КАЖДОЙ стороны
                # (`evaluate_game` отдаёт срезы по player_id), поэтому встроенный ИИ
                # можно мерить на той же карте и в той же партии, а не ссылаться на
                # давний чужой замер 152.50 (§13.317).
                try:
                    _obs = locals().get("obs")
                    _names: dict[int, str] = {}
                    for _p, _r in (as_dict((_obs or {}).get("player")) or {}).items():
                        if isinstance(_r, dict):
                            try:
                                _key = int(_r.get("player_id"))
                            except (TypeError, ValueError):
                                _key = int(_p)
                            _names[_key] = str(_r.get("name") or _p)
                    for _tag, _per in (cats or {}).items():
                        if str(_tag) != "score" or not isinstance(_per, dict):
                            continue
                        for _p, _ser in _per.items():
                            if not _ser:
                                continue
                            try:
                                _pid_i = int(_p)
                            except (TypeError, ValueError):
                                continue
                            print(f"  [счёт сторон] {_names.get(_pid_i, _p)} (id {_pid_i})"
                                  f" = {float(_ser[-1]):.0f}", flush=True)
                    # §13.333: не только счёт, но и СОСТАВ по каждой стороне — тогда
                    # видно, в какой статье встроенный ИИ уходит вперёд (города, население,
                    # земля, производство), а не только «он в 10 раз больше».
                    _rows: dict[int, dict[str, float]] = {}
                    for _tag, _per in (cats or {}).items():
                        if not isinstance(_per, dict):
                            continue
                        for _p, _ser in _per.items():
                            if not _ser:
                                continue
                            try:
                                _ppi = int(_p)
                            except (TypeError, ValueError):
                                continue
                            _rows.setdefault(_ppi, {})[str(_tag)] = float(_ser[-1])
                    for _ppi in sorted(_rows):
                        _vals = ", ".join(f"{k}={v:.0f}" for k, v in sorted(_rows[_ppi].items()))
                        print(f"  [состав сторон] {_names.get(_ppi, _ppi)} (id {_ppi}): {_vals}",
                              flush=True)
                except Exception as _exc:  # noqa: BLE001 - диагностика не рушит серию
                    print(f"  [счёт сторон] не прочитан: {type(_exc).__name__}: {_exc}",
                          flush=True)
            except Exception as exc:  # noqa: BLE001 - состав счёта не должен рушить серию
                print(f"  [счёт по категориям] не прочитан: {type(exc).__name__}: {exc}",
                      flush=True)
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass

    # Кривая самообучения (§10.32): срез склада фактов и покрытия по каждой игре.
    try:
        _write_learn_record(obs, extractor, metrics)
    except Exception as exc:  # noqa: BLE001 - запись меры не должна рушить серию
        print(f"  [обучение] срез не записан: {type(exc).__name__}: {exc}", flush=True)

    return metrics


def _resolve_agent_types(args) -> list[str]:
    agents = ["random", "no-op"] + [f"dof_{s.name}" for s in ALL_STRATEGIES]
    if not args.only.strip():
        return agents
    wanted = [a.strip() for a in args.only.split(",") if a.strip()]
    unknown = [a for a in wanted if a not in agents]
    if unknown:
        print(f"ERROR: unknown agent(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(agents)}")
        sys.exit(2)
    return wanted


def _print_report(agents: list[str], results: dict[str, list[dict]]) -> None:
    print("\n" + "=" * 88)
    print("RESULTS (all agents measured through the same recorder)")
    print("=" * 88)
    print(f"{'Agent':<20}{'N':>4}{'Turns':>7}{'Index':>10}{'AvgDoF':>9}"
          f"{'IrrRat':>8}{'Dec/turn':>9}{'SkipTurn':>9}{'Score↑':>9}{'Errs':>6}")
    print("-" * 88)
    for agent in agents:
        summary = agent_turns(results[agent])
        if summary["n"] == 0:
            print(f"{agent:<20}{0:>4}")
            continue
        records = results[agent]
        dec_per_turn = sum(r.get("decisions_per_turn_mean", 0.0) for r in records) / len(records)
        # «Score↑» — выигрыш по счёту игры за матч (серверная величина). Он не
        # выведен из наблюдения, поэтому пригоден и для сравнения с no-op.
        score = sum(r.get("score_gain", 0.0) or 0.0 for r in records) / len(records)
        print(f"{agent:<20}{summary['n']:>4}{summary['turns']:>7.1f}"
              f"{summary['avg_total_dof_index']:>10.3f}"
              f"{summary['avg_dof']:>9.3f}"
              f"{summary['irreversibility_ratio']:>8.2f}"
              f"{dec_per_turn:>9.1f}{summary['skipped_turns']:>9.1f}"
              f"{score:>9.1f}"
              f"{summary['errors']:>6}")

    for agent in agents:
        for record in results[agent]:
            if record.get("error"):
                print(f"  [error] {agent}: {record['error']}")
                break

    # Reconciliation is the point of the model being alive: show what the world
    # said about our claims, including whether it corrected anything.
    for agent in agents:
        for record in results[agent]:
            verdicts = record.get("reconciled") or {}
            if not verdicts:
                continue
            corrected = record.get("corrected_keys") or []
            claims = record.get("false_claims") or []
            if claims or corrected:
                print(f"  [model] {agent}: сверки {verdicts}"
                      + (f", ИСПРАВЛЕНО {corrected}" if corrected else "")
                      + (f", внедрено неверного: {claims}" if claims else ""))

    print("\nOne row per agent; Turn = game turns actually played (an agent that never")
    print("hands None to env.step never advances the game — see _turn_phase).")
    print("IrrRat = irreversible / decisions; SkipTurn = turns with no decision.")
    print("For N and confidence intervals run: bash do.sh analyze")


def main():
    args = ARGS

    if not args.auto_port:
        last_port = args.port + args.episodes - 1
        if args.port < MIN_PORT or last_port > MAX_PORT:
            print(f"ERROR: slots {args.port}-{last_port} outside {MIN_PORT}-{MAX_PORT}."
                  " Use auto-allocation (default) or lower --episodes.")
            sys.exit(2)

    agents = _resolve_agent_types(args)
    results: dict[str, list[dict]] = {a: [] for a in agents}

    mode = "auto slot allocation" if args.auto_port else f"slots {args.port}-{args.port + args.episodes - 1}"
    total = len(agents) * args.episodes
    print(f"REAL tournament: {len(agents)} agents x {args.episodes} episodes x "
          f"{args.turns} turns  ({total} matches)")
    print(f"Slot mode: {mode}")
    print(f"Curiosity bonus (probing unmeasured actions): "
          f"{'ON' if args.curiosity else 'OFF'}")
    print(f"Per-match timeout: {args.timeout}s (per step {STEP_TIMEOUT}s), "
          f"retries: {args.retries}\n")

    started = time.time()
    done_matches = 0

    bad_slots: set = set()
    consecutive_errors = 0
    for agent in agents:
        print(f"  {agent:<20}", end="", flush=True)
        for ep in range(args.episodes):
            # §13.359: новая партия — новая память о карте (иная карта, иное виденное).
            try:
                from env.world_memory import reset as _memory_reset
                _memory_reset()
            except Exception:  # noqa: BLE001
                pass
            # §13.412: своя память о площадках (основанные, отказные, удерживаемые цели) тоже
            # относится к партии: иная карта — иные координаты. Именно `clear()`, а не удаление
            # имени: эти имена объявлены на уровне модуля, и их удаление ломает партию
            # (`NameError: name '_FOUND_TARGET' is not defined` в самом первом прогоне).
            for _nm in ("_FOUNDED_SITES", "_FOUND_TARGET", "_FOUND_BLACK", "_FOUND_FAIL",
                        "_FOUND_REFUSALS", "_ORDERED_THIS_TURN"):
                _mem = globals().get(_nm)
                if hasattr(_mem, "clear"):
                    _mem.clear()
            seed = None if args.seed_base is None else args.seed_base + ep
            metrics = None
            port = None
            for _attempt in range(args.retries + 1):
                if args.auto_port:
                    port = allocate_port(args.port_wait, bad_slots)
                if port is None:
                    port = args.port + (ep % max(1, MAX_PORT - MIN_PORT + 1))
                metrics = run_match(agent, args.turns, port, args.timeout, seed,
                                    args.save_series, args.max_decisions_per_turn,
                                    args.lookahead, args.context_switch_penalty,
                                    args.max_candidates, args.pace, args.trace,
                                    args.curiosity,
                                    _parse_false_claims(args.false_claim))
                if not metrics.error:
                    consecutive_errors = 0
                    break
                bad_slots.add(port)
                consecutive_errors += 1
                # If many slots in a row die, reset the pool so Publite2
                # can recycle them (BeginTurnTimeout / stale slots).
                if consecutive_errors >= 3:
                    try:
                        from civrealm.freeciv.utils.port_utils import Ports
                        Ports.clear()
                        consecutive_errors = 0
                    except Exception:  # noqa: BLE001
                        pass
                metrics.error = f"{metrics.error} [slot {port}]"
                time.sleep(args.settle)

            results[agent].append(metrics.to_dict())
            done_matches += 1
            tag = "ok" if not metrics.error else "ERR"
            elapsed = time.time() - started
            rate = done_matches / elapsed if elapsed else 0.0
            remaining = (total - done_matches) / rate if rate else 0.0
            print(f" {tag}@{port}", end="", flush=True)
            if done_matches % 5 == 0:
                print(f"  [{done_matches}/{total}  eta {remaining/60:.1f}m]",
                      end="", flush=True)
            time.sleep(args.settle)
        print("")

    _print_report(agents, results)

    if args.output:
        payload = {
            "meta": {
                "agents": agents,
                "episodes": args.episodes,
                "turns": args.turns,
                "timeout": args.timeout,
                "match_timeout_s": args.timeout,
                "step_timeout_s": STEP_TIMEOUT,
                "curiosity": args.curiosity,
                "false_claim": args.false_claim,
                "lookahead": args.lookahead,
                "context_switch_penalty": args.context_switch_penalty,
                "max_candidates": args.max_candidates,
                "max_decisions_per_turn": args.max_decisions_per_turn,
                "save_series": args.save_series,
                "seed_base": args.seed_base,
                "elapsed_s": round(time.time() - started, 1),
            },
            "results": results,
        }
        with open(args.output, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()