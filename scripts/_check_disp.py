import json

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_s111.jsonl'
shown = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    cands = d.get('кандидаты') or []
    hit = [c for c in cands if 'встаём вплотную' in json.dumps(c, ensure_ascii=False)]
    if not hit:
        continue
    ch = d.get('выбрано') or {}
    print(f"=== ход {d.get('ход')} ===")
    print(f"  выбрано: цель={ch.get('goal')}, шаги={[s.get('action') for s in (ch.get('steps') or [])]}, "
          f"NetDelta={ch.get('net_delta')}")
    for c in hit[:2]:
        print(f"  кандидат-вытеснение: эффект={c.get('effect')} net_delta={c.get('net_delta')}")
        print(f"     почему: {str(c.get('почему'))[:220]}")
    shown += 1
    if shown >= 5:
        break
