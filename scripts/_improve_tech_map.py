"""Разведка каталога: какие УЛУЧШЕНИЯ открываются ТЕХНОЛОГИЯМИ и по какой цене.

Нужна для опыта 1 (владелец разрешил исследования): чтобы мир предложил городу улучшение, надо сперва
добыть технологию из его требований. Здесь — только чтение сохранённого наблюдения (живой стенд не занят).

Печатает: требования улучшений по видам, отображение «значение требования → имя», и список улучшений,
у которых требование одного вида (технология), с ценой и именем технологии.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "real_obs_01.json"


def main() -> int:
    obs = json.loads(FIX.read_text(encoding="utf-8"))
    if isinstance(obs, list):
        # Файл — записи шагов: `{action, info, observation, ...}`; наблюдение лежит в `observation`.
        snaps = [s for s in obs if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
        print(f"[каталог] в файле записей шагов {len(obs)}, с наблюдением {len(snaps)}")
        if not snaps:
            print("[каталог] наблюдений нет — читать нечего")
            return 1
        best, best_n = None, -1
        for s in snaps:
            o = s["observation"]
            n = len(((o.get("tech") or {}).get("sup_improvements") or []))
            if n > best_n:
                best, best_n = s, n
        last = best
        print(f"[каталог] полнее всех — шаг {last.get('step')}/(ход {last.get('turn')}): "
              f"улучшений в каталоге {best_n}")
        obs = last["observation"]
        info = last.get("info") or {}
        acts = (info.get("available_actions") or {})
        print(f"[каталог] сохранённые контроллеры действий: {sorted(str(k) for k in acts)}")
        tech_sec = acts.get("tech")
        if isinstance(tech_sec, dict):
            for k, v in list(tech_sec.items())[:1]:
                names = sorted(str(n) for n in v) if hasattr(v, "__iter__") else []
                res = [n for n in names if "research" in n.lower()]
                print(f"[каталог] контроллер tech ({k}): действий {len(names)}, про науку {len(res)}: "
                      f"{res[:5]}")
        print(f"[каталог] полей игрока: research_name={((obs.get('player') or {}).get(0) or {}).get('research_name')}"
              if isinstance(obs.get("player"), dict) else "")
    tech = obs.get("tech") or {}
    recs = tech.get("sup_improvements") or []
    print(f"[каталог] записей улучшений {len(recs)}")

    kind_of: dict[int, str] = {}
    name_of: dict[int, str] = {}
    for kind, lst in (tech.get("requirements") or {}).items() if isinstance(tech.get("requirements"), dict) else []:
        for e in lst if isinstance(lst, list) else []:
            if isinstance(e, dict) and e.get("id") is not None:
                kind_of[int(e["id"])] = str(kind)
                name_of[int(e["id"])] = str(e.get("name") or e.get("rule_name") or "")
    if not kind_of:
        print("[каталог] секции `requirements` у технологий нет — отображение требования возьмём по `reqs`")
    else:
        print(f"[каталог] видов требований {len(kind_of)}: "
              f"{dict(Counter(kind_of.values()))}")

    tech_names: dict[int, str] = {}
    for t in (tech.get("techs") or tech.get("sup_techs") or []):
        if isinstance(t, dict) and t.get("id") is not None:
            tech_names[int(t["id"])] = str(t.get("name") or t.get("rule_name") or "")
    if not tech_names:
        print("[каталог] списка технологий с `id` нет — имена технологий не достанем из этого файла")

    rows = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("name") or r.get("rule_name") or "")
        reqs = r.get("reqs") or []
        reqs = [int(x) for x in reqs] if isinstance(reqs, list) else []
        kinds = [kind_of.get(x, "?") for x in reqs]
        rows.append((nm, r.get("cost"), reqs, kinds))

    only_tech = [x for x in rows if x[3] and all(k == "tech" for k in x[3])]
    print(f"[каталог] улучшений с требованиями ТОЛЬКО технологии: {len(only_tech)}")
    for nm, cost, reqs, kinds in sorted(only_tech, key=lambda x: (x[1] or 10 ** 9))[:15]:
        names = [tech_names.get(v, f"id{v}") for v in reqs]
        print(f"   {nm:24s} цена {cost}  ← {names}")

    multi = [x for x in rows if len(x[3]) > 1]
    other = [x for x in rows if x[3] and not all(k == "tech" for k in x[3])]
    print(f"[каталог] с несколькими требованиями {len(multi)}; с требованиями не-технологического вида "
          f"{len(other)}; без требований {sum(1 for x in rows if not x[3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())