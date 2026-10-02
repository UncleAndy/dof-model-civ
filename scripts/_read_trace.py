import json
for line in open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_probe_crowd.jsonl'):
    try:
        d = json.loads(line)
    except Exception:
        continue
    r = d.get('решение') or {}
    if r.get('action') == 'build_city':
        v = d.get('выбрано') or {}
        print('ход', d.get('ход'), 'actor', r.get('actor'),
              '| goal:', v.get('goal'),
              '| source:', (v.get('source') or '')[:90])
