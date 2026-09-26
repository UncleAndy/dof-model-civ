"""Report which live actions are valid, by controller and family."""
import json
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/real_available_actions.json'
data = json.load(open(path))
avail = data[0]['info']['available_actions'] if isinstance(data, list) else data
if 'available_actions' in avail:
    avail = avail['available_actions']

for ctrl, actors in avail.items():
    valid_names = []
    for actor, acts in actors.items():
        if isinstance(acts, dict):
            valid_names += [n for n, p in acts.items() if p]
        elif isinstance(acts, list):
            valid_names += [str(n) for n in acts]
    fams = Counter('_'.join(n.split('_')[:2]) if n.count('_') else n
                   for n in valid_names)
    print(f'== {ctrl}: actors={len(actors)} valid={len(valid_names)}')
    for fam, n in sorted(fams.items(), key=lambda kv: -kv[1])[:12]:
        print(f'    {fam:<34} {n}')
    if ctrl == 'tech':
        rs = [n for n in valid_names if n.startswith('research_tech')]
        print(f'    research_tech valid: {len(rs)}; first 5: {sorted(rs)[:5]}')
        print(f'    set_tech_goal   valid: '
              f'{len([n for n in valid_names if n.startswith("set_tech_goal")])}')
