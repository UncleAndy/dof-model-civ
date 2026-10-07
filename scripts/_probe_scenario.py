"""Пробник сцены: сколько у нас «незнания» под туманом и есть ли скрытые соперники.

Отвечает на два вопроса, оба — до всякой правки модели:
1. какую долю карты наша сторона действительно видит под туманом (прежде я называл 4035/4056, но то
   измерение похоже на вид наблюдателя, а не наш — проверяю честно);
2. появляются ли в нашем поле зрения чужие (владельцы в `map.unit_owner`, кроме 255 и нашего id) и
   когда именно: если соперники скрыты и обнаруживаются лишь к середине партии — сцена годится для
   проверки «незнание становится знанием».

Две сцены за один прогон: `aifill` 4 (как сейчас) и 8 (больше скрытых соперников). Ходов по 20 —
пассивно, без решений: смотрим мир, а не себя.
"""
import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "knowledge" / "scenario_probe.jsonl"


def probe(port: int, seed: int, aifill: int, turns: int, fog: bool = True) -> dict:
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = port
    fc_args["aifill"] = aifill
    fc_args["debug.take_screenshot"] = False
    fc_args["debug.headless"] = True
    fc_args["debug.global_view_screenshot"] = not fog

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port, seed=seed)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0

    seen_owners: set = set()
    rows = []
    for t in range(turns):
        m = (obs or {}).get("map") or {}
        st = m.get("status")
        own = m.get("unit_owner")
        revealed = area = 0
        if st is not None:
            flat = [int(v) for row in st for v in row]
            area = len(flat)
            revealed = sum(1 for v in flat if v == 2)
        if own is not None:
            for row in own:
                for v in row:
                    iv = int(v)
                    if iv not in (255, own_id):
                        seen_owners.add(iv)
        units = ((obs or {}).get("unit") or {})
        my_units = sum(1 for u in units.values() if isinstance(u, dict) and int(u.get("owner", -1)) == own_id)
        cities = ((obs or {}).get("city") or {})
        my_cities = sum(1 for c in cities.values() if isinstance(c, dict) and int(c.get("owner", -1)) == own_id)
        rows.append({"ход": t, "открыто": revealed, "площадь": area,
                     "чужих_владельцев": sorted(seen_owners), "своих_юнитов": my_units,
                     "своих_городов": my_cities})
        obs, _r, term, trunc, info = env.step(None)
        if term or trunc:
            break
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass

    first, last = rows[0], rows[-1]
    res = {"сцена": f"aifill={aifill}", "порт": port, "сид": seed, "ходов": len(rows),
           "own_id": own_id,
           "открыто_в_начале": first["открыто"], "открыто_в_конце": last["открыто"],
           "площадь": last["площадь"] or first["площадь"],
           "доля_в_конце": (round(100.0 * last["открыто"] / last["площадь"], 1) if last["площадь"] else None),
           "чужих_владельцев_увидели": sorted(seen_owners),
           "своих_городов_в_конце": last["своих_городов"]}
    print(json.dumps(res, ensure_ascii=False), flush=True)
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=20)
    a = ap.parse_args()
    got = []
    for aifill, port, seed in ((4, 6000, 9400), (8, 6004, 9401)):
        try:
            got.append(probe(port, seed, aifill, a.turns))
        except Exception as exc:  # noqa: BLE001
            print(f"сцена aifill={aifill}: упало — {type(exc).__name__}: {exc}", flush=True)
    with OUT.open("a", encoding="utf-8") as fh:
        for r in got:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("записано в", OUT)