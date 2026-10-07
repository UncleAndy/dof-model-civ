"""Внести в прогон `v0.11` оснастку опыта «разведка против без разведки» (по слову владельца 2026-10-07).

Что делается:
1. `scripts/v011_live_run.py` получает переключатель `V011_SCOUT=1` — поведение «идти к невиданной
   клетке». Это ОСНАСТКА ОПЫТА, а не поведение модели: подпись источника печатается как таковая, по
   умолчанию переключатель выключен, и прогон без него не меняется ни на байт.
2. `scripts/v011_ab_city_norm.py` учится брать окружение плеча извне (`DOF_AB_ENV_A` / `DOF_AB_ENV_B`),
   чтобы тем же судьёй и тем же файлом опыта прогнать «со разведкой» против «без разведки».

Таблица направлений взята НЕ из головы, а из конфига самой игры
(`civrealm/src/civrealm/configs/llm_wrapper_settings.yaml`, строки 3–10): 0 NW, 1 N, 2 NE, 3 **W**,
4 **E**, 5 SW, 6 S, 7 SE — то есть «по кругу» она не читается, середину я бы угадал неверно.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
AB = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_ab_city_norm.py")

SCOUT_CODE = '''#: Направления игры `goto_N` → смещение клетки. Взято из конфига civrealm
#: (`configs/llm_wrapper_settings.yaml`, 0 NW, 1 N, 2 NE, 3 W, 4 E, 5 SW, 6 S, 7 SE) — проверить здесь,
#: а не помнить: 3 и 4 — это запад и восток, последовательность не круговая.
_SCOUT_DIRS = {0: (-1, -1), 1: (0, -1), 2: (1, -1), 3: (-1, 0),
               4: (1, 0), 5: (-1, 1), 6: (0, 1), 7: (1, 1)}
#: Открытая клетка в `obs["map"]["status"]`; всё прочее (0 — вне обзора, 1) считается нераскрытым.
_OPEN = 2


def _scout_action(obs, info):  # noqa: ANN001, ANN201
    """Оснастка опыта: шаг к нераскрытой клетке. `(unit, actor, действие)` или `None`.

    Правило объявлено ДО данных: (1) если рядом с юнитом есть нераскрытая клетка — шаг на неё, при
    нескольких — меньший номер направления; (2) иначе шаг, уменьшающий расстояние до ближайшей
    нераскрытой клетки карты; (3) если и такого нет — юнит пропускается. Ничего не подбирается и не
    взвешивается: это разведка, а не политика.
    """
    units = ((info or {}).get("available_actions") or {}).get("unit") or {}
    grid = ((obs or {}).get("map") or {}).get("status")
    if not units or not grid:
        return None
    xsize = int(((obs or {}).get("map") or {}).get("xsize") or 0)
    unseen = [(y, x) for y, row in enumerate(grid) for x, s in enumerate(row or []) if s != _OPEN]
    if not unseen:
        return None
    for actor in sorted(units):
        names = units.get(actor) or {}
        u = ((obs or {}).get("unit") or {}).get(actor) or {}
        ux, uy = u.get("x"), u.get("y")
        if ux is None or uy is None:
            continue
        here = [(ux + dx, uy + dy) for dx, dy in _SCOUT_DIRS.values()]
        for d in sorted(_SCOUT_DIRS):
            tx, ty = ux + _SCOUT_DIRS[d][0], uy + _SCOUT_DIRS[d][1]
            if tx < 0 or ty < 0 or (xsize and tx >= xsize):
                continue
            if 0 <= ty < len(grid) and 0 <= tx < len(grid[ty]) and grid[ty][tx] != _OPEN:
                if f"goto_{d}" in names:
                    return ("unit", actor, f"goto_{d}")
        best = min(unseen, key=lambda c: max(abs(c[1] - ux), abs(c[0] - uy)))
        dx = (best[1] > ux) - (best[1] < ux)
        dy = (best[0] > uy) - (best[0] < uy)
        for d, (ddx, ddy) in _SCOUT_DIRS.items():
            if (ddx, ddy) == (dx, dy) and f"goto_{d}" in names:
                return ("unit", actor, f"goto_{d}")
    return None


def decide(obs, info, own_id):  # noqa: ANN001, ANN201
'''

ANCHOR_DECIDE = "def decide(obs, info, own_id):  # noqa: ANN001, ANN201\n"
SCOUT_HOOK = '''    global _DRIVER, _LAST_TURN, _PREV_OBS, _SOURCE
    if str(os.environ.get("V011_SCOUT", "") or "").strip() not in ("", "0"):
        action = _scout_action(obs, info)
        _SOURCE[0] = ("РАЗВЕДКА (оснастка опыта «разведка против без разведки»), не поведение модели"
                      if action is not None else
                      "РАЗВЕДКА (оснастка опыта): нераскрытых клеток рядом нет — ход отдан драйверу")
        if action is not None:
            print(f"    разведка (оснастка): {action[2]} юнитом {action[1]}", flush=True)
            return action
'''
ANCHOR_GLOBAL = "    global _DRIVER, _LAST_TURN, _PREV_OBS, _SOURCE\n"

AB_HOOK = '''ARMS = {
    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on"},
    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},
}
for _lvl, _var in (("A", "DOF_AB_ENV_A"), ("B", "DOF_AB_ENV_B")):
    for _item in filter(None, str(os.environ.get(_var, "") or "").split(",")):
        _k, _, _v = _item.partition("=")
        if _k.strip():
            ARMS[_lvl][_k.strip()] = _v.strip()
'''
ANCHOR_ARMS = '''ARMS = {
    "A": {"DOF_CITY_NORM": "narrow", "DOF_PROD_GATE": "on"},
    "B": {"DOF_CITY_NORM": "wide", "DOF_PROD_GATE": "off"},
}
'''

run_text = RUN.read_text(encoding="utf-8")
if "_scout_action" in run_text:
    print("раннер: оснастка разведки уже внесена — пропуск")
else:
    if ANCHOR_DECIDE not in run_text or ANCHOR_GLOBAL not in run_text:
        raise SystemExit("раннер: якоря не найдены — правка не применена")
    run_text = run_text.replace(ANCHOR_DECIDE, SCOUT_CODE, 1)
    run_text = run_text.replace(ANCHOR_GLOBAL, SCOUT_HOOK + ANCHOR_GLOBAL, 1)
    RUN.write_text(run_text, encoding="utf-8")
    print("раннер: внесены _SCOUT_DIRS, _scout_action и хук V011_SCOUT")

ab_text = AB.read_text(encoding="utf-8")
if "DOF_AB_ENV_A" in ab_text:
    print("AB-скрипт: внешнее окружение плеч уже поддержано — пропуск")
else:
    if ANCHOR_ARMS not in ab_text:
        raise SystemExit("AB-скрипт: якорь ARMS не найден — правка не применена")
    ab_text = ab_text.replace(ANCHOR_ARMS, AB_HOOK, 1)
    if "\nimport os" not in ab_text and "import os" not in ab_text.split("\n\n")[0]:
        ab_text = ab_text.replace("import argparse", "import argparse\nimport os", 1)
    AB.write_text(ab_text, encoding="utf-8")
    print("AB-скрипт: окружение плеч берётся из DOF_AB_ENV_A / DOF_AB_ENV_B")

print("── как _run строит окружение (для проверки, что ARMS читается) ──")
for i, line in enumerate(ab_text.splitlines(), 1):
    if "_run(" in line and "def " in line:
        print("\n".join(f"{n:>4}|{l}" for n, l in enumerate(ab_text.splitlines()[i - 1:i + 12], i)))