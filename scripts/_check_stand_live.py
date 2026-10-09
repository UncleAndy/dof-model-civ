"""Готовность стенда перед долгой серией: слоты, ответ, свежесть артефактов (§13.107).

Почему прибор переписан (моя ошибка, измеренная). Первая версия спрашивала HTTP у ИГРОВЫХ портов
(6000, 6004, 6005) с таймаутом 2 с и объявляла стенд мёртвым при коде `000`. На деле:

* игровые порты говорят по WebSocket, HTTP там НЕ отвечает никогда — запрос висит до таймаута, и это
  не признак смерти стенда, а признак вопроса не тому порту (измерено: `curl -sv -m 20
  http://127.0.0.1:6000/pubstatus` — соединение установлено, ответа 0 байт за 20 с);
* страница живости `/pubstatus` живёт на ПАРНОМ ПРОКСИ (6000 ↔ 7000) и отвечает 200 с текстом
  «Process status: OK» (измерено: 7000/7001/7002/7003 — 200; 7004+ — нет);
* сокет в состоянии LISTEN не признак живости: мёртвый слушатель и живой приложение-сервер в `ss`
  выглядят одинаково.

Отсюда правило проверки: **живость = ответ парного прокси, а не HTTP на игровом порту.**

  П1 каждый слот: TCP-коннект на игровой порт И HTTP 200 с «Process status: OK» на парном прокси;
  П2 свежесть артефактов: возраст новейшей трассы в `knowledge/` (правило 84);
  П3 вердикт: серия возможна, только если живы обе руки A и B (и их прокси).

Код возврата: 0 — серия возможна, 1 — нет.
"""
from __future__ import annotations

import pathlib
import socket
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Слот: имя руки, игровой порт, парный порт прокси (6000 -> 7000).
SLOTS = (
    ("A", 6000, 7000),
    ("B", 6001, 7001),
    ("C", 6002, 7002),
)

TCP_TIMEOUT = 3.0
HTTP_TIMEOUT = 8.0


def tcp_ok(port: int) -> bool:
    """Принимает ли порт соединение (игровой порт говорит по WebSocket, не по HTTP)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TCP_TIMEOUT):
            return True
    except OSError:
        return False


def proxy_status(proxy: int) -> tuple[int, bool]:
    """Код ответа страницы живости и признак «Process status: OK»."""
    url = f"http://127.0.0.1:{proxy}/pubstatus"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            return int(r.status), "Process status: OK" in body
    except urllib.error.HTTPError as e:
        return int(e.code), False
    except Exception:
        return 0, False


def newest_artifact() -> tuple[str, float]:
    best, best_m = "", -1.0
    for p in ROOT.glob("knowledge/*.jsonl"):
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > best_m:
            best, best_m = str(p.relative_to(ROOT)), m
    if best_m < 0:
        return "(нет файлов)", float("inf")
    return best, (time.time() - best_m) / 60.0


def main() -> int:
    smoke = "--smoke" in sys.argv
    print("── слоты: игровой порт по TCP, парный прокси по HTTP ──")
    live: dict[str, bool] = {}
    for name, port, proxy in SLOTS:
        t = tcp_ok(port)
        code, ok_text = proxy_status(proxy)
        alive = t and code == 200 and ok_text
        live[name] = alive
        print(f"  {name}: игровой {port} TCP {'есть' if t else 'нет'} | прокси {proxy} "
              f"HTTP {code}{', «Process status: OK»' if ok_text else ''} ⇒ "
              f"{'годен по сокету' if alive else 'мёртв'}")

    if smoke:
        # Сокет и прокси НЕ доказывают, что слот отдаст партию: измерено (§13.108) — в один и тот
        # же момент 6000 и 6001 играли (код 0), а 6002 и 6003 давали BeginTurnTimeoutException.
        # Единственная честная проверка слота перед серией — сыграть в него.
        print("── проба игрой: по 5 ходов на слот (единственная честная проверка) ──")
        import subprocess
        for name, port, _proxy in SLOTS:
            seed = 9500 + port
            cmd = [str(ROOT / ".venv" / "bin" / "python"), "scripts/v011_live_run.py",
                   "--port", str(port), "--seed", str(seed), "--turns", "5"]
            try:
                r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180)
                code = r.returncode
                err = ""
                for token in ("BeginTurnTimeoutException", "AssertionError", "Timeout"):
                    if token in (r.stdout + r.stderr):
                        err = token
                        break
            except subprocess.TimeoutExpired:
                code, err = -1, "не ответил за 180 с"
            plays = code == 0
            live[name] = live[name] and plays
            print(f"  {name}: слот {port} — код {code}, играет: {'да' if plays else 'НЕТ'}"
                  f"{f', ошибка {err}' if err else ''}")

    art, age = newest_artifact()
    print("── свежесть артефактов (правило 84) ──")
    print("  трасс в knowledge/ нет вовсе" if age == float("inf")
          else f"  новейшая трасса: {art}, запись {age:.1f} мин назад")

    possible = live.get("A", False) and live.get("B", False)
    print()
    if possible:
        print("ВЕРДИКТ: серия возможна — руки A и B живы.")
        print("Пилот (своё имя файла, правило 78a):")
        print("  .venv/bin/python scripts/v011_ab_city_norm.py pairs --pairs 1 --first-seed 9200 \\")
        print("      --turns 150 --port-a 6000 --port-b 6001 --out knowledge/ab_pilot_9200.jsonl")
        print("Серия (отцепленно): тот же вызов с --pairs 10 --first-seed 9200 --detach \\")
        print("      --log /home/hermes/ab_series_9200.log --pid-file /home/hermes/ab_series_9200.pid")
    else:
        print("ВЕРДИКТ: серия НЕВОЗМОЖНА — живы руки:",
              ", ".join(k for k, v in live.items() if v) or "ни одной")
        print("Помни про ловушку: HTTP на ИГРОВОМ порту не отвечает никогда — спрашивай парный прокси.")
    return 0 if possible else 1


raise SystemExit(main())
