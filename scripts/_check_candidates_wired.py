"""Сквозная проверка проводки кандидатов (§13.70): синтетика по правилам владельца.

Проверяем ровно то, что подключено в `env/entity_extractor.py`: агрегатор
`observe_candidates` поверх правил §13.64. Положительный контроль (кандидат находится) и
отрицательный (мир молчит — кандидатов нет, но ПРИЧИНА названа).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_collapse_candidates as CC  # noqa: E402

EMPTY = 255


def grid(size, cells):
    g = [[EMPTY] * size for _ in range(size)]
    for (x, y), v in cells.items():
        g[y][x] = v
    return g


def status_grid(size, open_cells):
    g = [[0] * size for _ in range(size)]
    for (x, y) in open_cells:
        g[y][x] = 1
    return g


ok = 0
bad = 0


def check(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        bad += 1
        print(f"  ФЕЙЛ {name} {detail}")


# ── Положительный контроль: чужой юнит стоит на НАШЕЙ клетке и попадает в открытые ──
obs = {
    "unit": {},
    "city": {},
    "map": {
        "unit_owner": grid(6, {(4, 1): 3}),
        "tile_owner": grid(6, {(4, 1): 0, (0, 0): 0}),
        "status": status_grid(6, [(4, 1), (2, 2)]),
    },
}
res = CC.observe_candidates(None, obs, 0, 11)
check("посторонний на нашей клетке — кандидат", len(res["candidates"]) == 1
      and res["candidates"][0]["why"].startswith("посторонний юнит на нашей территории"),
      str(res["candidates"]))

# ── Пустой случай БЕЗ среза-предшественника: причина обязана называть, чего не хватает ──
_empty_obs = {"unit": {}, "city": {}, "map": {"unit_owner": grid(6, {}),
                                              "status": status_grid(6, [])}}
res_empty = CC.observe_candidates(None, _empty_obs, 0, 11)
check("нет среза-предшественника и нет чужих — причина названа",
      res_empty["candidates"] == [] and "предыдущего среза нет" in res_empty["reason"],
      res_empty["reason"])
check("пустой случай с кандидатами называет их число",
      "кандидатов 1" in res["reason"], res["reason"])

# ── Бой двух чужих: защитник по клетке ──
obs_fight = {
    "unit": {},
    "city": {},
    "map": {
        "unit_owner": grid(6, {(1, 1): 3, (1, 2): 4}),
        "tile_owner": grid(6, {(1, 1): 3, (1, 2): 0}),
        "status": status_grid(6, [(1, 1), (1, 2)]),
    },
}
pair = CC.classify_pair(obs_fight, {"owner": 3, "x": 1, "y": 1},
                        {"owner": 4, "x": 1, "y": 2})
check("защитник — на своей клетке, нападающий — на чужой",
      pair["attacker"] is not None and pair["attacker"]["owner"] == 4
      and pair["defender"]["owner"] == 3 and pair["candidates"] == [], str(pair))

# ── Признак недоступен: кандидатами идут ОБА воюющих (правило владельца) ──
obs_blind = {
    "unit": {},
    "city": {},
    "map": {"unit_owner": grid(6, {(1, 1): 3, (1, 2): 4})},   # слоя tile_owner нет
}
pair_blind = CC.classify_pair(obs_blind, {"owner": 3, "x": 1, "y": 1},
                              {"owner": 4, "x": 1, "y": 2})
check("признак клетки недоступен — оба воюющих кандидаты",
      len(pair_blind["candidates"]) == 2 and pair_blind["attacker"] is None, str(pair_blind))

# ── Потеря чужого юнита между срезами + единственный чужой рядом ──
prev = {"unit": {}, "city": {}, "map": {"unit_owner": grid(6, {(3, 3): 3}),
                                        "status": status_grid(6, [(3, 3)])}}
obs_after = {"unit": {}, "city": {},
             "map": {"unit_owner": grid(6, {(3, 4): 5}),
                     "tile_owner": grid(6, {(3, 4): 5}),
                     "status": status_grid(6, [(3, 4)])}}
loss = CC.observe_candidates(prev, obs_after, 0, 12)
kinds = {c.get("source") for c in loss["candidates"]}
check("потеря чужого юнита даёт кандидата со стороны потери",
      "loss" in kinds and any(c["why"] == "единственный чужой рядом с местом потери"
                              for c in loss["candidates"]), str(loss["candidates"]))
check("событие потери названо", loss["losses"] and loss["losses"][0]["kind"] == "unit",
      str(loss["losses"]))

# ── Отрицательный контроль: мир молчит — кандидатов нет, причина названа ──
quiet_prev = {"unit": {}, "city": {}, "map": {"unit_owner": grid(6, {}),
                                              "status": status_grid(6, [])}}
quiet_now = {"unit": {}, "city": {}, "map": {"unit_owner": grid(6, {}),
                                             "status": status_grid(6, [])}}
quiet = CC.observe_candidates(quiet_prev, quiet_now, 0, 13)
check("мир молчит: кандидатов 0 и причина названа",
      quiet["candidates"] == [] and "кандидатов нет" in quiet["reason"]
      and "не наблюдено" not in quiet["reason"].replace("потерь", ""), quiet["reason"])

# ── Наш собственный юнит кандидатом не становится ──
own = {"unit": {"5": {"owner": 0, "x": 2, "y": 2}}, "city": {},
       "map": {"unit_owner": grid(6, {}), "tile_owner": grid(6, {(2, 2): 0}),
               "status": status_grid(6, [(2, 2)])}}
own_res = CC.observe_candidates(None, own, 0, 14)
check("наш юнит кандидатом не становится", own_res["candidates"] == [], str(own_res))

print(f"\nпроверок: {ok + bad}, падений: {bad}")
sys.exit(1 if bad else 0)
