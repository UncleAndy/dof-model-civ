import json, math
d = json.load(open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/world.json'))
obs = d.get('observed') or {}

def med(chan, filt=None):
    rows = obs.get(chan) or []
    vals = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if filt and any(r.get(k) != v for k, v in filt.items()):
            continue
        for key in ('значение', 'value', 'dof', 'DoF'):
            if key in r and isinstance(r[key], (int, float)):
                vals.append(float(r[key]))
    if not vals:
        return None, 0
    vals.sort()
    return vals[len(vals)//2], len(vals)

r1 = med('dof_city_reach', {'размер': 1})
print('dof_city_reach (размер 1):', r1)
print('dof_city_reach (любой):   ', med('dof_city_reach'))
print('city_own_families (разм 1):', med('city_own_families', {'размер': 1}))
print('city_own_families (люб):   ', med('city_own_families'))
print('city_size_buildable (разм1):', med('city_size_buildable', {'размер': 1}))
if r1[0]:
    print('ln(DoF города) при dof_city_reach=', r1[0], '→ ln =', round(math.log(r1[0]), 3))