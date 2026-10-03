import json, collections, sys
path = "knowledge/traces_def7.jsonl"
lines = open(path, encoding="utf-8").read().splitlines()
print("всего строк:", len(lines))
print("ключи записи:")
for i in (0, 1, 900, 1200):
    if i < len(lines):
        try:
            print(f"  [{i}]", sorted(json.loads(lines[i]).keys()))
        except Exception as e:
            print(f"  [{i}] ошибка чтения: {e}")

def counts(lo, hi):
    c = collections.Counter()
    for l in lines[lo:hi]:
        try:
            d = json.loads(l)
        except Exception:
            continue
        ch = d.get("выбрано") or {}
        c[ch.get("goal") or "(нет)"] += 1
        act = ((ch.get("steps") or [{}])[0].get("action")) or ""
        if act.startswith("attack"):
            c["<attack>"] += 1
    return c

print("\nпервые 800 строк (мусор упавшей попытки):")
print(" ", dict(counts(0, 800)))
print("с 800 до конца (рабочая серия):")
print(" ", dict(counts(800, len(lines))))