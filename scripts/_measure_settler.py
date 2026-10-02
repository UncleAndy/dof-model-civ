import json
d = json.load(open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/world.json'))
for e in d.get('entities', []):
    if isinstance(e, dict) and e.get('kind') == 'unit_type' and e.get('name') == 'Settlers':
        print('Settlers unit_type:', {k: e.get(k) for k in ('name', 'dof_families', 'dof')})
        break
else:
    print('не найдено; ищу unit_type с build_city:')
    for e in d.get('entities', []):
        if isinstance(e, dict) and e.get('kind') == 'unit_type':
            attrs = e.get('attrs') or {}
            caps = attrs.get('caps') or attrs.get('abilities') or []
            if 'build_city' in str(caps):
                print(e.get('name'), {k: e.get(k) for k in ('name', 'dof_families', 'dof')})