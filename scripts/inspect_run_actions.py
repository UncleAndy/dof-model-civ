"""Print the actions an agent actually issued in a saved tournament result."""
import json
import sys
from collections import Counter

path = sys.argv[1]
want = sys.argv[2] if len(sys.argv) > 2 else 'random'
data = json.load(open(path))
results = data.get('results', data)
for agent, eps in results.items():
    if want and agent != want:
        continue
    for ep in eps:
        print('=' * 70)
        print(f"agent={agent} turns={ep.get('turns')} index={ep.get('final_total_dof_index')} "
              f"actions={ep.get('actions_issued')} skipped_turns={ep.get('skipped_turns')} "
              f"err={ep.get('error')}")
        fams = Counter()
        for d in ep.get('decisions') or []:
            act = d.get('action')
            if isinstance(act, (list, tuple)):
                act = act[-1]
            fams[str(act)] += 1
        for fam, n in fams.most_common(20):
            print(f'    {fam:<44} {n}')
        series = ep.get('series') or []
        if series:
            print('    index series:', [round(s.get('total_dof_index', 0), 2) for s in series[:10]])
            print('    entities:', [s.get('entity_count') for s in series[:10]])
