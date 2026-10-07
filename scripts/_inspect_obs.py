"""Осмотр наблюдения: какие слои карты и какие действия в меню нам вообще доступны.

Нужен ровно для того, чтобы инструмент разведки записывал «что открылось» по настоящим именам полей,
а не по моим догадкам (сегодня уже дважды правил вслепую — хватит). Ничего не меняет, только читает.
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


def main() -> int:
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = 6004
    fc_args["aifill"] = 8
    fc_args["debug.take_screenshot"] = False
    fc_args["debug.headless"] = True
    fc_args["debug.global_view_screenshot"] = False

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=6004, seed=9410)
    print("── верхние ключи наблюдения ──")
    print(sorted(obs.keys()))
    m = obs.get("map") or {}
    print("── слои карты ──")
    for k, v in m.items():
        try:
            shape = (len(v), len(v[0])) if hasattr(v, "__len__") and len(v) and hasattr(v[0], "__len__") else np_shape(v)
        except Exception:  # noqa: BLE001
            shape = "?"
        print(f"  {k}: тип {type(v).__name__}, форма {shape}")
    st = m.get("status")
    if st is not None:
        row = list(st[24]) if len(st) > 24 else list(st[0])
        print("  пример строки status:", json.dumps([int(x) for x in row])[:120])
    for k, v in m.items():
        if k == "status" or not hasattr(v, "__len__") or not len(v):
            continue
        try:
            row = list(v[24]) if len(v) > 24 else list(v[0])
            print(f"  пример строки {k}:", json.dumps([int(x) if not isinstance(x, str) else x for x in row])[:120])
        except Exception:  # noqa: BLE001
            pass
    print("── меню действий ──")
    aa = (info or {}).get("available_actions") or {}
    print("  контроллеры:", sorted(aa.keys()))
    for ctrl in ("unit", "city", "turn"):
        block = aa.get(ctrl) or {}
        if isinstance(block, dict) and block:
            k0 = sorted(block)[0]
            names = block[k0]
            names = list(names.keys()) if isinstance(names, dict) else list(names)
            print(f"  {ctrl}[{k0}]: {len(names)} действий, первые:", sorted(names)[:10])
    print("── юниты и города ──")
    u = obs.get("unit") or {}
    if u:
        k0 = sorted(u)[0]
        print(f"  unit[{k0}] поля:", sorted(u[k0].keys()) if isinstance(u[k0], dict) else type(u[k0]).__name__)
    c = obs.get("city") or {}
    print(f"  городов в наблюдении: {len(c)}")
    env.close()
    return 0


def np_shape(v):
    try:
        return tuple(v.shape)  # numpy
    except Exception:  # noqa: BLE001
        return "?"


if __name__ == "__main__":
    raise SystemExit(main())