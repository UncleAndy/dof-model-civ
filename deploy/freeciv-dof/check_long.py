#!/usr/bin/env python3
"""Журнальная проверка серии: у каждого объявления DOF-места был ли живой
помеченный юнит у цели на момент объявления; плюс счётчики журнала.

Запуск: .venv/bin/python deploy/freeciv-dof/check_long.py long_none long_dof long_even
Логи читаются из контейнера (docker exec cat).
"""
import re
import subprocess
import sys

C = "freeciv-web"
ROOT = "/home/docker/dofrun/series"

RE_SRC = re.compile(r"\[DOF\] unit_source turn=(\d+) unit=(-?\d+) utype=.+? owner=(.+) victim=(.+)$")
RE_SRC_BARB = re.compile(r"\[DOF\] unit_source_barb turn=(\d+) unit=(-?\d+) utype=.+? owner=(.+) victim=(.+)$")
RE_GONE = re.compile(r"\[DOF\] unit_gone turn=(\d+) unit=(-?\d+) owner=")
RE_DECL = re.compile(r"\[DOF\] declare turn=(\d+) declarer=(.+) target=(.+) declarer_dof=(\d)(.*)$")
RE_RULE = re.compile(r"\[DOF\] rule turn=(\d+) me=.+? other=(.+) what=([a-z_]+)( barb=1)?$")
# Строка отказа несёт юнит (P0: один отказ на пару «юнит, цель, ход»), поэтому
# хвост ` unit=ID` стал обязательным до варварской пометки.
RE_BLOCK = re.compile(r"\[DOF\] blocked turn=(\d+) me=.+? other=(.+) "
                      r"what=([a-z_]+)( unit=\d+)?( barb=1)?$")


def read(tag, idx):
    p = subprocess.run(["docker", "exec", C, "cat", f"{ROOT}/{tag}/{idx}/stdout.txt"],
                       capture_output=True, text=True, errors="replace")
    return p.stdout.split("\n") if p.returncode == 0 else []


def check(tag, games=20):
    st = dict(decl=0, decl_matched=0, unmatched=[], marks=0, marks_barb=0, gone=0,
              rules={}, rules_barb=0, blocked=0, blocked_barb=0)
    for idx in range(games):
        marks, gone, decls = [], {}, []
        lines = read(tag, idx)
        for no, ln in enumerate(lines):
            s = ln.strip()
            m = RE_SRC.match(s)
            if m:
                marks.append((int(m.group(1)), m.group(3).strip(), int(m.group(2)), no))
                gone.pop(int(m.group(2)), None)  # новая пометка = новая жизнь юнита
                st["marks"] += 1
                continue
            m = RE_SRC_BARB.match(s)
            if m:
                marks.append((int(m.group(1)), m.group(3).strip(), int(m.group(2)), no))
                st["marks_barb"] += 1
                continue
            m = RE_GONE.match(s)
            if m:
                gone[int(m.group(2))] = no
                st["gone"] += 1
                continue
            m = RE_DECL.match(s)
            if m and m.group(4) == "1":
                decls.append((int(m.group(1)), m.group(3).strip(), no))
                continue
            m = RE_RULE.match(s)
            if m:
                st["rules"][m.group(3)] = st["rules"].get(m.group(3), 0) + 1
                if m.group(4):
                    st["rules_barb"] += 1
                continue
            m = RE_BLOCK.match(s)
            if m:
                st["blocked"] += 1
                if m.group(4):
                    st["blocked_barb"] += 1
        for turn, tgt, dno in decls:
            st["decl"] += 1
            # Пометка считается живой, если её поставили не позже объявления, а
            # unit_gone (если он вообще есть) записан ПОСЛЕ объявления: юнит мог
            # погибнуть позже в тот же ход, и тогда движок прав.
            alive = [u for (t, o, u, mno) in marks
                     if o == tgt and t <= turn and gone.get(u, 10 ** 18) > dno]
            if alive:
                st["decl_matched"] += 1
            else:
                st["unmatched"].append((idx, turn, tgt))
    return st


def main():
    for tag in sys.argv[1:]:
        st = check(tag)
        print(f"== {tag}")
        print(f"  объявлений DOF-мест: {st['decl']} | с живой пометкой: {st['decl_matched']} "
              f"| без: {len(st['unmatched'])}")
        if st["unmatched"]:
            for u in st["unmatched"][:5]:
                print("   без пометки:", u)
        print(f"  пометок: {st['marks']} обычных + {st['marks_barb']} варварских | unit_gone: {st['gone']}")
        print(f"  правила: {st['rules']} | с варваром: {st['rules_barb']} "
              f"| blocked: {st['blocked']} (из них варварских {st['blocked_barb']})")


if __name__ == "__main__":
    main()
