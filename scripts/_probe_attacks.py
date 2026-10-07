"""Разведка: как записаны события нападений в трассах (для правила «напал / защищался»).

Только чтение. Ничего в модели не меняет — идёт опыт, код трогать нельзя.
"""
import collections
import glob
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    cal = ROOT / "drafts" / "DOF_CALIBRATION.md"
    txt = cal.read_text(encoding="utf-8", errors="replace")
    print("раздел 13.63 в журнале:", "13.63" in txt)

    print("\n--- опыт ---")
    for f in sorted(glob.glob(str(ROOT / "knowledge" / "live_trace_951*_*.jsonl"))):
        p = pathlib.Path(f)
        print(p.read_text(errors="replace").count("\n"), "ходов:", p.name)
    ab = ROOT / "knowledge" / "ab_scout_aifill8_v2.jsonl"
    print("файл опыта:", (sum(1 for _ in ab.open()) if ab.exists() else "ещё нет"))

    print("\n--- строки с нападениями ---")
    hits = collections.Counter()
    for f in glob.glob(str(ROOT / "knowledge" / "live_trace_*.jsonl")):
        try:
            t = pathlib.Path(f).read_text(errors="replace")
        except Exception:
            continue
        n = sum(1 for line in t.splitlines() if "attack" in line.lower())
        if n:
            hits[f] = n
    for f, n in hits.most_common(5):
        print(n, pathlib.Path(f).name)
    if not hits:
        print("строк со словом attack нет")
        return

    f0 = hits.most_common(1)[0][0]
    print(f"\n--- структура первой такой строки ({pathlib.Path(f0).name}) ---")
    for line in pathlib.Path(f0).read_text(errors="replace").splitlines():
        if "attack" in line.lower():
            row = json.loads(line)
            print("верхние ключи:", sorted(row.keys()))
            for k in sorted(row.keys()):
                v = row[k]
                kind = type(v).__name__
                size = f"len={len(v)}" if isinstance(v, (list, dict, str)) else ""
                print(f"  {k}: {kind} {size}")
            break


main()
