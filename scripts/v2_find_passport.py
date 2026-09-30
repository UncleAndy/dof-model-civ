"""Где в наблюдении лежит паспорт типа юнита (атака, цена) — ищем по всем секциям."""
import json

d = json.load(open("/tmp/v2_late_9000.json"))
obs = d["observation"]


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node[:200]):
            walk(v, f"{path}[{i}]")
    else:
        s = str(node)
        if s in ("Warriors", "Settlers"):
            print(f"  {path} = {s}")


print("где встречается Warriors/Settlers:")
walk(obs)
print("\nключи tech-записи (первая):")
tech = obs.get("tech") or {}
if tech:
    k0 = next(iter(tech))
    t = tech[k0]
    print(" ", k0, sorted(t.keys()))
    for key in ("sup_units", "sup_improvements"):
        v = t.get(key)
        if v:
            print(f"  {key}[0] =", json.dumps(v[0], ensure_ascii=False)[:300])