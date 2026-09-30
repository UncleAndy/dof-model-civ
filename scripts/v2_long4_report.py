"""Разбор long4: поймано ли настоящее наблюдённое нападение, что выбрал агент, чем кончилось."""
import collections
import json

rows = [json.loads(line) for line in open("knowledge/traces.jsonl")]
tail = rows[-1200:]
print("строк в хвосте:", len(tail))

ev = [r for r in tail if "нападение" in r]
print("событий нападения:", len(ev))
for r in ev[:6]:
    print("  ", json.dumps(r.get("нападение"), ensure_ascii=False)[:220])

src = [r for r in tail if r.get("источники_коллапса")]
print("решений с активными источниками коллапса:", len(src))
for r in src[:6]:
    print(f"  ход {r.get('ход')}: источников {len(r.get('источники_коллапса') or {})}, "
          f"цена {(r.get('риск') or {}).get('цена')}, угроз {(r.get('чужое') or {}).get('угроз')}")

nz = [r for r in tail if ((r.get("риск") or {}).get("цена") or 0) > 0]
print("решений с ценой риска > 0:", len(nz))
for r in nz[:8]:
    ch = r.get("выбрано") or {}
    best = None
    for c in (r.get("кандидаты") or []):
        if str(c.get("эффект")) == str(ch.get("effect")):
            best = c
    print(f"  ход {r.get('ход')}: цена {(r.get('риск') or {}).get('цена')}, "
          f"выбрано {ch.get('effect')}, net {ch.get('net_delta')}, "
          f"лучший вариант {best.get('лучший_вариант') if best else '?'}")

esc = [r for r in tail if str((r.get("выбрано") or {}).get("effect")).startswith("['escape'")]
print("выбран «выход»:", len(esc))
c = collections.Counter(str((r.get("выбрано") or {}).get("effect")) for r in tail)
print("выборы (топ-6):", dict(c.most_common(6)))