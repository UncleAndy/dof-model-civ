"""Сканирует все сохранённые наблюдения: есть ли в секции `unit` чужие юниты и что показывает
карта мира (`map.unit_owner`). Нужно решить, каким каналом считать угрозу."""
import glob
import json
import os
import sys

FILES = (sys.argv[1:] or
         ["tests/fixtures/real_obs_01.json", "/tmp/v2_capture_seed9000.json",
          "/tmp/h300q_0.json", "/tmp/h300q_1.json", "/tmp/h300r_0.json",
          "/tmp/c300_base.json", "/tmp/v300_0.json"])

for path in FILES:
    if not os.path.exists(path):
        print(f"{os.path.basename(path)}: файла нет")
        continue
    try:
        d = json.load(open(path))
    except Exception as exc:  # noqa: BLE001
        print(f"{os.path.basename(path)}: не разобрать ({exc})")
        continue
    obs = d.get("observation") if isinstance(d, dict) else None
    if obs is None and isinstance(d, list):
        # файл-список наблюдений: смотрим каждое, ищем хоть одно с чужим
        found = False
        for item in d:
            o = item.get("observation") if isinstance(item, dict) else None
            if not isinstance(o, dict):
                continue
            units = o.get("unit") or {}
            own = item.get("my_id")
            foreign = [u for u in units.values() if u.get("owner") not in (None, own)]
            if foreign:
                print(f"{os.path.basename(path)}: НАЙДЕН чужой в секции unit — "
                      f"{json.dumps(foreign[0], ensure_ascii=False)[:300]}")
                found = True
                break
        if not found:
            print(f"{os.path.basename(path)}: записей {len(d)}, ни в одной нет чужого в секции unit")
        continue
    if not isinstance(obs, dict) or "unit" not in obs:
        print(f"{os.path.basename(path)}: не похоже на наблюдение (ключи: "
              f"{sorted(obs.keys())[:6] if isinstance(obs, dict) else type(obs).__name__})")
        continue
    units = obs.get("unit") or {}
    owners: dict = {}
    for u in units.values():
        owners[u.get("owner")] = owners.get(u.get("owner"), 0) + 1
    m = obs.get("map") or {}
    uo = m.get("unit_owner")
    map_owners: dict = {}
    if uo is not None:
        def walk(node):
            if isinstance(node, (list, tuple)):
                for x in node:
                    walk(x)
            else:
                try:
                    map_owners[int(node)] = map_owners.get(int(node), 0) + 1
                except Exception:  # noqa: BLE001
                    map_owners[str(node)] = map_owners.get(str(node), 0) + 1
        walk(uo)
    print(f"{os.path.basename(path)}: секция unit -> владельцы {owners} | "
          f"map.unit_owner -> {dict(sorted(map_owners.items(), key=lambda kv: -kv[1])[:6])}")