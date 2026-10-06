"""Замер: помнит ли МИР открытые клетки, или память придётся вести нам.

**Вопрос владельца модели.** Нужна ли агенту память о параметрах открытых клеток. Прежде чем её
заводить, надо выяснить, не ведёт ли эту память сам мир: если наблюдение присылает клетки, которые мы
видели раньше и сейчас не видим, — копировать нечего, а если не присылает — хранить придётся нам, со
сроком давности по §3.4.2 («the resource map **with its staleness**»).

**Что прибор делает.** Гоняет стенд, двигает наших юнитов (СЦЕНАРИЙ, не поведение модели) и на каждом
ходу печатает:
* структуру `obs["map"]`: ключи, типы, примеры — без догадок о том, чего не видел;
* гистограмму значений `map.status` (если он есть) — чтобы узнать, различает ли мир «видно сейчас» и
  «видели раньше»;
* число клеток, известных миру по каждому состоянию, и растёт ли это множество от хода к ходу.

Если множество известных клеток растёт и **не сжимается**, когда юниты уходят, — мир ведёт память сам.
Это и будет ответ; никаких выводов «по смыслу» прибор не делает.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civrealm" / "src"))
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

DIRS = ["goto_1", "goto_3", "goto_5", "goto_7", "goto_0", "goto_2", "goto_4", "goto_6"]


def _shape(value: Any, tag: str) -> str:
    """Короткое описание структуры — без догадок: то, что реально лежит."""
    if isinstance(value, dict):
        keys = list(value)[:5]
        if not keys:
            return f"{tag}: dict(0)"
        return f"{tag}: dict({len(value)}), первые ключи {keys}, пример {value[keys[0]]!r}"[:300]
    if isinstance(value, list):
        head = value[0] if value else None
        return f"{tag}: list({len(value)}), [0] = {str(head)[:140]}"
    return f"{tag}: {type(value).__name__} = {str(value)[:120]}"


def _as_grid(value: Any) -> Any:
    """Привести значение к двумерной сетке — в наблюдении это `numpy.ndarray`, не список.

    Первый заход прибора проверял списки и вернул нули по всем ходам: числа лежали в `ndarray`,
    и проверка `isinstance(..., list)` их не видела. Ошибка была молчаливой — прибор печатал «клеток
    знает 0» так, будто мир пуст.
    """
    try:
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        arr = np.asarray(value)
    except Exception:  # noqa: BLE001
        return None
    return arr if arr.ndim >= 2 else None


def _grid_histogram(grid: Any, limit: int = 8) -> dict[str, int]:
    """Сколько клеток каждого состояния (значения — как есть, без переименования)."""
    import numpy as np  # noqa: PLC0415

    values, counts = np.unique(grid, return_counts=True)
    return {str(v): int(c) for v, c in list(zip(values, counts))[:limit]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Помнит ли мир открытые клетки")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=9440)
    ap.add_argument("--turns", type=int, default=5)
    a = ap.parse_args()

    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = a.port
    fc_args["debug.take_screenshot"] = False
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=a.port, seed=a.seed)

    unknown_markers = {"0", "None", "", "-", "unknown", "UNKNOWN", "none", "False"}
    ever_known: set = set()
    rows: list[dict[str, Any]] = []
    print(f"[память мира] сид {a.seed}, порт {a.port}; юниты двигаются — СЦЕНАРИЙ", flush=True)
    for i in range(a.turns):
        turn = (info or {}).get("turn")
        mp = (obs or {}).get("map") or {}
        print(f"\n[ход {turn}] ключи map: {sorted(mp)[:12]}", flush=True)
        for key in sorted(mp)[:12]:
            if key in ("terrain", "status", "extras", "output", "tile_owner", "unit_owner",
                       "city_owner", "xsize", "ysize"):
                print(f"    {_shape(mp[key], key)}", flush=True)
        status = mp.get("status")
        grid = _as_grid(status)
        if grid is None:
            print("    status: не двумерная сетка — считать нечем", flush=True)
            known: set = set()
            hist: dict[str, int] = {}
        else:
            import numpy as np  # noqa: PLC0415
            hist = _grid_histogram(grid)
            print(f"    status: shape {grid.shape}, состояния {hist}", flush=True)
            known = {(int(x), int(y)) for x, y in np.argwhere(grid != 0)}
        grew = len(known - ever_known)
        shrank = len(ever_known - known)
        ever_known |= known
        rows.append({"ход": turn, "status_видов": hist, "клеток_известно_миру": len(known),
                     "прибавилось": grew, "пропало": shrank, "за_все_ходы": len(ever_known)})
        print(f"    клеток мир знает: {len(known)} (+{grew}, пропало {shrank}); "
              f"за все ходы видели: {len(ever_known)}", flush=True)
        units = ((info or {}).get("available_actions") or {}).get("unit") or {}
        moved = 0
        for actor in sorted(units):
            names = units[actor] or {}
            for cand in (DIRS[(i + moved) % len(DIRS)], *DIRS):
                if cand in names and names[cand]:
                    env.step(("unit", actor, cand))
                    moved += 1
                    break
        print(f"    [сценарий] шагов отправлено: {moved}", flush=True)
        obs, _r, term, trunc, info = env.step(None)
        if not obs or term or trunc:
            print("мир закрыл партию — останавливаюсь", flush=True)
            break

    out = ROOT / "knowledge" / f"map_memory_{a.seed}_port{a.port}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[память мира] строк {len(rows)}; записано {out}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
