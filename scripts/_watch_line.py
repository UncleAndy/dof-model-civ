import json, glob, os, time, subprocess, datetime

now = int(time.time())
traces = glob.glob('knowledge/live_trace_952*.jsonl')
newest = max(traces, key=os.path.getmtime) if traces else None
age_min = int((now - os.path.getmtime(newest)) / 60) if newest else 9999

# valid closed pairs: seed has BOTH A and B with a real run (turns>=150, exit==0)
best = {}
for f in sorted(glob.glob('knowledge/ab_scout_only*.jsonl')):
    for ln in open(f):
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        key = (d['seed'], d['arm'])
        turns = int(d.get('turns') or 0)
        old = best.get(key)
        if old is None or turns > int(old.get('turns') or 0):
            best[key] = d

seeds = sorted({k[0] for k in best})
closed = 0
for s in seeds:
    a = best.get((s, 'A'))
    b = best.get((s, 'B'))
    if a and b and int(a.get('turns') or 0) >= 150 and int(b.get('turns') or 0) >= 150:
        closed += 1

alive = 'мёртв'
pids = subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True).stdout
if 'v011_live_run.py' in pids or 'v011_ab_city_norm.py' in pids:
    alive = 'жив' if age_min <= 20 else 'ВСТАЛ'

stamp = datetime.datetime.utcnow().strftime('%H:%M')
line = f"{stamp} | {alive} | запись {age_min} мин назад | пар {closed}/5 | вердикт: нет"
print(line)
print('newest_trace', newest, 'age_min', age_min)
with open('/home/hermes/watch_line.log', 'a', encoding='utf-8') as fh:
    fh.write(line + "\n")
