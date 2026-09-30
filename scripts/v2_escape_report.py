"""Как выбирается путь «выход»: по положительному NetDelta, как множитель или как проба?"""
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1200:]
n = 0
for r in tail:
    ch = r.get("выбрано") or {}
    eff = str(ch.get("effect"))
    if not eff.startswith("['escape'"):
        continue
    cands = r.get("кандидаты") or []
    match = [c for c in cands if str(c.get("эффект")) == eff]
    print(f"ход {r.get('ход')}: выбрано {eff}")
    print(f"   причина: {r.get('причина')}")
    for c in match:
        p = c.get("path") or {}
        print(f"   кандидат: kind={p.get('kind')} goal={p.get('goal')} "
              f"net={c.get('net_delta')} лучший_вариант={c.get('лучший_вариант')}")
        print(f"   почему: {str(c.get('почему'))[:150]}")
    print(f"   объявлено к исполнению: {(r.get('решение') or {}).get('action')}")
    n += 1
    if n >= 4:
        break

print("\nраспределение причин, когда выбран escape:")
import collections
c = collections.Counter()
for r in tail:
    if str((r.get("выбрано") or {}).get("effect")).startswith("['escape'"):
        c[str(r.get("причина"))[:40]] += 1
for k, v in c.most_common(5):
    print(f"  {v:4d}  {k}")