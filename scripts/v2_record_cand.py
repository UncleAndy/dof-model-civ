"""Какие цели вообще попадали в коридор в записанных партиях (почему город не основывался)."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces_record5.jsonl")]
cand = collections.Counter()
for r in rows:
    for c in (r.get("кандидаты") or []):
        cand[str((c.get("path") or {}).get("goal"))] += 1
print("цели кандидатов (все решения):", dict(cand.most_common(8)))
print("решений:", len(rows))
print("путей в среднем:", round(sum(len(r.get('кандидаты') or []) for r in rows) / max(1, len(rows)), 2))