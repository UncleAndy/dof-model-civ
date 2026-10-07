"""Почему город не может начать ни одного улучшения — ответ из живого наблюдения.

Разбор офлайн (сброс наблюдения снят прибором `v011_improve_probe.py --dump-obs`), стенд не занят.

Важно про структуру, которую я сперва прочитал неверно: каталог улучшений — это НЕ `tech["sup_improvements"]`,
а **под-ключ каждой записи технологии** (`tech["<id>"]["sup_improvements"]`), то есть мир прямо говорит, какая
технология что открывает. Плюс каждое требование — словарь с флагом `present`: мир сам сообщает, выполнено ли
требование, и оценивать их своими средствами не нужно (кроме подсчёта неоценённых видов — правило 15).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    dump = sorted((ROOT / "knowledge").glob("obs_dump_*.json"))
    if not dump:
        print("[разбор] сбросов наблюдения нет — сначала прогон с --dump-obs")
        return 1
    path = dump[-1]
    d = json.loads(path.read_text(encoding="utf-8"))
    obs, acts = d["observation"], d.get("available_actions") or {}
    print(f"[разбор] {path.name}, ход {d.get('turn')}")

    tech = obs.get("tech") or {}
    imps: list[dict] = []
    units = 0
    for tid, rec in tech.items():
        if not isinstance(rec, dict):
            continue
        units += len(rec.get("sup_units") or [])
        for spec in (rec.get("sup_improvements") or []):
            if isinstance(spec, dict):
                imps.append({"от_технологии": rec.get("name") or rec.get("rule_name") or tid, **spec})
    print(f"[разбор] технологий {len(tech)}; каталог: улучшений {len(imps)}, юнитов {units}")

    def req_state(spec: dict) -> tuple[int, list[str]]:
        unmet: list[str] = []
        present = 0
        for req in (spec.get("reqs") or []):
            if not isinstance(req, dict):
                continue
            if req.get("present"):
                present += 1
            else:
                unmet.append(f"{req.get('kind')}={req.get('value')}")
        return present, unmet

    ready = [s for s in imps if req_state(s)[1] == []]
    print(f"[разбор] улучшений со ВСЕМИ выполненными требованиями (вердикт мира): {len(ready)}")
    for s in ready[:8]:
        print(f"    {s.get('name')}: цена {s.get('cost')} (от технологии {s.get('от_технологии')})")

    print(f"[разбор] ближайшие по числу НЕвыполненных требований:")
    ranked = sorted(imps, key=lambda s: (len(req_state(s)[1]), s.get("cost") or 10 ** 9))
    for s in ranked[:8]:
        present, unmet = req_state(s)
        print(f"    {str(s.get('name'))[:24]:24s} цена {str(s.get('cost')):>4} "
              f"выполнено {present}, не выполнено {unmet[:3]}  ← тех. {s.get('от_технологии')}")

    city = obs.get("city") or {}
    for cid, rec in list(city.items())[:2]:
        if not isinstance(rec, dict):
            continue
        mask = rec.get("improvements")
        trues = [i for i, v in enumerate(mask) if v] if isinstance(mask, list) else []
        print(f"[разбор] город {cid}: размер {rec.get('size')}, истинных бит маски улучшений {len(trues)}: "
              f"{trues[:8]}")
    for ctrl in ("city", "tech"):
        sec = acts.get(ctrl) or {}
        if isinstance(sec, dict):
            for k, v in list(sec.items())[:1]:
                names = sorted(str(n) for n in v) if hasattr(v, "__iter__") else []
                prod = [n for n in names if n.startswith("produce_")]
                print(f"[разбор] меню {ctrl} ({k}): имён {len(names)}; производств {len(prod)}: {prod[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())