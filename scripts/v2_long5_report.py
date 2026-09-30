"""Разбор long5: бои, источники коллапса, удар, и что выбиралось."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1600:]
print("строк в хвосте:", len(tail))

ev = [r["нападение"] for r in tail if "нападение" in r]
print("событий нападения:", len(ev))
for e in ev[:8]:
    print("  ", json.dumps(e, ensure_ascii=False)[:180])

fights = [r["бой"] for r in tail if "бой" in r]
print("\nзаписей боя:", len(fights))
for f in fights[:6]:
    print("  ", json.dumps(f, ensure_ascii=False))

last = tail[-1].get("бои") if tail else None
print("\nстатистика боёв в последнем решении:", json.dumps(last, ensure_ascii=False))

print("\nисточники коллапса (по решениям):", sum(1 for r in tail if r.get("источники_коллапса")))
nz = [r for r in tail if ((r.get("риск") or {}).get("цена") or 0) > 0]
print("решений с ценой риска > 0:", len(nz))
c = collections.Counter()
for r in tail:
    ch = r.get("выбрано") or {}
    p = (ch.get("goal") if isinstance(ch, dict) else None)
    c[str(p)] += 1
print("цели выбранных решений:", dict(c.most_common(8)))

strike = [r for r in tail if str((r.get("выбрано") or {}).get("goal")) == "strike"]
print("выбран «удар»:", len(strike))
prod = collections.Counter()
for r in tail:
    act = str((r.get("решение") or {}).get("action"))
    if act.startswith("produce_"):
        prod[act] += 1
print("производство (исполнено):", dict(prod.most_common(8)))