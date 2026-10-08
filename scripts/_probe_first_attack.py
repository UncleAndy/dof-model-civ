"""§13.85: проба первого живого нападения — по объявленному протоколу, до вердикта."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = ROOT / "knowledge" / "live_trace_9570_port6003.jsonl"


def main() -> int:
    rows = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    print(f"ходов в записи: {len(rows)}")
    print(f"ключи хода: {sorted(rows[-1].keys())}")

    attacked = [(row.get("ход"), row.get("нападение") or {}) for row in rows
                if (row.get("нападение") or {}).get("attacked")]
    print(f"\n1) событий с attacked=true: {len(attacked)}")
    if not attacked:
        print("   нападений в записи нет — разбирать нечего")
        return 0

    turn, rec = attacked[0]
    print(f"\n2) событие на ходу {turn}:")
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    marked = [str(m) for m in (rec.get("marked") or [])]
    hold = rec.get("hold_turns")
    print(f"   помечено владельцев: {marked}; срок признака в событии: {hold}")

    timeline = [(row.get("ход"), [str(m) for m in ((row.get("нападение") or {}).get("marked") or [])])
                for row in rows]
    marked_turns = [t for t, m in timeline if m]
    first, last = (marked_turns[0], marked_turns[-1]) if marked_turns else (None, None)
    print(f"\n3) ходы с пометкой: {marked_turns}")
    if marked_turns:
        print(f"   пометка держится с хода {first} по ход {last} — это {last - first + 1} ходов; "
              f"объявленный срок {hold}")
        after = [t for t, m in timeline if t > last and not m]
        print(f"   первый ход без пометки после окна: {after[0] if after else 'нет'}")

    channel = [(row.get("ход"), row.get("кандидаты_коллапса")) for row in rows
               if row.get("кандидаты_коллапса")]
    print(f"\n4) канал `кандидаты_коллапса`: ходов с непустым каналом {len(channel)}")
    for t, c in channel[:6]:
        print(f"   ход {t}: {json.dumps(c, ensure_ascii=False)[:220]}")
    if len(channel) > 6:
        print(f"   … всего {len(channel)}; последний на ходу {channel[-1][0]}")

    print("\n5) помеченный владелец и набор счёта:")
    lo, hi = (turn - 2, (last or turn) + 2)
    for row in rows:
        h = row.get("ход")
        if not isinstance(h, int) or h < lo or h > hi:
            continue
        verdicts = row.get("вердикты") or {}
        split = row.get("разбивка") or []
        ids = {str(x.get("id")) for x in split if isinstance(x, dict)}
        count = row.get("в_расчёте")
        size = count if isinstance(count, int) else len(ids)
        bits = []
        for m in marked:
            v = verdicts.get(m) or {}
            where = "в наборе" if (not ids or m in ids) else "вне набора"
            bits.append(f"{m}: {where}, вердикт {v.get('verdict')}, "
                        f"наблюдение {v.get('observation')}")
        print(f"   ход {h}: сущностей в наборе {size}; " + "; ".join(bits))
        if h == turn:
            for m in marked:
                v = verdicts.get(m) or {}
                print(f"      причина вердикта {m}: {str(v.get('reason'))[:150]}")
                print(f"      свидетель {m}: {v.get('witness')}")

    return 0


raise SystemExit(main())
