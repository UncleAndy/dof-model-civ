"""Живая партия агента v2: знание копится в базе, решения — по DOF-SPEC.

Порядок хода: наблюдение → граф → пути (генератор) → DOF-фильтр (индекс, NetDelta) → действие →
запись эффекта. Пока проекция пуста, выбор падает на пробу — агент исследует.

Запуск:
  V2_STORE=knowledge/world.json V2_TURNS=60 V2_SEEDS=9000,9001 \
  python scripts/v2_play.py
"""
from __future__ import annotations

import json
import os
import signal
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2 import executor  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world.json"))
TRACE = os.environ.get("V2_TRACE", str(ROOT / "knowledge" / "traces.jsonl"))
TURNS = int(os.environ.get("V2_TURNS", "60"))
SEEDS = [int(s) for s in os.environ.get("V2_SEEDS", "9000,9001").split(",")]
PORT_BASE = int(os.environ.get("V2_PORT_BASE", "6300"))
STEP_TIMEOUT = float(os.environ.get("V2_STEP_TIMEOUT", "30"))
#: ПРЕДОХРАНИТЕЛЬ, а не политика: ход длится, пока есть действия с ценой > 0 (см. agent/calculus).
#: Значение выбрано с запасом, чтобы не обрезать ход; политику ограничивает сам агент.
MAX_DECISIONS_PER_TURN = 400


class StepTimeout(Exception):
    pass


def _on_alarm(_sig, _frm):
    raise StepTimeout()


signal.signal(signal.SIGALRM, _on_alarm)


def step(env, action):
    """Шаг среды с бюджетом: клин стенда не должен съедать партию целиком."""
    signal.setitimer(signal.ITIMER_REAL, STEP_TIMEOUT)
    try:
        return env.step(action)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def play(agent: Agent, seed: int, port: int, turns: int) -> dict:
    fc_args["client_port"] = port
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port, seed=seed)
    try:
        own_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        own_id = 0
    own_id = own_id or 0

    used: set = set()
    played = 0
    actions = 0
    turns_without_action = 0
    terminated = truncated = False
    try:
        for _ in range(turns):
            acted_this_turn = False
            for _ in range(MAX_DECISIONS_PER_TURN):
                action = agent.decide(obs, info, own_id, used)
                if action is None:
                    break
                acted_this_turn = True
                actions += 1
                for k in executor.used_keys(action):
                    used.add(k)
                obs, _r, terminated, truncated, info = step(env, action)
                agent.record_outcome(obs, own_id)
                if terminated or truncated:
                    break
            if terminated or truncated:
                break
            obs, _r, terminated, truncated, info = step(env, None)
            agent.record_outcome(obs, own_id)
            used.clear()
            played += 1
            if not acted_this_turn:
                turns_without_action += 1
            if terminated or truncated:
                break
    except StepTimeout:
        pend = getattr(agent, "_pending", None)
        ctrl = getattr(pend, "ctrl", "unknown")
        act = getattr(pend, "action", "timeout")
        wedges.record_wedge(ctrl, act, turn=played, agent="v2",
                            context={"source": "v2 agent, живой прогон"})
        print(f"  [клин] {ctrl}/{act} не вернулся за {STEP_TIMEOUT} с — партия прервана",
              flush=True)
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass

    players = (obs or {}).get("player") or {}
    me = players.get(str(own_id)) or players.get(own_id) or {}
    cities = [c for c in ((obs or {}).get("city") or {}).values() if c.get("owner") == own_id]
    units = [u for u in ((obs or {}).get("unit") or {}).values() if u.get("owner") == own_id]

    # снимок конца партии: по нему можно разбирать решения на состоянии, которое уже выросло
    dump = os.environ.get("V2_DUMP")
    if dump:
        from brain.v2.provenance import json_default
        Path(dump).write_text(json.dumps(
            {"seed": seed, "port": port, "my_id": own_id, "turn": (info or {}).get("turn"),
             "observation": obs, "available_actions": (info or {}).get("available_actions") or {}},
            ensure_ascii=False, default=json_default))
        print(f"  [снимок] {dump}", flush=True)

    # ВАЖНО: пустое наблюдение — это НЕ «потеряли всё». Мир при серверной проблеме отдаёт
    # `observation = {}` и `truncated = True` (freeciv_base_env.py:146), и тогда итог читается как
    # «0 городов, 0 юнитов». Поэтому различаем явно: конец партии, обрыв и пустое наблюдение.
    return {"seed": seed, "port": port, "ходов_сыграно": played, "счёт": me.get("score"),
            "городов": len(cities), "юнитов": len(units),
            "золото": me.get("gold"), "наука_баллов": me.get("bulbs_researched"),
            "действий": actions, "ходов_без_действия": turns_without_action,
            "партия_окончена": bool(terminated), "обрыв": bool(truncated),
            "наблюдение_пустое": not bool(obs)}


def main() -> int:
    growth = os.environ.get("V2_GROWTH", str(ROOT / "knowledge" / "city_growth.jsonl"))
    agent = Agent(STORE, trace_path=TRACE, avoid=wedges.is_wedged, growth_path=growth)
    print(f"[агент] база: {STORE}; трасса: {TRACE}")
    print(agent.store.report(limit=5))

    results = []
    for i, seed in enumerate(SEEDS):
        port = PORT_BASE + i
        print(f"\n===== партия {i + 1}: сид {seed}, порт {port} =====", flush=True)
        r = play(agent, seed, port, TURNS)
        agent.end_game()
        results.append(r)
        print(f"  итог: {r}", flush=True)
        print(agent.store.report(limit=0))

    print("\n===== сверка «объявлено ↔ использовано» =====")
    print(" ", agent.journal.counters())
    print("\n===== эффекты, добытые агентом =====")
    for k, v in sorted(agent.store.graph.effects.items()):
        cc = ", ".join(f"{a}:{b}" for a, b in sorted((v.get("change_counts") or {}).items())[:6])
        print(f"  {k}: наблюдено {v.get('seen')} раз — {cc}")
    print("\n===== партии =====")
    for r in results:
        print(" ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())