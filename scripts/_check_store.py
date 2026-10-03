import json

for p in ['knowledge/world.json', 'knowledge/world_v2109.json']:
    d = json.load(open(p))
    print('===', p, '===')
    eff = d.get('effects') or {}
    for k in sorted(eff):
        if k in ('turn/advance', 'unit/build_city', 'unit/conquer_city', 'city/produce'):
            print('  ', k, json.dumps(eff[k], ensure_ascii=False)[:400])
    print('  партий:', len(d.get('games') or d.get('parties') or []), '| ключи верхнего уровня:', list(d.keys())[:12])
