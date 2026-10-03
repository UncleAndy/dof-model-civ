import json

for p in ['knowledge/world.json', 'knowledge/world_v2109.json']:
    d = json.load(open(p))
    cc = (d.get('effects') or {}).get('turn/advance', {}).get('change_counts', {})
    print(p, '-> city_lost =', cc.get('city_lost'), '| city_new =', cc.get('city_new'),
          '| city_grew =', cc.get('city_grew'), '| unit_lost =', cc.get('unit_lost'),
          '| seen =', (d.get('effects') or {}).get('turn/advance', {}).get('seen'))
