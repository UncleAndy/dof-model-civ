"""Что видно у чужого юнита: поля в срезах и есть ли чужие юниты в фикстурах."""
import json, glob, os

# 1) поля записи чужого юнита в срезе
path = "/tmp/h300q_base.json.state.jsonl"
shown = 0
with open(path) as f:
    for line in f:
        r = json.loads(line)
        for u in (r.get("foreign_units") or []):
            print("foreign_units запись:", json.dumps(u, ensure_ascii=False)[:500])
            shown += 1
            break
        if shown:
            break
if not shown:
    print("в срезах записей чужого юнита не найдено")

# 2) чужие юниты в фикстурах
for p in sorted(glob.glob("tests/fixtures/*.json")):
    try:
        with open(p) as f:
            data = json.load(f)
    except Exception as e:
        print(f"{os.path.basename(p)}: не читается ({e})")
        continue
    recs = data if isinstance(data, list) else [data]
    owners, types = set(), set()
    for rec in recs:
        obs = rec.get("observation", rec) if isinstance(rec, dict) else {}
        units = obs.get("unit", {}) if isinstance(obs, dict) else {}
        for uid, u in (units or {}).items():
            if isinstance(u, dict):
                owners.add(u.get("owner"))
                if u.get("owner") not in (0, None):
                    types.add(u.get("type_rule_name"))
    print(f"{os.path.basename(p)}: owners={sorted(owners, key=lambda v: (v is None, v))} чужие_типы={sorted(types, key=str)}")