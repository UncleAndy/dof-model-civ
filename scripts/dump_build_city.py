import json
p = '/home/hermes/projects/AI/DOF-MODEL-CIV/tests/fixtures/real_available_actions.json'
d = json.load(open(p))
for ctrl, actors in d.items():
    print('== ctrl', ctrl, 'actors', len(actors) if isinstance(actors, dict) else type(actors))
    if ctrl != 'unit':
        continue
    for aid, actions in actors.items():
        for name, params in actions.items():
            if params and ('city' in name or 'found' in name or 'settle' in name):
                print(' ', aid, '|', name, '|', json.dumps(params, ensure_ascii=False)[:400])
