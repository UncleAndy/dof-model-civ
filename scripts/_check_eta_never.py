"""Проверка §13.75: предел шкалы в сроке постройки — «никогда», а не число ходов.

Правило одно на проект (`env/video.py`, смоук линз): 32767 = срока нет. Здесь оно проверяется на
читателе срока — с положительным контролем (настоящий срок проходит как срок), отрицательными
(предел в публикации, в собственном замере, в среднем) и контролем честного незнания.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env import spec_eta as E  # noqa: E402

ok = 0
bad = 0


def check(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        bad += 1
        print(f"  ФЕЙЛ {name} {detail}")


NEVER = E.ETA_NEVER
print(f"предел шкалы в читателе: {NEVER}")

check("предел в публикации — срок не выдуман, причина названа",
      E.build_eta(published=NEVER) == (None, "never_scale_limit"),
      str(E.build_eta(published=NEVER)))
check("предел в собственном замере — то же",
      E.build_eta(measured=NEVER) == (None, "never_scale_limit"),
      str(E.build_eta(measured=NEVER)))
check("положительный контроль: настоящий срок проходит как срок",
      E.build_eta(published=5) == (5.0, "published_current"),
      str(E.build_eta(published=5)))
check("предел пропускается в пользу выведенного срока",
      E.build_eta(published=NEVER, price=30, stock=0, shields_per_turn=6)
      == (5.0, "derived_price_shields"),
      str(E.build_eta(published=NEVER, price=30, stock=0, shields_per_turn=6)))
check("предел в среднем не участвует",
      E.build_eta(known_etas=[NEVER, 4, 6]) == (5.0, "estimated_mean"),
      str(E.build_eta(known_etas=[NEVER, 4, 6])))
check("незнание без предела остаётся честным unknown",
      E.build_eta() == (None, "unknown"), str(E.build_eta()))
check("источник never_scale_limit объявлен в списке источников",
      "never_scale_limit" in E.ETA_SOURCES, str(E.ETA_SOURCES))

print(f"\nпроверок: {ok + bad}, падений: {bad}")
sys.exit(1 if bad else 0)
