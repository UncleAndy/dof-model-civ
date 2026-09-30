"""Что агент РЕАЛЬНО исполняет в канале gov: метка пути или выбранный вариант?"""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
c = collections.Counter()
for r in rows:
    eff = str((r.get("выбрано") or {}).get("effect"))
    if eff.startswith("['channel', 'gov'"):
        act = (r.get("решение") or {}).get("action")
        c[(eff, str(act))] += 1
print("пары (метка пути -> реально исполненное действие):")
for (eff, act), v in c.most_common(10):
    print(f"  {v:4d}  {eff}  ->  {act}")