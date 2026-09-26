"""Dump the ruleset description the stand itself publishes (obs['rules']).

The game hands over its own rules text/structures, which is a better source than
any external document: it describes THIS stand's ruleset (civ2civ3).

Usage: .venv/bin/python scripts/inspect_rules.py [fixture.json]
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/real_obs_01.json'
recs = json.load(open(path))
obs = recs[0]['observation']
rules = obs.get('rules')

print('type:', type(rules).__name__)
if isinstance(rules, dict):
    print('keys:', list(rules)[:40])
    for key, value in rules.items():
        kind = type(value).__name__
        preview = ''
        if isinstance(value, (str, int, float, bool)):
            preview = repr(value)[:200]
        elif isinstance(value, dict):
            preview = f'{len(value)} entries; sample={list(value)[:6]}'
        elif isinstance(value, (list, tuple)):
            preview = f'{len(value)} items; sample={[str(v)[:60] for v in value[:4]]}'
        print(f'  {key:<28} {kind:<6} {preview}')
else:
    print(repr(rules)[:2000])

# Anything anywhere that mentions the city work space or resources.
blob = json.dumps(rules, ensure_ascii=False, default=str)
for needle in ('radius', 'granary', 'worked', 'special', 'resource', 'wheat',
               'oasis', 'mine', 'irrigation', 'center', 'centre', 'corrupt'):
    idx = blob.lower().find(needle)
    if idx >= 0:
        print(f'  ...{needle}: {blob[max(0, idx - 90):idx + 120]!r}')
