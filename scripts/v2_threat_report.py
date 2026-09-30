"""Разбор прогона: что агент выбирал, когда была угроза, и как это кончилось."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
print("всего решений:", len(rows))

with_threat = [r for r in rows if (r.get("чужое") or {}).get("угроз")]
print("решений с угрозой:", len(with_threat))

c = collections.Counter()
for r in with_threat:
    eff = (r.get("выбрано") or {}).get("effect")
    c[str(eff)] += 1
print("\nчто выбрано при наличии угрозы:")
for k, v in c.most_common(10):
    print(f"  {v:4d}  {k}")

c2 = collections.Counter()
for r in rows:
    c2[str((r.get("выбрано") or {}).get("effect"))] += 1
print("\nчто выбрано вообще (топ-10):")
for k, v in c2.most_common(10):
    print(f"  {v:4d}  {k}")

print("\nпервые 15 решений с ценой риска > 0:")
n = 0
for r in rows:
    p = (r.get("риск") or {}).get("цена") or 0
    if p and p > 0:
        ch = r.get("выбрано") or {}
        print(f"  ход {r.get('ход')}: цена {p}, угроз {(r.get('чужое') or {}).get('угроз')}, "
              f"выбрано {ch.get('effect')} (net {ch.get('net_delta')}), причина: "
              f"{str(r.get('причина'))[:70]}")
        n += 1
        if n >= 15:
            break

print("\nцели без пути (топ причин):")
c3 = collections.Counter(str(r.get("причина"))[:60] for r in rows)
for k, v in c3.most_common(6):
    print(f"  {v:4d}  {k}")