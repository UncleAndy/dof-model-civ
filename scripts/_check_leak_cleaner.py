"""Проверка уборщика утечек: он обязан видеть СИРОТ, но не браузер живого прогона.

Собираем две поддельные пары, не трогая стенд:

* «живой прогон» — процесс с `v011_live_run.py` в командной строке, который САМ рождает ребёнка-браузер
  и печатает его pid в файл; значит у браузера в предках есть прогон, и уборщик его трогать не должен;
* «сирота» — такой же браузер, но его родитель умирает сразу, поэтому он остаётся под init.

Ожидание в сухом прогоне уборщика: найден ровно ОДИН съёмочный браузер (сирота), а pid живого в списке
отсутствует и процесс жив.

Почему подделка сделана именно так: `exec -a` здесь не годится (здешний `sleep` — многопрограммный
coreutils, он разбирает `argv[0]` и падает), а `#` вне кавычек съедается оболочкой, поэтому слова-приметы
(`firefox --marionette --headless`) стоят ВНУТРИ кода python — в командной строке они видны, для python
это комментарий.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
CLEANER = ROOT / "scripts" / "kill_leaked_browsers.py"
MARK = "firefox --marionette --headless"

RUNNER_CODE = f"""
import pathlib, subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(45)  # {MARK}"])
pathlib.Path(sys.argv[1]).write_text(str(kid.pid))
time.sleep(45)
"""


def line_value(out: str, prefix: str) -> int:
    for line in out.splitlines():
        if line.startswith(prefix):
            return int(line.split(":")[1].strip())
    raise SystemExit(f"нет строки «{prefix}» в выводе уборщика:\n{out}")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        script = tmp / "v011_live_run.py"
        script.write_text(RUNNER_CODE, encoding="utf-8")
        live_pid_file = tmp / "live.pid"
        runner = subprocess.Popen([PY, str(script), str(live_pid_file)])
        for _ in range(50):
            if live_pid_file.exists() and live_pid_file.read_text().strip():
                break
            time.sleep(0.2)
        live_pid = int(live_pid_file.read_text().strip())

        # Сирота: рождается от короткоживущего `sh`, который сразу умирает, значит остаётся у init.
        short = tmp / "orphan.pid"
        subprocess.run(
            ["bash", "-c", f'"{PY}" -c "import time; time.sleep(45)  # {MARK}" & echo $! > {short}'],
            check=True, stdout=subprocess.DEVNULL,
        )
        for _ in range(50):
            if short.exists() and short.read_text().strip():
                break
            time.sleep(0.2)
        orphan_pid = int(short.read_text().strip())
        time.sleep(1.5)

        out = subprocess.run([PY, str(CLEANER), "--dry"], capture_output=True, text=True,
                             cwd=str(ROOT)).stdout
        seen = line_value(out, "найдено съёмочных браузеров:")

        print("── вывод уборщика ──")
        print(out.strip())
        print("── проверки ──")
        ok = True

        def check(name: str, cond: bool) -> None:
            nonlocal ok
            print(f"  {'OK  ' if cond else 'ФЕЙЛ'} {name}")
            ok = ok and cond

        check(f"сирота {orphan_pid} попал в список", f"  {orphan_pid}:" in out)
        check(f"съёмочных браузеров найдено ровно 1 (сирота), а не 2: найдено {seen}", seen == 1)
        check(f"живой браузер {live_pid} (ребёнок прогона {runner.pid}) в списке отсутствует",
              f"  {live_pid}:" not in out)
        check(f"живой браузер {live_pid} жив", alive(live_pid))
        check("обёртка живого прогона жива", runner.poll() is None)

        for pid in (runner.pid, live_pid, orphan_pid):
            try:
                os.kill(pid, 15)
            except (ProcessLookupError, PermissionError):
                pass
        print("ВСЁ ЗЕЛЁНОЕ" if ok else "ЕСТЬ ПАДЕНИЯ")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
