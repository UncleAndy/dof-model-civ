#!/usr/bin/env python
"""Есть ли в наблюдении координаты цели движения?

`goto_N` в `available_actions` несёт только `true` — индекса в списке целей нет.
Но цель может лежать в самой записи юнита (поле вроде `goto`, `orders`, `target`).
От этого зависит конструкция прогноза: если цели видны, движение можно называть
конкретным действием; если нет — движение приходится оценивать как семейство с
абстрактным преемником («носитель ушёл на лучшую достижимую площадку»).

Печатает ключи и «координатные» поля юнита, затем останавливается.

    python scripts/inspect_unit_targets.py
"""
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main():
    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    def _on_alarm(signum, frame):
        raise TimeoutError("budget")

    signal.signal(signal.SIGALRM, _on_alarm)

    import gymnasium
    from civrealm.configs import fc_args
    from civrealm.freeciv.utils.port_utils import Ports

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs = info = None
    for attempt in range(5):
        port = Ports.get()
        print(f"слот {port}", flush=True)
        fc_args["client_port"] = port
        try:
            signal.alarm(90)
            obs, info = env.reset(client_port=port)
            signal.alarm(60)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  не поднялся: {type(exc).__name__}", flush=True)
            time.sleep(3)
    if obs is None:
        raise SystemExit(5)

    units = obs.get("unit") or {}
    print(f"юнитов в наблюдении: {len(units)}")
    for uid, u in list(units.items())[:2]:
        if not isinstance(u, dict):
            continue
        print(f"\n=== unit {uid}: ключи")
        print(sorted(u.keys()))
        print("координатные/целевые поля:")
        for key, value in u.items():
            low = key.lower()
            if any(tok in low for tok in ("x", "y", "goto", "order", "target",
                                          "dest", "pos", "activity", "moves")):
                print(f"   {key} = {json.dumps(value, default=str)[:160]}")

    print("\n=== доступные `goto_*` у юнитов:")
    for uid, acts in ((info.get("available_actions") or {}).get("unit") or {}).items():
        gotos = {k: v for k, v in acts.items() if k.startswith("goto_")}
        if gotos:
            print(f"   unit {uid}: {len(gotos)} вариантов, пример: "
                  f"{json.dumps(dict(list(gotos.items())[:3]), default=str)}")

    print("\n=== прочие ключи наблюдения:", sorted(obs.keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
