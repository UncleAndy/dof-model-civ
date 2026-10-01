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
    print(f"{'сид':>6} | {'A счёт':>6} {'A город':>7} {'A юнит':>6} | "
          f"{'B счёт':>6} {'B город':>7} {'B юнит':>6} | разность")
    diffs_all: list[int] = []
    pairs_clean: list[tuple[int, int]] = []
    eliminated: list[int] = []
    for s in seeds:
        a, b = A[s], B[s]
        ea, eb = a.get("счёт") is None, b.get("счёт") is None
        av = 0 if ea else (a.get("счёт") or 0)
        bv = 0 if eb else (b.get("счёт") or 0)
        diffs_all.append(av - bv)
        if ea or eb:
            eliminated.append(s)
        else:
            pairs_clean.append((av, bv))
        mark = (" A вымер" if ea else "") + (" B вымер" if eb else "")
        print(f"{s:>6} | {str(a.get('счёт')):>6} {a.get('городов'):>7} {a.get('юнитов'):>6} | "
              f"{str(b.get('счёт')):>6} {b.get('городов'):>7} {b.get('юнитов'):>6} | "
              f"{av - bv:>+4}{mark}")

    def verdict(pairs: list[tuple[int, int]], title: str) -> None:
        """Посчитать вердикт по объявленному правилу на заданном наборе пар."""
        if not pairs:
            print(f"\n{title}: пар нет — вердикт невозможен")
            return
        ds = [a - b for a, b in pairs]
        med_a = statistics.median(a for a, _ in pairs)
        med_b = statistics.median(b for _, b in pairs)
        med_d = statistics.median(ds)
        pos = sum(1 for d in ds if d > 0)
        n = len(ds)
        from math import comb
        k = max(pos, n - pos)
        p = min(1.0, 2 * sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n))
        ok_abs, ok_rel, ok_sign = med_d >= 2, med_b > 0 and med_d >= 0.10 * med_b, p < 0.05
        print(f"\n{title} (пар {n})")
        print(f"  медиана A = {med_a}; медиана B = {med_b}; медиана разностей = {med_d:+.2f}")
        print(f"  положительных: {pos} из {n}; знаковый тест p = {p:.3f}")
        print(f"  правило: |разность|≥2 — {'да' if ok_abs else 'нет'}; ≥10 % медианы B — "
              f"{'да' if ok_rel else 'нет'}; p<0.05 — {'да' if ok_sign else 'нет'}")
        print("  ВЕРДИКТ:", "ЭФФЕКТ УСТАНОВЛЕН (цена города улучшает исход)"
              if (ok_abs and ok_rel and ok_sign) else "ЭФФЕКТ НЕ УСТАНОВЛЕН")

    verdict(pairs_clean, "ОСНОВНОЙ набор: только пары, где обе партии доиграны и счёт опубликован")
    if eliminated:
        print(f"\nВЫМЕРШИЕ партии (счёт не опубликован, в основном наборе их нет): сиды {eliminated}")
        print("  Правило вердикта (§10.95) этот случай НЕ оговаривало — это упущение протокола;")
        print("  ниже — проверка устойчивости, где вымирание считается нулём.")
        verdict(list(zip([0 if A[s].get("счёт") is None else (A[s].get("счёт") or 0) for s in seeds],
                         [0 if B[s].get("счёт") is None else (B[s].get("счёт") or 0) for s in seeds])),
                "ПРОВЕРКА УСТОЙЧИВОСТИ: все пары, вымирание = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())