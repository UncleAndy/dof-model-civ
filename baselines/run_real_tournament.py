#!/usr/bin/env python3
"""Стенд-харнесс v2: соединяет агента со стендом CivRealm и записывает, что говорит мир.

ЧТО ЭТО. **Прибор, а не модель.** Он создаёт партию, гоняет ходы, пишет счёт мира, состав
счёта и срезы наблюдений. Из v1 не перенесено ничего: политика, прогноз и любые коэффициенты
сняты вместе с моделью. Политики v2 подключаются через реестр `AGENTS` (см. низ файла).

ЧТО СОХРАНЕНО КАК ЗНАНИЕ О СТЕНДЕ (всё измерено в v1; §10.42–§10.59 `drafts/DOF_CALIBRATION.md`):

* **Парные карты.** `--seed-base N` → эпизод i получает `seed = N + i`; `env.reset(seed=...)`
  выставляет `randomly_generate_seeds=False`, `mapseed=seed`, `agentseed=seed`. Один и тот же
  эпизод в разных ветвях идёт на ОДНОЙ карте. Без этого удача карты перекрывает эффект —
  измерено: вердикт переворачивался между кругами на 150 ходах.
* **Бюджет матча.** Полная игра на 300 ходов длится ≈450 с. `--timeout 240` обрывал игры на
  90–124 ходах и обрезал счёт; для 300 ходов брать `--timeout 1500`.
* **Ход завершает только `None`.** Реальное действие ход не двигает: без явного шага `None`
  агент играет всю партию внутри первого хода, а соперники не ходят вовсе.
* **Счёт мира отдаётся приростом** (`current_score - last_score`); сумма приростов = выигрыш
  по счёту за матч. Первый вызов возвращает весь накопленный счёт сразу.
* **Состав счёта читается у сервера** в конце игры: `env.evaluate_game()` → четвёртый элемент
  `{категория: {player_id: [значения по ходам]}}`. Нужен, чтобы видеть, ЧЕМ взят счёт: сумма
  категорий нафармируется юнитами (`units_built`, `units_lost` считаются положительно) и
  неистраченной казной (`gold`) — измерено на 24 картах.
* **Приборные отказы помечаются полем `error`** (обрыв бюджета времени, падение библиотеки).
  Это не исход: игру с непустым `error` нельзя ставить в вердикт — измерено на серии, где
  пять упавших эпизодов «сделали» положительный результат.
* **Контракт интерфейса** сохранён ради `run_duel.py` и `analyze.py`: те же флаги CLI и форма
  результата `{"meta": ..., "results": {агент: [эпизоды…]}}`.

АГЕНТЫ. `no-op`, `random` и две вырожденные **канарейки** (`canary_units`, `canary_hoard`):
любая честная мера обязана ставить их низко, иначе мера негодна (проверено: «копилка» набирала
280 очков по сумме категорий против 23 у честной ветви — мера провалила проверку).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Optional

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "civrealm" / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: Бюджет одного шага по умолчанию. 20 с — значение, проверенное в v1: нормальный шаг
#: возвращается быстрее, а шаг, который не вернулся за 20 с, — это клин стенда, а не
#: медленный сервер. Переопределяется `--step-timeout`.
STEP_TIMEOUT = 20.0


# ── CLI. ВАЖНО: разбирается ДО импорта civrealm и не съедает аргументы ─────────
# civrealm/configs/__init__.py на импорте сам вызывает `parse_known_args()` по sys.argv и
# собирает свой парсер из `default_settings.yaml`. Поэтому `--aifill`, `--minp`, `--username`,
# `--debug.begin_turn_timeout`, `--debug.server_timeout` и прочие настройки партии попадают в
# `fc_args` именно так. Наш разбор обязан идти первым и оставлять sys.argv нетронутым.
def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_real_tournament.py",
        description="Стенд CivRealm: агент играет настоящие партии, прибор пишет исход.",
    )
    parser.add_argument("--episodes", type=int, default=1, help="партий на агента")
    parser.add_argument("--turns", type=int, default=30, help="ходов в партии")
    parser.add_argument("--port", type=int, default=6001,
                        help="слот; используется при --no-auto-port")
    parser.add_argument("--auto-port", dest="auto_port", action="store_true", default=True,
                        help="брать свободный слот через civrealm Ports.get() (по умолчанию)")
    parser.add_argument("--no-auto-port", dest="auto_port", action="store_false",
                        help="использовать --port + номер эпизода")
    parser.add_argument("--timeout", type=int, default=240,
                        help="бюджет матча, с; для 300 ходов ≈1500")
    parser.add_argument("--retries", type=int, default=1,
                        help="повторов партии при приборном отказе (обрыв бюджета)")
    parser.add_argument("--settle", type=float, default=5.0, help="пауза между партиями, с")
    parser.add_argument("--pace", type=float, default=0.0, help="пауза между решениями, с")
    parser.add_argument("--seed-base", type=int, default=None,
                        help="эпизод i играет seed=N+i; ОДНА карта во всех ветвях")
    parser.add_argument("--only", type=str, default="",
                        help="агенты через запятую; пусто — все известные")
    parser.add_argument("--output", type=str, default="tournament_results.json",
                        help="куда писать результат (форма совместима с analyze.py)")
    parser.add_argument("--dump-state", type=int, default=0,
                        help="писать срез наблюдения каждый ход до N-го")
    parser.add_argument("--max-decisions-per-turn", type=int, default=20,
                        help="потолок решений внутри одного хода")
    parser.add_argument("--trace", action="store_true", help="печатать каждое решение")
    parser.add_argument("--step-timeout", type=float, default=STEP_TIMEOUT,
                        help="бюджет одного шага, с; не вернулся — считаем клином стенда")
    parser.add_argument("--avoid-wedges", dest="avoid_wedges", action="store_true", default=True,
                        help="не выбирать действия из реестра клинов (по умолчанию)")
    parser.add_argument("--no-avoid-wedges", dest="avoid_wedges", action="store_false",
                        help="выбирать всё, включая известные клины (для проверки реестра)")
    parser.add_argument("--duel", action="store_true",
                        help="в игре несколько наших сторон: ход считать по общему счётчику")
    parser.add_argument("--duel-wait", type=float, default=0.5,
                        help="пауза, пока соперник закрывает свою фазу, с")
    # Настройки партии — их читает сам civrealm (см. комментарий выше); здесь объявлены,
    # чтобы наш разбор их принимал и не падал. Имена — ровно как ключи
    # `default_settings.yaml` (проверено: `username`, `server_timeout`, `begin_turn_timeout`,
    # `aifill`, `minp`, `max_turns`, `follower_take_player`).
    parser.add_argument("--username", type=str, default=None)
    parser.add_argument("--aifill", type=int, default=None)
    parser.add_argument("--minp", type=int, default=None)
    parser.add_argument("--max_turns", type=int, default=None)
    parser.add_argument("--server_timeout", type=int, default=None)
    parser.add_argument("--begin_turn_timeout", type=int, default=None)
    parser.add_argument("--follower_take_player", type=str, default=None)
    return parser.parse_args(argv)


ARGS = _parse_cli(sys.argv[1:])

import gymnasium  # noqa: E402
from civrealm.configs import fc_args  # noqa: E402

from metrics.tracker import MatchMetrics  # noqa: E402

from baselines import wedges  # noqa: E402


class MatchTimeout(Exception):
    """Обрыв бюджета матча: приборный отказ, а не исход игры."""


def _on_alarm(signum, frame):  # noqa: ANN001
    raise MatchTimeout("match exceeded wall-clock budget")


# ── Мир: читаем то, что он сам говорит ────────────────────────────────────────

def offered(info: dict) -> dict[str, dict]:
    """Меню сервера: {контроллер: {актор: {действие: параметры}}} — факт мира, не вывод модели."""
    raw = (info or {}).get("available_actions") or {}
    out: dict[str, dict] = {}
    for ctrl, actors in raw.items():
        if isinstance(actors, dict):
            out[str(ctrl)] = actors
    return out


def legal_actions(menu: dict[str, dict]) -> list[tuple[str, Any, str]]:
    """Годные действия: сервер отдаёт пустые параметры у негодных (измерено).

    Из выбора вычитаются действия из реестра клинов (`baselines/wedges.py`): на них сервер
    не отвечает, и партия теряется целиком. Отключается `--no-avoid-wedges`.
    """
    out: list[tuple[str, Any, str]] = []
    for ctrl, actors in menu.items():
        for actor, acts in actors.items():
            if not isinstance(acts, dict):
                continue
            for name, params in acts.items():
                if not params:
                    continue
                if ARGS.avoid_wedges and wedges.is_wedged(ctrl, str(name)):
                    continue
                out.append((ctrl, actor, str(name)))
    return out


def own_records(obs: dict, section: str, my_id: Optional[int]) -> dict[str, dict]:
    """Записи секции, принадлежащие нашей стороне. `my_id` неизвестен — берём все."""
    recs = (obs or {}).get(section) or {}
    out: dict[str, dict] = {}
    if not isinstance(recs, dict):
        return out
    for key, rec in recs.items():
        if not isinstance(rec, dict):
            continue
        if my_id is None or rec.get("owner") == my_id:
            out[str(key)] = rec
    return out


def dump_row(obs: dict, info: dict, my_id: Optional[int], *, episode: int, turn: int,
             port: int, agent: str, actions: list[list[str]]) -> dict:
    """Одна строка среза: что мир показал на этом ходу и что мы сделали."""
    cities = own_records(obs, "city", my_id)
    units = own_records(obs, "unit", my_id)
    foreign = 0
    for rec in ((obs or {}).get("unit") or {}).values():
        if isinstance(rec, dict) and rec.get("owner") != my_id:
            foreign += 1
    return {
        "эпизод": episode,
        "ветвь": agent,
        "порт": port,
        "turn_played": turn,
        "turn": (info or {}).get("turn"),
        "my_cities": [{"id": c.get("id"), "size": c.get("size"), "x": c.get("x"),
                       "y": c.get("y"), "food_stock": c.get("food_stock"),
                       "surplus_food": c.get("surplus_food"),
                       "prod_food": c.get("prod_food")} for c in cities.values()],
        "my_units": [{"type": u.get("type"), "x": u.get("x"), "y": u.get("y")}
                     for u in units.values()],
        "foreign_units": foreign,
        "действия_за_ход": actions,
        "messages": str((info or {}).get("messages") or ""),
    }


def pick_port(auto: bool, base: int, episode: int) -> int:
    """Слот партии. `Ports.get()` зацикливается, когда свободных слотов нет."""
    if not auto:
        return base + episode
    try:
        from civrealm.freeciv.utils.port_utils import Ports
        return Ports.get()
    except Exception as exc:  # noqa: BLE001 - отсутствие пула не должно рушить серию
        print(f"  [слот] Ports.get() недоступен ({type(exc).__name__}), беру {base + episode}",
              flush=True)
        return base + episode


# ── Агенты: политика и канарейки ──────────────────────────────────────────────
# Сигнатура одна: (obs, info, rng) -> (контроллер, актор, действие) | None.
# `None` закрывает ход — это единственный способ его продвинуть.

Policy = Callable[[dict, dict, random.Random], Optional[tuple[str, Any, str]]]


def agent_no_op(obs: dict, info: dict, rng: random.Random) -> None:
    """Бездействие: ничего не делает, ход закрывает сразу."""
    return None


def agent_random(obs: dict, info: dict, rng: random.Random) -> Optional[tuple[str, Any, str]]:
    """Случайное годное действие — планка, с которой сравнивают всё остальное."""
    actions = legal_actions(offered(info))
    return rng.choice(actions) if actions else None


def agent_canary_units(obs: dict, info: dict, rng: random.Random) -> Optional[tuple[str, Any, str]]:
    """КАНАРЕЙКА «спам юнитов»: всегда что-то производить. Обязана проигрывать честной мере."""
    actions = legal_actions(offered(info))
    produce = [a for a in actions if a[2].startswith("produce_")]
    if produce:
        return produce[0]
    return rng.choice(actions) if actions else None


def agent_canary_hoard(obs: dict, info: dict, rng: random.Random) -> Optional[tuple[str, Any, str]]:
    """КАНАРЕЙКА «копилка»: только исследование, ничего не тратить.

    Измерено в v1: такая политика набирала 280 очков по сумме категорий против 23 у честной
    ветви — исключительно за счёт неистраченной казны. Любая мера, которая её не наказывает,
    негодна.
    """
    actions = legal_actions(offered(info))
    research = [a for a in actions if a[2].startswith("research_tech")]
    return research[0] if research else None


AGENTS: dict[str, Policy] = {
    "no-op": agent_no_op,
    "random": agent_random,
    "canary_units": agent_canary_units,
    "canary_hoard": agent_canary_hoard,
}


def build_agent(name: str) -> Policy:
    """Политика по имени. Точка подключения v2 — `baselines/policies.py`."""
    if name in AGENTS:
        return AGENTS[name]
    try:  # политики v2 кладутся в baselines/policies.py функцией с именем политики
        from baselines import policies  # type: ignore
        fn = getattr(policies, name.replace("-", "_"), None)
        if callable(fn):
            return fn
    except Exception:  # noqa: BLE001 - модуля может ещё не быть
        pass
    raise SystemExit(f"неизвестный агент {name!r}. Известные: {', '.join(sorted(AGENTS))}")


# ── Партия ────────────────────────────────────────────────────────────────────

def run_match(agent_name: str, policy: Policy, *, turns: int, port: int, timeout: int,
              seed: Optional[int], dump_state: int, trace: bool, pace: float,
              max_decisions: int, episode: int) -> MatchMetrics:
    """Одна партия: возвращает метрики прибора (по записи на ход).

    `turns` считает ХОДЫ игры, а не решения: внутри хода агент может выдать несколько решений
    (по одному на актора), а ход закрывается явным шагом `None`.
    """
    metrics = MatchMetrics(agent_name=agent_name)
    metrics.port = port
    metrics.seed = seed
    rng = random.Random(0 if seed is None else seed)
    dump_path = Path(f"{ARGS.output}.state.jsonl") if dump_state else None

    signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.time() + timeout
    signal.alarm(timeout)
    env = None
    my_id: Optional[int] = None
    done = False
    try:
        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port, seed=seed)
        try:
            my_id = env.get_playerid()
        except Exception:  # noqa: BLE001 - идентификатор нужен как контекст, не как условие
            my_id = None
        players = (obs or {}).get("player") or {}
        names = sorted(str(r.get("name")) for r in players.values() if isinstance(r, dict))
        print(f"  [старт] порт {port}, seed {seed}, мой player_id={my_id}, "
              f"сторона видит: {names}", flush=True)

        turns_played = 0
        decisions_this_turn = 0
        used: set = set()
        turn_actions: list[list[str]] = []
        last_global = (info or {}).get("turn")

        while not done and turns_played < turns:
            if pace:
                time.sleep(pace)
            menu = offered(info)
            action = policy(obs, info, rng)
            if action is not None and (decisions_this_turn >= max_decisions
                                       or (action[0], action[1]) in used):
                # Одно решение на актора за ход (конвенция civrealm): без этого
                # обратимое действие повторяется внутри одного хода бесконечно.
                action = None

            if action is not None:
                used.add((action[0], action[1]))
                decisions_this_turn += 1
                metrics.record_decision(turns_played + 1, action)
                turn_actions.append([str(action[0]), str(action[1]), str(action[2])])
                if trace:
                    print(f"      ход {turns_played + 1}: "
                          f"{action[0]}/{action[1]}/{action[2]}", flush=True)
                end_turn = False
            else:
                end_turn = True
                if decisions_this_turn == 0 and menu:
                    # Меню было, а выбора нет: это про политику, а не про стенд.
                    metrics.empty_action_turns += 1
                decisions_this_turn = 0
                used = set()

            stepped = False
            budget = max(1.0, min(ARGS.step_timeout, deadline - time.time()))
            signal.setitimer(signal.ITIMER_REAL, budget)
            try:
                stepped = True
                obs, reward, terminated, truncated, info = env.step(action)
            except MatchTimeout as exc:
                if not stepped:
                    raise
                # Клин — измерение, а не шум: семейство уходит в реестр, и следующая
                # партия за него уже не платит (реестр вычитается в `legal_actions`).
                if action is not None:
                    try:
                        wedges.record_wedge(str(action[0]), str(action[2]),
                                            turn=turns_played + 1, agent=agent_name)
                    except OSError as werr:  # noqa: PERF203 - диск, а не логика
                        print(f"      [клин] не записан: {werr}", flush=True)
                raise MatchTimeout(f"клин на {action} на ходу {turns_played + 1}") from exc
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)

            done = bool(terminated or truncated)
            metrics.record_score(turns_played + 1, reward)

            global_turn = (info or {}).get("turn")
            if end_turn and ARGS.duel and global_turn == last_global:
                # Наша фаза закрыта, ход двигает пара фаз: не считаем это ходом.
                time.sleep(max(0.0, ARGS.duel_wait))
            elif end_turn:
                turns_played += 1
                last_global = global_turn
                metrics.record_step(turns_played, 0.0,
                                    len(own_records(obs, "unit", my_id))
                                    + len(own_records(obs, "city", my_id)),
                                    None)
                if dump_state and turns_played <= dump_state and dump_path is not None:
                    try:
                        row = dump_row(obs, info, my_id, episode=episode, turn=turns_played,
                                       port=port, agent=agent_name, actions=turn_actions)
                        with dump_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    except Exception as exc:  # noqa: BLE001 - срез не должен рушить партию
                        print(f"      [срез] сбой: {type(exc).__name__}: {exc}", flush=True)
                turn_actions = []

    except MatchTimeout as exc:
        metrics.error = f"timeout: {exc}"
        print(f"  [прибор] {metrics.error}", flush=True)
    except Exception as exc:  # noqa: BLE001 - падение стенда не должно рушить серию
        metrics.error = f"{type(exc).__name__}: {exc}"
        print(f"  [прибор] отказ: {metrics.error}", flush=True)
    finally:
        signal.alarm(0)
        if env is not None:
            # Состав счёта — ДО закрытия среды: видеть, чем взят счёт, важнее итоговой суммы.
            try:
                res = env.evaluate_game()
                cats = res[3] if isinstance(res, tuple) and len(res) == 4 else res
                pid = my_id if my_id is not None else env.get_playerid()
                final: dict[str, float] = {}
                for tag, per_player in (cats or {}).items():
                    series = per_player.get(pid) if isinstance(per_player, dict) else None
                    if series:
                        final[str(tag)] = float(series[-1])
                metrics.category_scores = final
                if final:
                    print("  [состав счёта] " + ", ".join(
                        f"{k}={v:.0f}" for k, v in sorted(final.items())), flush=True)
            except Exception as exc:  # noqa: BLE001 - состав счёта не должен рушить серию
                print(f"  [состав счёта] не прочитан: {type(exc).__name__}: {exc}", flush=True)
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass
    metrics.finished = done
    return metrics


def main() -> int:
    wanted = [a.strip() for a in ARGS.only.split(",") if a.strip()] or sorted(AGENTS)
    out_path = Path(ARGS.output)
    if ARGS.dump_state:
        Path(f"{ARGS.output}.state.jsonl").unlink(missing_ok=True)
    print(f"Партий на ветвь: {ARGS.episodes}, ходов: {ARGS.turns}, "
          f"бюджет матча: {ARGS.timeout} с, парные карты: "
          f"{'нет' if ARGS.seed_base is None else f'{ARGS.seed_base}+i'}", flush=True)

    results: dict[str, list[dict]] = {}
    for name in wanted:
        policy = build_agent(name)
        episodes: list[dict] = []
        for ep in range(ARGS.episodes):
            seed = None if ARGS.seed_base is None else ARGS.seed_base + ep
            attempt = 0
            while True:
                port = pick_port(ARGS.auto_port, ARGS.port, ep)
                print(f"=== {name} · эпизод {ep + 1}/{ARGS.episodes} · порт {port} ===", flush=True)
                metrics = run_match(name, policy, turns=ARGS.turns, port=port,
                                    timeout=ARGS.timeout, seed=seed,
                                    dump_state=ARGS.dump_state, trace=ARGS.trace,
                                    pace=ARGS.pace,
                                    max_decisions=ARGS.max_decisions_per_turn,
                                    episode=ep + 1)
                print(f"  итог: ходы={metrics.turns_played} счёт={metrics.score_cum:.1f} "
                      f"решений={metrics.actions_issued} отказ={metrics.error!r}", flush=True)
                if not metrics.error or attempt >= ARGS.retries:
                    episodes.append(metrics.to_dict())
                    break
                attempt += 1
                print(f"  [прибор] повтор партии (попытка {attempt} из {ARGS.retries})", flush=True)
            if ARGS.settle:
                time.sleep(ARGS.settle)
        results[name] = episodes

    payload = {
        "meta": {"args": vars(ARGS), "engine": "v2-stand",
                 "created": time.strftime("%Y-%m-%d %H:%M:%S")},
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nсохранено: {out_path}", flush=True)
    print("Разбор: python baselines/analyze.py " + str(out_path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())