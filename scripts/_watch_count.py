import json, glob, os
closed = {}
for f in sorted(glob.glob('knowledge/ab_scout_only*.jsonl')):
    for ln in open(f):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        s = d.get('seed')
        arm = d.get('arm') or d.get('side') or d.get('env') or d.get('плечо')
        closed.setdefault(s, set()).add(str(arm))
k = 0
for s in sorted(closed):
    arms = closed[s]
    pair_no = s - 9519 if isinstance(s, int) else '?'
    both = ('A' in arms and 'B' in arms)
    if both:
        k += 1
    print('seed', s, 'arm', sorted(arms), 'closed' if both else '')
print('CLOSED', k)
