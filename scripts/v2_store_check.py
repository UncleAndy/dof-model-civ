"""Проверка МЕХАНИЗМА базы знаний (не сбор данных вручную).

Что проверяется:
1. база живёт между партиями: знание первой партии доступно во второй;
2. постоянное знание (типы, технологии, словарь меню) копится, состояние партии — нет;
3. открытые вопросы ВЫВОДЯТСЯ из графа, а не написаны человеком.

Данные наполняет мир в ходе игры — это то, что в настоящей модели делает сам агент.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

from brain.v2.knowledge import GAME_KINDS, PERMANENT_KINDS  # noqa: E402
from brain.v2.store import KnowledgeStore  # noqa: E402

STORE = os.environ.get("V2_STORE", "/tmp/v2_knowledge.json")
TURNS = int(os.environ.get("V2_TURNS", "4"))
GAMES = [(9000, 6300), (9001, 6301)]


def play(store: KnowledgeStore, seed: int, port: int, turns: int) -> None:
    fc_args["client_port"] = port
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=port, seed=seed)
    try:
        my_id = env.get_playerid()
    except Exception:  # noqa: BLE001
        my_id = 0
    for _ in range(turns):
        store.observe(obs, (info or {}).get("available_actions") or {}, own_id=my_id or 0)
        obs, _r, terminated, truncated, info = env.step(None)
        if terminated or truncated:
            break
    try:
        env.close()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    if os.environ.get("V2_FRESH", "1") == "1" and Path(STORE).exists():
        Path(STORE).unlink()
    store = KnowledgeStore(STORE)
    print("== до партий ==")
    print(store.report())

    for i, (seed, port) in enumerate(GAMES, start=1):
        play(store, seed, port, TURNS)
        kinds_before_save = {}
        for e in store.graph.entities.values():
            kinds_before_save[e.kind] = kinds_before_save.get(e.kind, 0) + 1
        store.end_game()
        print(f"\n== после партии {i} (сид {seed}, порт {port}) ==")
        print("  в памяти было:", dict(sorted(kinds_before_save.items())))
        print(store.report(limit=8))

    print("\n== перезагрузка базы с диска (что пережило партии) ==")
    reloaded = KnowledgeStore(STORE)
    st = reloaded.graph.stats()
    print("  сущностей на диске:", st["entities"], st["by_kind"])
    print("  постоянные виды:", list(PERMANENT_KINDS), "| виды партии отброшены:", list(GAME_KINDS))
    print("  наборы возможностей:", reloaded.summary()["наборы_возможностей"])
    ok = not any(k in st["by_kind"] for k in GAME_KINDS)
    print(f"\n  состояние партии на диск НЕ попало: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())