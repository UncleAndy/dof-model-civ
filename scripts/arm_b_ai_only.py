"""Плечо B: партия, где ВСЕ места отданы встроенному ИИ мира (уровень normal — умолчание).

Что делает:
  1) создаёт партию на слоте (наш клиент — создатель, `aifill N`, `minp 1`);
  2) уступает СВОЁ место встроенному ИИ командой `/aitoggle <наше имя>`;
  3) уходит из партии, чтобы за все места играл только мир;
  4) через заданную паузу возвращается и смотрит, СДВИНУЛСЯ ли ход: если ход
     сдвинулся — партия без наших клиентов идёт; если нет — стоит, и это факт.

Печатает только измеренное: состав на старте, номер хода до ухода, номер хода
после возвращения.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("CIVREALM_LOG_LEVEL", "ERROR")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ProbeTimeout(Exception):
    pass


def _on_alarm(signum, frame):  # noqa: ARG001
    raise ProbeTimeout("проба не успела в отведённое время")


def _guard(seconds, fn, *a, **kw):
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(int(seconds))
    try:
        return fn(*a, **kw)
    finally:
        signal.alarm(0)


def _parse_cli(argv):
    p = argparse.ArgumentParser(description="Плечо B: все места — встроенный ИИ",
                                allow_abbrev=False)
    p.add_argument("--players", type=int, default=4)
    p.add_argument("--slot", type=int, default=0)
    p.add_argument("--pause", type=int, default=300)
    p.add_argument("--reset-timeout", type=int, default=240)
    p.add_argument("--out", default="knowledge/arm_b_probe.json")
    # Чужие флаги (civrealm: --aifill, --minp, --username и их значения)
    # parse_known_args пропускает. Фильтровать по «начинается с --» нельзя:
    # так срезаются значения флагов.
    return p.parse_known_args(argv)[0]


import gymnasium  # noqa: E402
from civrealm.configs import fc_args  # noqa: E402
from civrealm.freeciv.utils.port_utils import Ports  # noqa: E402


def main() -> int:
    args = _parse_cli(sys.argv[1:])

    print("=" * 84)
    print("ПЛЕЧО B: все места — встроенный ИИ мира")
    print("=" * 84)
    print(f"  aifill={fc_args.get('aifill')!r}  minp={fc_args.get('minp')!r}  "
          f"maxplayers={fc_args.get('maxplayers')!r}  "
          f"имя={fc_args.get('username')!r}")

    port = args.slot or _guard(45, Ports.get)
    fc_args["client_port"] = port
    print(f"  слот: {port}")

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = _guard(args.reset_timeout, env.reset, client_port=port)

    ctl = getattr(env.unwrapped, "civ_controller", None)
    pctl = getattr(ctl, "player_ctrl", None)
    our_name = fc_args.get("username")
    our_id = getattr(pctl, "my_player_id", None)
    print(f"  наш игрок: номер {our_id}, имя {our_name!r}, ход {info.get('turn')}")

    try:
        players = list((obs or {}).get("player", {}).get("player_list", {}).keys())
    except Exception:  # noqa: BLE001
        players = []
    print(f"  игроков в партии: {len(players)} -> {players}")

    if our_name:
        ctl.clstate.aitoggle_player(our_name)
        print(f"  отдал своё место ИИ командой /aitoggle {our_name}")
    turn_before = info.get("turn")

    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    print(f"  наш клиент вышел; ход на уходе: {turn_before}")

    print(f"  ждём {args.pause} с без наших клиентов…")
    time.sleep(args.pause)

    turn_after = None
    moved = False
    env2 = gymnasium.make("civrealm/FreecivBase-v0")
    try:
        obs2, info2 = _guard(args.reset_timeout, env2.reset, client_port=port)
        turn_after = info2.get("turn")
        print(f"  ход после возвращения: {turn_after}")
        moved = (turn_after is not None and turn_before is not None
                 and turn_after > turn_before)
        print("  ВЕРДИКТ ПРОБЫ: партия без наших клиентов "
              f"{'ИДЁТ' if moved else 'СТОИТ'}")
    finally:
        try:
            env2.close()
        except Exception:  # noqa: BLE001
            pass

    try:
        with open(os.path.join(ROOT, args.out), "w", encoding="utf-8") as fh:
            json.dump({"slot": port, "players": len(players), "names": players,
                       "turn_before": turn_before, "turn_after": turn_after,
                       "moved": bool(moved)}, fh, ensure_ascii=False, indent=2)
        print(f"  записано: {args.out}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] запись не удалась: {exc!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
