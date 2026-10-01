"""Вердикт по парной абляции: плечо A (цена города ВКЛ) против B (ВЫКЛ).

Правило вердикта ОБЪЯВЛЕНО ДО ДАННЫХ (§10.95):
  медиана попарных разностей (A − B) ≥ 2 очка И ≥ 10 % медианы плеча B И знаковый тест p < 0.05.
Иначе — «эффект не установлен». Мера — игровой счёт (публикует мир), не наш индекс.

Запуск: .venv/bin/python scripts/v2_ablation_verdict.py knowledge/ablation_A.log knowledge/ablation_B.log
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys


def read_scores(path: str) -> dict[int, dict]:
    """Достать из лога строки итогов партий (последняя запись на сид)."""
    out: dict[int, dict] = {}
    for line in pathlib.Path(path).read_text(errors="replace").splitlines():
        if "'seed':" not in line or "'счёт':" not in line:
            continue
        m_seed = re.search(r"'seed':\s*(\d+)", line)
        if not m_seed:
            continue
        try:
            body = line[line.index("{"):]
            rec = json.loads(body.replace("'", '"').replace("None", "null").replace("False", "false")
                             .replace("True", "true"))
        except Exception:  # noqa: BLE001
            continue
        out[int(m_seed.group(1))] = rec
    return out


def main() -> int:
    a_path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/ablation_A.log"
    b_path = sys.argv[2] if len(sys.argv) > 2 else "knowledge/ablation_B.log"
    A, B = read_scores(a_path), read_scores(b_path)
    seeds = sorted(set(A) & set(B))
    if not seeds:
        print("нет общих сидов в логах — вердикт невозможен")
        return 1
    print(f"пар: {len(seeds)} (сиды {seeds})\n")
    print(f"{'сид':>6} | {'A счёт':>6} {'A город':>7} {'A юнит':>6} | {'B счёт':>6} {'B город':>7} {'B юнит':>6} | разность")
    diffs = []
    for s in seeds:
        a, b = A[s], B[s]
        d = (a.get("счёт") or 0) - (b.get("счёт") or 0)
        diffs.append(d)
        print(f"{s:>6} | {a.get('счёт'):>6} {a.get('городов'):>7} {a.get('юнитов'):>6} | "
              f"{b.get('счёт'):>6} {b.get('городов'):>7} {b.get('юнитов'):>6} | {d:>+4}")
    med_a = statistics.median(A[s].get("счёт") or 0 for s in seeds)
    med_b = statistics.median(B[s].get("счёт") or 0 for s in seeds)
    med_d = statistics.median(diffs)
    positives = sum(1 for d in diffs if d > 0)
    n = len(diffs)
    # знаковый тест (двусторонний, точный): p = 2 * P(X >= max(k, n-k)) при p0 = 0.5
    from math import comb
    k = max(positives, n - positives)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n))
    print(f"\nмедиана A = {med_a}; медиана B = {med_b}; медиана разностей = {med_d:+.2f}")
    print(f"положительных разностей: {positives} из {n}; знаковый тест p = {p:.3f}")
    ok_abs = med_d >= 2
    ok_rel = med_b > 0 and med_d >= 0.10 * med_b
    ok_sign = p < 0.05
    print(f"\nправило (объявлено до данных): |разность|≥2: {'да' if ok_abs else 'нет'}; "
          f"≥10 % медианы B: {'да' if ok_rel else 'нет'}; p<0.05: {'да' if ok_sign else 'нет'}")
    print("ВЕРДИКТ:", "ЭФФЕКТ УСТАНОВЛЕН (цена города улучшает исход)" if (ok_abs and ok_rel and ok_sign)
          else "ЭФФЕКТ НЕ УСТАНОВЛЕН")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())