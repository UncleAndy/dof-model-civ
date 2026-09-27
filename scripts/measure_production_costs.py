#!/usr/bin/env python
"""Сколько ходов занимает производство и откуда это видно?

Подключать производство в прогноз нужно по числам мира, а не подставляя «один ход»
вместо расчёта. В записи города есть `prod_shield` (щиты за ход), `prod_process`
(доля готовности), `shield_stock` (накоплено) и `turns_to_prod_complete`.

ПРАВИЛО — ИЗМЕРЕНО (не выведено в уме), сверено с серверным `turns_to_prod_complete`:

    стоимость = shield_stock / prod_process        # prod_process = готовность, доля
    срок      = max(1, ceil((стоимость − shield_stock) / prod_shield))

Подтверждения (живой стенд, разные города): Settlers stock=3 proc=0.075 → 40 → 13=13;
Warriors stock=6 proc=0.6 → 10 → 2=2; Workers stock=9 proc=0.9 → 10 → 1=1;
Settlers stock=5 proc=0.125, щитов 5 → 40 → 7=7; Workers stock=5 proc=0.5 → 10 → 1=1.

Нижняя граница `max(1, …)` — отдельный замер: при `stock == стоимость` (Warriors:
stock=10, proc=1.0, стоимость 10) формула без границы даёт 0, а сервер отвечает
**1** — он считает и текущий ход.

ОТОЗВАНО: первая версия этого файла считала `стоимость = prod_shield / prod_process`
и проверяла её через `buy_cost` по формуле `осталось = (buy_cost − 2) / 2`. Оба
положения неверны: `buy_cost` даёт 73 при настоящей стоимости 40 (у достройки своё
правило, не выведено), а `prod_shield / prod_process` случайно совпал ровно потому,
что в том городе stock был равен prod_shield.

Замер СКЛАДЫВАЕТСЯ в склад измеренных фактов (`env/measured_facts.py`), потому что
срок производства нельзя вывести из наблюдения — его можно только измерить, а
измеренное должно использоваться дальше, а не оставаться строкой в логе.

    python scripts/measure_production_costs.py --types Settlers Warriors Workers
    python scripts/measure_production_costs.py --improvements Granary Temple
"""
import argparse
import json
import math
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)

from env.measured_facts import MeasuredFacts  # noqa: E402

PROBE_UNITS = ("Settlers", "Warriors", "Workers", "Explorers", "Phalanx", "Horsemen")
PROBE_IMPROVEMENTS = ("Granary", "Temple", "Barracks", "Library")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=40)
    parser.add_argument("--types", nargs="*", default=list(PROBE_UNITS),
                        help="типы юнитов для замера")
    parser.add_argument("--improvements", nargs="*", default=[],
                        help="улучшения для замера (у них поля приходят позже)")
    parser.add_argument("--out", default="production_costs.jsonl")
    parser.add_argument("--facts", default=None,
                        help="путь склада измеренных фактов")
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

    facts = MeasuredFacts(args.facts)

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

    #: Очередь проб: (имя, вид). Юниты и улучшения мерятся одинаково, различается
    #: только ярлык вида — он и уходит в склад.
    queue = [(name, "unit") for name in args.types]
    queue += [(name, "improvement") for name in args.improvements]

    rows = []

    def emit(row):
        rows.append(row)
        with open(args.out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def offered_for(pool, entity_id):
        """Предложения актёра. Ключ бывает и строкой, и числом — сравниваем по str.

        Проверено: `.get(str(city_id))` не находит предложения, потому что ключ
        приходит целым, и замер молча записал 0 строк.
        """
        bare = str(entity_id).split("_", 1)[-1]
        for key, acts in (pool or {}).items():
            if str(key) == bare:
                return acts if isinstance(acts, dict) else {}
        return {}

    def city_actions(info):
        return ((info.get("available_actions") or {}).get("city") or {})

    def unit_actions(info):
        return ((info.get("available_actions") or {}).get("unit") or {})

    def snapshot(obs, cid):
        rec = (obs.get("city") or {}).get(cid)
        if not isinstance(rec, dict):
            rec = next((c for c in (obs.get("city") or {}).values()
                        if isinstance(c, dict) and str(c.get("id")) == str(cid)), {})
        shields = rec.get("prod_shield")
        process = rec.get("prod_process")
        stock = rec.get("shield_stock")
        turns = rec.get("turns_to_prod_complete")
        cost = None
        try:
            if stock is not None and process:
                cost = float(stock) / float(process)
        except Exception:  # noqa: BLE001
            cost = None
        expected = None
        try:
            if cost and shields:
                # Нижняя граница 1: при `stock == стоимость` сервер отвечает
                # «1 ход» (измерено), то есть срок не бывает нулевым.
                expected = max(1, math.ceil(max(0.0, cost - float(stock or 0))
                                            / float(shields)))
        except Exception:  # noqa: BLE001
            expected = None
        return {"city": str(cid), "production_kind": rec.get("production_kind"),
                "prod_shield": shields, "prod_process": process,
                "shield_stock": stock, "turns_to_prod_complete": turns,
                "buy_cost": rec.get("buy_cost"),
                "cost_from_process": None if cost is None else round(cost, 3),
                "cost_from_buy": None,
                "turns_expected": expected}

    founded = None
    probed_any = False
    pending = None      # проба, у которой поля производства приходят на след. ходу
    for turn in range(args.turns):
        cities = obs.get("city") or {}
        if founded is None and cities:
            founded = next(iter(cities.keys()))
            print(f"город {founded} основан на ходу {turn}", flush=True)

        # Добор отложенной пробы: ход уже сменился обычным `env.step(None)`.
        if pending is not None and founded is not None:
            want, kind = pending
            pending = None
            row = snapshot(obs, founded)
            row.update({"kind": kind, "turn": turn, "wanted": want, "lag": "next turn"})
            emit(row)
            cost = row.get("cost_from_process")
            expected = row.get("turns_expected")
            server = row.get("turns_to_prod_complete")
            print(f"   {want:14s} ({kind:11s}, добор) → стоимость={cost} "
                  f"срок расчётный={expected} сервер={server}", flush=True)
            if cost and expected is not None and server is not None and expected == server:
                facts.observe_cost(want, cost, kind=kind, source="probe", turn=turn)
                facts.save()

        if founded is not None and queue:
            offered = offered_for(city_actions(info), founded)
            if offered:
                if not probed_any:
                    probed_any = True
                    have = [f"produce_{n}" for n, _k in queue if f"produce_{n}" in offered]
                    print(f"   предложений у города: {len(offered)}, "
                          f"из них наших типов: {len(have)} {have[:4]}", flush=True)
                for index, (want, kind) in enumerate(list(queue)):
                    name = f"produce_{want}"
                    if name not in offered:
                        continue
                    try:
                        obs, reward, term, trunc, info = env.step(
                            ("city", founded, name))
                    except Exception as exc:  # noqa: BLE001
                        emit({"kind": "err", "turn": turn, "wanted": want,
                              "error": f"{type(exc).__name__}: {exc}"})
                        queue.pop(index)
                        continue
                    row = snapshot(obs, founded)
                    if kind == "improvement" and row.get("prod_process") is None:
                        # Улучшения отдают поля производства только на следующем
                        # ходу. Второй `env.step(None)` здесь НЕЛЬЗЯ: он роняет
                        # контроллер (`server_timeout_handle`), проверено. Поэтому
                        # добор откладывается до начала следующего хода.
                        pending = (want, kind)
                        queue.pop(index)
                        break
                    row.update({"kind": kind, "turn": turn, "wanted": want})
                    emit(row)
                    print(f"   {want:14s} ({kind:11s}) → " + json.dumps(
                        {k: row.get(k) for k in
                         ("prod_shield", "prod_process", "shield_stock",
                          "turns_to_prod_complete", "cost_from_process",
                          "turns_expected")}, ensure_ascii=False), flush=True)
                    cost = row.get("cost_from_process")
                    if cost and row.get("turns_expected") is not None \
                            and row.get("turns_to_prod_complete") is not None:
                        agree = row["turns_expected"] == row["turns_to_prod_complete"]
                        print(f"        сверка: срок расчётный "
                              f"{row['turns_expected']} vs сервер "
                              f"{row['turns_to_prod_complete']} — "
                              f"{'СОВПАЛО' if agree else 'РАСХОЖДЕНИЕ'}", flush=True)
                        if agree:
                            facts.observe_cost(want, cost, kind=kind, source="probe",
                                               turn=turn)
                            facts.save()   # сразу: падение прогона не должно
                                           # уносить уже сделанный замер
                    queue.pop(index)
                    break
            if not queue:
                break

        for uid, acts in unit_actions(info).items():
            if isinstance(acts, dict) and acts.get("build_city"):
                try:
                    obs, reward, term, trunc, info = env.step(
                        ("unit", uid, "build_city"))
                except Exception:  # noqa: BLE001
                    pass
                break

        obs, reward, term, trunc, info = env.step(None)
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    facts.save()
    print(f"\nстрок записано: {len(rows)} → {args.out}", flush=True)
    print(f"склад фактов: {json.dumps(facts.summary(), ensure_ascii=False)}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
