"""Диагностика: читается ли занятие юнита из мира вообще (§13.281).

Правило удержания сработало 0 раз за прогон, и я не могу отличить два случая: (а) правило
молчит, потому что юниты свободны, (б) занятие в НАШЕМ наблюдении не приходит. Печатаю оба
факта, чтобы не гадать. Идемпотентно.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

OLD_FIELD = '''            if not isinstance(unit, dict) or "activity" not in unit:
                continue
'''
NEW_FIELD = '''            if not isinstance(unit, dict):
                continue
            if "activity" not in unit:
                # Диагностика §13.281: без неё «правило молчит» и «занятие не приходит»
                # неразличимы, и правку нельзя проверить честно.
                _activity_diag("нет поля activity", uid)
                continue
'''
OLD_EMPTY = '''        return out
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [занят] занятие юнитов не прочитано: {type(exc).__name__}: {exc}",
                  flush=True)
        return {}
'''
NEW_EMPTY = '''        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [занят-диагностика] прочитано занятий: {len(out)} "
                  f"(юнитов в мире {len(units) if isinstance(units, dict) else 0}, "
                  f"мой id {my_id}); состояния {list(out.values())[:6]}", flush=True)
        return out
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("DOF_TRACE_FILTERS") == "1":
            print(f"  [занят] занятие юнитов не прочитано: {type(exc).__name__}: {exc}",
                  flush=True)
        return {}
'''

HELPER = '''def _activity_diag(why: str, uid=None) -> None:
    """Почему занятие не прочитано — иначе «правило молчит» неотличимо от «данных нет»."""
    if os.environ.get("DOF_TRACE_FILTERS") != "1":
        return
    print(f"  [занят-диагностика] {why} (юнит {uid})", flush=True)


'''

text = PATH.read_text(encoding="utf-8")
changed = 0

if "def _activity_diag(" in text:
    print("диагностика уже есть")
else:
    anchor = "def _is_idle_activity(value) -> bool:\n"
    assert text.count(anchor) == 1, "якорь _is_idle_activity не однозначен"
    text = text.replace(anchor, HELPER + anchor)
    changed += 1

for old, new in ((OLD_FIELD, NEW_FIELD), (OLD_EMPTY, NEW_EMPTY)):
    if new in text:
        print("уже внесено")
        continue
    assert text.count(old) == 1, f"якорь не однозначен: {old[:50]!r}"
    text = text.replace(old, new)
    changed += 1

PATH.write_text(text, encoding="utf-8")
print(f"правок внесено: {changed}")

import ast  # noqa: E402
ast.parse(text)
print("синтаксис ок")
