"""Замер: добавляет ли открытие клеток наблюдаемые переходы и измеримый DoF.

**Зачем этот прибор.** Вопрос поставлен нормативно: разведку можно мотивировать только измерением.
Стандарт (§4.6) относит и горизонт счёта, и определение вектора реакции к **декларации**, а §4.2
запрещает считать величину потому, что её упомянул кандидат («generator-dependent witness … in
arithmetic form»). Значит вопрос сводится к измеримому и проверяемому: **появляются ли в наблюдённом
графе новые переходы, доступные нашим сущностям, когда сходит туман, и растёт ли от этого их DoF**.

**Что прибор делает.** Гоняет ту же стойку (`spec_obs.measure_step`), что и живой прогон, и на каждом
ходу печатает: сколько клеток видно, сколько переходов доступно каждой нашей сущности, какие действия
появились у той же сущности против прошлого хода и как при этом изменился её `DoF`.
Наши юниты **двигаются** — это СЦЕНАРИЙ открытия клеток, а не поведение модели, и в выводе так и
подписано. В мир отправляются только шаги `goto_*`; ядро решений не принимает и ничего не выбирает.

**Чего прибор не делает.** Он ничего не меняет в мере. Если окажется, что новые клетки не приносят
новых переходов, это будет факт о мере, и его надо назвать, а не подпереть коэффициентом.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civrealm" / "src"))
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from env import spec_lenses as L  # noqa: E402
from env import spec_obs as SO  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402

#: Направления по кругу: сценарий снимает туман равномерно во все стороны.
DIRS = ["goto_1", "goto_3", "goto_5", "goto_7", "goto_0", "goto_2", "goto_4", "goto_6"]


def _tiles(obs: dict) -> tuple[int, str]:
    """Сколько клеток видно и откуда взято число (источник называется, чтобы не выдумывать)."""
    mp = obs.get("map") or {}
    if isinstance(mp, dict):
        for key in ("tile", "tiles", "terrain"):
            inner = mp.get(key)
            if isinstance(inner, dict) and inner:
                return len(inner), f"map.{key}"
        return 0, f"нет map.tile (ключи map: {sorted(mp)[:10]})"
    return 0, f"map не словарь, а {type(mp).__name__}"


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Замер: открытие клеток против наблюдаемых переходов")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=9410)
    ap.add_argument("--turns", type=int, default=8)
    return ap.parse_args()


def main() -> int:
    a = _args()
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = a.port
    fc_args["debug.take_screenshot"] = False      # прибор ничего не снимает: он мерит
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=a.port, seed=a.seed)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    extractor = GameStateExtractor(my_player_id=own_id)

    prev_menus: dict[str, set[str]] = {}
    rows: list[dict[str, Any]] = []
    print(f"[замер] сид {a.seed}, порт {a.port}, наш игрок {own_id}; "
          f"юниты двигаются — СЦЕНАРИЙ снятия тумана, не поведение модели", flush=True)
    for i in range(a.turns):
        turn = (info or {}).get("turn")
        m = SO.measure_step(obs, info, turn, extractor, prev_obs=None, my_player_id=own_id)
        tiles, tile_src = _tiles(obs)
        menus = {eid: set(names) for eid, names in (m["raw_menus"] or {}).items()
                 if eid.startswith(("unit_", "city_"))}
        appeared: dict[str, list[str]] = {}
        for eid, names in menus.items():
            old = prev_menus.get(eid)
            if old is None:
                continue
            fresh = sorted(names - old)
            if fresh:
                appeared[eid] = fresh
        dofs = {eid: round(float(m["dof"][eid]), 4) for eid in sorted(menus) if eid in (m["dof"] or {})}
        powers = L.foreign_powers(obs, own_id)
        counters = {}
        for eid, names in menus.items():
            kind = L.entity_type_of(eid)
            v_env = L.disturbance_count(SO.disturbances(obs, eid, kind, own_id),
                                        foreign_powers=powers)
            counters[eid] = {"V": L.response_vector_count(names), "V_env": v_env}
        rows.append({"ход": turn, "клеток": tiles, "откуда_клетки": tile_src,
                     "переходов": {eid: len(n) for eid, n in sorted(menus.items())},
                     "счётчики": counters, "держав_видно": len(powers),
                     "появились": appeared, "dof": dofs, "индекс": float(m["index"])})
        print(f"\n[ход {turn}] клеток видно {tiles} ({tile_src}) | индекс {float(m['index']):.4f} | "
              f"держав видно {len(powers)}", flush=True)
        for eid in sorted(menus):
            d, c = m["dof"].get(eid), counters[eid]
            met = (m["measured"] or {}).get(eid)
            shares = ""
            if met is not None:
                parts = []
                for key in ("psi_var", "psi_opt", "psi_con"):
                    if hasattr(met, key):
                        parts.append(f"{key[4:]} {round(float(getattr(met, key)), 4)}")
                if parts:
                    shares = " | ψ: " + ", ".join(parts)
            print(f"    {eid}: переходов {len(menus[eid])}, V(меню) {c['V']}, "
                  f"V(стейта) {m['counts'].get(eid)}, V_env {c['V_env']}, "
                  f"DoF {'—' if d is None else round(float(d), 4)}{shares}", flush=True)
        for eid, fresh in sorted(appeared.items()):
            print(f"    НОВЫЕ переходы у {eid}: {fresh[:8]}", flush=True)
        prev_menus = menus

        # Сценарий: по одному шагу каждым нашим юнитом, направление меняется по кругу.
        units = ((info or {}).get("available_actions") or {}).get("unit") or {}
        moved = 0
        for actor in sorted(units):
            names = units[actor] or {}
            want = DIRS[(i + moved) % len(DIRS)]
            for cand in (want, *DIRS):
                if cand in names and names[cand]:
                    env.step(("unit", actor, cand))
                    moved += 1
                    break
        print(f"    [сценарий] шагов отправлено: {moved}", flush=True)
        obs, _r, term, trunc, info = env.step(None)
        if not obs or term or trunc:
            print("мир закрыл партию — останавливаюсь", flush=True)
            break

    out = ROOT / "knowledge" / f"explore_{a.seed}_port{a.port}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[замер] строк: {len(rows)}; записано {out}", flush=True)
    total_new = sum(len(v) for r in rows for v in r["появились"].values())
    print(f"[замер] всего появившихся переходов у наших сущностей: {total_new}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
