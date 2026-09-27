#!/usr/bin/env python
"""Улучшения: предлагает ли их сервер и переживает ли матч их ПОСТАНОВКУ?

Что уже известно: `produce_<улучшение>` появляется в меню города, поля производства
у улучшения приходят `null`, а «дозвон» (второй `env.step` в том же ходу) роняет
контроллер (`AssertionError: server_timeout_handle == None`). Из этого НЕ следует,
что постановка улучшения убивает матч: раньше падал дозвон, а не постановка.

ГИПОТЕЗЫ ОБЪЯВЛЕНЫ ДО ДАННЫХ:

  H1. Постановка улучшения матч НЕ убивает: матч продолжает идти вперёд не меньше
      5 ходов после постановки, и `turns_to_prod_complete` у улучшения видно.
  H0. Постановка улучшения матч убивает или матч перестаёт двигаться.

Порог вердикта (задан ДО данных): H1 принимается, если хотя бы в ОДНОЙ постановке
матч прожил ≥5 ходов после неё и ход сменился; иначе H0 с названной причиной.

Побочно измеряется: сколько ходов нужно улучшению (сверка правила
`ceil((стоимость − stock) / prod_shield)`), появляется ли оно в списке `improvements`
города, и какие поля производства у него публикуются.

    python scripts/probe_improvement_family.py --turns 40
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
    parser.add_argument("--out", default="improvement_probe.jsonl")
    parser.add_argument("--watch", type=int, default=5,
                        help="сколько ходов наблюдать после постановки")
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

    def city_rec(obs, cid):
        rec = (obs.get("city") or {}).get(cid)
        if isinstance(rec, dict):
            return rec
        for value in (obs.get("city") or {}).values():
            if isinstance(value, dict) and str(value.get("id")) == str(cid):
                return value
        return {}

    def improvement_names(obs):
        """Имена улучшений из спецификаций технологий (`sup_improvements`)."""
        names = set()
        for rec in (obs.get("tech") or {}).values():
            if not isinstance(rec, dict):
                continue
            for spec in (rec.get("sup_improvements") or []):
                if isinstance(spec, dict):
                    name = str(spec.get("rule_name") or spec.get("name") or "")
                    if name:
                        names.add(name)
        return names

    def offered_for(pool, entity_id):
        bare = str(entity_id).split("_", 1)[-1]
        for key, acts in (pool or {}).items():
            if str(key) == bare:
                return acts if isinstance(acts, dict) else {}
        return {}

    improvements_seen = set()
    produce_logged = [False]
    posted = None          # (city_id, name, turn)
    watched = 0
    founded = None
    started_turn = None
    for turn in range(args.turns):
        turn_now = (info or {}).get("turn")
        if started_turn is None:
            started_turn = turn_now
        cities = obs.get("city") or {}
        if founded is None and cities:
            founded = next(iter(cities))
            print(f"город {founded} основан на ходу {turn}", flush=True)
        if founded is None:
            # Держава без города: ставим город поселенцем.
            for uid, acts in ((info.get("available_actions") or {})
                              .get("unit") or {}).items():
                if isinstance(acts, dict) and acts.get("build_city"):
                    try:
                        obs, _r, _t, _tr, info = env.step(
                            ("unit", uid, "build_city"))
                    except Exception:  # noqa: BLE001
                        pass
                    break

        names = improvement_names(obs)
        if names and not improvements_seen:
            improvements_seen = names
            print(f"улучшения в спецификациях: {len(names)} "
                  f"{sorted(names)[:8]}", flush=True)

        # 1) Добор наблюдения после постановки — БЕЗ дозвона в том же ходу.
        if posted is not None and founded is not None:
            cid, name, at_turn = posted
            watched += 1
            rec = city_rec(obs, cid)
            # Ловушка numpy: `rec.get("improvements") or []` падает, потому что
            # истинность МАССИВА неоднозначна. Проверяем на None, а не на «пусто».
            flags = rec.get("improvements")
            flags = list(flags) if flags is not None else []
            in_city = sum(1 for value in flags if bool(value))
            row = {"kind": "watch", "turn": turn, "city": str(cid), "wanted": name,
                   "since_post": watched, "turn_now": turn_now,
                   "prod_shield": rec.get("prod_shield"),
                   "prod_process": rec.get("prod_process"),
                   "shield_stock": rec.get("shield_stock"),
                   "turns_to_prod_complete": rec.get("turns_to_prod_complete"),
                   "improvements_count": in_city,
                   "err": None}
            emit(row)
            print(f"  наблюдение {watched} (ход {turn}): щиты={row['prod_shield']} "
                  f"готовность={row['prod_process']} срок={row['turns_to_prod_complete']} "
                  f"улучшений у города={row['improvements_count']}", flush=True)
            if watched >= args.watch:
                print(f"  ВЕРДИКТ по постановке: матч прожил {watched} ходов после "
                      f"неё, сбоя нет", flush=True)
                posted = None

        # 2) Постановка улучшения — ТОЛЬКО из того, что сервер предлагает сейчас.
        #    Урок этой же пробы: постановка имени из спецификаций, которого в меню
        #    нет (`produce_A.Smith's Trading Co.`), отвечает `Action ... is not
        #    valid` и роняет матч (`AssertionError` на конце хода). Список
        #    спецификаций — это «что вообще существует», а не «что доступно городу».
        if posted is None and founded is not None:
            offered = offered_for(((info.get("available_actions") or {})
                                   .get("city") or {}), founded)
            produce_names = [n for n in offered
                             if n.startswith("produce_") and offered.get(n)]
            if produce_names and not produce_logged[0]:
                produce_logged[0] = True
                print(f"  в меню города: {produce_names}", flush=True)
                emit({"kind": "menu", "turn": turn, "city": str(founded),
                      "produce": produce_names})
            want = next((n for n in sorted(produce_names)
                         if n[len("produce_"):] in improvements_seen), None)
            if want is not None:
                try:
                    signal.setitimer(signal.ITIMER_REAL, 20)
                    obs, _r, term, trunc, info = env.step(("city", founded, want))
                    signal.setitimer(signal.ITIMER_REAL, 0)
                except Exception as exc:  # noqa: BLE001
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    emit({"kind": "post", "turn": turn, "city": str(founded),
                          "wanted": want, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"  постановка {want} НЕ вернулась: "
                          f"{type(exc).__name__}: {exc}", flush=True)
                    posted = None
                    want = None
                if want is not None:
                    posted = (founded, want[len("produce_"):], turn)
                    watched = 0
                    rec = city_rec(obs, founded)
                    emit({"kind": "post", "turn": turn, "city": str(founded),
                          "wanted": want[len("produce_"):], "offered": want,
                          "prod_shield": rec.get("prod_shield"),
                          "prod_process": rec.get("prod_process"),
                          "shield_stock": rec.get("shield_stock"),
                          "turns_to_prod_complete": rec.get("turns_to_prod_complete")})
                    print(f"  поставлено: {want} (ход {turn}); поля сразу: щиты="
                          f"{rec.get('prod_shield')} готовность={rec.get('prod_process')} "
                          f"срок={rec.get('turns_to_prod_complete')}", flush=True)

        try:
            signal.setitimer(signal.ITIMER_REAL, 30)
            obs, _r, term, trunc, info = env.step(None)
            signal.setitimer(signal.ITIMER_REAL, 0)
        except Exception as exc:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            emit({"kind": "endturn-err", "turn": turn,
                  "error": f"{type(exc).__name__}: {exc}"})
            print(f"  конец хода {turn} не прошёл: {type(exc).__name__}: {exc}",
                  flush=True)
            break
        if term or trunc:
            print(f"  матч завершён на ходу {turn}", flush=True)
            break

    print(f"\nстрок записано: {len(rows)} → {args.out}", flush=True)
    posts = [r for r in rows if r.get("kind") == "post"]
    print(f"постановок: {len(posts)}; из них с ошибкой: "
          f"{sum(1 for r in posts if r.get('error'))}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
