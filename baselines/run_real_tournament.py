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
        for _owner, ux, uy in _threat.foreign_units_from_map(obs, my_id):
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
#: §13.348: ЦЕЛЬ поселенца — как его миссия `AIUNIT_BUILD_CITY` (`daisettler.c:1029-1054`):
#: он ставит поселенцу задачу с клеткой-целью и ведёт его туда, пока цель годна, и только по
#: прибытии основывает город. У нас цель пересчитывалась КАЖДЫЙ ход, а внутри цены площадки
#: сидит дорога (`amortize(total, PERFECTION*turns)`), поэтому «лучшая» переезжала на соседнюю
#: клетку и обратно: поселенец качался между двумя и не основывал вовсе (измерено §13.347).
_FOUND_TARGET: dict = {}

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


def _founder_step(obs: dict, avail: dict, mindist: int | None = None):
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
            city_positions, rank_sites, step_toward,
        )
        from env.food_gate import food_cost_of
        from env.site_eval import evaluate_site
    except Exception:  # noqa: BLE001
        return None
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
    _known_cities = city_positions(obs)
    if os.environ.get("DOF_FOUND_DEBUG") == "1":
        _seen_cm = globals().setdefault("_CM_SEEN", set())
        if _mindist_src not in _seen_cm:
            _seen_cm.add(_mindist_src)
            print(f"  [citymindist] {_mindist} (источник: {_mindist_src}), "
                  f"городов известно {len(_known_cities)}", flush=True)
    for uid, actions in unit_actions.items():
        offered = as_dict(actions) or {}
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
        if os.environ.get("DOF_FOUND_DEBUG") == "1":
            _seen = globals().setdefault("_FOUND_DEBUG_SEEN", set())
            if (uid, tuple(pos)) not in _seen:
                _seen.add((uid, tuple(pos)))
                try:
                    _all = rank_sites(obs, exclude=city_positions(obs), reference=tuple(pos),
                                      cities=_known_cities, mindist=_mindist)
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
            ranked_all = rank_sites(obs, exclude=city_positions(obs),
                                    reference=tuple(pos), settler_shield_cost=0.0,
                                    cities=_known_cities, mindist=_mindist)
        except Exception:  # noqa: BLE001
            ranked_all = []
        if not ranked_all:
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid} на {tuple(pos)}: достижимых площадок нет",
                      flush=True)
            continue                      # некуда идти — не мешаем основанию
        here = next((c for c in ranked_all
                     if (int(c[0]), int(c[1])) == tuple(pos)), None)
        best = ranked_all[0]
        on_best = (int(best[0]), int(best[1])) == tuple(pos)
        starved = bool(getattr(site, "starved_food", False)
                       or getattr(site, "starved_shield", False))
        if on_best and can_found_here:
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid} на {tuple(pos)}: на лучшей площадке, "
                      f"основывает общий путь", flush=True)
            _FOUND_TARGET.pop(str(uid), None)   # стоим на лучшей: основывает общий путь
            continue                      # лучшая и есть текущая — его правило основывает здесь
        if can_found_here and not starved and here is not None \
                and float(best[3]) <= float(here[2]):
            if os.environ.get("DOF_FOUND_DEBUG") == "1":
                print(f"  [пропуск] unit/{uid} на {tuple(pos)}: лучшая {tuple(best[:2])} "
                      f"не окупает дорогу ({float(best[3]):.1f} <= {float(here[2]):.1f})",
                      flush=True)
            continue                      # лучше, но не настолько: дорога съедает выигрыш
        ranked = [c for c in ranked_all if (int(c[0]), int(c[1])) != tuple(pos)]
        gotos = [str(n) for n, params in offered.items()
                 if str(n).startswith("goto_") and truthy(params)]
        # ── §13.348: ДЕРЖИМ цель, как его миссия (`daisettler.c:1029-1054`): пока цель годна,
        # ведём поселенца к НЕЙ, а не к пересчитанной заново. По прибытии — не мешаем общему
        # пути основать (`build_city`), цель снимаем. Цель стала недостижимой — пересчитываем.
        _held = _FOUND_TARGET.get(str(uid))
        if _held is not None:
            if (int(pos[0]), int(pos[1])) == _held:
                _FOUND_TARGET.pop(str(uid), None)
                continue
            _step_held = step_toward(tuple(pos), _held, offered=gotos or None,
                                     blocked=_blocked_step)
            if _step_held is not None:
                if os.environ.get("DOF_TRACE_FILTERS") == "1":
                    print(f"  [поселенец] unit/{uid}: держу цель {_held} (его миссия) "
                          f"→ шаг {_step_held}", flush=True)
                return ("unit", uid, _step_held)
            _FOUND_TARGET.pop(str(uid), None)
        # Берётся ПЕРВАЯ площадка, к которой мир предлагает законный шаг. Измерено: без
        # этого поселенец 11 раз подряд выбирал шаг к воде, не сдвигался и не основывал
        # город вовсе — цена площадки без достижимости вредна.
        step = None
        target = None
        for cand in ranked:
            step = step_toward(tuple(pos), (cand[0], cand[1]), offered=gotos or None,
                               blocked=_blocked_step)
            if step is not None:
                target = cand
                break
        if step is None or target is None:
            continue
        _FOUND_TARGET[str(uid)] = (int(target[0]), int(target[1]))   # §13.348: держим до прибытия
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [поселенец] unit/{uid}: площадка {pos} голодная "
                  f"({getattr(site, 'reason', '')}) → иду к {target[:2]} (его total "
                  f"{target[2]:.1f}), шаг {step}", flush=True)
        return ("unit", uid, step)
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
    # Сперва — спасение голодающего города: годность ПЕРЕД выгодой (его порядок).
    # Только если спасать нечего, переходим к выбору по выигрышу.
    _rescue = _city_tile_rescue(obs, avail)
    if _rescue is not None:
        _LAST_TILE_ACTION[str(_rescue[1])] = _rescue[2]
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
    cities = (obs or {}).get("city") or {}
    # Его правило: чудеса строит ТОЛЬКО город чудес (`daicity.c:1972`). Без этой проверки
    # наш город населением 3 ставил `Colossus` (измерено, игра 6001: `produce_Colossus` ×5) —
    # вложение в 100 щитов, которое окупается позже конца партии, тогда как у него чудо
    # получает ровно один город, и то по щитам.
    wonder_city = _wonder_city_id(obs)
    for cid, rec in cities.items():
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
            names_sorted = sorted(offered)
            print(f"  [постановка] город {cid}: стенд предлагает {len(names_sorted)} "
                  f"предметов: {names_sorted[:14]}", flush=True)
        best: tuple[float, str, int] | None = None
        scored: list[tuple[float, str, int]] = []
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
            scored.append((value, str(name), turns))
            if best is None or value > best[0]:
                best = (value, str(name), turns)
        if best is None:
            if _filters_trace():
                print(f"  [постановка] город {cid}: маски дали {len(allowed)} типов, "
                      f"ни один не оценён — постановку не меняем", flush=True)
            continue
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
    if not keep:
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
                                _us = getattr(getattr(_c, "unit_ctrl", None), "units", None)
                                if isinstance(_us, dict) and _us:
                                    _k0, _u0 = next(iter(_us.items()))
                                    print(f"  [контроллер] units[{_k0!r}]: тип {type(_u0).__name__}, "
                                          f"значение {str(_u0)[:100]!r}", flush=True)
                        except Exception as _exc:  # noqa: BLE001
                            print(f"  [позиции] ошибка: {type(_exc).__name__}: {_exc}", flush=True)
                    _founder = _founder_step(obs, avail,
                                             mindist=_world_citymindist(env_getter()))
                    if _founder is not None:
                        return _founder
                    _tile_pick = _city_tile_candidate(obs, avail)
                    if _tile_pick is not None:
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
                            _LAST_PROD[str(_prod.get("actor_id"))] = _com
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