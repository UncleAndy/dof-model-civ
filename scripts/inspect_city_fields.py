#!/usr/bin/env python
"""Какие числа о городе и производстве отдаёт мир?

Нужно, чтобы подключить производство **по числам мира**, а не подставлять «один
ход» вместо расчёта. Вопросы:

1. Есть ли в записи города стоимость и срок текущего производства
   (`production_kind`, `production_value`, `turns_to_prod_complete`, `prod_shield`)?
2. Что несут предложенные действия `produce_*` — есть ли в параметрах стоимость
   типа или срок?
3. Виден ли каталог типов юнитов со стоимостью (`type_build_cost`) помимо живых
   юнитов?

Печатает сырые поля и останавливается: ничего не додумывает.

    python scripts/inspect_city_fields.py --turns 8
"""
import argparse
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=8)
    args = parser.parse_args()

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
            signal.alarm(0)
            break
        except Exception as exc:  # noqa: BLE001
            signal.alarm(0)
            print(f"  не поднялся: {type(exc).__name__}", flush=True)
            time.sleep(3)
    if obs is None:
        raise SystemExit(5)

    def city_actions(info):
        return ((info.get("available_actions") or {}).get("city") or {})

    def unit_actions(info):
        return ((info.get("available_actions") or {}).get("unit") or {})

    seen_city = None
    for turn in range(args.turns):
        cities = obs.get("city") or {}
        if cities and seen_city is None:
            cid, rec = next(iter(cities.items()))
            seen_city = cid
            print(f"\n=== город {cid}: ключи записи", flush=True)
            if isinstance(rec, dict):
                print(sorted(rec.keys()), flush=True)
                print("\nполные значения (обрезано):", flush=True)
                for key, value in rec.items():
                    print(f"   {key} = {json.dumps(value, default=str)[:200]}",
                          flush=True)
            else:
                print(f"   (не словарь: {type(rec).__name__} {rec!r})", flush=True)

            print("\n=== предложенные действия по городам (все):", flush=True)
            for key, acts in city_actions(info).items():
                if not isinstance(acts, dict):
                    print(f"   city {key}: {acts!r}", flush=True)
                    continue
                print(f"   city {key}: {sorted(acts.keys())}", flush=True)
                # ВАЖНО: значения параметров. Валидность = непустые параметры
                # (так заведено в проекте для unit-действий), и если у `produce_*`
                # значения `false`, то фильтр валидности выбросит ВСЁ производство.
                produce = {name: params for name, params in acts.items()
                           if name.startswith("produce_")}
                print(f"      всего `produce_*`: {len(produce)}; "
                      f"с непустыми параметрами: "
                      f"{sum(1 for p in produce.values() if p)}", flush=True)
                for name, params in list(produce.items())[:5]:
                    print(f"      {name} → params={params!r}", flush=True)
                for name, params in list(acts.items())[:3]:
                    print(f"      {name} → {json.dumps(params, default=str)[:120]}",
                          flush=True)
            print("\n=== действие по умолчанию/текущее производство (если есть):",
                  flush=True)

        # Основываем город, если предлагают: без города запись города не появится.
        for uid, acts in unit_actions(info).items():
            if isinstance(acts, dict) and acts.get("build_city"):
                try:
                    obs, reward, term, trunc, info = env.step(
                        ("unit", uid, "build_city"))
                except Exception as exc:  # noqa: BLE001
                    print(f"   build_city не прошёл: {type(exc).__name__}", flush=True)
                break

        # Раз предложение по городу появилось — печатаем и останавливаемся.
        if seen_city is not None and city_actions(info):
            print(json.dumps({k: (sorted(v.keys()) if isinstance(v, dict) else v)
                              for k, v in city_actions(info).items()},
                             ensure_ascii=False, default=str)[:1500], flush=True)
            shots = [name for acts in city_actions(info).values()
                     if isinstance(acts, dict) for name in acts]
            print(f"\nвсего предложений по городу: {len(shots)}", flush=True)
            units = obs.get("unit") or {}
            print("\n=== есть ли стоимость типа у живых юнитов:", flush=True)
            for uid, u in list(units.items())[:3]:
                if isinstance(u, dict):
                    print(f"   unit {uid}: " + json.dumps(
                        {k: v for k, v in u.items()
                         if "cost" in k.lower() or "build" in k.lower()
                         or "shield" in k.lower()}, default=str)[:300], flush=True)
            break

        obs, reward, term, trunc, info = env.step(None)
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    print("\n=== ключи наблюдения:", sorted(obs.keys()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
