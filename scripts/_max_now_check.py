"""Проверка инварианта «сейчас ≤ потолок» на фикстуре и на живом сбросе (числа, не догадки).

Печатает по каждому городу: сколько имён разрешил мир (флаги истинны), сколько наших векторов
посчитано в «сейчас», сколько в потолке, и разность. Если «сейчас» больше потолка — печатает
имена, которых нет в потолке: это и есть причина, а не догадка.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import spec_obs as S  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402

FIXTURE = Path("tests/fixtures/real_obs_01.json")


def report(path: str, label: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        print(f"[{label}] шагов в записи: {len(data)}; беру последний")
        last = data[-1] if data else {}
        obs = last.get("observation") if isinstance(last, dict) else None
    else:
        obs = data.get("observation") if "observation" in data else data
    if not isinstance(obs, dict):
        print(f"[{label}] форма наблюдения не словарь — пропуск")
        return
    info = (data[-1].get("info") if isinstance(data, list) and data
            else data.get("info") if isinstance(data, dict) else None)
    m = S.measure_step(obs, info, (info or {}).get("turn"), GameStateExtractor(), None, 0)
    now = m.get("vectors") or {}
    mx = m.get("v_max") or {}
    print(f"[{label}] сущностей {len(now)}; потолок объявлен у {len(mx)}")
    for eid in sorted(mx):
        counted = sorted(now.get(eid) or [])
        raw = (m.get("raw_menus") or {}).get(eid) or []
        missing = sorted(set(counted) - set(raw) - set())
        print(f"  {eid}: сейчас {len(counted)} ({counted[:6]}), потолок {float(mx[eid]):.1f}")
        if len(counted) > float(mx[eid]):
            print(f"    ⚠ «сейчас» больше потолка — в меню не хватает имён: {missing[:8]}")
    flags = []
    cities = obs.get("city") or {}
    if isinstance(cities, dict):
        for cid, rec in cities.items():
            menu = S.menu_by_entity(obs, valid_only=True)
            got = sorted(set(menu.get(f"city_{cid}", ())) | set(menu.get(str(cid), ())))
            flags.append(f"city_{cid}: флагов мира {len(got)}")
    print("  " + ("; ".join(flags) if flags else "городов в записи нет"))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(FIXTURE)
    report(target, Path(target).name if len(sys.argv) > 1 else "фикстура")