"""Есть ли в артефактах СЫРЫЕ захваты — вход, по которому можно перемерить опубликованный ряд (§13.100).

Вопрос простой и проверяемый: чтобы перемерить индекс после правки читателя, нужны наблюдения
(`observation`). Зонд смотрит первые строки всех `knowledge/*.jsonl` и отдельно ищет `observation`
в самых крупных файлах (ограниченно, чтобы не читать гигабайты целиком).
"""
from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
KN = ROOT / "knowledge"
BOUND = 100_000_000          # сколько байт смотрим в крупных файлах

BIG = ("traces.jsonl", "traces_cap.jsonl", "traces_armA.jsonl", "traces_ab116_A.jsonl")


def first_keys(path: pathlib.Path) -> tuple[str, list[str]]:
    try:
        with path.open(encoding="utf-8") as fh:
            line = fh.readline()
    except OSError as exc:
        return f"не открылось: {type(exc).__name__}", []
    if not line.strip():
        return "пустой файл", []
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return "первая строка не JSON", []
    if not isinstance(rec, dict):
        return f"первая строка — {type(rec).__name__}", []
    return "ok", sorted(rec)


def count_observations(path: pathlib.Path) -> int:
    if not path.exists():
        return -1
    data = path.read_bytes()[:BOUND]
    return data.count(b'"observation"')


def main() -> int:
    files = sorted(KN.glob("*.jsonl"))
    raw: list[str] = []
    empty: list[str] = []
    journals: list[str] = []
    for p in files:
        state, keys = first_keys(p)
        if state == "пустой файл" or state == "первая строка не JSON":
            empty.append(p.name)
            continue
        if state != "ok":
            empty.append(p.name)
            continue
        if "observation" in keys:
            raw.append(p.name)
        else:
            journals.append(p.name)
    print(f"файлов: {len(files)}; с наблюдениями в первой строке: {len(raw)}; "
          f"результатов замера: {len(journals)}; пустых/битых: {len(empty)}")
    print("СЫРЫЕ (первая строка):", raw or "нет ни одного")
    print("\nпоиск `observation` в крупных файлах (первые 100 МБ каждого):")
    for name in BIG:
        n = count_observations(KN / name)
        size = (KN / name).stat().st_size if (KN / name).exists() else 0
        print(f"  {name}: размер {size // 1048576} МБ, вхождений {n}")
    print(f"\nпустые/битые ({len(empty)}): " + ", ".join(empty))
    return 0


raise SystemExit(main())
