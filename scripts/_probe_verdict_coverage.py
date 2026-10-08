"""§13.82 (долг): охватывает ли поле `вердикты` все СЧИТАЕМЫЕ сущности.

Вопрос поставлен по наблюдению: раненый `unit_111` был в наборе счёта, а строки вердикта у него
не нашлось. Здесь сравниваются ТРИ множества на каждом шаге настоящего захвата: измеренные,
получившие строку вердикта и вошедшие в `calc(S)`.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import entity_extractor as E   # noqa: E402
from env import spec_graph as G         # noqa: E402
from env import spec_obs as SO          # noqa: E402


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    e = E.GameStateExtractor()
    prev = None
    bad = 0
    for i, rec in enumerate(rows):
        ob = rec["observation"]
        turn = rec.get("turn", i + 1)
        m = SO.measure_step(ob, rec.get("info") or {}, turn, e, prev_obs=prev, my_player_id=0)
        dof_ids = {str(k) for k in (m["dof"] or {})}
        verd = {str(k) for k in (m["вердикты"] or {})}
        gr = G.world_graph(m["vectors"], m["fields"], m["dof"], catalogue=m["catalogue"],
                           known_techs=m["known_techs"], raw_menus=m["raw_menus"],
                           strikes=(getattr(e, "last_attack_event", {}) or {}).get("strikes") or ())
        st = G.state_with_measured_dof(m["state"], m["dof"])
        members, _idx = G.calc_and_index(st, G.observation_context(gr, m["dof"]))
        members = {str(x) for x in members}
        no_row = sorted(members - verd)
        no_measure = sorted(verd - dof_ids)
        if no_row or no_measure:
            bad += 1
        print(f"ход {turn}: измерено {len(dof_ids)}, вердиктов {len(verd)}, в счёте {len(members)}, "
              f"в счёте без строки {len(no_row)} {no_row[:4]}, строк без измерения "
              f"{len(no_measure)} {no_measure[:4]}")
        prev = ob
    print(f"\nшагов с расхождением: {bad} из {len(rows)}")
    return 1 if bad else 0


raise SystemExit(main())
