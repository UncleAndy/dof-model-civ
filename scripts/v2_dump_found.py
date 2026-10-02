"""Показать решения build_city/found_city с их net_delta и штрафами (после §10.108)."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/traces_site.jsonl"
for line in open(path, errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except Exception:  # noqa: BLE001
        continue
    ch = r.get("выбрано")
    if ch and ch.get("steps", []) and ch["steps"][0].get("ctrl") == "unit" \
            and ch["steps"][0].get("action") == "build_city":
        print(f"\nход {r.get('ход')}: выбрано build_city {ch['steps'][0].get('actor')}")
        print(f"  причина: {r.get('причина')}")
    for c in r.get("кандидаты") or []:
        eff = c.get("эффект")
        if isinstance(eff, list) and eff and eff[0] == "found_city":
            print(f"  кандидат found_city net={c.get('net_delta')}")