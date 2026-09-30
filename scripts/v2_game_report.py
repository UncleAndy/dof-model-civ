"""Разбор по партиям: где теряли, что выбирали, не зациклился ли `change_gov`."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
games, cur, prev = [], [], None
for r in rows:
    t = r.get("ход")
    # новая партия — когда счётчик хода возвращается к 1 после хода > 1
    if prev is not None and t == 1 and isinstance(prev, int) and prev > 1:
        games.append(cur)
        cur = []
    cur.append(r)
    prev = t
games.append(cur)
# в traces.jsonl накоплены прогоны подряд: берём последние три партии (это long3)
games = games[-3:]

for i, g in enumerate(games, 1):
    print(f"\n===== партия {i}: решений {len(g)} =====")
    last_turn = max((r.get("ход") or 0) for r in g)
    print(f"  последний ход в журнале: {last_turn}")
    th = [r for r in g if (r.get("чужое") or {}).get("угроз")]
    print(f"  решений с угрозой: {len(th)}")
    prices = [((r.get("риск") or {}).get("цена") or 0) for r in g]
    nz = [p for p in prices if p > 0]
    print(f"  цена риска: ненулевых {len(nz)}, максимум {max(nz) if nz else 0}")
    esc = [r for r in g if str((r.get("выбрано") or {}).get("effect")).startswith("['escape'")]
    print(f"  выбрано escape: {len(esc)}")
    c = collections.Counter(str((r.get("выбрано") or {}).get("effect")) for r in g)
    print("  выборы:", dict(c.most_common(5)))
    idle = sum(1 for r in g if (r.get("выбрано") is None))
    print(f"  решений без действия: {idle}")
    print("  хвост (последние 6 решений):")
    for r in g[-6:]:
        ch = r.get("выбрано") or {}
        print(f"    ход {r.get('ход')}: выбрано {ch.get('effect')}, цена риска "
              f"{(r.get('риск') or {}).get('цена')}, угроз {(r.get('чужое') or {}).get('угроз')}, "
              f"путей {r.get('путей')}, причина {str(r.get('причина'))[:50]}")