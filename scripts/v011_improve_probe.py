"""Замер: скорость накопления щитов у УЛУЧШЕНИЯ (своё правило семейства или юнитовое).

**Зачем.** `v2` (§10.21.3) измерил на этом же стенде, что у улучшений накопление идёт **1 щит за ход
независимо от `prod_shield`** (City Walls 58, Great Wall 293 при ценах 60 и 300), и предупредил:
при смене стенда правило надо перемерить. Наш `city_requirements` пока считает улучшения **юнитовым**
правилом, и `MEASURED_IMPROVEMENT_ACCUMULATION_PER_TURN = None`. Этот прибор добывает **наше** число.

**Объявление ДО данных (правило владельца).**

* Кандидаты — ровно два, из `v2` и из нашей стойки:
  * **A («семейство»)**: скорость = 1 щит/ход, независимо от `prod_shield`;
  * **B («юниты»)**: скорость = `prod_shield` города.
* Измерение: скорость = медиана Δ`shield_stock` за ход **по последовательным наблюдениям одного и того
  же проекта** (смена проекта обрывает серию — иначе замер смешивается).
* Порог вердикта ДО данных: нужно **≥ 3** последовательных наблюдений одного проекта; затем
  `|скорость − 1| < 0.5` → принят A; `|скорость − prod_shield| < 0.5` → принят B; иначе «не установлено».
  Меньше трёх наблюдений — вердикта нет, так и печатается.
* Постановка улучшения — **опыт, а не смена политики**: прибор один раз ставит улучшение сам (иначе
  город остаётся на «процессе» и мерить нечего), и это печатается в выводе как опыт.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "civrealm" / "src"))
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from env import spec_lenses as L  # noqa: E402
from env import spec_obs as SO  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402


def pick_improvement(actions: dict, city_key: str, costs: dict[str, float],
                     unit_names: set[str]) -> Optional[str]:
    """Имя ПОСТРОЙКИ, которое мир САМ предлагает городу сейчас (ставить чужое нельзя: убивает матч).

    Гейт — само предложение мира (`True` у имени), а не каталог технологий: замерено, что каталог
    **неполон** относительно меню (в нём есть `Barracks II`/`Barracks III`, но нет простого `Barracks`,
    а мир его предлагает). Вид определяется отрицанием: имя, которого нет среди ЮНИТОВ мира, — постройка.
    Предпочитается дешёвая известная цена; при равном незнании — порядок мира (алфавитный), который
    заодно уводит от повторяемых «процессов» (`Coinage`) к настоящим постройкам.
    """
    offered = L.section_for(actions.get("city"), city_key)   # ключ живой секции числовой
    if isinstance(offered, dict):
        names = [a for a, ok in offered.items() if ok] or list(offered)
    elif isinstance(offered, list):
        names = list(offered)
    else:
        names = []
    prod = [str(a) for a in names if str(a).startswith(L.SPEC_PRODUCTION_ACTION_PREFIX)]
    cand = [n[len(L.SPEC_PRODUCTION_ACTION_PREFIX):] for n in prod
            if n[len(L.SPEC_PRODUCTION_ACTION_PREFIX):] not in unit_names]
    if not cand:
        print(f"  [опыт] построек не предложено: имён {len(names)} (тип секции {type(offered).__name__}), "
              f"из них производств {len(prod)}, доступные производства: {sorted(prod)[:6]}; "
              f"юнитов в каталоге {len(unit_names)}", flush=True)
        return None
    cand.sort(key=lambda n: (costs.get(n, 10 ** 9), n))
    why = "цена известна" if cand[0] in costs else "цены нет в каталоге — берём по порядку мира"
    name = cand[0]
    print(f"  [опыт] выбрана постройка {name} ({why}); всего доступных построек {len(cand)}: "
          f"{sorted(cand)[:5]}", flush=True)
    return name


def rate_verdict(rows: list[dict[str, Any]]) -> tuple[Optional[float], str]:
    """Скорость по объявленному правилу: медиана Δзапаса по последовательным наблюдениям одного проекта.

    Берутся только наблюдения **после постановки опыта** (`поставлено` заполнено): до неё город строит
    процесс (Coinage-подобный), у которого запас обнуляется по завершении, и его колебания к скорости
    улучшения отношения не имеют.
    """
    series: list[tuple[float, Optional[float]]] = []   # (Δзапаса, выход города В ЭТОЙ паре)
    prev: Optional[dict[str, Any]] = None
    for r in rows:
        if not r.get("поставлено"):
            prev = None
            continue
        if prev is not None and prev.get("проект") == r.get("проект") and prev.get("проект"):
            d = (r.get("запас_щитов") or 0) - (prev.get("запас_щитов") or 0)
            if d > 0:                      # падение = завершение/покупка, скорость оно не показывает
                out = r.get("выход_щитов")
                series.append((float(d), float(out) if isinstance(out, (int, float)) else None))
        prev = r
    if len(series) < 3:
        return None, (f"наблюдений одного проекта после опыта {len(series)} — это мало данных, "
                      f"а не отсутствие правила")
    deltas = [d for d, _ in series]
    rate = float(statistics.median(deltas))
    # Сравнение с выходом города делается ПО СТРОКАМ СЕРИИ: после смены проекта выход другой, и
    # сравнение с последней строкой отчёта давало ложное «не установлено» (замерено 2026-10-07).
    pairs = [(d, o) for d, o in series if o is not None]
    same_as_out = sum(1 for d, o in pairs if abs(d - o) < 0.5)
    if abs(rate - 1.0) < 0.5:
        return rate, f"принят кандидат A («семейство», v2): скорость {rate:g} ≈ 1 щит/ход"
    if pairs and same_as_out == len(pairs):
        return rate, (f"принят кандидат B («юниты»): скорость {rate:g} = выход города "
                      f"в каждой из {len(pairs)} пар наблюдений (v2-правило 1 щит/ход здесь опровергнуто)")
    return rate, (f"скорость {rate:g} (Δ {deltas}); совпало с выходом {same_as_out} из {len(pairs)} пар — "
                  f"ни A, ни B не подтверждены: «не установлено»")


def main() -> int:
    ap = argparse.ArgumentParser(description="Замер скорости накопления улучшения")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=9630)
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--accept-as-rule-a", action="store_true",
                    help="записать принятое число в отчёт (значение в код не вписывается прибором)")
    ap.add_argument("--dump-obs", action="store_true",
                    help="сбросить живое наблюдение на диск (разбор офлайн, стенд не занят)")
    ap.add_argument("--replay", default=None,
                    help="пересудить сохранённый замер (JSON из knowledge/) без стенда")
    a = ap.parse_args()

    if a.replay:
        saved = json.loads(Path(a.replay).read_text(encoding="utf-8"))
        rate, why = rate_verdict(saved.get("строки") or [])
        print(f"[пересуд] {a.replay}")
        print(f"[пересуд] строк {len(saved.get('строки') or [])}; поставлено {saved.get('поставлено')}")
        print(f"[пересуд] ВЕРДИКТ: {why}")
        return 0

    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402

    fc_args["client_port"] = a.port
    fc_args["debug.take_screenshot"] = False
    env = gymnasium.make("civrealm/FreecivBase-v0")
    obs, info = env.reset(client_port=a.port, seed=a.seed)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    extractor = GameStateExtractor(my_player_id=own_id)
    from env.spec_drive import Decider  # noqa: PLC0415
    dec = Decider(extractor, own_id=own_id)
    prev_obs = None
    last_turn = None
    rows: list[dict[str, Any]] = []
    placed: Optional[str] = None
    placed_ok: Optional[bool] = None
    map_printed = [False]
    research_act: Optional[str] = None
    pending_act: Optional[tuple] = None
    bulbs_prev: Optional[int] = None
    bulbs_flat = 0
    try_i = 0
    tried: list[str] = []
    sci_rows: list[dict[str, Any]] = []
    MAX_TRIES = 3

    print(f"[замер] сид {a.seed}, порт {a.port}, наш игрок {own_id}", flush=True)
    print("[замер] кандидаты объявлены ДО данных: A «семейство» (1 щит/ход, v2) против B «юниты» "
          "(prod_shield)", flush=True)
    for step in range(a.turns):
        turn = (info or {}).get("turn")
        if a.dump_obs and step == 2:
            dump = ROOT / "knowledge" / f"obs_dump_{a.seed}_port{a.port}.json"
            dump.write_text(json.dumps(
                {"observation": obs, "available_actions": (info or {}).get("available_actions"),
                 "turn": turn},
                ensure_ascii=False, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
                encoding="utf-8")
            print(f"  [сброс] наблюдение записано: {dump} ({dump.stat().st_size} байт)", flush=True)
        m = SO.measure_step(obs, info, turn, extractor, prev_obs=None, my_player_id=own_id)
        actions = (info or {}).get("available_actions") or {}
        costs = SO.build_cost_index(obs)
        kinds_map = L.name_kind_map(obs.get("tech") or {})
        improve_names = {n for n, k in kinds_map.items() if k == "improvement"}
        unit_names = {n for n, k in kinds_map.items() if k == "unit"}
        try:      # второй источник имён юнитов — мировая таблица (каталог технологий неполон)
            from civrealm.freeciv.utils.unit_improvement_const import UNIT_TYPES  # noqa: PLC0415
            unit_names = unit_names | {str(n) for n in UNIT_TYPES}
        except Exception:  # noqa: BLE001
            pass
        city_sec = actions.get("city") or {}
        if step == 0 or placed is None:
            ck = sorted(str(k) for k in city_sec)[:4]
            prod_names: list[str] = []
            if ck:
                first_key = ck[0] if ck[0] in city_sec else list(city_sec)[0]
                first = city_sec.get(first_key) or {}
                if hasattr(first, "__iter__"):
                    prod_names = sorted({str(n) for n in first
                                         if str(n).startswith(L.SPEC_PRODUCTION_ACTION_PREFIX)})
            print(f"  [диагностика] каталог: имён {len(kinds_map)}, улучшений {len(improve_names)}; "
                  f"контроллеры {sorted(str(k) for k in actions)[:6]}; городские ключи {ck}", flush=True)
            print(f"  [диагностика] предложенные производства: {prod_names[:10]} (всего {len(prod_names)})",
                  flush=True)
            print(f"  [диагностика] пересечение производств с каталогом улучшений: "
                  f"{sorted({n[len(L.SPEC_PRODUCTION_ACTION_PREFIX):] for n in prod_names} & improve_names)[:6]}",
                  flush=True)
        # ── разведка канала науки (владелец разрешил исследования; опыт 1) ──
        pl_sec = actions.get("player") or {}
        pl_rec = L.section_for(obs.get("player"), own_id)
        ps = dict(pl_rec) if isinstance(pl_rec, dict) else {}
        res: list[str] = []
        if step == 0:
            print(f"  [наука] контроллер player: тип {type(pl_sec).__name__}", flush=True)
            pl_names: list[str] = []
            if isinstance(pl_sec, dict):
                for _k in list(pl_sec)[:4]:
                    sec = L.section_for(pl_sec, _k)
                    if hasattr(sec, "__iter__"):
                        pl_names += [str(n) for n in sec]
            elif hasattr(pl_sec, "__iter__"):
                pl_names = [str(n) for n in pl_sec]
            res = sorted({n for n in pl_names if "research" in n.lower() or "tech" in n.lower()})
            print(f"  [наука] предложено игроку действий {len(pl_names)}, из них про науку {len(res)}: "
                  f"{res[:6]}", flush=True)
            print("  [наука] поля игрока: " + ", ".join(
                f"{k}={ps.get(k)}" for k in ("research_name", "researching_cost", "bulbs_researched",
                                             "science_cost", "total_bulbs_prod", "science", "gold")),
                  flush=True)
        print(f"  [наука] ход {turn}: цель {ps.get('research_name')}, цена {ps.get('researching_cost')}, "
              f"накоплено {ps.get('bulbs_researched')}", flush=True)
        # ── ОПЫТ 1: цель науки (владелец разрешил исследования; без цели колотые не копятся) ──
        tsec = (L.section_for(actions.get("tech"), own_id)
                or L.section_for(actions.get("tech"), "cur_player") or {})
        rcand = []
        if hasattr(tsec, "__iter__"):
            rcand = sorted((str(n) for n in tsec if str(n).lower().startswith("research")),
                           key=lambda n: (int(str(n).rsplit("_", 1)[-1])
                                          if str(n).rsplit("_", 1)[-1].isdigit() else 10 ** 6, n))
        bulbs_now = ps.get("bulbs_researched")
        if isinstance(bulbs_now, int):
            if bulbs_prev is not None and bulbs_now <= bulbs_prev:
                bulbs_flat += 1
            else:
                bulbs_flat = 0
            bulbs_prev = bulbs_now
        if pending_act is None and rcand and len(tried) < MAX_TRIES and (
                research_act is None or bulbs_flat >= 2):
            if research_act is not None:
                bulbs_flat = 0
            research_act = rcand[min(len(tried), len(rcand) - 1)]
            tried.append(research_act)
            pending_act = ("tech", "cur_player", research_act)   # контроллер tech адресует актора так же
            print(f"  ОПЫТ: цель науки — {research_act} (попытка {len(tried)} из {MAX_TRIES}; "
                  f"предложено миров {len(rcand)})", flush=True)
        # ── карта «технология → улучшения» по живому каталогу (инструмент выбора цели) ──
        tech_sec = obs.get("tech") or {}
        imp = tech_sec.get("sup_improvements") or []
        if imp and not map_printed[0]:
            map_printed[0] = True
            r0 = imp[0] if isinstance(imp[0], dict) else {}
            print(f"  [карта] секция tech: ключей {len(tech_sec)}; примеры ключей "
                  f"{[str(k) for k in list(tech_sec)[:6]]}; улучшений {len(imp)}", flush=True)
            print(f"  [карта] запись улучшения 0: ключи {sorted(str(k) for k in r0)[:10]}; "
                  f"имя {r0.get('name') or r0.get('rule_name')}; reqs {r0.get('reqs')}", flush=True)
            for act_name in rcand[:4]:
                tid = str(act_name).rsplit("_", 1)[-1]
                cnt = sum(1 for r in imp if isinstance(r, dict) and tid.isdigit()
                          and int(tid) in (r.get("reqs") or []))
                print(f"  [карта] {act_name}: улучшений с этим id в reqs — {cnt}", flush=True)
        sci_rows.append({"ход": turn, "цель": ps.get("research_name"),
                             "цена": ps.get("researching_cost"), "накоплено": ps.get("bulbs_researched"),
                             "изучено": ps.get("techs_researched"),
                             "цель_выбрана_нами": research_act})
        for cid in (() if pending_act is not None else
                    sorted(e for e in m["raw_menus"] if e.startswith("city_"))):
            key = str(cid).split("_", 1)[1]
            fields = m["fields"].get(cid) or {}
            row = {"ход": turn, "город": cid, "запас_щитов": fields.get("shield_stock"),
                   "выход_щитов": fields.get("prod_shield"), "размер": fields.get("size"),
                   "проект": f"{fields.get('production_kind')}:{fields.get('production_value')}",
                   "к_завершению": fields.get("turns_to_prod_complete"),
                   "поставлено": placed}
            rows.append(row)
            print(f"  ход {turn} {cid}: щиты {row['запас_щитов']} (выход {row['выход_щитов']}), "
                  f"проект {row['проект']}, к завершению {row['к_завершению']}, "
                  f"поставлено {placed}", flush=True)
            if placed is None:
                name = pick_improvement(actions, key, costs, unit_names)
                if name:
                    act = ("city", int(key) if str(key).isdigit() else key,
                           f"{L.SPEC_PRODUCTION_ACTION_PREFIX}{name}")   # контроллер города ждёт число
                    offered = actions.get("city", {}).get(key)
                    print(f"  ОПЫТ: ставим улучшение {name} (действие {act}); "
                          f"цена {costs.get(name)}", flush=True)
                    obs2, _r, term2, trunc2, info2 = env.step(act)
                    placed = name
                    before = row["проект"]
                    m2 = SO.measure_step(obs2, info2, (info2 or {}).get("turn"), extractor,
                                         prev_obs=None, my_player_id=own_id)
                    f2 = (m2["fields"].get(cid) or {})
                    after = f"{f2.get('production_kind')}:{f2.get('production_value')}"
                    placed_ok = (before != after)
                    print(f"  ОПЫТ: проект был {before}, стал {after} → "
                          f"{'постановка принята' if placed_ok else 'постановка НЕ принята'}", flush=True)
                    if not obs2 or term2 or trunc2:
                        break
                    obs, info, prev_obs = obs2, info2, obs2
                    break
        if last_turn is not None and turn != last_turn:
            dec.new_turn()
        last_turn = turn
        if pending_act is not None:
            act = pending_act                 # ОПЫТ 1: постановка цели науки
        elif placed is None:
            act = dec.decide(obs, info, turn, prev_obs=prev_obs)
        else:
            act = None                       # после опыта ведём пассивно: мерим, не мешаем
        pending_act = None
        prev_obs = obs
        obs, _r, term, trunc, info = env.step(act)
        if not obs or term or trunc:
            break

    rate, why = rate_verdict(rows)
    rates = [b - a for a, b in zip([r["накоплено"] for r in sci_rows],
                                   [r["накоплено"] for r in sci_rows][1:])
             if isinstance(a, int) and isinstance(b, int)]
    print(f"\n[замер] строк {len(rows)}; постановка улучшения: {placed} "
          f"({'принята' if placed_ok else 'не принята' if placed_ok is not None else 'не сделана'})",
          flush=True)
    print(f"[замер] канал науки: цель {research_act}; цель мира на последнем ходу "
          f"{sci_rows[-1]['цель'] if sci_rows else None}; изучено "
          f"{sci_rows[-1]['изучено'] if sci_rows else None};"
          f" дельты колотых {rates[:12] if rates else 'нет'}", flush=True)
    print(f"[замер] ВЕРДИКТ: {why}", flush=True)
    if rate is not None and a.accept_as_rule_a and abs(rate - 1.0) < 0.5:
        print(f"[замер] к внесению: MEASURED_IMPROVEMENT_ACCUMULATION_PER_TURN = {rate:g}", flush=True)
    out = ROOT / "knowledge" / f"improve_rate_{a.seed}_port{a.port}.json"
    out.write_text(json.dumps({"строки": rows, "наука": sci_rows, "скорость": rate, "вердикт": why,
                               "поставлено": placed, "принята": placed_ok},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[замер] записано {out}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
