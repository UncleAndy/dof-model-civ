"""List the REAL action vocabulary from the captured live observation fixture."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/real_obs_01.json'
recs = json.load(open(path))
info = recs[0]['info']
avail = info.get('available_actions', {})
for ctrl in ('city', 'unit', 'tech', 'player'):
    actors = avail.get(ctrl, {})
    names = set()
    for actor, acts in actors.items():
        if isinstance(acts, dict):
            names.update(acts.keys())
        elif isinstance(acts, list):
            names.update(str(n) for n in acts)
    print(f'== {ctrl}: actors={len(actors)} names={len(names)}')
    # family prefixes (first two underscore-joined tokens)
    fams = {}
    for n in names:
        parts = n.split('_')
        fam = '_'.join(parts[:2]) if len(parts) > 1 else n
        fams.setdefault(fam, []).append(n)
    for fam, members in sorted(fams.items()):
        print(f'   {fam:<34} n={len(members):<4} e.g. {sorted(members)[:3]}')
