"""Разбор: какие векторы меню отбрасывает счёт и по какому основанию.

**Зачем.** Замер показал разрыв: мир отдаёт 10–12 векторов на юнита, стойка считает 1–2. Меню
проходит через `available_vectors` (§4.6: «меню — предложение мира, а не список возможного»), и там
ровно три основания для отказа:

1. действие над **уже открытой дверью** (`action_targets_open_gate`);
2. **позиция каталога**, требования которой ещё не выполнены (`item_available`);
3. действие с **замороженной переменной** (`SPEC_VARIABLE_BY_CATEGORY` + `frozen_variables`).

Прибор гоняет ту же стойку (`spec_obs.measure_step`), берёт из неё **сырое** меню (`raw_menus`) и те же
входы, что видит счёт (`fields`, `known_techs`, `catalogue`), и печатает по каждому юниту: сколько
векторов отброшено по каждому основанию и какие именно имена. Ничего не меняет — только называет.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civrealm" / "src"))
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from env import spec_lenses as L  # noqa: E402
from env import spec_obs as SO  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402


def classify(kind: str, fields: dict, raw_names: list[str], known_gates: set,
             catalogue: dict, known_techs: set) -> dict[str, list[str]]:
    """Повторить ровно те три фильтра, что стоят в `available_vectors`, и назвать их."""
    frozen = set(L.frozen_variables(kind, fields))
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for name in raw_names:
        if L.action_targets_open_gate(name, known_gates):
            groups["дверь_уже_открыта"].append(name)
            continue
        if name.startswith(L.SPEC_PRODUCTION_ACTION_PREFIX) and catalogue:
            item = name[len(L.SPEC_PRODUCTION_ACTION_PREFIX):]
            if not L.item_available(item, catalogue, known_techs):
                groups["каталог_не_выполнен"].append(name)
                continue
        variable = L.SPEC_VARIABLE_BY_CATEGORY.get(L.action_category(name))
        if variable is not None and variable in frozen:
            groups[f"переменная_заморожена:{variable}"].append(name)
            continue
        groups["ОСТАЁТСЯ"].append(name)
    return dict(groups)


def main() -> int:
    ap = argparse.ArgumentParser(description="Разбор отброшенных векторов меню")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=9460)
    ap.add_argument("--turns", type=int, default=2)
    a = ap.parse_args()

    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = a.port
    fc_args["debug.take_screenshot"] = False
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=a.port, seed=a.seed)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    extractor = GameStateExtractor(my_player_id=own_id)
    # Действие тем же драйвером, что и в живом прогоне: пассивный прогон города НЕ основывает,
    # и разбирать «сколько у города векторов» становится не на чем.
    from env.spec_drive import Decider  # noqa: PLC0415
    dec = Decider(extractor, own_id=own_id)
    prev_obs = None
    last_turn = None

    print(f"[разбор] сид {a.seed}, порт {a.port}, наш игрок {own_id}", flush=True)
    print(f"[разбор] правило счёта векторов: {L.SPEC_RESPONSE_VECTOR_RULE}", flush=True)
    print(f"[разбор] таблица категория→переменная: {dict(L.SPEC_VARIABLE_BY_CATEGORY)}", flush=True)
    out_rows: list[dict[str, Any]] = []
    for _ in range(a.turns):
        turn = (info or {}).get("turn")
        m = SO.measure_step(obs, info, turn, extractor, prev_obs=None, my_player_id=own_id)
        print(f"\n[ход {turn}] индекс {float(m['index']):.4f} | юнитов в меню: "
              f"{sum(1 for e in m['raw_menus'] if e.startswith('unit_'))}", flush=True)
        for eid in sorted(m["raw_menus"]):
            if not eid.startswith(("unit_", "city_")):
                continue
            kind = L.entity_type_of(eid)
            fields = m["fields"].get(eid) or {}
            raw_names = list(m["raw_menus"][eid])
            groups = classify(kind, fields, raw_names, set(m["known_techs"] or ()),
                              m["catalogue"] or {}, set(m["known_techs"] or ()))
            frozen = L.frozen_variables(kind, fields)
            print(f"\n  {eid} ({kind}): сырых {len(raw_names)}, посчитано "
                  f"{len(groups.get('ОСТАЁТСЯ', []))} | V(стейта) {m['counts'].get(eid)}", flush=True)
            print(f"    замороженные переменные: {list(frozen)}", flush=True)
            for reason in sorted(groups):
                names = groups[reason]
                shown = ", ".join(sorted(names)[:10])
                print(f"    {reason}: {len(names)} → {shown}", flush=True)
            out_rows.append({"ход": turn, "сущность": eid, "сырых": len(raw_names),
                             "остаётся": len(groups.get("ОСТАЁТСЯ", [])),
                             "основания": {k: sorted(v) for k, v in groups.items()},
                             "заморожено": list(frozen)})
        if last_turn is not None and turn != last_turn:
            dec.new_turn()
        last_turn = turn
        act = dec.decide(obs, info, turn, prev_obs=prev_obs)
        if act is not None:
            print(f"    [драйвер] действие: {act}", flush=True)
        prev_obs = obs
        obs, _r, term, trunc, info = env.step(act)
        if not obs or term or trunc:
            break

    out = ROOT / "knowledge" / f"vectors_{a.seed}_port{a.port}.json"
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[разбор] строк {len(out_rows)}; записано {out}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
