import json, glob, collections
keys = collections.Counter()
rows = collections.Counter()
sample = None
for f in sorted(glob.glob('knowledge/ab_scout_only*.jsonl')):
    n = 0
    for ln in open(f):
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        n += 1
        if sample is None:
            sample = d
    print(f, n)
print('KEYS', list(sample.keys()))
print('SAMPLE', json.dumps(sample, ensure_ascii=False)[:2000])
