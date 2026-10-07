"""Офлайн-проверка пометки измерения (§3.3 `discovers`) на живом сбросе — стенд не нужен.

Пометка читает только `option_id` кандидата и наблюдение, поэтому кандидаты здесь берутся из меню
юнитов как есть (вектор `goto_N`), без сборки полного дерева опций: проверяется ПРАВИЛО пометки, а
не порождение кандидатов (его проверяет смоук). Отсутствие пометки при массе невиданных клеток —
отказ, который надо увидеть числом, а не принять за факт мира.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import spec_obs as SO  # noqa: E402
from env import spec_options as O  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
dumps = sorted((ROOT / "knowledge").glob("obs_dump_*.json"))
if not dumps:
    print("сбросов нет — сначала прогон с --dump-obs")
    raise SystemExit(1)
dump = dumps[-1]
d = json.loads(dump.read_text(encoding="utf-8"))
obs = d["observation"]
info = {"available_actions": d.get("available_actions"), "turn": d.get("turn")}

m = SO.measure_step(obs, info, d.get("turn"), GameStateExtractor(my_player_id=0), None, 0)

stubs = [SimpleNamespace(option_id=f"{eid}:{name}", discovers=[])
         for eid, names in (m.get("raw_menus") or {}).items()
         for name in names if str(name).startswith("goto_")]
marked = O.mark_measure(stubs, obs)

status = (obs.get("map") or {}).get("status")
rows = status.tolist() if hasattr(status, "tolist") else (status or [])
flat = [v for row in rows for v in row]
unseen = sum(1 for v in flat if int(v) == 0)

print(f"[{dump.name}] ход {d.get('turn')}; кандидатов `goto_*`: {len(stubs)}")
print(f"клеток вне обзора: {unseen} из {len(flat)} (0 = вне обзора, 2 = открыта)")
print(f"помечено измерением: {len(marked)}")
print("примеры:", sorted(marked)[:6] if marked else "НЕТ — это отказ, а не факт мира")
units = sorted({o.option_id.split(":", 1)[0] for o in stubs})
print(f"сущностей с вектором `goto_*`: {len(units)} — {units[:6]}")