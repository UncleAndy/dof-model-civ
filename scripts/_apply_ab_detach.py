"""Применить к `scripts/v011_ab_city_norm.py`: отделение от сессии (`--detach`) и продолжение с места.

Точечный инструмент правок потерял рабочий каталог, поэтому правка идёт скриптом: две конкретные
замены, каждая должна найтись ровно один раз, и файл после правки разбирается синтаксически.
"""
import ast
from pathlib import Path

DOC = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")
text = DOC.read_text(encoding="utf-8")

OLD_PAIRS_HEAD = '''def cmd_pairs(args: argparse.Namespace) -> int:
    global OUT
    if args.out:
        OUT = Path(args.out)
    rows: list[dict] = []
    for i in range(args.pairs):
        seed = args.first_seed + i
        pair = i + 1
'''

NEW_PAIRS_HEAD = '''def _daemonize(args: argparse.Namespace) -> int:
    """Уйти из-под сессии вызывающего: двойной fork + своя сессия + свой лог.

    Долгий опыт не должен зависеть от оболочки, которая его запустила: иначе сигнал сессии убивает
    прогон на середине (проверено: exit −1 после ~35 минут). Пишем `pid`-файл, чтобы живость
    проверялась по процессу, а не по факту запуска.
    """
    log = Path(args.log or "/home/hermes/ab_full.log")
    first = os.fork()
    if first > 0:
        os.waitpid(first, 0)
        return 0
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    with log.open("a", encoding="utf-8") as fh:
        os.dup2(fh.fileno(), 1)
        os.dup2(fh.fileno(), 2)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    Path(args.pid_file or "/home/hermes/ab_run.pid").write_text(str(os.getpid()), encoding="utf-8")
    env = dict(os.environ)
    env["DOF_AB_DETACHED"] = "1"
    argv = [sys.executable] + [a for a in sys.argv if a != "--detach"]
    os.execve(sys.executable, argv, env)
    return 0


def _done_pairs(path: Path) -> set[int]:
    """Пары, у которых уже записаны ОБА плеча: продолжение не должно дублировать прогоны."""
    done: dict[int, set[str]] = {}
    if not path.exists():
        return set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        done.setdefault(int(rec.get("pair") or 0), set()).add(str(rec.get("arm")))
    return {pair for pair, arms in done.items() if {"A", "B"} <= arms}


def cmd_pairs(args: argparse.Namespace) -> int:
    global OUT
    if args.out:
        OUT = Path(args.out)
    if getattr(args, "detach", False) and os.environ.get("DOF_AB_DETACHED") != "1":
        _daemonize(args)
        return 0
    finished = _done_pairs(OUT)
    rows: list[dict] = []
    for i in range(args.pairs):
        seed = args.first_seed + i
        pair = i + 1
        if pair in finished:
            print(f"пара {pair} (сид {seed}) уже записана — пропуск")
            continue
'''

OLD_ARGS = '''    p_pairs.add_argument("--out", default="", help="свой файл опыта (пилоту — своё имя, а не общее)")
'''

NEW_ARGS = '''    p_pairs.add_argument("--out", default="", help="свой файл опыта (пилоту — своё имя, а не общее)")
    p_pairs.add_argument("--detach", action="store_true",
                         help="уйти из-под сессии (двойной fork + своя сессия): долгий опыт не гибнет с оболочкой")
    p_pairs.add_argument("--log", default="", help="куда писать вывод при --detach")
    p_pairs.add_argument("--pid-file", default="", help="файл с pid отделённого опыта")
'''

for old, new, label in ((OLD_PAIRS_HEAD, NEW_PAIRS_HEAD, "голова pairs"),
                        (OLD_ARGS, NEW_ARGS, "аргументы pairs")):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: найдено {count} вхождений, ожидалось 1 — правка не применена")
    text = text.replace(old, new, 1)

DOC.write_text(text, encoding="utf-8")
ast.parse(text)
print("правка применена, синтаксис ок, строк:", text.count(chr(10)) + 1)