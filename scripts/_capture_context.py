"""Что делали наши военные рядом с городом в ходах ПЕРЕД его захватом."""
import json, sys, collections
trace = sys.argv[1]
deflog = sys.argv[2]

# 1) моменты захвата: город сменил owner с нашего
rows = [json.loads(l) for l in open(deflog) if l.strip()]
capture = {}
own = collections.defaultdict(set)
owners = collections.defaultdict(set)
for r in rows:
    owners[r['город']].add(r['owner'])
    if r['свой']:
        own[r['город']].add(r['ход'])
for c, o in owners.items():
    if own.get(c) and any(x != 0 for x in o):
        capture[c] = max(own[c])
print("захваченные города и последний наш ход:", capture)

# 2) выбранные действия наших военных рядом с этими городами
# соберём позиции городов из deflog
pos = {}
for r in rows:
    pos[r['город']] = (r['x'], r['y'])

recs = []
for l in open(trace):
    try:
        recs.append(json.loads(l))
    except Exception:
        pass

def cheb(a, b):
    return max(abs(a[0]-b[0]), abs(a[1]-b[1]))

window = 6
for c, tcap in capture.items():
    if c not in pos:
        continue
    cx, cy = pos[c]
    print(f"\n=== {c} @ ({cx},{cy}), захвачен после хода {tcap} ===")
    cnt = collections.Counter()
    for d in recs:
        t = d.get('ход')
        if not isinstance(t, int) or not (tcap - window <= t <= tcap):
            continue
        ch = d.get('выбрано') or {}
        for s in (ch.get('steps') or []):
            a = s.get('action') or ''
            cnt[a.split('_')[0]] += 1
    print("   действия в окне:", dict(cnt.most_common(10)))
