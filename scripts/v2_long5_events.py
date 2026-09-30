"""Две записи нападения в last-трёх партиях: что это было и не ложные ли это срабатывания."""
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
for r in rows[-660:]:
    if "нападение" in r:
        print(json.dumps(r.get("нападение"), ensure_ascii=False))
        print("   ход", r.get("ход"), "| чужое:", json.dumps(r.get("чужое"), ensure_ascii=False)[:200])
        print("   источники:", json.dumps(r.get("источники_коллапса"), ensure_ascii=False)[:150])