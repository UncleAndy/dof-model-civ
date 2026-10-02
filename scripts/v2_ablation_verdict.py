"""Вердикт по парной абляции: плечо A (цена города ВКЛ) против B (ВЫКЛ).

Правило вердикта ОБЪЯВЛЕНО ДО ДАННЫХ (§10.100) и здесь не меняется:
  * мера — игровой счёт партии (публикует мир);
  * вымершие/оборванные партии НЕ выбрасываются: счёт берётся на момент окончания партии,
    а если счёт вообще отсутствует — 0;
  * медиана попарных разностей (A − B) ≥ 2 очка И односторонний знаковый тест p < 0.05
    И (медиана разностей ≥ 10 % медианы |B| — только если медиана B ≠ 0; при медиане B = 0
    относительный порог снимается, он вырожден).
Иначе — «эффект не установлен».

Запуск: .venv/bin/python scripts/v2_ablation_verdict.py knowledge/ablation_A2.log knowledge/ablation_B2.log
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys
from math import comb


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
    a_path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/ablation_A2.log"
    b_path = sys.argv[2] if len(sys.argv) > 2 else "knowledge/ablation_B2.log"
    A, B = read_scores(a_path), read_scores(b_path)
    seeds = sorted(set(A) | set(B))
    if not seeds:
        print("в логах нет ни одного итога партии — вердикт невозможен")
        return 1
    missing = [s for s in seeds if s not in A or s not in B]
    if missing:
        print(f"ВНИМАНИЕ: у сидов {missing} нет итога в одном из плеч — пара берётся со счётом 0 "
              f"для отсутствующей стороны (правило §10.100).")
    print(f"пар: {len(seeds)} (сиды {seeds})\n")
    print(f"{'сид':>6} | {'A счёт':>6} {'A город':>7} {'A юнит':>6} | "
          f"{'B счёт':>6} {'B город':>7} {'B юнит':>6} | разность")
    pairs: list[tuple[int, int]] = []
    ext_a = ext_b = 0
    for s in seeds:
        a, b = A.get(s, {}), B.get(s, {})
        ea, eb = a.get("счёт") is None, b.get("счёт") is None
        av = 0 if ea else int(a.get("счёт") or 0)
        bv = 0 if eb else int(b.get("счёт") or 0)
        ext_a += 1 if ea else 0
        ext_b += 1 if eb else 0
        pairs.append((av, bv))
        mark = (" A без счёта" if ea else "") + (" B без счёта" if eb else "")
        print(f"{s:>6} | {str(a.get('счёт')):>6} {str(a.get('городов')):>7} {str(a.get('юнитов')):>6} | "
              f"{str(b.get('счёт')):>6} {str(b.get('городов')):>7} {str(b.get('юнитов')):>6} | "
              f"{av - bv:>+4}{mark}")

    ds = [a - b for a, b in pairs]
    n = len(ds)
    med_a = statistics.median(a for a, _ in pairs)
    med_b = statistics.median(b for _, b in pairs)
    med_d = statistics.median(ds)
    pos = sum(1 for d in ds if d > 0)
    neg = sum(1 for d in ds if d < 0)
    k = max(pos, neg)
    p_one = sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n)  # односторонний, как объявлено
    ok_abs = med_d >= 2
    ok_rel = (med_b != 0) and (abs(med_d) >= 0.10 * abs(med_b))
    ok_sign = p_one < 0.05
    print(f"\nОСНОВНОЙ набор: все {n} пар (вымирание/обрыв не выбрасывается, §10.100)")
    print(f"  медиана A = {med_a}; медиана B = {med_b}; медиана разностей = {med_d:+.2f}")
    print(f"  A>B: {pos}; A<B: {neg}; равно: {n - pos - neg}; односторонний знаковый тест p = {p_one:.4f}")
    print(f"  правило: медиана ≥ 2 — {'да' if ok_abs else 'нет'}; "
          f"≥10 % медианы B — {'да' if ok_rel else ('снято, медиана B = 0' if med_b == 0 else 'нет')}; "
          f"p<0.05 — {'да' if ok_sign else 'нет'}")
    print("  ВЕРДИКТ:", "ЭФФЕКТ УСТАНОВЛЕН (цена города улучшает исход)"
          if (ok_abs and ok_rel and ok_sign) else "ЭФФЕКТ НЕ УСТАНОВЛЕН")

    print(f"\nВТОРИЧНО (описательно, вердикт не решают):")
    print(f"  без счёта: A — {ext_a} из {n}, B — {ext_b} из {n}")
    ca = [int(x.get("городов") or 0) for x in (A.get(s, {}) for s in seeds) if x]
    cb = [int(x.get("городов") or 0) for x in (B.get(s, {}) for s in seeds) if x]
    ua = [int(x.get("юнитов") or 0) for x in (A.get(s, {}) for s in seeds) if x]
    ub = [int(x.get("юнитов") or 0) for x in (B.get(s, {}) for s in seeds) if x]
    if ca:
        print(f"  города (медиана): A = {statistics.median(ca)}, B = {statistics.median(cb)}")
    if ua:
        print(f"  юниты (медиана): A = {statistics.median(ua)}, B = {statistics.median(ub)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())