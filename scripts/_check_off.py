import json
path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_off.jsonl'
tot = 0
src_gt0 = 0
disp = 0
for line in open(path):
    try:
        d = json.loads(line)
    except Exception:
        continue
    tot += 1
    p = d.get('потенциальные') or {}
    if (p.get('источников') or 0) > 0:
        src_gt0 += 1
    if 'встаём вплотную' in line:
        disp += 1
print(f"строк={tot}; потенциальные.источников>0: {src_gt0}; упоминаний 'встаём вплотную': {disp}")