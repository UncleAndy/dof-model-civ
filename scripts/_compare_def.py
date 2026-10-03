"""Сравнение серий обороны: атаки за партию + потерянные города (по городам, не по флипам)."""
import json, collections


def attacks(path):
    a = collections.Counter()
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ch = d.get("выбрано") or {}
        act = ((ch.get("steps") or [{}])[0].get("action")) or ""
        if act.startswith("attack"):
            a[d.get("партия") or 0] += 1
    return a


def lost_cities(path):
    """Города, которые были нашими и перестали (по последней записи)."""
    seq = collections.defaultdict(dict)      # партия -> город -> последний свой?
    ever_own = collections.defaultdict(set)
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        p, c = d.get("партия"), d.get("город")
        seq[p][c] = bool(d.get("свой"))
        if d.get("свой"):
            ever_own[p].add(c)
    lost = {}
    for p, cities in seq.items():
        lost[p] = sum(1 for c in ever_own[p] if seq[p].get(c) is False)
    return lost


for label, tr, dl in [("СТАРАЯ (def)", "knowledge/traces_def.jsonl",
                       "knowledge/city_defense_def.jsonl"),
                      ("НОВАЯ (def4)", "knowledge/traces_def4.jsonl",
                       "knowledge/city_defense_def4.jsonl")]:
    try:
        a = attacks(tr)
        l = lost_cities(dl)
        print(f"{label}:")
        print(f"  атак по партиям: {dict(sorted(a.items()))}  (всего {sum(a.values())})")
        print(f"  потеряно городов по партиям: {dict(sorted(l.items()))}")
    except FileNotFoundError as e:
        print(f"{label}: нет файла {e.filename}")