#!/usr/bin/env python
"""Сверка прогноза города на площадке с фактом: основали — сравнили.

Прогноз считается ДО основания по площадке под носителем (те же 21 клетка,
та же формула города). Затем игра основывает город этим носителем, и мы смотрим
настоящий город. Ошибка прогноза — единственный честный критерий: если формула
и площадка верны, прогноз должен попасть близко, а не на +170%, как когда
прогноз был константой 3.0.

    python scripts/validate_site_prediction.py
"""
import argparse
import os
import signal
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


class MatchTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise MatchTimeout("match exceeded budget")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--turns", type=int, default=4)
    args = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    from env.entity_extractor import GameStateExtractor, is_population_carrier, truthy

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(500)
    try:
        from civrealm.freeciv.utils.port_utils import Ports
        import gymnasium
        from civrealm.configs import fc_args

        port = Ports.get()
        print(f"slot: {port}", flush=True)
        fc_args["client_port"] = port
        env = gymnasium.make("civrealm/FreecivBase-v0")
        obs, info = env.reset(client_port=port)

        ex = GameStateExtractor(my_player_id=0)
        result = ex.extract(obs, info, info.get("turn", 1))
        bridge = result.state.bridge

        print("\n=== ПРОГНОЗ ПО ПЛОЩАДКЕ (до основания) ===")
        print(f"  средняя оценка империи (старая): {bridge.new_city_options:.3f} опции")
        for uid, opts in bridge.new_city_options_by_unit.items():
            rep = bridge.site_report.get(uid, {})
            print(f"  {uid}: город на площадке = {opts:.3f} опции "
                  f"(еда {rep.get('food')}, гейт {'ок' if rep.get('viable') else 'НЕТ'}, "
                  f"размер на 15-м ходу {rep.get('size_at_horizon')}, "
                  f"задержка {rep.get('delay_per_turn')}/ход)")
        for uid in bridge.nonviable_carrier_sites:
            print(f"  {uid}: площадка НЕ прошла гейт — основание вырезано: "
                  f"{bridge.site_report.get(uid, {}).get('reason')}")

        # Ищем build_city у носителя и основываем город.
        predicted = None
        target = None
        avail = info.get("available_actions") or {}
        for actor_id, actions in (avail.get("unit") or {}).items():
            for name, params in actions.items():
                if name.startswith("build_city") and params:
                    target = actor_id
                    break
            if target is not None:
                break
        unit_obs = (obs.get("unit") or {}).get(str(target))
        entity_id = f"unit_{target}"
        predicted = bridge.new_city_options_by_unit.get(entity_id)
        if predicted is not None:
            print(f"\nосновываем город носителем {target} (прогноз {predicted:.3f})")
            obs, _r, term, trunc, info = env.step(("unit", target, "build_city"))
        else:
            print(f"\nноситель {target}: площадка вырезана гейтом, основание не делаем")

        # Смотрим, что получилось в мире.
        after = ex.extract(obs, info, info.get("turn", 1))
        cities = {cid: c for cid, c in (obs.get("city") or {}).items() if isinstance(c, dict)}
        print("\n=== ФАКТ В МИРЕ ===")
        for cid, c in cities.items():
            owner = c.get("owner")
            if owner is not None and int(owner) != 0:
                continue
            ent = after.state.entities.get(f"city_{cid}")
            dof = ent.dof_count if ent else None
            # `improvements` приходит numpy-массивом: `or` на нём бросает
            # ValueError, поэтому проверяем на None явно.
            imps = c.get('improvements')
            n_imps = sum(1 for v in (imps if imps is not None else []) if truthy(v))
            print(f"  city_{cid}: size={c.get('size')} owner={owner} "
                  f"surplus_food={c.get('surplus_food')} surplus_shield={c.get('surplus_shield')} "
                  f"surplus_trade={c.get('surplus_trade')} "
                  f"improvements={n_imps} "
                  f"-> DoF={dof if dof is None else round(dof, 4)}")
            if predicted is not None and dof:
                err = dof - predicted
                print(f"     прогноз {predicted:.4f} против факта {dof:.4f}: "
                      f"ошибка {err:+.4f} ({100 * err / max(abs(predicted), 1e-9):+.1f}%)")
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    import traceback

    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"ERR: {type(exc).__name__}: {exc}")
        raise SystemExit(3)
