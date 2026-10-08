import json, glob
rows = []
for f in sorted(glob.glob('knowledge/ab_scout_only*.jsonl')):
    for ln in open(f):
        ln = ln.strip()
        if not ln:
            continue
        rows.append((f, json.loads(ln)))
for f, d in rows:
    print(f.split('/')[-1], d['seed'], d['arm'], 'turns', d.get('turns'), 'asked', d.get('turns_asked'), 'score', d.get('score'), 'exit', d.get('exit'))
