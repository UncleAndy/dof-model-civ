"""Что происходило с производством в живых партиях: были ли варианты `produce_*` и какие net."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1500:]

prod = collections.Counter()
chan = collections.Counter()
for r in tail:
    for c in (r.get("кандидаты") or []):
        eff = str(c.get("эффект"))
        if eff.startswith("['channel', 'city'"):
            chan[c.get("net_delta")] += 1
        p = c.get("path") or {}
        st = (p.get("steps") or [{}])[0]
        for a in (st.get("alternatives") or []):
            if str(a).startswith("produce_"):
                prod[(a, c.get("net_delta"))] += 1

print("кандидаты канала города (net -> сколько раз):", dict(chan.most_common(6)))
print("\nварианты produce_*:", dict(prod.most_common(8)))

# сколько раз вообще встречались пути канала города
n = sum(1 for r in tail for c in (r.get("кандидаты") or [])
        if str((c.get("path") or {}).get("goal")) == "channel"
        and str((c.get("path") or {}).get("steps", [{}])[0].get("ctrl")) == "city")
print("решений с кандидатом канала города:", n)

# что выбиралось в канале города
c2 = collections.Counter()
for r in tail:
    ch = r.get("выбрано") or {}
    if str(ch.get("effect")).startswith("['channel', 'city'"):
        c2[str((r.get("решение") or {}).get("action"))] += 1
print("исполнено в канале города:", dict(c2.most_common(8)))