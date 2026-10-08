"""Замер §13.75 (часть 1, архив): где в базе прошлой линии стоит значение 32767 и что рядом.

Только чтение архива `baselines/world.json`; стенд не задействован, опытные записи не трогаются.
Печатается: сколько мест со значением 32767 и их пути; распределение значений по всем ключам,
похожим на срок; и контекст каждого места — соседние поля того же узла.
"""
from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "baselines" / "world.json"

SENTINEL = 32767
data = json.loads(BASE.read_text(encoding="utf-8"))
print("архив:", BASE, "| разделы верхнего уровня:", sorted(data)[:12])

ETA_WORDS = ("eta", "turns_to", "prod_complete", "cost", "срок", "prod")


def is_eta_key(k: str) -> bool:
    kl = k.lower()
    return any(w in kl for w in ETA_WORDS)


# ── 1. Все места со значением 32767: путь, соседние ключи того же узла ──────────────
hits: list[tuple[str, dict]] = []


def walk(node, path, parent):
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}/{k}", node)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]", parent)
    else:
        if node == SENTINEL:
            hits.append((path, parent if isinstance(parent, dict) else {}))


walk(data, "", None)
print(f"\nмест со значением {SENTINEL}: {len(hits)}")
for path, parent in hits[:25]:
    sib = {k: v for k, v in list(parent.items())[:12] if not isinstance(v, (dict, list))}
    print(f"  {path}\n     рядом: {sib}")

# ── 2. Распределение по ключам, похожим на срок ─────────────────────────────────────
kv = collections.defaultdict(collections.Counter)


def walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (int, float, str, type(None))) and is_eta_key(k):
                kv[k][repr(v)] += 1
            walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            walk_keys(v)


walk_keys(data)
print("\n── ключи, похожие на срок ──")
for k, c in sorted(kv.items(), key=lambda x: -sum(x[1].values())):
    top = ", ".join(f"{v}×{n}" for v, n in c.most_common(6))
    print(f"  {k}: {len(c)} разных значений; топ: {top}")

# ── 3. Прямой ответ на H1: сколько раз 32767 стоит в ключе срока ────────────────────
eta_hits = [(p, par) for p, par in hits if is_eta_key(p.rsplit("/", 1)[-1])]
print(f"\nиз них в ключах, похожих на срок: {len(eta_hits)}")
for path, parent in eta_hits[:15]:
    print(f"  {path} | рядом: "
          f"{ {k: v for k, v in list(parent.items())[:10] if not isinstance(v, (dict, list))} }")
