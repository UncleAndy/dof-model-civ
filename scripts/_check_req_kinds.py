"""§13.96: проверки П1-П6 — виды требований и их оценка по состоянию города.

Объявлено ДО кода (§13.96): неоценённых станет 8 вместо 22; вид «постройка» судится по маске ЭТОГО
города; незнание остаётся не-запретом; эффект измеряется, а не объявляется.

Важно (моя ошибка первого захода): технологический гейт и гейт построек — РАЗНЫЕ запреты. Предмет
«Bank» требует и технологии, и постройки, поэтому судить о виде «постройка» по нему нельзя, пока не
выполнены технологические требования. Здесь берутся предметы, у которых технологический гейт УЖЕ
пройден, и сравнивается старый вердикт каталога с новым.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_lenses as L   # noqa: E402

OK = 0
BAD = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, BAD
    if cond:
        OK += 1
        print(f"  хорошо: {name}" + (f" | {detail}" if detail else ""))
    else:
        BAD += 1
        print(f"  ПЛОХО: {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    raw = json.loads((ROOT / "tests" / "fixtures" / "real_obs_01.json").read_text("utf-8"))
    rows = [s for s in raw if isinstance(s, dict) and isinstance(s.get("observation"), dict)]
    obs = rows[-1]["observation"]
    info = rows[-1].get("info") or {}
    tech = obs.get("tech") or {}
    cat = L.catalogue_index(tech)
    known = {tid for tid, rec in tech.items() if isinstance(rec, dict) and L.gate_is_open(rec)}
    city_id, city_fields = next(((k, v) for k, v in (obs.get("city") or {}).items()
                                 if isinstance(v, dict) and int(v.get("owner", 0) or 0) == 0))
    mask = list(city_fields.get("improvements") or [])
    print(f"город {city_id}: построено {[i for i, on in enumerate(mask) if on]}; "
          f"технологий открыто {len(known)}; предметов {len(cat['items'])}; "
          f"справочник улучшений {len(cat['improvements'])}")

    # П1: объявленное число неоценённых
    check("П1 неоценённых требований стало 8 вместо 22 (объявлено до кода)",
          cat["unevaluated"] == 8, f"измерено {cat['unevaluated']}")

    # Технологически открытые предметы — на них и судим вид «постройка»
    tech_open = {name: e for name, e in cat["items"].items()
                 if set(e["advance"]) <= {str(k) for k in known}}
    with_reqs = {n: e for n, e in tech_open.items() if e["reqs"]}
    print(f"  технологически открытых предметов {len(tech_open)}, из них с требованием «постройка» "
          f"{len(with_reqs)}: {sorted(with_reqs)}")

    old_rule = {n: (not e["unevaluated"]) and set(e["advance"]) <= {str(k) for k in known}
                for n, e in tech_open.items()}
    new_rule = {n: L.item_available(n, cat, known, fields=city_fields)
                for n in tech_open}
    turned = sorted(n for n in tech_open if old_rule[n] and not new_rule[n])
    print(f"  старое правило доступно {sum(old_rule.values())}, новое {sum(new_rule.values())}; "
          f"закрыто видом «постройка»: {len(turned)} {turned}")

    # П2/П3: на этом срезе таких предметов нет среди технологически открытых — технологии их ещё не
    # открыли. Поэтому проверка идёт ЯВНЫМ СЦЕНАРИЕМ на любом предмете с требованием «постройка»:
    # технология считается исследованной, и тогда решает ИМЕННО постройка. Сценарий назван сценарием.
    with_reqs_all = {n: e for n, e in cat["items"].items() if e["reqs"]}
    print(f"  предметов с требованием «постройка» во всём каталоге {len(with_reqs_all)}: "
          f"{sorted(with_reqs_all)[:6]}")
    if not with_reqs_all:
        check("П2 предмет с требованием «постройка» есть в каталоге", False, "нет ни одного")
    else:
        sample = sorted(with_reqs_all)[0]
        need = int(with_reqs_all[sample]["reqs"][0]["value"])
        known_plus = set(known) | {str(v) for v in with_reqs_all[sample]["advance"]}
        old_av = (set(with_reqs_all[sample]["advance"]) <= known_plus
                  and not with_reqs_all[sample]["unevaluated"])
        new_av = L.item_available(sample, cat, known_plus, fields=city_fields)
        built = list(mask)
        if len(built) > need:
            built[need] = True
        new_built = L.item_available(sample, cat, known_plus, fields={"improvements": built})
        full = L.item_available(sample, cat, known_plus, fields={"improvements": [True] * len(mask)})
        check(f"П2 сценарий «технология открыта»: «{sample}» закрыт, пока постройка {need} не стоит; "
              f"с построенной доступен",
              old_av is True and new_av is False and new_built is True,
              f"старое правило {old_av}, новое {new_av}, с построенной {new_built}")
        check("П3 оценка идёт по маске именно этого города (полная маска открывает)",
              new_av is False and full is True, f"наша маска {new_av}, полная {full}")

    # П4: незнание — не запрет (id вне справочника, отсутствие города, отсутствие маски)
    fake = {"items": {"Выдумка": {"advance": set(), "unevaluated": 0,
                                 "reqs": [{"kind": 3, "value": 999, "range": 4}]}},
            "unlocks": {}, "unevaluated": 0, "improvements": cat["improvements"]}
    outside = L.item_available("Выдумка", fake, known, fields={"improvements": mask})
    no_city = L.item_available("Выдумка", fake, known)
    no_mask = L.item_available("Выдумка", fake, known, fields={"owner": 0})
    check("П4 id вне справочника, отсутствие города и отсутствие маски не запрещают предмет",
          outside is True and no_city is True and no_mask is True,
          f"вне справочника {outside}, без города {no_city}, без маски {no_mask}")

    # П5: объявленный эффект. На срезе измерено 0 закрытых позиций — и это ЗАПИСЫВАЕТСЯ как есть:
    # предметы с требованием «постройка» здесь ещё не открыты технологиями, поэтому ни один прежний
    # прогон этой правкой не сдвинут. Механизм проверен сценарием П2, а не подогнан под ожидание.
    check("П5 на срезе вид «постройка» не закрывает ни одной позиции (прежние прогоны стоят)",
          len(turned) == 0,
          f"закрыто {len(turned)}; технологически открытых {len(tech_open)}, с требованием «постройка» "
          f"среди них {len(with_reqs)}")

    # П6: инертность — у сущности без маски построек ничего не меняется
    unit_fields = {"owner": 0, "moves_left": 1, "max_moves": 1}
    unit_same = {n: L.item_available(n, cat, known, fields=unit_fields) for n in tech_open}
    check("П6 без маски построек (юнит) вердикт каталога не меняется ни на одном предмете",
          all(unit_same[n] == old_rule[n] for n in tech_open),
          f"расхождений {sum(1 for n in tech_open if unit_same[n] != old_rule[n])} из {len(tech_open)}")

    print(f"\nитог: ok {OK}, плохо {BAD}")
    return 1 if BAD else 0


raise SystemExit(main())
