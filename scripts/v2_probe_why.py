"""Почему агент не пробует постройку: смотрим, что предлагает проба и что выбирается."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-700:]

print("выбранные действия (исполнено):")
c = collections.Counter()
for r in tail:
    act = str((r.get("решение") or {}).get("action"))
    if act != "None":
        c[act] += 1
for k, v in c.most_common(12):
    print(f"  {v:4d}  {k}")

print("\nпричины решений (топ-8):")
c2 = collections.Counter(str(r.get("причина"))[:52] for r in tail)
for k, v in c2.most_common(8):
    print(f"  {v:4d}  {k}")

print("\nбыли ли пробы вообще:")
probes = [r for r in tail if str((r.get("выбрано") or {}).get("goal")) == "probe"]
print("  выбрано проб:", len(probes))
for r in probes[:5]:
    print(f"    ход {r.get('ход')}: {(r.get('решение') or {}).get('action')}")
print("\nзамеры срока постройки:", sum(1 for r in tail if "замер_срока" in r))