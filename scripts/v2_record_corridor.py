"""Состав коридора в записанных партиях: какие цели вообще рассматривались."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces_record5.jsonl")]
c = collections.Counter()
for r in rows:
    for k in (r.get("кандидаты") or []):
        eff = str(k.get("эффект"))
        name = eff.split(",")[0].strip("[]' ")
        c[name] += 1
print("состав коридора (эффект кандидата):", dict(c.most_common(8)))
print("решений:", len(rows))