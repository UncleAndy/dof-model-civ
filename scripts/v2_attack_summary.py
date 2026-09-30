"""Сводка наблюдённых нападений за long4: атрибуция, нападающие, исход партий."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1200:]
ev = [r["нападение"] for r in tail if "нападение" in r]
print("событий нападения:", len(ev))
attr = [e for e in ev if e.get("нападающий")]
print(f"атрибутировано: {len(attr)}, без видимого нападающего: {len(ev) - len(attr)}")
c = collections.Counter((str(e.get("нападающий")), e.get("владелец")) for e in attr)
print("нападающие:", dict(c))
print("по виду жертвы:", dict(collections.Counter(e.get("вид") for e in ev)))
print("как:", dict(collections.Counter(e.get("как") for e in ev)))
for e in ev:
    if not e.get("нападающий"):
        print("  без атрибуции:", json.dumps(e, ensure_ascii=False)[:170])