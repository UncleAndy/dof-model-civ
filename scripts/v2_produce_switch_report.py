"""Замер §10.102: сколько щитов теряется при СМЕНЕ производства в городе.

Вопрос Andy: почему город не доводит постройку до конца. Причина — у отказа от начатой постройки
нет цены. Величина измерима: мир публикует `shield_stock`, а агент записывает канал наблюдений
`produce_switch` при каждом действии `produce_*` (до/после, потеряно, сменил ли вариант).

Печатает распределение потерь отдельно для смены варианта и для повтора того же варианта, а также
сводку по эффекту `city/produce` из графа (сколько раз щиты вообще менялись).

Запуск: .venv/bin/python scripts/v2_produce_switch_report.py [knowledge/world.json]
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "knowledge" / "world.json"
    data = json.loads(path.read_text())
    rows = [r for r in (data.get("observed", {}).get("produce_switch") or [])
            if isinstance(r, dict)]
    print(f"база: {path}")
    print(f"записей канала `produce_switch`: {len(rows)}")
    if not rows:
        print("замеров нет: канал пишется только при действии `produce_*` нашего города.")
        return 0

    switched = [r for r in rows if r.get("сменил") is True]
    same = [r for r in rows if r.get("сменил") is False]
    unknown = [r for r in rows if r.get("сменил") is None]

    def stat(title: str, group: list[dict]) -> None:
        if not group:
            print(f"\n{title}: нет записей")
            return
        losses = [int(r.get("потеряно") or 0) for r in group]
        stocks = [int(r.get("щиты_до") or 0) for r in group]
        zero = sum(1 for x in losses if x == 0)
        print(f"\n{title}: n = {len(group)}")
        print(f"  потеряно щитов: медиана {statistics.median(losses)}, "
              f"среднее {sum(losses) / len(losses):.2f}, макс {max(losses)}, нулей {zero}")
        print(f"  щитов до действия: медиана {statistics.median(stocks)}")
        print(f"  примеры: {[{'до': r.get('щиты_до'), 'после': r.get('щиты_после'), 'потеряно': r.get('потеряно')} for r in group[:6]]}")

    stat("СМЕНА варианта производства (сменил = True)", switched)
    stat("ПОВТОР того же варианта (сменил = False)", same)
    if unknown:
        print(f"\nсменил = None (мир не публикует код/индекс производства): {len(unknown)}")

    # сводка по записи эффекта семейства `produce` у города
    ents = data.get("entities") or []
    it = ents.items() if isinstance(ents, dict) else ((e.get("eid"), e) for e in ents)
    for k, v in it:
        if not k or not str(k).startswith("controller:city"):
            continue
        eff = v.get("effects") or {}
        rec = eff.get("produce") if isinstance(eff, dict) else None
        if rec:
            cc = rec.get("change_counts") or {}
            print(f"\nэффект {k}/produce: наблюдений {rec.get('seen')}, "
                  f"city_shields_changed {cc.get('city_shields_changed')}, "
                  f"city_shields_delta {cc.get('city_shields_delta')}, "
                  f"city_prod_switched {cc.get('city_prod_switched')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())