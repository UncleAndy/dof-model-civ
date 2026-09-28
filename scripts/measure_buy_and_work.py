#!/usr/bin/env python
"""Цены двух семейств, которых у прогноза нет: покупка производства и клетки города.

Что измеряется и зачем. Серия A (§10.24.1) показала: различие движков не в выборе из
доступного, а в САМОМ НАБОРЕ действий — прежний путь пользуется `city_buy_production`
(покупка за золото) и `city_work`/`city_unwork` (распоряжение клетками), а у прогноза
таких семейств нет. Чтобы добавить их, нужна цена: не «на глаз», а из полей мира и с
проверкой на живом городе.

ГИПОТЕЗЫ ОБЪЯВЛЕНЫ ДО ДАННЫХ:

  H_buy_1. Покупка завершает постройку НЕМЕДЛЕННО: срок становится 1 ход (или предмет
           появляется сразу), а золото падает на `buy_cost`.
  H_buy_2. Золото падает не на `buy_cost`, а на другую величину (тогда её надо вывести:
           кандидаты объявлены заранее — `buy_cost`, `buy_cost/2`, `2·buy_cost`,
           `buy_cost − накопленное`, `buy_cost − 2·shield_stock`).
  H_work_1. Перевод жителя меняет выход клеток города, и прирост опций города равен
           разнице формулы города до и после (`city_options(после) − city_options(до)`).
  H_work_0. Поля города после `city_work` не меняются (или приходят на след. ходу), то
           есть наблюдением это не проверяется — тогда семейство придётся оценивать
           иначе, и это тоже результат.

Порядок: по одному действию за ход, «после» читается на следующем ходу (город отдаёт
поля по событиям, и дозвон в том же ходу роняет контроллер — измерено ранее). Каждый шаг
с таймером, строки пишутся сразу.

    python scripts/measure_buy_and_work.py --turns 40
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
    parser.add_argument("--turns", type=int, default=40)
    parser.add_argument("--out", default="buy_and_work.jsonl")
    parser.add_argument("--watch", type=int, default=3,
                        help="сколько ходов держать действие под наблюдением")
    parser.add_argument("--buy-limit", dest="buy_limit", type=int, default=3,
                        help="сколько покупок сделать за матч")
    parser.add_argument("--work-limit", dest="work_limit", type=int, default=8,
                        help="сколько переводов жителей сделать за матч")
    parser.add_argument("--no-buy", dest="no_buy", action="store_true",
                        help="не трогать производство вовсе (чистый замер клеток: покупка "
                             "и постановка очереди меняют состояние города и пачкают "
                             "дельту перевода жителя)")
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
    from env.entity_extractor import city_options

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs = info = None
    for _attempt in range(5):
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

    rows = []

    def emit(row):
        rows.append(row)
        with open(args.out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def number(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def player(obs):
        """Запись игрока по ЗНАЧЕНИЯМ, а не по ключу: живьём ключи целые."""
        best = None
        for rec in (obs.get("player") or {}).values():
            if not isinstance(rec, dict):
                continue
            if rec.get("is_me"):
                return rec
            if best is None:
                best = rec
        return best or {}

    def cities(obs):
        out = {}
        for rec in (obs.get("city") or {}).values():
            if isinstance(rec, dict) and rec.get("id") is not None:
                out[str(rec.get("id"))] = rec
        return out

    def offered_for(pool, entity_id):
        """(ключ актёра, предложения) — ключ возвращаем ТЕМ ЖЕ типом, что в меню.

        Ловушка провода: живьём ключи актёров целые (`121`), и `env.step` с ключом-
        строкой падает `KeyError: '121'` — собственный замер это и поймал. Поэтому
        актёра для провода берём из самого меню, а не из наших строковых ключей.
        """
        bare = str(entity_id).split("_", 1)[-1]
        for key, acts in (pool or {}).items():
            if str(key) == bare:
                return key, (acts if isinstance(acts, dict) else {})
        return None, {}

    def snapshot(rec, player_rec):
        try:
            options = round(float(city_options(rec)), 4)
        except Exception:  # noqa: BLE001
            options = None
        return {
            "size": rec.get("size"),
            "prod_food": rec.get("prod_food"), "prod_shield": rec.get("prod_shield"),
            "prod_trade": rec.get("prod_trade"),
            "surplus_food": rec.get("surplus_food"),
            "surplus_shield": rec.get("surplus_shield"),
            "surplus_trade": rec.get("surplus_trade"),
            "shield_stock": rec.get("shield_stock"),
            "prod_process": rec.get("prod_process"),
            "turns_to_prod_complete": rec.get("turns_to_prod_complete"),
            "buy_cost": rec.get("buy_cost"),
            "gold": player_rec.get("gold"),
            "options": options,
        }

    pending = []
    issued = {"buy": 0, "work": 0, "prime": 0, "unwork": 0}
    tile_state: dict = {}
    menu_logged = 0
    founded = None
    for turn in range(args.turns):
        cities_now = cities(obs)
        if founded is None and cities_now:
            founded = next(iter(cities_now))
            print(f"город {founded} основан на ходу {turn}", flush=True)

        player_rec = player(obs)
        # 1) отложенное «после»: читаем НЕСКОЛЬКО ходов подряд (город отдаёт поля по
        #    событиям, и один снимок может прийти до того, как покупка разрешится).
        for item in list(pending):
            kind, cid, name, before = item["kind"], item["city"], item["name"], item["before"]
            rec = cities_now.get(str(cid))
            if rec is None:
                if turn - item["at_turn"] >= args.watch + 2:
                    pending.remove(item)
                continue
            after = snapshot(rec, player_rec)
            row = {"kind": kind, "turn": turn, "city": str(cid), "action": name,
                   "since": turn - item["at_turn"]}
            row.update({f"before_{k}": v for k, v in before.items()})
            row.update({f"after_{k}": v for k, v in after.items()})
            row["delta_options"] = (None if before.get("options") is None
                                    or after.get("options") is None
                                    else round(after["options"] - before["options"], 4))
            row["gold_spent"] = (None if before.get("gold") is None
                                 or after.get("gold") is None
                                 else round(number(before["gold"]) - number(after["gold"]), 1))
            emit(row)
            print(f"  ход {turn}: {kind} {name} (+{row['since']}) → опции "
                  f"{before.get('options')} → {after.get('options')} "
                  f"(Δ{row['delta_options']}), золото {before.get('gold')} → "
                  f"{after.get('gold')} (потрачено {row['gold_spent']}), срок "
                  f"{after.get('turns_to_prod_complete')}", flush=True)
            if turn - item["at_turn"] >= args.watch:
                pending.remove(item)

        # 2) Держава без города: сначала основать. Без действий мир не шлёт пакетов о
        #    городе (§5.2e) — измерено: прибор прошёл 12 ходов и записал 0 строк, потому
        #    что ждал город, которого наблюдение не отдавало.
        if founded is None:
            for uid, acts in ((info.get("available_actions") or {})
                              .get("unit") or {}).items():
                if isinstance(acts, dict) and acts.get("build_city"):
                    try:
                        signal.setitimer(signal.ITIMER_REAL, 20)
                        obs, _r, term, trunc, info = env.step(
                            ("unit", uid, "build_city"))
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    except Exception:  # noqa: BLE001
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    break
            cities_now = cities(obs)
            if cities_now:
                founded = next(iter(cities_now))
                print(f"город {founded} основан на ходу {turn}", flush=True)

        # 3) одно действие за ход: сначала покупка (её эффект сильнее), потом клетки.
        if not pending and founded is not None:
            _pool = ((info.get("available_actions") or {}).get("city") or {})
            if turn <= 4 and not _pool:
                print(f"  [диагностика] ход {turn}: в меню города пусто; контроллеры: "
                      f"{ {k: len(v) if hasattr(v, '__len__') else '?' for k, v in (info.get('available_actions') or {}).items()} }",
                      flush=True)
            wire_actor, offered = offered_for(_pool, founded)
            # Запись города может НЕ прийти в этом наблюдении (пакеты по событиям,
            # §5.2e) — действуем по МЕНЮ, а снимок берём, когда он есть: иначе прибор
            # молчит ровно тогда, когда мир ничего не изменил.
            rec = cities_now.get(str(founded)) or {}
            if offered and wire_actor is not None:
                # Журнал меню: без него «city_work не предлагался» не отличить от
                # «предлагался, но мы его не увидели». Печатаем редко.
                work_now = sorted(n for n in offered if n.startswith("city_"))
                valid_work = [n for n in offered if n.startswith("city_work_")
                              and offered.get(n)]
                valid_unwork = [n for n in offered if n.startswith("city_unwork_")
                                and offered.get(n)]
                if menu_logged < 60:
                    menu_logged += 1
                    emit({"kind": "menu", "turn": turn, "city": str(founded),
                          "actions": sorted(offered), "city_actions": work_now,
                          "valid_city_work": len(valid_work),
                          "valid_city_unwork": len(valid_unwork),
                          "valid_city_work_names": valid_work[:4],
                          "turns_left": rec.get("turns_to_prod_complete"),
                          "buy_cost": rec.get("buy_cost"),
                          "gold": player_rec.get("gold"),
                          "size": rec.get("size"), "stage": tile_state.get("stage")})
                    print(f"  ход {turn}: меню {len(offered)}, годных city_work "
                          f"{len(valid_work)}, city_unwork {len(valid_unwork)}, размер "
                          f"{rec.get('size')}", flush=True)
                # Покупка — только когда есть что покупать: при `срок == 1` покупать
                # нечего, и такая «покупка» ничего не измеряет (это был первый заход).
                something_to_buy = False
                try:
                    something_to_buy = number(rec.get("turns_to_prod_complete"), 0) > 1
                except Exception:  # noqa: BLE001
                    something_to_buy = False
                if args.no_buy:
                    something_to_buy = False
                if not something_to_buy and not args.no_buy and issued["prime"] < 3 \
                        and offered.get("produce_Settlers"):
                    # Покупать нечего: ставим ДЛИННУЮ постройку, чтобы было что покупать.
                    # Settlers стоит 40 щитов (измерено) — при 5 щитах/ход это 8 ходов.
                    try:
                        signal.setitimer(signal.ITIMER_REAL, 20)
                        obs, _r, term, trunc, info = env.step(
                            ("city", wire_actor, "produce_Settlers"))
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    except Exception as exc:  # noqa: BLE001
                        signal.setitimer(signal.ITIMER_REAL, 0)
                        emit({"kind": "prime_err", "turn": turn, "city": str(founded),
                              "error": f"{type(exc).__name__}: {exc}"})
                        issued["prime"] = 3
                    else:
                        issued["prime"] += 1
                        emit({"kind": "prime", "turn": turn, "city": str(founded),
                              "action": "produce_Settlers"})
                        print(f"  ход {turn}: поставлены Settlers, чтобы было что "
                              f"покупать", flush=True)
                if offered.get("city_buy_production") and issued["buy"] < args.buy_limit \
                        and something_to_buy:
                    name = "city_buy_production"
                    before = snapshot(rec, player_rec)
                    try:
                        signal.setitimer(signal.ITIMER_REAL, 20)
                        obs, _r, term, trunc, info = env.step(("city", wire_actor, name))
                        signal.setitimer(signal.ITIMER_REAL, 0)
                    except Exception as exc:  # noqa: BLE001
                        signal.setitimer(signal.ITIMER_REAL, 0)
                        emit({"kind": "buy_err", "turn": turn, "city": str(founded),
                              "action": name, "error": f"{type(exc).__name__}: {exc}"})
                        print(f"  ПОКУПКА не вернулась: {type(exc).__name__}: {exc}",
                              flush=True)
                        issued["buy"] = args.buy_limit
                    else:
                        issued["buy"] += 1
                        emit({"kind": "buy_post", "turn": turn, "city": str(founded),
                              "action": name, **{f"at_{k}": v for k, v in before.items()}})
                        pending.append({"kind": "buy", "city": founded, "name": name,
                                        "before": before, "at_turn": turn})
                        print(f"  ход {turn}: покупка отправлена (щиты "
                              f"{before.get('shield_stock')}, срок "
                              f"{before.get('turns_to_prod_complete')}, buy_cost "
                              f"{before.get('buy_cost')}, золото {before.get('gold')})",
                              flush=True)
                elif issued["work"] < args.work_limit:
                    # Перевод жителя делается ПАРОЙ: `city_work_*` валиден только когда
                    # житель не занят, поэтому сначала снимаем (`city_unwork_*`, он и
                    # есть единственный годный), на следующем ходу ставим на другую
                    # клетку. Измерено: годных city_work ровно 0 на каждом ходу, годных
                    # city_unwork — ровно 1 (та клетка, что занята сейчас).
                    valid_unwork = sorted(n for n in offered
                                          if n.startswith("city_unwork_") and offered.get(n))
                    valid_work = sorted(n for n in offered
                                        if n.startswith("city_work_") and offered.get(n))
                    if tile_state.get("stage") is None and valid_unwork:
                        name = valid_unwork[0]
                        tile_state = {"stage": "unworked", "tile": name,
                                      "before": snapshot(rec, player_rec),
                                      "turn": turn}
                        post = "unwork"
                    elif tile_state.get("stage") == "unworked" and valid_work:
                        # Берём ДРУГУЮ клетку, а не ту же: иначе «перевод» ничего не
                        # меняет и мерит только шум (первый заход так и сделал).
                        # Сравниваем ПО КЛЕТКЕ (суффикс `_<dx>_<dy>`), а не по имени:
                        # у снятия префикс `city_unwork_`, у постановки `city_work_`,
                        # и сравнение полных имён всегда «разное».
                        same_suffix = str(tile_state.get("tile", "")).split("city_unwork_")[-1]
                        others = [n for n in valid_work
                                  if n.split("city_work_")[-1] != same_suffix] or valid_work
                        # Предпочитаем клетку с наибольшим выходом: интepесен случай,
                        # где формула города обязана отреагировать заметно.
                        def tile_score(action_name):
                            parts = action_name.split("_")
                            try:
                                dx, dy = int(parts[-2]), int(parts[-1])
                            except (TypeError, ValueError):
                                return 0.0
                            cx, cy = number(rec.get("x"), 0), number(rec.get("y"), 0)
                            layer = (obs.get("map") or {}).get("output")
                            try:
                                cell = layer[int(cx + dx)][int(cy + dy)]
                                return sum(float(v) for v in list(cell)[:3])
                            except Exception:  # noqa: BLE001
                                return 0.0
                        name = max(others, key=tile_score)
                        post = "work"
                        try:
                            tile_state["tile_to"] = name
                            tile_state["tile_to_output"] = tile_score(name)
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        name = None
                        post = None
                    if name is not None:
                        try:
                            signal.setitimer(signal.ITIMER_REAL, 20)
                            obs, _r, term, trunc, info = env.step(
                                ("city", wire_actor, name))
                            signal.setitimer(signal.ITIMER_REAL, 0)
                        except Exception as exc:  # noqa: BLE001
                            signal.setitimer(signal.ITIMER_REAL, 0)
                            emit({"kind": "work_err", "turn": turn, "city": str(founded),
                                  "action": name, "error": f"{type(exc).__name__}: {exc}"})
                            print(f"  КЛЕТКИ не вернулись: {type(exc).__name__}: {exc}",
                                  flush=True)
                            issued["work"] = args.work_limit
                        else:
                            emit({"kind": f"{post}_post", "turn": turn,
                                  "city": str(founded), "action": name,
                                  **{f"at_{k}": v for k, v in
                                     tile_state.get("before", {}).items()}})
                            print(f"  ход {turn}: {name} отправлено ({post}; еда "
                                  f"{tile_state['before'].get('prod_food')}, щиты "
                                  f"{tile_state['before'].get('prod_shield')}, опции "
                                  f"{tile_state['before'].get('options')})", flush=True)
                            if post == "unwork":
                                issued["unwork"] = issued.get("unwork", 0) + 1
                            else:
                                issued["work"] += 1
                                pending.append({"kind": "pair", "city": founded,
                                                "name": name,
                                                "before": tile_state.get("before", {}),
                                                "at_turn": turn})
                                tile_state = {}

        try:
            signal.setitimer(signal.ITIMER_REAL, 30)
            obs, _r, term, trunc, info = env.step(None)
            signal.setitimer(signal.ITIMER_REAL, 0)
        except Exception as exc:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            emit({"kind": "endturn-err", "turn": turn,
                  "error": f"{type(exc).__name__}: {exc}"})
            print(f"  конец хода {turn} не прошёл: {type(exc).__name__}: {exc}", flush=True)
            break
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    print(f"\nстрок записано: {len(rows)} → {args.out}", flush=True)
    print(f"покупок отправлено: {issued['buy']}, постановок клеток: {issued['work']}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
