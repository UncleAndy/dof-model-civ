"""Пробник: что мир публикует про срок постройки и когда он становится «неизвестен».

Задача (вопрос Andy по игре 9115): в тексте на кадре у городов появилось «срок неизвестен», хотя
ранее были нормальные значения. Нужно понять, ЧТО именно публикует мир в такие моменты.

Пишем по каждому шагу поля города в JSONL и отдельно печатаем строки, где срок отсутствует или
подозрительно велик (>= 1000), вместе с состоянием города (щиты, еда, довольство, что строится).
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import sys
from pathlib import Path

os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from baselines import wedges  # noqa: E402
from brain.v2.agent import Agent  # noqa: E402

STORE = os.environ.get("V2_STORE", str(ROOT / "knowledge" / "world_eta.json"))
TURNS = int(os.environ.get("V2_TURNS", "60"))
SEED = int(os.environ.get("V2_SEED", "9120"))
PORT = int(os.environ.get("V2_PORT", "6308"))
OUT = Path(os.environ.get("V2_OUT", str(ROOT / "knowledge" / "eta_probe.jsonl")))


class StepTimeout(Exception):
    pass


def _on_alarm(_sig, _frm):
    raise StepTimeout()


signal.signal(signal.SIGALRM, _on_alarm)


def main() -> int:
    fc_args["client_port"] = PORT
    agent = Agent(STORE, trace_path=ROOT / "knowledge" / "traces_eta.jsonl",
                  avoid=wedges.is_wedged)
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=PORT, seed=SEED)
    try:
        own_id = env.get_playerid() or 0
    except Exception:  # noqa: BLE001
        own_id = 0
    used: set = set()
    bad = good = 0
    shown_ok = 0
    with OUT.open("w") as fh:
        try:
            for _ in range(TURNS):
                for _ in range(8):
                    action = agent.decide(obs, info, own_id, used)
                    if action is None:
                        break
                    used.add((action[0], action[1]))
                    signal.setitimer(signal.ITIMER_REAL, 30)
                    try:
                        obs, _r, term, trunc, info = env.step(action)
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    agent.record_outcome(obs, own_id)
                    for cid, c in (obs.get("city") or {}).items():
                        if c.get("owner") != own_id:
                            continue
                        eta = c.get("turns_to_prod_complete")
                        cbu = c.get("can_build_unit")
                        cbu_list = list(cbu) if cbu is not None else []
                        row = {"ход": (info or {}).get("turn"), "город": c.get("name"), "cid": cid,
                               "размер": c.get("size"), "prod_kind": c.get("production_kind"),
                               "prod_value": c.get("production_value"), "срок": eta,
                               "щиты_запас": c.get("shield_stock"), "щиты_в_ход": c.get("prod_shield"),
                               "щиты_чистый": c.get("surplus_shield"),
                               "потери_щитов": c.get("city_waste"),
                               "еда": c.get("surplus_food"), "злые": c.get("ppl_angry"),
                               "недовольные": c.get("ppl_unhappy"), "довольные": c.get("ppl_content"),
                               "счастливые": c.get("ppl_happy"),
                               "разрешено_строить": sum(1 for v in cbu_list if bool(v))}
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        bad_eta = not isinstance(eta, int) or eta >= 1000
                        if bad_eta and bad < 12:
                            bad += 1
                            print("ПЛОХОЙ СРОК:", json.dumps(row, ensure_ascii=False), flush=True)
                        elif not bad_eta and good < 6:
                            good += 1
                            print("нормальный срок:", json.dumps(row, ensure_ascii=False), flush=True)
                        net = c.get("surplus_shield")
                        if isinstance(net, int) and net <= 0:
                            graph = getattr(getattr(agent, "store", None), "graph", None)
                            ce = graph.entity(f"city:{cid}") if graph is not None else None
                            if ce is not None and ce.dof is not None:
                                print(f"  ЗАСТОЙ ход {(info or {}).get('turn')}: DoF города "
                                      f"{ce.dof.v} (разрешено было {ce.attrs.get('n_produce_allowed')} "
                                      f"постр.); «{ce.dof.note}»", flush=True)
                        elif shown_ok < 4:
                            shown_ok += 1
                            graph = getattr(getattr(agent, "store", None), "graph", None)
                            ce = graph.entity(f"city:{cid}") if graph is not None else None
                            if ce is not None and ce.dof is not None:
                                print(f"  ИДЁТ ход {(info or {}).get('turn')}: DoF города {ce.dof.v} "
                                      f"(разрешено {ce.attrs.get('n_produce_allowed')} постр.); "
                                      f"«{ce.dof.note}»", flush=True)
                    if term or trunc:
                        break
                else:
                    pass
                if term or trunc:
                    break
                signal.setitimer(signal.ITIMER_REAL, 30)
                try:
                    obs, _r, term, trunc, info = env.step(None)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                agent.record_outcome(obs, own_id)
                used.clear()
                if term or trunc:
                    break
        except StepTimeout:
            print("  [клин] шаг не вернулся", flush=True)
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    print(f"\nзаписей: плохих {bad}, нормальных {good} (полный список в {OUT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())