"""Проверка хвоста журнала: у новых решений (после правки) цена риска должна быть нулевой,
источников коллапса — пусто, пока нападение не наблюдено."""
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-73:]
nz = [(r.get("ход"), (r.get("риск") or {}).get("цена")) for r in tail
      if ((r.get("риск") or {}).get("цена") or 0) > 0]
print(f"последних решений: {len(tail)}")
print(f"с ненулевой ценой риска: {len(nz)} {nz[:5]}")
print(f"с источниками коллапса: "
      f"{sum(1 for r in tail if r.get('источники_коллапса'))}")
print(f"событий нападения в хвосте: "
      f"{sum(1 for r in tail if 'нападение' in r)}")