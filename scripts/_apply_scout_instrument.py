"""Довести оснастку разведки до инструмента, который записывает «что открылось».

Владелец (2026-10-07): «Доводи инструмент и запускай».

Что делается и почему:
1. ИСПРАВЛЯЕТСЯ ТРАНСПОЗИЦИЯ. Карта приходит слоями формы (xsize, ysize) = (78, 52), то есть первый
   индекс — x. Оснастка читала `grid[y][x]` — то есть шла не к ближайшей нераскрытой клетке, а куда
   попало. Прошлый опыт из-за этого мерил «движение вообще», а не разведку: это надо было назвать.
2. РЕЖИМЫ. `V011_SCOUT_MODE`:
   - `idle-only` — драйвер первым; разведка только если драйвер не выбрал действия (приоритет у дела);
   - `settler-first` — пока своего города нет, поселенец идёт к нераскрытой клетке; после основания
     первого города оснастка выключается и ход целиком у драйвера (разведка ради места под город).
3. ЗАПИСЬ «ЧТО ОТКРЫЛОСЬ». `V011_SCOUT_LOG=1` → `knowledge/scout_reveal_<метка>.jsonl`: по каждому ходу
   перечень НОВЫХ открытых клеток и что на них — `terrain`, `extras`, `output`, владелец клетки, город,
   юнит и его владелец. Имена слоёв не выдуманы: они прочитаны осмотром наблюдения.
4. ТРЕТЬЕ ПЛЕЧО в AB-скрипте: `C` со своим портом, чтобы контроль (`B`) сравнивался и с приоритетом у
   дела, и с разведкой ради основания.

Ничего в модели не меняется: мера, ядро и генератор нетронуты, оснастка помечена в прогоне и
выключена, если переменной нет.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
AB = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")
text = RUN.read_text(encoding="utf-8")
changed: list[str] = []

# --- 1. Транспозиция в _scout_action ---
OLD_IDX = """    unseen = [(y, x) for y, row in enumerate(grid) for x, s in enumerate(row) if s != _OPEN]"""
NEW_IDX = """    # Слои карты имеют форму (xsize, ysize) → первый индекс это x, а не y. Здесь раньше стояло
    # `grid[y][x]` — транспозиция, из-за которой «ближайшая нераскрытая клетка» была не той.
    unseen = [(x, y) for x, col in enumerate(grid) for y, s in enumerate(col) if s != _OPEN]"""
if OLD_IDX in text:
    text = text.replace(OLD_IDX, NEW_IDX, 1)
    changed.append("индекс карты исправлен на [x][y]")

OLD_CELL = """            if 0 <= ty < len(grid) and 0 <= tx < len(grid[ty]) and grid[ty][tx] != _OPEN:"""
NEW_CELL = """            if 0 <= tx < len(grid) and 0 <= ty < len(grid[tx]) and grid[tx][ty] != _OPEN:"""
if OLD_CELL in text:
    text = text.replace(OLD_CELL, NEW_CELL, 1)
    changed.append("проверка клетки-цели исправлена на [x][y]")

OLD_BOUND = """            if tx < 0 or ty < 0 or (xsize and tx >= xsize):"""
NEW_BOUND = """            if tx < 0 or ty < 0 or (xsize and tx >= xsize) or (ysize and ty >= ysize):"""
if OLD_BOUND in text:
    text = text.replace(OLD_BOUND, NEW_BOUND, 1)
    changed.append("границы по обеим осям")

OLD_XS = """    xsize = int(((obs or {}).get("map") or {}).get("xsize") or 0)"""
NEW_XS = """    xsize = len(grid)
    ysize = len(grid[0]) if grid else 0"""
if OLD_XS in text:
    text = text.replace(OLD_XS, NEW_XS, 1)
    changed.append("размеры берутся из формы слоя, а не из несуществующего ключа")

OLD_NEAR = """        best = min(unseen, key=lambda c: max(abs(c[1] - ux), abs(c[0] - uy)))"""
NEW_NEAR = """        best = min(unseen, key=lambda c: max(abs(c[0] - ux), abs(c[1] - uy)))"""
if OLD_NEAR in text:
    text = text.replace(OLD_NEAR, NEW_NEAR, 1)
    changed.append("расстояние до цели считается по (x, y)")

# --- 2. Запись «что открылось» ---
REC = '''

def _own_city_count(obs) -> int:  # noqa: ANN001
    """Сколько своих городов в наблюдении — считает оснастка, а не догадка."""
    own = None
    try:
        own = int(os.environ.get("V011_OWN_ID", "0"))
    except Exception:  # noqa: BLE001
        own = 0
    cities = (obs or {}).get("city") or {}
    return sum(1 for c in cities.values()
               if isinstance(c, dict) and int(c.get("owner", -1)) == own)


def _record_reveals(obs, turn, tag) -> None:  # noqa: ANN001, ANN201
    """Записать, что открылось за прошедший ход: клетки и их содержимое по слоям наблюдения."""
    if str(os.environ.get("V011_SCOUT_LOG", "") or "").strip() in ("", "0"):
        return
    m = (obs or {}).get("map") or {}
    status = m.get("status")
    if status is None:
        return
    grid = [[int(v) for v in col] for col in status]
    now = {(x, y) for x, col in enumerate(grid) for y, v in enumerate(col) if v == _OPEN}
    prev, prev_turn = _REVEAL["set"], _REVEAL["turn"]
    _REVEAL["set"], _REVEAL["turn"] = now, turn
    if prev is None or prev_turn is None or prev_turn == turn:
        return
    fresh = sorted(now - prev)
    if not fresh:
        return
    def layer(name):  # noqa: ANN001
        arr = m.get(name)
        return [[int(v) for v in col] for col in arr] if arr is not None else None
    layers = {n: layer(n) for n in ("terrain", "extras", "output", "tile_owner",
                                    "city_owner", "unit", "unit_owner")}
    rows = []
    for x, y in fresh:
        item = {"x": x, "y": y}
        for name, arr in layers.items():
            if arr is not None and 0 <= x < len(arr) and 0 <= y < len(arr[x]):
                item[name] = arr[x][y]
        rows.append(item)
    path = ROOT / "knowledge" / f"scout_reveal_{tag or 'none'}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ход": turn, "новых_клеток": len(fresh), "клетки": rows},
                            ensure_ascii=False) + "\\n")

'''
if "_record_reveals" not in text:
    anchor = "\ndef _scout_action(obs, info):  # noqa: ANN001, ANN201"
    if anchor not in text:
        raise SystemExit("место для записи открытий не найдено")
    text = text.replace(anchor, REC + anchor.lstrip("\n"), 1)
    text = text.replace("_SCOUT_DONE_TURNS: set = set()\n",
                        "_SCOUT_DONE_TURNS: set = set()\n"
                        "#: Состояние записи открытий: множество открытых клеток прошлого хода.\n"
                        "_REVEAL: dict = {\"set\": None, \"turn\": None}\n", 1)
    changed.append("запись «что открылось» и счёт своих городов")

# --- 3. Режимы и точки вставки ---
OLD_HOOK = '''    if str(os.environ.get("V011_SCOUT", "") or "").strip() not in ("", "0"):
        # Темп объявлен: один шаг разведки за ход. Иначе на каждый шаг приходится обмен с сервером
        # игры, и мир не успевает за ход (`AssertionError` на `server_timeout_handle`).
        _turn_now = (info or {}).get("turn")
        if _turn_now in _SCOUT_DONE_TURNS:
            action = None
        else:
            action = _scout_action(obs, info)
            if action is not None:
                _SCOUT_DONE_TURNS.add(_turn_now)
'''
NEW_HOOK = '''    _scout_on = str(os.environ.get("V011_SCOUT", "") or "").strip() not in ("", "0")
    _scout_mode = (_scout_mode() or "idle-only")
    # Темп объявлен: один шаг разведки за ход. Иначе на каждый шаг приходится обмен с сервером игры,
    # и мир не успевает за ход (`AssertionError` на `server_timeout_handle`).
    if _scout_on and _scout_mode == "settler-first" and _own_city_count(obs) == 0 \\
            and (info or {}).get("turn") not in _SCOUT_DONE_TURNS:
        _act = _scout_action(obs, info)
        if _act is not None:
            _SCOUT_DONE_TURNS.add((info or {}).get("turn"))
            _SOURCE[0] = "РАЗВЕДКА РАДИ ОСНОВАНИЯ (оснастка опыта), не поведение модели"
            print(f"    разведка ради основания: {_act[2]} юнитом {_act[1]}", flush=True)
            return _act
'''
if OLD_HOOK in text:
    text = text.replace(OLD_HOOK, NEW_HOOK, 1)
    changed.append("режим settler-first")
else:
    print("прежний хук не найден — смотрю прогон вручную")

# после драйвера: idle-only
OLD_TAIL = '''    _SOURCE[0] = ("драйвер: ядро выбрало из измерения" if action is not None
                  else "драйвер: ядро оставило систему на месте")'''
NEW_TAIL = '''    if action is None and _scout_on and _scout_mode == "idle-only" \\
            and turn not in _SCOUT_DONE_TURNS:
        _act = _scout_action(obs, info)
        if _act is not None:
            _SCOUT_DONE_TURNS.add(turn)
            _SOURCE[0] = "РАЗВЕДКА ПРИ ПРОСТОЕ (оснастка опыта), не поведение модели"
            print(f"    разведка при простое: {_act[2]} юнитом {_act[1]}", flush=True)
            action = _act
    _SOURCE[0] = ("драйвер: ядро выбрало из измерения" if action is not None
                  else "драйвер: ядро оставило систему на месте")'''
if OLD_TAIL in text:
    text = text.replace(OLD_TAIL, NEW_TAIL, 1)
    changed.append("режим idle-only")

# вызов записи открытий на каждом ходу
OLD_LAST = """    _LAST_TURN = turn
"""
NEW_LAST = """    _LAST_TURN = turn
    _record_reveals(obs, turn, V.RUN_TAG if hasattr(V, "RUN_TAG") else "")
"""
if "_record_reveals(obs, turn" not in text and OLD_LAST in text:
    text = text.replace(OLD_LAST, NEW_LAST, 1)
    changed.append("запись открытий вызывается каждый ход")

# функция чтения режима
if "def _scout_mode(" not in text:
    text = text.replace("def _own_city_count(obs) -> int:", '''def _scout_mode() -> str:
    """Объявленный режим оснастки: `idle-only` (приоритет у дела) или `settler-first`."""
    return str(os.environ.get("V011_SCOUT_MODE", "") or "").strip()


def _own_city_count(obs) -> int:''', 1)
    changed.append("чтение объявленного режима")

RUN.write_text(text, encoding="utf-8")
print("раннер:", "; ".join(changed) or "ничего не менялось")

# --- 4. Третье плечо в AB-скрипте ---
ab = AB.read_text(encoding="utf-8")
ach: list[str] = []
if '"C"' not in ab.split("for _lvl")[0]:
    ab = ab.replace('''    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},
}''', '''    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},
    "C": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on", "V011_SCOUT": "1",
          "V011_SCOUT_MODE": "settler-first", "V011_SCOUT_LOG": "1"},
}''', 1)
    ach.append("плечо C")
if "V011_SCOUT_LOG" not in ab.split("ARMS = {")[1].split("}")[0]:
    ab = ab.replace('''    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on"},''',
                    '''    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on", "V011_SCOUT": "1",
          "V011_SCOUT_MODE": "idle-only", "V011_SCOUT_LOG": "1"},''', 1)
    ach.append("A: режим приоритета у дела + запись открытий")
    ab = ab.replace('''    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},''',
                    '''    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off", "V011_SCOUT_LOG": "1"},''', 1)
    ach.append("B: контроль + запись открытий")
if "port_c" not in ab:
    ab = ab.replace('''p_pairs.add_argument("--port-b", type=int, default=6004)''',
                    '''p_pairs.add_argument("--port-b", type=int, default=6004)
    p_pairs.add_argument("--port-c", type=int, default=6008)''', 1)
    ab = ab.replace('''        for arm, port in (("A", args.port_a), ("B", args.port_b)):''',
                    '''        for arm, port in (("A", args.port_a), ("B", args.port_b), ("C", args.port_c)):''', 1)
    ab = ab.replace('''            print(f"пара {pair}/2, плечо {arm}''',
                    '''            print(f"пара {pair}/3, плечо {arm}''', 1)
    ach.append("три плеча в цикле пар")
AB.write_text(ab, encoding="utf-8")
print("AB-скрипт:", "; ".join(ach) or "ничего не менялось")

import py_compile  # noqa: E402
for p in (RUN, AB):
    py_compile.compile(str(p), doraise=True)
    print(f"{p.name}: компиляция ок")