"""Замер факта (фальсификация tau-приора, §10.60): ход первого чужого юнита и первого подхода к нашему городу.

Читает state.jsonl уже собранных серий. Только чтение.
"""
import json, sys, glob, os
from collections import defaultdict

def xy(rec):
    if isinstance(rec, dict):
        return rec.get("x"), rec.get("y")
    if isinstance(rec, (list, tuple)) and len(rec) >= 2:
        return rec[0], rec[1]
    return None, None

def scan(path):
    per_ep = defaultdict(lambda: dict(first_foreign=None, first_adjacent=None,
                                      max_foreign=0, last_turn=0, types={}))
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ep = r.get("эпизод")
            turn = r.get("turn")
            d = per_ep[ep]
            if isinstance(turn, int):
                d["last_turn"] = max(d["last_turn"], turn)
            fu = r.get("foreign_units") or []
            mc = r.get("my_cities") or []
            d["max_foreign"] = max(d["max_foreign"], len(fu))
            if fu:
                if d["first_foreign"] is None or (isinstance(turn, int) and turn < d["first_foreign"]):
                    d["first_foreign"] = turn
                for u in fu:
                    tn = u.get("type_rule_name") if isinstance(u, dict) else None
                    d["types"][tn] = d["types"].get(tn, 0) + 1
                # близость к нашему городу
                for u in fu:
                    ux, uy = xy(u)
                    for c in mc:
                        cx, cy = xy(c)
                        if None in (ux, uy, cx, cy):
                            continue
                        if max(abs(ux - cx), abs(uy - cy)) <= 1:
                            if d["first_adjacent"] is None or (isinstance(turn, int) and turn < d["first_adjacent"]):
                                d["first_adjacent"] = turn
    return per_ep

def report(path):
    per_ep = scan(path)
    ff = [d["first_foreign"] for d in per_ep.values() if d["first_foreign"] is not None]
    fa = [d["first_adjacent"] for d in per_ep.values() if d["first_adjacent"] is not None]
    print(f"\n== {os.path.basename(path)} ==")
    print(f"  эпизодов: {len(per_ep)}; с чужими юнитами: {len(ff)}/{len(per_ep)}")
    if ff:
        ff_s = sorted(ff)
        print(f"  ход первого чужого юнита: min={ff_s[0]} медиана={ff_s[len(ff_s)//2]} max={ff_s[-1]}")
    if fa:
        fa_s = sorted(fa)
        print(f"  ход первого подхода (<=1 клетки): min={fa_s[0]} медиана={fa_s[len(fa_s)//2]} max={fa_s[-1]}")
    else:
        print("  подходов вплотную не зафиксировано")
    allt = defaultdict(int)
    for d in per_ep.values():
        for t, n in d["types"].items():
            allt[t] += n
    if allt:
        print("  типы чужих юнитов:", dict(sorted(allt.items(), key=lambda kv: -kv[1])))

if __name__ == "__main__":
    pats = sys.argv[1:] or ["/tmp/h300q_*.json.state.jsonl", "/tmp/h300r_*.json.state.jsonl"]
    files = []
    for p in pats:
        files += sorted(glob.glob(p))
    for p in files:
        try:
            report(p)
        except Exception as e:
            print(f"{os.path.basename(p)}: ОШИБКА {type(e).__name__} {e}")