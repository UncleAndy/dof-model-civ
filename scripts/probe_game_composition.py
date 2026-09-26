#!/usr/bin/env python3
"""Состав игры: сколько цивилизаций в мире и можно ли играть без встроенных ИИ.

Проверка возможности «игры только из наших агентов». Настройки стенда шлёт сам
клиент чат-командами (`/set aifill N`, `/set minp N`), а значения берутся из
аргументов, которые civrealm строит по ключам `default_settings.yaml`. Значит
`--aifill 0` — это параметр запуска, а не доработка.

Проба обязана быть **сравнительной**: «ИИ не подсаживаются» и «флаг
проигнорирован» выглядят одинаково, поэтому запуск с `--aifill 0` сверяется с
запуском по умолчанию (`--aifill 4`). Если состав в обоих случаях одинаков —
флаг не работает, и вывод «играть без ИИ можно» был бы ложным.

Не-наши флаги (всё, что не `--turns`) уходят в civrealm: его парсер читает
`sys.argv` при импорте, поэтому свои аргументы разбираются ДО импорта.

    .venv/bin/python scripts/probe_game_composition.py --turns 12 --aifill 0 --minp 1
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

warnings_filter = None
import warnings  # noqa: E402

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _parse_cli(argv):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--turns", type=int, default=12)
    p.add_argument("--steps-per-turn", type=int, default=6,
                   help="сколько шагов бездействия на один ход")
    p.add_argument("--slot", type=int, default=None,
                   help="пришпилить слот (для дуэли: два процесса на один слот)")
    p.add_argument("--reset-timeout", type=int, default=580,
                   help="сколько ждать старта игры в reset (в дуэли ход ждёт второго)")
    args, rest = p.parse_known_args(argv)
    # civrealm строит свои флаги из настроек; всё лишнее отдаём ему как есть.
    sys.argv = [sys.argv[0]] + rest
    return args


ARGS = _parse_cli(sys.argv[1:])

import gymnasium  # noqa: E402
from civrealm.configs import fc_args  # noqa: E402
from civrealm.freeciv.utils.port_utils import Ports  # noqa: E402


class ProbeTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise ProbeTimeout("проба превысила бюджет времени")


def _guard(seconds, fn, *a, **kw):
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*a, **kw)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    print("=" * 84)
    print("СОСТАВ ИГРЫ: проверка «можно ли играть без встроенных ИИ»")
    print("=" * 84)
    # Печатаем то, что процесс РЕАЛЬНО получил: если флаг не дошёл, это видно
    # здесь, а не выводится догадкой по поведению мира.
    print(f"  aifill={fc_args.get('aifill')!r}  minp={fc_args.get('minp')!r}  "
          f"maxplayers={fc_args.get('maxplayers')!r}  "
          f"phasemode={'player' if not fc_args.get('hotseat_game') else 'hotseat'}")

    port = ARGS.slot if ARGS.slot else _guard(45, Ports.get)
    print(f"  слот: {port}  имя: {fc_args.get('username')!r}")
    fc_args["client_port"] = port

    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = _guard(ARGS.reset_timeout, env.reset, client_port=port)

    def our_id(obs_, env_):
        """Наш номер игрока. Не из `fc_args['player_id']` — там его нет, и
        именно на этой выдумке проба сначала записала себя же в «чужих»."""
        ctl = getattr(getattr(env_.unwrapped, "civ_controller", None),
                      "player_ctrl", None)
        pid = getattr(ctl, "my_player_id", None)
        if pid is not None:
            return pid
        players = obs_.get("player") or obs_.get("players") or {}
        if isinstance(players, dict) and len(players) == 1:
            return list(players.keys())[0]
        return None

    def composition(obs_):
        """Состав слоя игроков: имя, жив, ИИ — то, что сообщает сам мир."""
        players = obs_.get("player") or obs_.get("players") or {}
        out = []
        if isinstance(players, dict):
            for pid, pdata in players.items():
                if isinstance(pdata, dict):
                    out.append((pid, pdata.get("name") or pdata.get("username"),
                                pdata.get("ai", pdata.get("is_ai")),
                                pdata.get("is_alive", pdata.get("alive"))))
                else:
                    out.append((pid, str(pdata)[:40], None, None))
        return out

    print(f"  наш игрок: {our_id(obs, env)!r}")
    print(f"  слой игроков на старте ({len(composition(obs))}): "
          f"{composition(obs)}")

    def others(obs_, info_):
        """Чужие цивилизации: по дипломатии и по владельцам видимых объектов."""
        dipl = (info_.get("available_actions", {}) or {}).get("dipl") or {}
        owners = set()
        for key in ("unit", "city"):
            for item in (obs_.get(key) or {}).values():
                if isinstance(item, dict) and item.get("owner") is not None:
                    owners.add(item["owner"])
        return sorted(dipl.keys()), sorted(owners)

    seen_dipl: set = set()
    seen_owners: set = set()
    turn0 = info.get("turn")
    turns_played = 0
    last_turn = turn0
    print(f"  ход на старте: {turn0}")

    steps = 0
    budget_steps = max(1, ARGS.turns) * max(1, ARGS.steps_per_turn) + 10
    try:
        while turns_played < ARGS.turns and steps < budget_steps:
            steps += 1
            obs, _r, terminated, truncated, info = _guard(
                40, env.step, None)  # бездействие: только оно двигает ход
            d, o = others(obs, info)
            seen_dipl.update(d)
            seen_owners.update(o)
            turn = info.get("turn")
            if turn != last_turn:
                turns_played += 1
                last_turn = turn
            if terminated or truncated:
                print("  игра завершилась досрочно")
                break
    except ProbeTimeout as exc:
        print(f"  [!] {exc} — фиксируем то, что успели увидеть")
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] сбой: {exc!r}")

    print(f"\n  сыграно ходов: {turns_played} (шагов {steps})")
    print(f"  чужие цивилизации в дипломатии: {len(seen_dipl)} -> {seen_dipl}")
    print(f"  владельцы видимых юнитов/городов: {seen_owners}")
    mine = our_id(obs, env)
    final = composition(obs)
    print(f"  слой игроков в конце ({len(final)}): {final}")
    print(f"  наш игрок: {mine!r}")

    foreign = [o for o in seen_owners if mine is None or o != mine]
    foreign_players = [p for p in final if mine is None or p[0] != mine]
    print()
    if seen_dipl or foreign or foreign_players:
        print(f"ВЫВОД: в игре ЕСТЬ чужие цивилизации (дипломатия: {len(seen_dipl)}, "
              f"чужие владельцы: {foreign}, чужие игроки в слое: {len(foreign_players)}).")
    else:
        print("ВЫВОД: чужих цивилизаций НЕ видно и чужих владельцев нет — при "
              f"aifill={fc_args.get('aifill')!r} игра шла без встроенных ИИ.")
    print("Сверяйте с контрольным запуском (aifill по умолчанию): вывод имеет")
    print("смысл только как РАЗНИЦА между двумя запусками.")
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
