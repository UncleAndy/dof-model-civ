import json, sys, hashlib
p = sys.argv[1]
d = json.load(open(p))
print("файл:", p)
print("размер:", __import__("os").path.getsize(p), "байт")
print("md5:", hashlib.md5(open(p, "rb").read()).hexdigest())
print("ключи:", sorted(d.keys())[:14])
print("games:", d.get("games"))
obs = d.get("observations")
print("наблюдений:", len(obs) if isinstance(obs, (list, dict)) else obs)
ent = d.get("entities")
if isinstance(ent, dict):
    print("сущностей:", len(ent))