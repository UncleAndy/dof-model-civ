"""Завести ИЗМЕРЕННЫЙ DoF города в базу знаний (канал наблюдений `dof_city`).

Зачем: цена основания города была `null` — в графе нет ни одного города, пока агент своего не основал,
и `impute("city")` не находил ничего. Это замкнутый круг: город не основан → DoF города не измерен →
цене неоткуда взяться → город не основан. Разрываем его замером, который уже собран в пробных играх
(`knowledge/city_growth.jsonl`), а дальше агент продолжает накапливать замер сам.

Правила (согласованы с Andy, §10.88):
* DoF города = число ПРЕДЛОЖЕННЫХ переходов меню (`переходов_предложено`);
* срез — **размер 1** (новый город рождается размером 1);
* записи с нулём переходов **исключаются**: это пустое окно обёртки `PersistentCityProduction`
  (загрязнение, §10.69), а не «у города нет действий». Структурный признак: 0 переходов при
  ≥ 3 позициях постройки;
* порог вердикта (объявлен до данных): победа при `ln(DoF) > 0.097` ⇔ `DoF > 1.10`.

Запуск: `.venv/bin/python scripts/v2_city_dof_import.py [--dry-run]`
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
GROWTH = ROOT / "knowledge" / "city_growth.jsonl"
WORLD = ROOT / "knowledge" / "world.json"
KEY = "dof_city"
SRC = "замер меню города (прошлые партии)"


def main() -> int:
    dry = "--dry-run" in sys.argv
    world_path = WORLD
    for i, a in enumerate(sys.argv):
        if a == "--world" and i + 1 < len(sys.argv):
            world_path = pathlib.Path(sys.argv[i + 1])
    rows = [json.loads(l) for l in GROWTH.read_text().splitlines() if l.strip()]
    total = len(rows)

    # исключаем пустое окно: 0 переходов — это загрязнение, а не «нет действий»
    clean = [r for r in rows if isinstance(r.get("переходов_предложено"), int)
             and r["переходов_предложено"] > 0]
    zeros = total - len(clean)
    s1 = [r["переходов_предложено"] for r in clean if r.get("размер") == 1]

    print(f"записей всего: {total}; исключено (0 переходов = пустое окно): {zeros}; чистых: {len(clean)}")
    print(f"размер 1: n={len(s1)}, медиана {statistics.median(s1)}, распределение "
          f"{dict(sorted(Counter(s1).items()))}")

    world = json.loads(world_path.read_text())
    obs = world.setdefault("observed", {})
    already = [v for v in (obs.get(KEY) or [])
               if isinstance(v, dict) and str(v.get("источник", "")).startswith(SRC)]
    if already:
        print(f"уже импортировано ранее: {len(already)} записей — проверяю второй канал")
    else:
        records = [{"значение": r["переходов_предложено"], "размер": r.get("размер"),
                    "источник": SRC} for r in clean]
        med = graph_median(records)
        print(f"импортирую {len(records)} записей в {world_path.name}: observed['{KEY}']")
        print(f"медиана по всем размерам: {med}; по размеру 1: {statistics.median(s1)}")
        print(f"цена основания города = ln(медиана размера 1) = ln({statistics.median(s1)}) "
              f"= {math.log(statistics.median(s1)):.4f}")
        print(f"порог вердикта: ln(DoF) > 0.097 ⇔ DoF > {math.exp(0.097):.4f} — выполняется "
              f"({'да' if statistics.median(s1) > math.exp(0.097) else 'НЕТ'})")
        if not dry:
            obs[KEY] = list(obs.get(KEY) or []) + records

    # Второй канал: СВОИ действия города в семействах (та же валюта, что у юнитов). Нужен для
    # расчёта достижимого DoF, когда своего города ещё нет (на старте партии).
    key2, src2 = "city_own_families", "замер меню города: семейства (прошлые партии)"
    already2 = [v for v in (obs.get(key2) or [])
                if isinstance(v, dict) and str(v.get("источник", "")).startswith(src2)]
    fam_rows = [r for r in clean if isinstance(r.get("семейств"), int) and r["семейств"] > 0]
    if already2:
        print(f"канал {key2}: уже есть {len(already2)} записей")
    elif fam_rows:
        rec2 = [{"значение": r["семейств"], "размер": r.get("размер"), "источник": src2}
                for r in fam_rows]
        f1 = [r["значение"] for r in rec2 if r.get("размер") == 1]
        print(f"канал {key2}: импортирую {len(rec2)} записей; медиана размера 1 = {statistics.median(f1)}")
        if not dry:
            obs[key2] = list(obs.get(key2) or []) + rec2

    if dry:
        print("--dry-run: файл не тронут")
        return 0
    world_path.write_text(json.dumps(world, ensure_ascii=False, indent=1))
    print(f"записано. dof_city: {len(obs.get(KEY) or [])}, {key2}: {len(obs.get(key2) or [])}")
    return 0


def graph_median(records: list[dict]) -> float:
    vals = sorted(float(r["значение"]) for r in records)
    return vals[len(vals) // 2]


if __name__ == "__main__":
    raise SystemExit(main())