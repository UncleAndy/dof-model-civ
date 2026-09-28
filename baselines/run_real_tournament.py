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


_CANDIDATE_DUMPS: list = []
_BUY_DIAG_PRINTED: list = []
_TECH_NUMBERS_SEEN: list = []


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


def _gold_of(obs, extractor) -> float:
    """Золото игрока — по ЗАПИСИ игрока, а не по ключу словаря (ловушка §5.2f/13)."""
    try:
        from brain.forecast.live import _player_record
        rec = _player_record(obs, getattr(extractor, "my_player_id", None)) or {}
        return float(rec.get("gold") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _forecast_decide(obs, info, dof, extractor, avail, *, type_names=None,
                     gold=None) -> tuple[bool, tuple | None]:
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
                            if _USED_ACTORS else None,
                            type_names=type_names, gold=gold)
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
                dof = extractor.extract(obs, info, info.get("turn", 0))
                avail = info.get("available_actions", {})

                # ПРОГНОЗ: перебор вариантов с перевыводом возможностей в будущем
                # состоянии (brain/forecast). Он решает ход; прежний путь ниже
                # остаётся как fallback на случай сбоя прогноза, а не как
                # альтернативное мнение: два решателя одновременно — это не
                # сравнение, а неопределённость.
                decided, wire = _forecast_decide(
                    obs, info, dof, extractor, avail,
                    type_names=(_unit_type_names(env_getter())
                                if env_getter is not None else None),
                    gold=lambda: _gold_of(obs, extractor))
                if decided:
                    return wire

                cands = gen.generate_candidates(dof.state, avail)
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
    _SITE_SAMPLE_SEEN.clear()      # забор площадок — заново на каждый матч
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