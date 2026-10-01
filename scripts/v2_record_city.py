"""Была ли у агента хоть одна попытка основать город в записанных партиях."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces_record5.jsonl")]
acts = collections.Counter(str((r.get("решение") or {}).get("action")) for r in rows)
print("топ действий:", dict(acts.most_common(6)))
print("build_city:", acts.get("build_city", 0))
goals = collections.Counter()
for r in rows:
    ch = r.get("выбрано")
    if isinstance(ch, dict):
        goals[str(ch.get("goal"))] += 1
print("цели выбранных путей:", dict(goals.most_common(5)))
# предлагались ли пути основания города
found = 0
for r in rows:
    for c in (r.get("кандидаты") or []):
        if str((c.get("path") or {}).get("goal")) == "found_city":
            found += 1
print("решений, где кандидат «основать город» был:", found)