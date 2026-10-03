import json, sys, collections
path = sys.argv[1]
shown = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    src = d.get("источники_коллапса")
    if src:
        print("--- ход", d.get("ход"), "---")
        print("источники_коллапса:", json.dumps(src, ensure_ascii=False)[:300])
        print("чужое:", json.dumps(d.get("чужое"), ensure_ascii=False)[:300])
        print("кандидаты (первые 3):",
              json.dumps([c.get("лучший_вариант") or c.get("action")
                          for c in (d.get("кандидаты") or [])[:3]], ensure_ascii=False))
        print("выбрано:", json.dumps(d.get("выбрано"), ensure_ascii=False)[:160])
        shown += 1
    if shown >= 3:
        break
