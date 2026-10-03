import json, sys, collections
path = sys.argv[1]
per = collections.defaultdict(lambda: {"город": set(), "своих_ходов": 0})
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    p = d.get("партия")
    per[p]["город"].add(d.get("город"))
    if d.get("свой"):
        per[p]["своих_ходов"] += 1
for p in sorted(per):
    print(f"партия {p}: городов в журнале {len(per[p]['город'])} -> "
          f"{sorted(per[p]['город'])}; ходов со своим городом {per[p]['своих_ходов']}")