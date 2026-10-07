"""Дешёвая проверка сценария по тому, что трасса ДЕЙСТВИТЕЛЬНО хранит.

Трасса ходового прогона карты не пишет (в строке: `V_всего`, `city_output`, `индекс`, `медиана_боевой`,
`меток`, `нападение`, `почему_риска`, `почему_смены`, `разбивка`, `риск`, `строк_смены`, `сущностей`,
`счёт_мира`, `ход`), поэтому спрашиваем у неё то, что она знает:
1. видели ли мы чужих вообще — по строкам `нападение` и по меткам источников коллапса (`меток`);
2. росли ли наши города — по `city_output` (число городов, размеры, щиты);
3. как двигался счёт мира и `V_всего` — чтобы видеть, был ли прогресс в принципе.

Открытость карты сюда не входит: она измерена отдельно (4035 из 4056 клеток на 40-м ходу), и это
говорит, что «незнания» как такового в этом сценарии почти не осталось — засветка идёт от городов.
"""
import glob
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/home/hermes/projects/AI/DOF-MODEL-CIV")
traces = sorted(glob.glob(str(ROOT / "knowledge/live_trace_9200_port6004_ab*.jsonl")))
if not traces:
    raise SystemExit("трасса не найдена — проверка не идёт")
print("трасса:", traces[0].rsplit("/", 1)[-1])

attacks = Counter()
marks_total = 0
marks_rows = 0
cities_by_turn: list[int] = []
sizes_by_turn: list[int] = []
shields_by_turn: list[int] = []
scores: list[float] = []
rows = 0

with open(traces[0], encoding="utf-8") as fh:
    for line in fh:
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        rows += 1
        for ev in (rec.get("нападение") or []):
            if isinstance(ev, dict):
                attacks[str(ev.get("вид") or ev.get("владелец") or "?")] += 1
            else:
                attacks["?"] += 1
        m = rec.get("меток")
        if isinstance(m, (int, float)):
            marks_total += int(m)
            marks_rows += 1
        out = rec.get("city_output") or []
        if isinstance(out, list):
            cities_by_turn.append(len(out))
            sz = [int(o.get("размер") or 0) for o in out if isinstance(o, dict)]
            sizes_by_turn.append(sum(sz))
            shields_by_turn.append(sum(int(o.get("щиты") or 0) for o in out if isinstance(o, dict)))
        s = rec.get("счёт_мира")
        if isinstance(s, (int, float)):
            scores.append(float(s))

def head(tag, xs):
    if not xs:
        print(f"{tag}: нет данных")
        return
    print(f"{tag}: начало {xs[0]}, середина {xs[len(xs)//2]}, конец {xs[-1]}")

print(f"строк: {rows}")
print("── чужие ──")
print(f"строк с нападением: {sum(attacks.values())}, по видам: {dict(attacks) or '—'}")
print(f"меток источников коллапса: всего {marks_total} в {marks_rows} строках (в остальных — пусто)")
print("── наши города ──")
head("городов", cities_by_turn)
head("суммарный размер", sizes_by_turn)
head("суммарные щиты", shields_by_turn)
head("счёт мира", scores)
peak = max(cities_by_turn) if cities_by_turn else 0
print(f"максимум городов за партию: {peak}; рост размера: "
      f"{(sizes_by_turn[-1] - sizes_by_turn[0]) if sizes_by_turn else '—'}")