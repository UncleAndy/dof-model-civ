#!/usr/bin/env python3
"""Сводка по игре, где ВСЕ стороны — наши агенты: счёт и DoF по всем игрокам.

Владелец объявил (до данных, §13.125): сторон не менее шести; война — любые
нападения; и счёт, и DoF считаем в трёх вариантах — **сумма**, **среднее**,
**разброс** по игрокам. Целевой величиной может служить счёт игры, но данные
собираются по максимуму (§13.126).

Скрипт читает записи сторон (файлы `run_real_tournament.py --output`), достаёт
объявленные величины и печатает их рядом — чтобы расхождение между серверным
счётом и нашей меркой было видно, а не спрятано. Номер игрока берётся не из
записи (там его нет), а из лога стороны: иначе неизвестно, кто есть кто.

    .venv/bin/python scripts/seats_report.py --glob '/tmp/seat_6301_*.json'
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics as st

SCORE_FIELD = "score_cum"
INDEX_FIELD = "avg_total_dof_index"


def _player_id_from_log(json_path: pathlib.Path) -> int | None:
    log = json_path.with_suffix(".log")
    if not log.exists():
        return None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "мой player_id=" in line:
            tail = line.split("мой player_id=")[-1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                return int(digits)
    return None


def _episode(path: pathlib.Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = raw.get("results") or {}
    for _policy, episodes in results.items():
        if episodes:
            return episodes[0]
    return {}


def _spread(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
        "std": st.pstdev(values) if len(values) > 1 else 0.0,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--glob", required=True, help="шаблон записей сторон")
    p.add_argument("--out", default=None, help="куда сохранить сводку (json)")
    args = p.parse_args()

    files = sorted(pathlib.Path("/").glob(args.glob.lstrip("/")))
    if not files:
        print(f"не найдено записей по шаблону {args.glob}")
        return 2

    rows = []
    for f in files:
        ep = _episode(f)
        if not ep:
            print(f"[!] {f.name}: записи нет")
            continue
        rows.append({
            "file": f.name,
            "player_id": _player_id_from_log(f),
            "score_cum": float(ep.get("score_cum") or 0.0),
            "score_gain": float(ep.get("score_gain") or 0.0),
            "index_avg": float(ep.get(INDEX_FIELD) or 0.0),
            "index_final": float(ep.get("final_total_dof_index") or 0.0),
            "decisions_per_turn": float(ep.get("decisions_per_turn_mean") or 0.0),
            "actions": int(ep.get("actions_issued") or 0),
            "revealed_cells": int(ep.get("revealed_cells") or 0),
            "turns": int(ep.get("turns") or 0),
            "met": bool(ep.get("met_opponent")),
            "contact_turns": list(ep.get("enemy_contact_turns") or []),
            "combat": list(ep.get("combat_actions") or []),
            "enemy_min_distance": ep.get("enemy_min_distance"),
            "fingerprint": ep.get("start_fingerprint"),
            "error": ep.get("error") or "",
        })

    rows.sort(key=lambda r: (r["player_id"] is None, r["player_id"]))

    print("=" * 100)
    print("ИГРА, ГДЕ ВСЕ СТОРОНЫ — НАШИ АГЕНТЫ: счёт и DoF по всем игрокам")
    print("=" * 100)
    print(f"  записей: {len(rows)}   слот/партия по отпечатку карты: "
          f"{sorted({r['fingerprint'] for r in rows})}")
    print()
    head = (f"{'игрок':>6} {'счёт':>7} {'прирост':>8} {'DoF средн':>10} "
            f"{'решений/х':>10} {'шагов':>6} {'карты':>6} {'контакт':>8} "
            f"{'бой':>4} {'беда':>5}")
    print(head)
    print("-" * len(head))
    for r in rows:
        pid = "-" if r["player_id"] is None else str(r["player_id"])
        contact = len(r["contact_turns"])
        print(f"{pid:>6} {r['score_cum']:>7.1f} {r['score_gain']:>8.1f} "
              f"{r['index_avg']:>10.2f} {r['decisions_per_turn']:>10.2f} "
              f"{r['actions']:>6} {r['revealed_cells']:>6} {contact:>8} "
              f"{len(r['combat']):>4} {('да' if r['error'] else 'нет'):>5}")

    scores = [r["score_cum"] for r in rows]
    indexes = [r["index_avg"] for r in rows]
    print()
    print("ОБЪЯВЛЕННЫЕ ВАРИАНТЫ (§13.125) — по игрокам:")
    for name, values, unit in (("счёт игры", scores, "очк."),
                               ("индекс DoF (средний за игру)", indexes, "ед.")):
        s = _spread(values)
        print(f"  {name}: сумма {sum(values):.2f} {unit}; среднее "
              f"{st.mean(values):.2f}; разброс: min {s['min']:.2f} / "
              f"max {s['max']:.2f} / диапазон {s['range']:.2f} / σ {s['std']:.2f}")

    met = sum(1 for r in rows if r["met"])
    fighting = sum(1 for r in rows if r["combat"])
    print()
    print(f"  встречи: сторон с контактом {met} из {len(rows)}; "
          f"сторон с боевыми действиями {fighting} из {len(rows)}")
    print(f"  война по объявленному правилу (любое нападение): "
          f"{'БЫЛА' if fighting else 'не было ни одного нападения'}")

    summary = {
        "players": len(rows),
        "fingerprints": sorted({r["fingerprint"] for r in rows}),
        "rows": rows,
        "score_sum": sum(scores),
        "score_mean": st.mean(scores),
        "score_spread": _spread(scores),
        "index_sum": sum(indexes),
        "index_mean": st.mean(indexes),
        "index_spread": _spread(indexes),
        "met_players": met,
        "fighting_players": fighting,
    }
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n  сводка сохранена: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
