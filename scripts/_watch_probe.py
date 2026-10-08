import json, glob, os, datetime, time, subprocess

now = time.time()
files = sorted(glob.glob('knowledge/live_trace_952*.jsonl'), key=os.path.getmtime, reverse=True)
for p in files[:6]:
    lines = open(p).read().splitlines()
    age = None
    last = None
    if lines:
        try:
            d = json.loads(lines[-1])
            last = d
        except Exception as e:
            last = {'err': str(e)}
    # mtime age in minutes
    mage = (now - os.path.getmtime(p)) / 60.0
    print('==', p, 'lines=', len(lines), 'mtime_age_min=%.1f' % mage)
    if last is not None:
        keys = ('turn', 'turns', 'step', 'ts', 'time', 'timestamp', 'done', 'finished')
        print('   last:', {k: last.get(k) for k in keys if k in last})

print('=== ab files ===')
for f in sorted(glob.glob('knowledge/ab_scout_only*.jsonl')):
    print('--', f)
    rows = []
    for ln in open(f):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception as e:
            print('  parse err', e)
    for r in rows:
        print('   ', {k: r.get(k) for k in ('seed', 'arm', 'side', 'turns', 'turn') if k in r})