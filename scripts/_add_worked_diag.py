"""Диагностика: сколько клеток реально обрабатывает город (§13.290).

Зачем. Рост упирался в излишек еды 0 при размере 1. У города размера 1 должен быть один
горожанин вне центра, то есть как минимум ДВЕ обработанные клетки (центр + горожанин). Если
обработана только одна, дело не в клетках и не в ценах, а в том, что горожане не
расставлены — и тогда чинить надо расстановку, а не выбор работы рабочим.

Источник факта — сам клиент: у каждой клетки есть поле `worked` = id города, который её
обрабатывает (`civrealm/src/civrealm/freeciv/map/tile.py:63`). Печатаем только под следом и
только для своих городов.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "baselines" / "run_real_tournament.py"

OLD = """    print(f"      [состояние {row['turn']}] сущ={row['obs_entities']} \""""

NEW = """    if os.environ.get("DOF_TRACE_FILTERS") == "1":
        # §13.290: сколько клеток обрабатывает каждый свой город. Мир помечает клетку полем
        # `worked` = id города (`civrealm/.../map/tile.py:63`). Город размера 1 обязан
        # обрабатывать центр И клетку горожанина: если обработана одна — горожане не
        # расставлены, и дело не в ценах и не в работах.
        try:
            _worked_layer = (as_dict(obs.get("map")) or {}).get("worked")
            _counts = {}
            if _worked_layer is not None:
                import numpy as np

                _wa = np.asarray(_worked_layer)
                _ids = [c.get("id") for c in my_cities]
                for _cid in _ids:
                    if _cid is None:
                        continue
                    _counts[_cid] = int((_wa == _cid).sum())
            _sizes = {c.get("id"): c.get("size") for c in my_cities}
            print(f"      [обработка] свои города: "
                  f"{[(cid, f'размер {_sizes.get(cid)}', f'клеток {n}') for cid, n in _counts.items()]}"
                  f"{' (слой worked не пришёл)' if not _counts else ''}",
                  flush=True)
        except Exception as _exc:  # noqa: BLE001 - диагностика не должна рушить матч
            print(f"      [обработка] не измерена: {_exc!r}", flush=True)
    print(f"      [состояние {row['turn']}] сущ={row['obs_entities']} \""""

text = PATH.read_text(encoding="utf-8")
if "[обработка]" in text:
    print("уже внесено")
else:
    assert text.count(OLD) == 1, "якорь не однозначен"
    PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("внесено")
ast.parse(PATH.read_text(encoding="utf-8"))
print("синтаксис ок")
