"""Сухой прогон решающего слоя: что ядро выбрало бы — БЕЗ отправки действий в мир.

Зачем отдельный скрипт. Владелец модели требует видеть рекомендованные числа **до** того, как модель
начнёт действовать. Здесь ровно это: мир играет сам, мы каждый ход считаем кандидатов, допустимость и
выбор ядром (`env.spec_options.decide` — ядро решает, драйвер платит) и **печатаем** результат. Действия
не отправляются: `env.step(None)`.

Проверяются сразу два состава решающих — «игрок + города» (как в проверках ветки) и «игрок + города +
юниты»: это выбор модели, и его надо видеть числами, а не решать за владельца.

Запуск (порт — свежий и свободный; слоты singleplayer 6000/6003):

    P=$PWD; SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
    PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP" PYTHONWARNINGS=ignore \
    .venv/bin/python scripts/v011_decide_probe.py --port 6000 --seed 9300 --turns 6
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env import spec_lenses as L  # noqa: E402
from env import spec_obs as SO  # noqa: E402
from env import spec_options as O  # noqa: E402
from env import spec_graph as G  # noqa: E402
from env.action_mapper import FOUNDING_ACTIONS, founding_delta  # noqa: E402
from env.dof_deltas import measured_delta_any_controller  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402
from brain.spec.calculus_core import DOFCalculusCore  # noqa: E402


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Сухой прогон решающего слоя v0.11")
    ap.add_argument("--port", type=int, default=int(os.environ.get("V011_PORT", "6000")))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("V011_SEED", "9300")))
    ap.add_argument("--turns", type=int, default=int(os.environ.get("V011_TURNS", "6")))
    ap.add_argument("--units", action="store_true",
                    help="включить юнитов в состав решающих (по умолчанию показываются оба состава)")
    return ap.parse_args()


def _decide_turn(obs: dict, info: dict, turn: Any, extractor: Any, prev_obs: Optional[dict],
                 own_id: int, core: Any, with_units: bool) -> dict[str, Any]:
    """Один сухой расчёт: кандидаты → допустимость → выбор ядром. В мир — ничего."""
    m = SO.measure_step(obs, info, turn, extractor, prev_obs=prev_obs, my_player_id=own_id)
    costs = SO.build_cost_index(obs)
    means = L.means_with_income(
        SO.empire_stocks(obs, own_id), SO.empire_incomes(obs, own_id),
        measured_tech_rate=L.measured_science_rate(prev_obs, obs, own_id))
    graph = G.world_graph(m["vectors"], m["fields"], m["dof"], catalogue=m["catalogue"],
                          known_techs=m["known_techs"], raw_menus=m["raw_menus"])
    ctx = G.observation_context(graph, m["dof"])
    st = G.state_with_measured_dof(m["state"], m["dof"])
    player_id = f"player_{own_id}"

    def remeasure(vecs, means2=None):
        """Пересчёт DoF при другом составе векторов — так считается прирост опции (§4.3)."""
        fresh = {}
        for eid, names in vecs.items():
            kind = L.entity_type_of(eid)
            names = list(names)
            fresh[eid] = L.lens_observation(
                variety=L.variety_counters(names, SO.disturbances(obs, eid, kind, own_id),
                                           SO.powers_of(obs, own_id)),
                requirements=(SO.city_requirements(m["fields"][eid], costs, names,
                                                   m["fields"][eid].get("prod_shield"))
                              if kind == "city" else {}),
                constraint=L.constraint_observation(kind, m["fields"][eid]),
            )
        return {eid: met.current_dof
                for eid, met in L.measure(fresh, means if means2 is None else means2).items()}

    deciders = [player_id] + sorted(e for e in m["vectors"] if e.startswith("city_"))
    if with_units:
        deciders += sorted(e for e in m["vectors"] if e.startswith("unit_"))
    production = {e: float(m["fields"][e].get("prod_shield") or 0.0)
                  for e in m["fields"] if e.startswith("city_")}
    standing = {e: float(m["fields"][e]["turns_to_prod_complete"])
                for e in m["fields"] if e.startswith("city_")
                and m["fields"][e].get("turns_to_prod_complete") is not None}
    st.deadlines = O.budget_deadlines(deciders)
    st.resources = O.resource_observations(means)
    tech = ((obs.get("player") or {}).get(str(own_id)) or {})
    # Источник ИЗМЕРЕННОГО прироста (§3.3): таблица живых замеров (у большинства действий
    # честный 0.0) + цена основания, считаемая НАШИМИ линзами в нормированных DoF.
    founding_rows: list[dict[str, Any]] = []

    def measured(eid: str, action: str) -> Optional[float]:
        name = str(action)
        if any(name.startswith(a) for a in FOUNDING_ACTIONS):
            # Нормированный прирост основания: DoF города размера 1 на клетке юнита минус
            # DoF самого поселенца. Обе величины — в тех же единицах, что и поле ядра (§3.3).
            # `founding_delta` из прежней стойки здесь НЕ годится: он считает в ШТУКАХ опций
            # (6.99), а поле ожидает нормированный DoF — это разные единицы, и подстановка
            # одной вместо другой даёт выдуманный мотив.
            made = _hypothetical_city_dof(eid)
            have = (m["dof"] or {}).get(str(eid))
            city_dof = None if made is None else made[0]
            if city_dof is None or have is None:
                founding_rows.append({
                    "unit": str(eid), "doF_поселенца": have, "doF_города": city_dof,
                    "прирост": None,
                    "причина": (made[1] if made is not None and len(made) > 1
                                else "нет клетки или каталога для счёта города")
                    if city_dof is None else "DoF поселенца не измерен",
                    "каталог_цен": len(costs or {})})
                return None
            value = float(city_dof) - float(have)
            founding_rows.append({"unit": str(eid), "doF_поселенца": float(have),
                                  "doF_города": float(made[0]), "прирост": value,
                                  "причина": made[1]})
            return value
        return measured_delta_any_controller(name)

    def _hypothetical_city_dof(uid: str) -> Optional[tuple[float, str]]:
        """DoF города размера 1 на клетке юнита, посчитанный НАШИМИ линзами.

        Меню города берётся из опубликованного каталога цен (разрешённое к постройке), выход
        щитов у будущего города неизвестен — и это не подставляется нулём: требование
        считается без него, а причина так и называет.
        """
        field = (m["fields"] or {}).get(str(uid)) or {}
        x, y = field.get("x"), field.get("y")
        source = "измеренные поля"
        if x is None or y is None:
            # Клетку собственного юнита наблюдение отдаёт всегда; в самом наблюдении юнит
            # лежит под «голым» номером (`103`), а сущность модели зовётся `unit_103`.
            raw = {}
            for key in (str(uid).split("_", 1)[-1], str(uid)):
                raw = ((obs.get("unit") or {}).get(key)) or {}
                if raw:
                    break
            x, y = raw.get("x"), raw.get("y")
            source = "наблюдение (unit)"
        names = sorted(costs or {})
        if not names:
            return None, ("каталог цен пуст — город нечем измерить "
                          "(мир ещё не публикует цены)")
        city_fields = {"size": 1, "prod_shield": None, "shield_stock": 0}
        if x is not None and y is not None:
            city_fields["x"], city_fields["y"] = x, y
        obs_lens = L.lens_observation(
            variety=L.variety_counters(names, [], SO.powers_of(obs, own_id)),
            requirements=SO.city_requirements(city_fields, costs, names, None),
            constraint=L.constraint_observation("city", city_fields))
        met = L.measure({"city_будущий": obs_lens}, means)
        return (float(met["city_будущий"].current_dof),
                f"город по каталогу ({source}), prod_shield неизвестен")

    options = O.build_options(m["vectors"], m["raw_menus"], m["catalogue"], m["known_techs"],
                              graph, remeasure, only=deciders, costs=costs, means=means,
                              production=production, standing=standing,
                              tech_price=tech.get("researching_cost"),
                              tech_progress=tech.get("bulbs_researched"),
                              tech_rate=L.measured_science_rate(prev_obs, obs, own_id),
                              tech_target=tech.get("researching"),
                              measured=measured)
    winner, rows, barred = O.decide(core, st, options, ctx)
    bars = collections.Counter(str(r.get("barred_by")) for r in rows if r.get("barred_by"))
    tops = sorted(rows, key=lambda r: -float(r.get("net_delta") or -9e9))[:5]
    tops = [{"id": r.get("option_id"), "net_delta": r.get("net_delta"),
             "d1": r.get("d1"), "d2": r.get("d2"), "d3": r.get("d3"),
             "viable": r.get("viable"), "resources_ok": r.get("resources_ok"),
             "barred_by": r.get("barred_by")} for r in tops]
    win_row = next((r for r in rows if r.get("option_id") == getattr(winner, "option_id", None)
                    and winner is not None), None)
    return {"ход": turn, "решающих": len(deciders), "кандидатов": len(options),
            "с_ценой": len([o for o in options if o.projected_resource_delta]),
            "цена_неизвестна": len([o for o in options if o.requires
                                    and not o.projected_resource_delta]),
            "индекс": round(float(m["index"]), 4), "средства_energy": round(means.get("energy", 0.0), 1),
            "выбор": getattr(winner, "option_id", None),
            "выбор_описание": (getattr(winner, "description", "") or "")[:90] if winner else None,
            "выбор_прирост": (winner.flat_delta() if winner is not None else None),
            "строка_выбора": win_row, "барьеры": dict(bars.most_common(4)),
            "цена_смены": getattr(st, "context_switch_cost", None),
            "лучшие": tops, "основание": founding_rows, "отказов": len(barred)}


def main() -> int:
    a = _args()
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = a.port
    fc_args["debug.take_screenshot"] = False      # сухой прогон: браузер не нужен
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=a.port, seed=a.seed)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    extractor = GameStateExtractor(my_player_id=own_id)
    core = DOFCalculusCore()
    prev, rows_all = obs, []
    for i in range(a.turns):
        obs, _r, term, trunc, info = env.step(None)
        if not obs:
            print("мир отдал пустое наблюдение (обрыв) — останавливаюсь")
            break
        turn = (info or {}).get("turn")
        for with_units in ((False, True) if not a.units else (True,)):
            r = _decide_turn(obs, info, turn, extractor, prev, own_id, core, with_units)
            r["состав"] = "игрок+города+юниты" if with_units else "игрок+города"
            rows_all.append(r)
            print(f"\n[ход {r['ход']}] состав: {r['состав']} | решающих {r['решающих']} | "
                  f"кандидатов {r['кандидатов']} (с ценой {r['с_ценой']}, "
                  f"цена неизвестна {r['цена_неизвестна']}) | средства energy {r['средства_energy']} | "
                  f"индекс {r['индекс']}")
            print(f"  выбор ядра: {r['выбор']}  прирост {r['выбор_прирост']}")
            print(f"  описание: {r['выбор_описание']}")
            print(f"  барьеры: {r['барьеры']}  (отказов всего {r['отказов']})")
            print(f"  цена смены (в состоянии): {r['цена_смены']}")
            for t in r["лучшие"]:
                print(f"    {t['id']}: net {t['net_delta']} | d1={t['d1']} d2={t['d2']} d3={t['d3']} "
                      f"| годен {t['viable']} | оплата {t['resources_ok']} | барьер {t['barred_by']}")
            for f in r["основание"]:
                if f["прирост"] is None:
                    print(f"    основание {f['unit']}: прироста нет — {f['причина']} "
                          f"(DoF поселенца {f['doF_поселенца']}, DoF города {f['doF_города']})")
                else:
                    print(f"    основание {f['unit']}: DoF поселенца {f['doF_поселенца']:.4f} → "
                          f"DoF города {f['doF_города']:.4f} = прирост {f['прирост']:+.4f} "
                          f"({f['причина']})")
        prev = obs
        if term or trunc:
            print("партия окончена миром")
            break
    out = ROOT / "knowledge" / f"decide_probe_{a.seed}_port{a.port}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows_all),
                   encoding="utf-8")
    print(f"\nтрасса сухого прогона: {out}  (строк {len(rows_all)})")
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
