"""Категории действий: пробел объявлен явно, и это проверяется, а не подразумевается (§13.104).

Решение владельца (2026-10-09): «объявить пробел явно и заполнять его по мере игры». Проверки:

П1 каждая категория, которую МОЖЕТ вернуть классификатор, объявлена в `SPEC_ACT_EFFECT`;
П2 `misc` объявлен именно нулём — это решение, а не совпадение;
П3 у `misc` нет своей переменной (`SPEC_VARIABLE_BY_CATEGORY`) — он системный;
П4 категория наблюдённого нападения в таблицу величин НЕ входит намеренно (§13.93);
П5 на реальном захвате: ни одно имя не даёт категории вне таблицы, и печатается список семейств,
   которые сейчас попадают в `misc` — то есть что заполнять дальше;
П6 отрицательный контроль: выдуманное имя даёт `misc`, ноль и не создаёт ребра.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import config as C            # noqa: E402
from env import spec_lenses as L       # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "real_obs_01.json"

OK = 0
BAD = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  ok   {name}" + (f" | {detail}" if detail else ""))
    else:
        BAD += 1
        print(f"  ПЛОХО {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    declared = set(C.SPEC_ACT_EFFECT)
    reachable = {cat for _p, cat in C.SPEC_ACTION_CATEGORY} | {"misc"}

    # ── П1
    missing = sorted(reachable - declared)
    check("П1 каждая достижимая категория объявлена в SPEC_ACT_EFFECT",
          not missing, f"недостающие: {missing or 'нет'}; достижимых {len(reachable)}")

    # ── П2
    check("П2 `misc` объявлен именно нулём (решение, а не совпадение)",
          C.SPEC_ACT_EFFECT.get("misc") == 0.0, f"значение {C.SPEC_ACT_EFFECT.get('misc')}")

    # ── П3
    check("П3 у `misc` нет своей переменной — категория системная",
          C.SPEC_VARIABLE_BY_CATEGORY.get("misc", "нет ключа") is None,
          f"значение {C.SPEC_VARIABLE_BY_CATEGORY.get('misc', 'нет ключа')}")

    # ── П4
    check("П4 наблюдённое нападение в таблицу величин не входит намеренно (§13.93)",
          C.SPEC_OBSERVED_ATTACK_CATEGORY not in declared,
          f"категория {C.SPEC_OBSERVED_ATTACK_CATEGORY}")

    # ── П5
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    names = collections.Counter()
    for rec in rows:
        aa = (rec.get("info") or {}).get("available_actions") or {}
        if not isinstance(aa, dict):
            continue
        for _section, per_key in aa.items():
            if not isinstance(per_key, dict):
                continue
            for _key, actions in per_key.items():
                if isinstance(actions, list):
                    for a in actions:
                        names[str(a)] += 1
    cats = {L.action_category(n) for n in names}
    outside = sorted(cats - declared)
    check("П5 на реальном захвате ни одно имя не даёт категории вне таблицы",
          not outside, f"вне таблицы: {outside or 'нет'}; имён {len(names)}")

    misc_fams = collections.Counter()
    for name, n in names.items():
        if L.action_category(name) == "misc":
            fam = name.split("_", 1)[0] if "_" in name else name
            misc_fams[fam] += n
    print(f"  ЧТО ЗАПОЛНЯТЬ ДАЛЬШЕ: в `misc` сейчас {len(misc_fams)} семейств, "
          f"{sum(misc_fams.values())} предложений:")
    print("   ", ", ".join(f"{f}({c})" for f, c in misc_fams.most_common()))

    # ── П6
    fake = "zzz_never_seen_action"
    cat = L.action_category(fake)
    eff = float(C.SPEC_ACT_EFFECT.get(cat, -1.0))
    check("П6 выдуманное имя даёт `misc`, ноль и ребра не создаёт",
          cat == "misc" and eff == 0.0,
          f"категория {cat}, величина {eff}")

    print(f"\nитог: ok {OK}, плохо {BAD}")
    return 1 if BAD else 0


raise SystemExit(main())
