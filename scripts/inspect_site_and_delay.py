#!/usr/bin/env python
"""Живой прогон: оценка площадки носителей + цена задержки (фактор (б)).

Печатает по каждому носителю (Settlers/Engineers) площадку вокруг него:
еда/щиты/торговля лучших size+1 клеток, гейт качества, излишек, размер города
на горизонте 15 ходов, цену задержки в опт./ход — и показывает рост системного
стока по ходам (то, чего не было при плоском прокси 0.02/ход).

    python scripts/inspect_site_and_delay.py --turns 6
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
    p.add_argument("--turns", type=int, default=6)
    p.add_argument("--max-decisions", type=int, default=10)
    args = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    os.environ["PYTHONWARNINGS"] = "ignore"

    from env.entity_extractor import GameStateExtractor, is_population_carrier
    from env.site_eval import (counterfactual_growth_sink_per_turn, evaluate_site,
                               size_at_horizon)

    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(600)
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
        vals = dict(ex.model.values())
        if "rules.food_cost" in vals:
            vals["FOOD_COST"] = vals["rules.food_cost"]
        print(f"vals: FOOD_COST={vals.get('FOOD_COST')} W_GROWTH={vals.get('W_GROWTH')} "
              f"DOF_SCALE={vals.get('DOF_SCALE')} SITE_MIN_FOOD={vals.get('SITE_MIN_FOOD')} "
              f"floor={vals.get('UNDEPLOYED_CARRIER_SINK_PER_TURN')}")

        map_obs = obs.get("map") or {}
        carriers = {uid: u for uid, u in (obs.get("unit") or {}).items()
                    if isinstance(u, dict) and is_population_carrier(u)}
        print(f"\n=== ПЛОЩАДКИ НОСИТЕЛЕЙ (ход {info.get('turn')}) ===")
        for uid, u in carriers.items():
            site = evaluate_site(map_obs, int(u["x"]), int(u["y"]), size=1, vals=vals)
            rate = counterfactual_growth_sink_per_turn(site if site.viable else None, vals)
            size15, _ = size_at_horizon(site, turns=int(vals.get("GROWTH_HORIZON_TURNS", 15)))
            print(f"  unit {uid} @ ({int(u['x'])},{int(u['y'])}) "
                  f"еда={site.food:.1f} (диапазон {site.food_low:.1f}..{site.food_high:.1f}) "
                  f"щиты={site.shields:.1f} торг={site.trade:.1f} "
                  f"видимо {site.known_tiles}/{site.total_tiles} "
                  f"излишек={site.food_surplus:+.1f}")
            print(f"     гейт: viable={site.viable} ({site.reason}); "
                  f"еда гейта {site.gate_food:.1f} на {site.gate_size + 1} клетках; "
                  f"город на 15-м ходу был бы размера {size15}; "
                  f"цена задержки {rate:.3f} опт./ход "
                  f"({rate * 15:.2f} за 15 ходов)")

        print("\n=== СТОК ПО ХОДАМ (системный сток, опции) ===")
        # Куда идти: выигрыш от перехода к лучшей площадке в пределах хода.
        mover = ex.extract(obs, info, info.get("turn", 1)).state.bridge
        if mover.site_move_gain_by_unit:
            print("\n=== КУДА ИДТИ (выигрыш площадки, дисконтированный) ===")
            for uid, gain in mover.site_move_gain_by_unit.items():
                rep = mover.site_move_report.get(uid, {})
                tgt = rep.get("target") or {}
                print(f"  {uid}: сейчас {rep.get('current_value')} -> "
                      f"в ({tgt.get('target_x')},{tgt.get('target_y')}) "
                      f"{rep.get('best_value')}; сырой {rep.get('raw_gain')}, "
                      f"дисконт {gain:.3f} (ход {rep.get('reach')})")
        else:
            print("\n=== КУДА ИДТИ: выигрыша нет (стоять не хуже) ===")

        for t in range(args.turns):
            turn = info.get("turn")
            result = ex.extract(obs, info, turn)
            n_carriers = sum(1 for u in (obs.get("unit") or {}).values()
                             if isinstance(u, dict) and is_population_carrier(u))
            print(f"  turn {turn}: sink={result.state.dof_sink:.4f} "
                  f"entities={len(result.state.entities)} carriers={n_carriers}",
                  flush=True)
            decisions = 0
            while decisions < args.max_decisions:
                avail = info.get("available_actions") or {}
                chosen = None
                # Только перемещения/работы: проверенный паттерн (без произвольных
                # действий — те могут оборвать матч).
                prefixes = ("goto", "move", "road", "irrigate", "mine", "fortify")
                for ctrl in ("unit",):
                    for actor_id, actions in (avail.get(ctrl) or {}).items():
                        for name, params in actions.items():
                            if params and any(name.startswith(w) for w in prefixes):
                                chosen = (ctrl, actor_id, name)
                                break
                        if chosen:
                            break
                    if chosen:
                        break
                if chosen is None:
                    break
                obs, _r, term, trunc, info = env.step(chosen)
                decisions += 1
                if term or trunc:
                    break
            obs, _r, term, trunc, info = env.step(None)
            if term or trunc:
                print("  (игра окончена)")
                break
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
