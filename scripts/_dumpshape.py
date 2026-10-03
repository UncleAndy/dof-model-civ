import json, sys
path = sys.argv[1]
n = 0
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    ch = d.get("выбрано")
    if ch:
        print(json.dumps(ch, ensure_ascii=False)[:400])
        n += 1
    if n >= 3:
        break
print("--- ключи записи:", sorted(d.keys()))