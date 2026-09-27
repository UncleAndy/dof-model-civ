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
    parser.add_argument("--no-forecast", dest="forecast", action="store_false",
                        help="прежний путь: ядро оценивает один шаг по сегодняшнему "
                             "меню (для сравнения, а не для результатов)")
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
    parser.add_argument("--save-series", dest="save_series", action="store_true",
                        default=False,
                        help="also persist per-step DoF/entity/action series "
                             "(larger JSON, enables trajectory analysis)")
    parser.add_argument("--output", type=str, help="write per-episode metrics to JSON")
    args, rest = parser.parse_known_args(argv)
    sys.argv = [sys.argv[0]] + rest
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium
from civrealm.configs import fc_args
from civrealm.agents import RandomAgent, BaseAgent

from env import config as env_config
from env.config import AXIOM4_PENALTY_OPTIONS, CORE_DOF_SCALE
from env.entity_extractor import GameStateExtractor, as_dict, compute_total_dof_index
from env.experiments import note_choice
from env.wedged import record_wedged
from env.world_model import FALSE_CLAIM_MARKER
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


def _forecast_decide(obs, info, dof, extractor, avail) -> tuple[bool, tuple | None]:
    """Прогноз решает ход: `(взял_ли_решение, действие)`.

    Различать «прогноз решил не действовать» и «прогноз недоступен» обязательно:
    первое — законный исход DOF-Core (нет строгого улучшения), и подменять его
    прежним путём нельзя; второе — сбой, и тогда работает прежний путь.
    """
    if not ARGS.forecast:
        return False, None
    try:
        from brain.forecast import choose
        from brain.forecast.live import _player_record, build_context

        ctx = build_context(obs, info, dof, extractor,
                            exclude_actors=set(_USED_ACTORS[0])
                            if _USED_ACTORS else None)
        _watch_tech(ctx, obs, info)
        _learn_type_cost(ctx, obs)      # вторая половина прошлого замера
        if not _FORECAST_NOTES_PRINTED and ctx.notes:
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
        if probe is not None:
            _FORECAST_STATS["probes"] += 1
            if _FORECAST_STATS["probes"] <= 3:
                print(f"        [прогноз] пустой ход потрачен на замер: "
                      f"{probe[0]}/{probe[1]}/{probe[2]}", flush=True)
            return True, probe
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
    _FORECAST_STATS["acted"] += 1
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
            # Координат цели у `goto_N` нет: берём первый предложенный вариант —
            # ценность хода прогноз посчитал, а конкретную цель выбирает сервер.
            for cand_name, params in actions.items():
                if cand_name.startswith("goto") and params:
                    return ("unit", key, cand_name)
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
                max_candidates: int = 8, trace: bool = False):
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
                dof = extractor.extract(obs, info, info.get("turn", 0))
                avail = info.get("available_actions", {})

                # ПРОГНОЗ: перебор вариантов с перевыводом возможностей в будущем
                # состоянии (brain/forecast). Он решает ход; прежний путь ниже
                # остаётся как fallback на случай сбоя прогноза, а не как
                # альтернативное мнение: два решателя одновременно — это не
                # сравнение, а неопределённость.
                decided, wire = _forecast_decide(obs, info, dof, extractor, avail)
                if decided:
                    return wire

                cands = gen.generate_candidates(dof.state, avail)
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
                    return _to_action(best) if best else None

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
                        return _to_action(cand)
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
    if action is None:
        return "end_turn", None
    if decisions_this_turn >= max_decisions:
        return "end_turn", None

    key = (action[0], action[1])
    if key in used_actors:
        # One decision per actor per turn (civrealm's own convention): without
        # this, a reversible action with a positive-looking projection is
        # repeated forever inside a single turn.
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


def _record_wedge(metrics: MatchMetrics, action, turn: int) -> None:
    """Записать выбор, о который заклинило стенд, — это измерение, а не шум.

    Матч потерян, но знание остаётся: семейство уходит в реестр, и следующий
    матч (в т.ч. следующий агент того же прогона) за него уже не заплатит и не
    выберет его.
    """
    if action is None:
        return
    ctrl, name = str(action[0]), str(action[2])
    metrics.wedge_action = {"ctrl_type": ctrl, "action_name": name, "turn": turn}
    try:
        record_wedged(ctrl, name, turn=turn, context={"agent": metrics.agent_name})
    except OSError as exc:  # pragma: no cover - диск, а не логика
        print(f"  [warn] не записал клинч {ctrl}/{name}: {exc}", flush=True)


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
    metrics.curiosity = curiosity
    metrics.port = port
    # Метка для корпуса сверок площадок: строки должны различаться по агентам,
    # иначе «прогноз против факта» смешает города всех вариантов в одну кучу.
    os.environ["DOF_RUN_TAG"] = f"{agent_type}{'' if curiosity else '/no-curiosity'}"
    # The A/B switch: read at every bonus call, so it takes effect per match.
    env_config.CURIOSITY_ENABLED = curiosity
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
                           context_switch_penalty, max_candidates, trace)

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
                action = agent.act(obs, info)
                phase, key = _turn_phase(action, used_actors, decisions_this_turn,
                                         max_decisions_per_turn)

                if phase == "act":
                    used_actors.add(key)
                    decisions_this_turn += 1
                    end_turn = False
                    metrics.record_decision(turns_played + 1, action)
                    if trace:
                        print(f"      turn {turns_played + 1}: "
                              f"{action[0]}/{action[1]}/{action[2]}", flush=True)
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
                    action = None  # stepping None is what ends the turn
                    decisions_this_turn = 0
                    used_actors = set()

                stepped = True  # from here a hang belongs to the chosen action
                obs, reward, terminated, truncated, info = env.step(action)
                # Замер засчитывается только ПОСЛЕ шага: отклонённое сервером
                # действие ничему не учит, и тратить на него бюджет любопытства
                # нельзя (то же правило, что для неизмеренных действий проекта).
                _note_probe_taken()
            except MatchTimeout as exc:
                if not stepped or step_budget < STEP_TIMEOUT - 1e-6:
                    # Either the match budget ran out, or the agent itself hung:
                    # neither names an action, so there is nothing to measure.
                    raise
                _record_wedge(metrics, action, turns_played + 1)
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
                extraction = extractor.extract(obs, info, info.get("turn", turns_played))
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
        if ARGS.forecast:
            # Итог прогноза: без него «0 решений» снова было бы неотличимо от
            # «прогноз не работал и всё делал fallback».
            _print_forecast_summary()
            _print_tech_trace()
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
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass

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