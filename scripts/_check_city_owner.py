import json

d = json.load(open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/world_v2109_def2.json'))
cities = [e for e in d['entities'] if e.get('kind') == 'city']
print(f"city-сущностей в базе: {len(cities)}")
for e in sorted(cities, key=lambda x: x['eid']):
    a = e.get('attrs') or {}
    print(f"  {e['eid']}: own={e.get('is_own')} owner={e.get('owner')} name={e.get('name')} "
          f"x={a.get('x')} y={a.get('y')} size={a.get('size')}")
print("\nвладельцы_юнитов (мир):", (d.get('world') or {}).get('владельцы_юнитов'))
print("games:", (d.get('world') or {}).get('games'))
