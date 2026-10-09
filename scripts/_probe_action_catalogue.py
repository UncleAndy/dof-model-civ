"""Каталог имён действий мира: сколько их, что покрыто таблицей категорий, что осталось без величины.

Источник — `info["available_actions"]` реального захвата: секция -> ключ -> СПИСОК имён
(`city_work_13_-2_-1`, `research_tech_Alphabet_2`, `goto_0`, ...). Имя нормализуется до префикса из
`SPEC_ACTION_CATEGORY`; если префикса нет — берётся первый смысловой токен.

Отдельно показываются категории, у которых объявленная величина в `SPEC_ACT_EFFECT` равна нулю:
это и есть «не измерено» (объявленное отсутствие величины, а не забывчивость).
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import config as C   # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "real_obs_01.json"


def raw_names(obs_steps) -> collections.Counter:
    seen: collections.Counter = collections.Counter()
    for rec in obs_steps:
        aa = (rec.get("info") or {}).get("available_actions") or {}
        if not isinstance(aa, dict):
            continue
        for _section, per_key in aa.items():
            if not isinstance(per_key, dict):
                continue
            for _key, actions in per_key.items():
                if not isinstance(actions, list):
                    continue
                for a in actions:
                    seen[str(a)] += 1
    return seen


def normalise(name: str) -> str:
    best = ""
    for prefix, _cat in C.SPEC_ACTION_CATEGORY:
        if (name == prefix or name.startswith(prefix)) and len(prefix) > len(best):
            best = prefix
    if best:
        return best
    return name.split("_", 1)[0] if "_" in name else name


def main() -> int:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    seen = raw_names(rows)
    print(f"шагов: {len(rows)}; предложений действий: {sum(seen.values())}; "
          f"РАЗЛИЧНЫХ имён как их пишет мир: {len(seen)}")

    norm = collections.Counter()
    for name, n in seen.items():
        norm[normalise(name)] += n
    print(f"различных НОРМАЛИЗОВАННЫХ имён: {len(norm)}")

    cat_of = dict(C.SPEC_ACTION_CATEGORY)
    measured, unmeasured, unmapped = [], [], []
    for name in sorted(norm):
        if name in cat_of:
            cat = cat_of[name]
            (measured if float(C.SPEC_ACT_EFFECT.get(cat, 0.0)) > 0.0 else unmeasured).append(
                (name, cat, norm[name]))
        else:
            unmapped.append((name, norm[name]))

    print(f"\nс объявленной величиной (не ноль): {len(measured)}")
    print(f"с объявленным НУЛЁМ (не измерено): {len(unmeasured)}")
    for name, cat, n in unmeasured:
        print(f"   {name:<28} категория {cat:<12} предложений {n}")
    print(f"\nнет в таблице категорий: {len(unmapped)}")
    for name, n in unmapped[:30]:
        print(f"   {name:<28} предложений {n}")
    print("\nПРИМЕРЫ СЫРЫХ ИМЁН по каждому непокрытому семейству (доказательство, а не догадка):")
    for name, _n in unmapped:
        examples = sorted({r for r in seen if normalise(r) == name})[:4]
        print(f"   {name:<14} <- {examples}")
    print("\nSPEC_ACT_EFFECT:", dict(C.SPEC_ACT_EFFECT))
    return 0


raise SystemExit(main())
