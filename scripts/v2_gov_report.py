"""Почему `change_gov` выбирается десятки раз за партию: смотрим net и обоснование."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
gov = [r for r in rows if str((r.get("выбрано") or {}).get("effect")).startswith("['channel', 'gov'")]
print("решений с выбором gov:", len(gov))
c = collections.Counter()
for r in gov:
    for cand in (r.get("кандидаты") or []):
        if str(cand.get("эффект")).startswith("['channel', 'gov'"):
            c[(str(cand.get("эффект")), cand.get("net_delta"))] += 1
print("\nтоп кандидатов gov (эффект, net):")
for (eff, net), v in c.most_common(8):
    print(f"  {v:4d}  {eff}  net={net}")
print("\nобоснования (первые 6):")
n = 0
for r in gov:
    for cand in (r.get("кандидаты") or []):
        if str(cand.get("эффект")).startswith("['channel', 'gov'"):
            print(f"  ход {r.get('ход')}: {cand.get('эффект')} net={cand.get('net_delta')} | "
                  f"{str(cand.get('почему'))[:120]}")
            n += 1
            break
    if n >= 6:
        break