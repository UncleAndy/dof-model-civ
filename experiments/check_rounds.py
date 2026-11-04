#!/usr/bin/env python3
"""Смоук-тест драйвера раундов и проверка артефактов серии.

Две задачи, обе без запуска партий:

  check_rounds.py --self-test              проверить сам драйвер (руки, роспись мест,
                                           сборку раунда, индекс, запись версии движка)
  check_rounds.py --series DIR [...]       проверить готовую серию: все руки на месте,
                                           роспись совпадает с политикой, агрегаты
                                           сходятся с нациями, индекс соответствует раундам
  check_rounds.py --all                    то же по всем experiments/dof-*

Код возврата 1, если нашли нарушение (не предупреждение): этим проверка годится
как гейт перед отчётом.
"""
import argparse
import glob
import json
import os
import re
import statistics as st
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ab_rounds as drv  # noqa: E402

ROSTER_RX = re.compile(r"idx=(\d+):dof=(\d)")
ARMS_11 = "d0:none;d1:rot1;d2:rot2;d3:rot3;d4:rot4;d5:rot5;d6:rot6;d7:rot7;d8:rot8;d9:rot9;d10:all"
FAKE_ENGINE = {"binary_md5": "f" * 32, "binary_path": "/x/freeciv-web",
               "sources_md5": {"dofpolicy.c": "a" * 32, "dofpolicy.h": "b" * 32},
               "sources_local_md5": {"dofpolicy.c": "a" * 32, "dofpolicy.h": "b" * 32},
               "sources_match_local": True, "image_tag": "img:1", "image_id": "sha256:0"}


def expected_dof(policy, seats):
    """Сколько мест с dof=1 должно быть в партии при такой политике.

    seats — индексы мест партии: even/odd в движке выбирают по чётности
    индекса, поэтому на карте с 8 местами это 4, а не 5.
    """
    p = (policy or "").strip().split(":")[0].strip()
    n = len(seats)
    if p == "none":
        return 0
    if p == "all":
        return n
    if p == "even":
        return sum(1 for i in seats if i % 2 == 0)
    if p == "odd":
        return sum(1 for i in seats if i % 2 == 1)
    if re.fullmatch(r"rot\d+", p):
        return int(p[3:])
    if re.fullmatch(r"\d+(,\d+)*", p):
        return len([x for x in p.split(",") if x.strip()])
    return None


class Report:
    def __init__(self, name):
        self.name = name
        self.bad, self.warn = [], []
        self.checked = 0

    def fail(self, where, msg):
        self.bad.append(f"{where}: {msg}")

    def warn_(self, where, msg):
        self.warn.append(f"{where}: {msg}")

    def dump(self):
        print(f"\n[{self.name}] проверено записей: {self.checked}")
        for w in self.warn[:12]:
            print(f"  предупреждение  {w}")
        if len(self.warn) > 12:
            print(f"  ... предупреждений ещё {len(self.warn) - 12}")
        for b in self.bad[:20]:
            print(f"  НАРУШЕНИЕ       {b}")
        if len(self.bad) > 20:
            print(f"  ... нарушений ещё {len(self.bad) - 20}")
        print(f"[{self.name}] итог: {'OK' if not self.bad else 'FAIL'}"
              f" (нарушений {len(self.bad)}, предупреждений {len(self.warn)})")
        return not self.bad


# ---------------------------------------------------------------- серия


def verify_config(rep, where, base_dir, cfg):
    """Конфиги партии лежат рядом с раундом и должны совпадать по sha256."""
    d = os.path.join(base_dir, cfg.get("dir") or "")
    for name, key in (("s.serv", "s_serv_sha256"), ("policy.conf", "policy_file_sha256")):
        want = cfg.get(key)
        path = os.path.join(d, name)
        if not want or want == "?":
            rep.fail(where, f"в конфиге нет {key}")
            continue
        if not os.path.exists(path):
            rep.warn_(where, f"файл конфига {name} отсутствует в артефактах")
            continue
        import hashlib
        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if got != want:
            rep.fail(where, f"sha256 {name} не совпадает с записанным в разделе")


def check_section(rep, where, arm, sec, params, base_dir, legacy=False):
    if not isinstance(sec, dict):
        rep.fail(where, "раздел руки не объект")
        return
    roster = sec.get("dof_roster")
    if roster is None:
        rep.warn_(where, "нет росписи мест (dof_roster)")
    else:
        seats = {int(i): int(v) for i, v in ROSTER_RX.findall(roster)}
        aifill = sec.get("aifill") or params.get("aifill") or 10
        if len(seats) != aifill:
            rep.fail(where, f"в росписи {len(seats)} мест, в партии aifill={aifill}: {roster!r}")
        want = expected_dof(sec.get("policy"), list(seats))
        have = sum(1 for v in seats.values() if v == 1)
        if want is None:
            rep.warn_(where, f"неизвестная политика {sec.get('policy')!r}")
        elif want != have:
            rep.fail(where, f"политика {sec.get('policy')!r}: мест с dof=1 {have}, ожидалось {want}")
    if not isinstance(sec.get("final_turn"), int) or sec["final_turn"] <= 0:
        if legacy:
            rep.warn_(where, "старая схема раздела: нет финального хода (до save_facts)")
        else:
            rep.fail(where, f"нет финального хода: {sec.get('final_turn')!r}")
    save = sec.get("save") or {}
    if legacy and not save:
        pass
    elif not save.get("sha256") or save.get("sha256") == "?":
        rep.fail(where, "у партии нет sha256 финального сейва")
    elif not save.get("bytes"):
        rep.warn_(where, "размер сейва 0")

    nations = [n for n in sec.get("nations") or [] if not n.get("is_barbarian")]
    if not nations:
        rep.fail(where, "в разделе нет наций")
        return
    t = sec.get("totals") or {}
    seats = [n for n in nations if (n.get("id") or 0) < 10]
    split = [n for n in nations if (n.get("id") or 0) >= 10]
    checks = {
        "score_sum": sum(n.get("score") or 0 for n in seats),
        "cities_sum": sum(n.get("ncities") or 0 for n in seats),
        "population_sum": sum(n.get("population_real") or 0 for n in seats),
        "splinters": len(split),
        "splinters_score_sum": sum(n.get("score") or 0 for n in split),
    }
    if t.get("totals_schema") != 2:
        # старая схема: агрегаты считались по всем нациям вместе с отколовшимися
        if t.get("score_sum") != sum(n.get("score") or 0 for n in nations):
            rep.fail(where, "totals.score_sum не сходится с нациями (старая схема)")
    else:
        for k, v in checks.items():
            if t.get(k) != v:
                rep.fail(where, f"totals.{k}={t.get(k)} не сходится с местами ({v})")
        if t.get("nations") != len(nations):
            rep.fail(where, f"totals.nations={t.get('nations')} против {len(nations)} наций")

    cfg = sec.get("config") or {}
    if cfg:
        verify_config(rep, where, base_dir, cfg)
    elif sec.get("engine_totals"):
        # новая схема (P0): итоги движка есть, а конфиг партии не сохранён
        rep.fail(where, "есть engine_totals, но нет config партии")

    et = sec.get("engine_totals") or {}
    for name, row in et.items():
        if row.get("blocked_unique", 0) > row.get("blocked_attempts", 0):
            rep.fail(where, f"у {name} blocked_unique > blocked_attempts "
                            f"({row.get('blocked_unique')} > {row.get('blocked_attempts')})")
        if row.get("supp_pairs", 0) > row.get("supp_events", 0):
            rep.fail(where, f"у {name} supp_pairs > supp_events")
    rep.checked += 1


def check_series(path, deep=True):
    name = os.path.basename(path.rstrip("/"))
    rep = Report(name)
    rdir = os.path.join(path, "rounds")
    if not os.path.isdir(rdir):
        rep.fail(path, "нет каталога rounds/")
        return rep.dump()

    files = sorted(f for f in os.listdir(rdir) if re.fullmatch(r"round_\d+\.json", f))
    if not files:
        # Серия ещё идёт: каталог создан, первый раунд не записан.
        print(f"\n[{name}] раундов пока нет (серия идёт) — проверять нечего")
        return True

    rounds, arms_ref, engines, games = {}, None, {}, 0
    for f in files:
        rnd = int(re.search(r"(\d+)", f).group(1))
        try:
            with open(os.path.join(rdir, f), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            rep.fail(f, f"не читается: {e}")
            continue
        rounds[rnd] = data
        if data.get("round") != rnd:
            rep.fail(f, f"поле round={data.get('round')} не совпадает с именем файла")
        sections = data.get("sections") or {}
        arms = sorted(sections)
        if arms_ref is None:
            arms_ref = arms
        elif arms != arms_ref:
            rep.fail(f, f"состав рук {arms} отличается от {arms_ref}")
        if len(arms) < 2:
            rep.fail(f, f"в раунде одна рука: {arms}")
        params = data.get("params") or {}
        engines.setdefault(params.get("engine_md5"), []).append(rnd)
        games += len(arms)
        if deep:
            for arm in arms:
                sec = sections[arm]
                legacy = isinstance(sec, dict) and "final_turn" not in sec
                check_section(rep, f"{f}:{arm}", arm, sec, params, path, legacy=legacy)

    if not rounds:
        return rep.dump()

    # сиды: base + 17*r, если раунд не помечен переигранным
    base = rounds[min(rounds)]["seed"]
    for rnd, data in sorted(rounds.items()):
        want = base + rnd * 17
        ov = data.get("seed_override") or data.get("seed_fallback")
        if ov:
            if ov.get("used") != data.get("seed"):
                rep.fail(f"round_{rnd:04d}", f"пометка переигранного раунда не совпадает с сидом "
                                             f"{ov.get('used')} != {data.get('seed')}")
        elif data.get("seed") != want:
            rep.fail(f"round_{rnd:04d}", f"сид {data.get('seed')}, ожидался {want}")

    legacy_n = sum(1 for w in rep.warn if "старая схема раздела" in w)
    if legacy_n:
        rep.warn = [w for w in rep.warn if "старая схема раздела" not in w]
        rep.warn.insert(0, f"серия снята по старой схеме раздела ({legacy_n} партий): "
                          f"нет финального хода — это формат, а не порча данных")

    if len(engines) > 1:
        parts = "; ".join(f"{k}: раунды {v[0]}–{v[-1]} ({len(v)})" for k, v in engines.items())
        rep.warn_("движок", f"внутри серии менялся, данные несравнимы: {parts}")

    # индекс: производная, обязан совпадать с файлами раундов
    idx_path = os.path.join(path, "rounds.jsonl")
    if not os.path.exists(idx_path):
        rep.warn_("rounds.jsonl", "индекса нет (пересобирается драйвером при следующем раунде)")
    else:
        rows = []
        with open(idx_path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    rows.append(json.loads(ln))
        if [r.get("round") for r in rows] != sorted(rounds):
            rep.fail("rounds.jsonl", f"индекс содержит {len(rows)} раундов, файлов {len(rounds)}; "
                                     f"наборы не совпадают")
        for r in rows:
            data = rounds.get(r.get("round"))
            if data is None:
                continue
            if r.get("games") != len(data.get("sections") or {}):
                rep.fail("rounds.jsonl", f"раунд {r.get('round')}: {r.get('games')} партий "
                                         f"в индексе против {len(data.get('sections') or {})} в файле")
            if r.get("seed") != data.get("seed"):
                rep.fail("rounds.jsonl", f"раунд {r.get('round')}: сид индекса не совпадает с файлом")

    print(f"\n[{name}] раундов {len(rounds)}, рук {len(arms_ref or [])}, партий {games}, "
          f"сиды {min(r['seed'] for r in rounds.values())}–{max(r['seed'] for r in rounds.values())}")
    return rep.dump()


# ---------------------------------------------------------------- сам драйвер


def self_test():
    rep = Report("self-test")
    real_facts = drv.engine_facts
    drv.engine_facts = lambda refresh=False: dict(FAKE_ENGINE)
    try:
        # руки
        drv.configure_arms(drv.DEFAULT_ARMS)
        if [a["name"] for a in drv.ARMS] != ["nodof", "dof", "half"]:
            rep.fail("configure_arms", f"руки по умолчанию: {[a['name'] for a in drv.ARMS]}")
        drv.configure_arms(ARMS_11)
        if len(drv.ARMS) != 11 or drv.ARMS[-1]["policy"] != "all":
            rep.fail("configure_arms", "11 рук не разобрались")
        for bad in ("a:none;a:all", "nocolon", ":none"):
            try:
                drv.configure_arms(bad)
            except SystemExit:
                pass
            else:
                rep.fail("configure_arms", f"принял некорректную запись {bad!r}")

        # роспись мест: уникальность, диапазон, рост с дозой
        for r in range(0, 100):
            for k in range(1, 11):
                seats = [int(x) for x in drv._rot_seats(r, k).split(",")]
                if len(seats) != k or len(set(seats)) != k or not all(0 <= s <= 9 for s in seats):
                    rep.fail("_rot_seats", f"r={r} k={k}: {seats}")
                    break
        if len(set(drv._rot_seats(0, 10).split(","))) != 10:
            rep.fail("_rot_seats", "при k=10 не все места")
        if drv._rot_seats(0, 5) == drv._rot_seats(1, 5):
            rep.fail("_rot_seats", "состав мест не меняется от раунда к раунду")

        # политика руки раскрывается в список мест
        for r in (0, 4, 17):
            if drv._policy_of("d5", r) != drv._rot_seats(r, 5):
                rep.fail("_policy_of", f"rot5 на раунде {r} не совпал с _rot_seats")

        # сборка раунда: все руки на месте, 55 парных сравнений, версия движка в params
        class A:
            turns, aifill, size, par_games, seed_base = 3000, 10, 2, 4, 200000
            seed_override, arms = None, ARMS_11
        args = A()
        secs = {}
        for i, a in enumerate(drv.ARMS):
            secs[a["name"]] = {"totals": {"score_mean": 10.0 + i, "bulbs_mean": 1.0,
                                          "techs_mean": 2.0},
                               "alive": 10, "units_killed": 1, "dof_declares": 0,
                               "final_turn": 3001}
        data = drv._assemble(0, 200000, secs, args, alt=0)
        if sorted(data["sections"]) != sorted(secs):
            rep.fail("_assemble", "потерялись руки раунда")
        if len(data["comparison"]) != 55:
            rep.fail("_assemble", f"парных сравнений {len(data['comparison'])}, ожидалось 55")
        for k in ("engine_md5", "engine_sources_md5", "engine_image"):
            if k not in data["params"]:
                rep.fail("_assemble", f"в params нет {k}")
        if data["params"]["engine_md5"] != FAKE_ENGINE["binary_md5"]:
            rep.fail("_assemble", "params.engine_md5 не от движка")

        # пометки переигранного раунда
        d2 = drv._assemble(4, 200069, secs, args, alt=1)
        if d2.get("seed_fallback", {}).get("used") != 200069:
            rep.fail("_assemble", "нет пометки seed_fallback")
        args.seed_override = 1234
        d3 = drv._assemble(4, 1234, secs, args, alt=0)
        if d3.get("seed_override", {}).get("used") != 1234:
            rep.fail("_assemble", "нет пометки seed_override")
        args.seed_override = None

        # агрегаты: варвары не входят
        section = {"units_killed": 3, "units_lost": 2, "alive": 2, "players": 2,
                   "dof_declares": 5, "dof_news": 7,
                   "nations": [{"id": 0, "score": 10, "ncities": 1, "population_real": 4,
                                "techs": 2, "bulbs_last_turn": 3, "science_rate": 50},
                               {"id": 3, "score": 20, "ncities": 2, "population_real": 6,
                                "techs": 4, "bulbs_last_turn": 5, "science_rate": 60},
                               {"id": 11, "score": 500, "ncities": 5, "population_real": 9,
                                "techs": 9, "bulbs_last_turn": 9, "science_rate": 70},
                               {"id": 12, "score": 999, "is_barbarian": True, "ncities": 9}]}
        t = drv.totals(section)
        if (t["nations"], t["seats"], t["splinters"]) != (3, 2, 1):
            rep.fail("totals", f"состав посчитан неверно: {t}")
        if (t["score_sum"], t["cities_sum"], t["population_sum"]) != (30, 3, 10):
            rep.fail("totals", f"в средние попали варвары или отколовшиеся: {t}")
        if (t["splinters_score_sum"], t["splinters_cities_sum"]) != (500, 5):
            rep.fail("totals", f"отколовшиеся посчитаны неверно: {t}")

        # индекс пересобирается из файлов: порядок, отсутствие дублей, дыры не страшны
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "rounds"))
            with open(os.path.join(td, "rounds.jsonl"), "w", encoding="utf-8") as f:
                f.write('{"round": 99, "seed": 0, "arms": [], "games": 0}\n')  # мусор от старого прогона
            for rnd in (3, 1):
                d = drv._assemble(rnd, 200000 + 17 * rnd, secs, args, alt=0)
                drv.write_round(d, td)
            rows = [json.loads(x) for x in open(os.path.join(td, "rounds.jsonl"), encoding="utf-8")]
            if [r["round"] for r in rows] != [1, 3]:
                rep.fail("write_index", f"индекс: {[r['round'] for r in rows]}, ожидалось [1, 3]")
            if any(r["games"] != 11 for r in rows):
                rep.fail("write_index", "в индексе неверное число партий")
            if drv.write_index(td) != 2:
                rep.fail("write_index", "пересборка индекса дала не 2 раунда")
            # перезапись раунда обновляет его строку, а не оставляет старую
            d = drv._assemble(3, 999999, secs, args, alt=0)
            drv.write_round(d, td)
            rows = [json.loads(x) for x in open(os.path.join(td, "rounds.jsonl"), encoding="utf-8")]
            if rows[-1]["seed"] != 999999:
                rep.fail("write_index", f"после перезаписи раунда в индексе старый сид "
                                        f"{rows[-1]['seed']}")
            # удалённый файл раунда выпадает из индекса
            os.remove(os.path.join(td, "rounds", "round_0001.json"))
            if drv.write_index(td) != 1:
                rep.fail("write_index", "индекс не выбросил удалённый раунд")

            # версия движка: ENGINE.json + один блок в SERIES.md, повтор не копит
            with open(os.path.join(td, "SERIES.md"), "w", encoding="utf-8") as f:
                f.write("# Серия: проверка\n\nруками написано\n")
            drv.record_engine(td, args)
            drv.record_engine(td, args)
            eng = json.load(open(os.path.join(td, "ENGINE.json"), encoding="utf-8"))
            text = open(os.path.join(td, "SERIES.md"), encoding="utf-8").read()
            if eng.get("binary_md5") != FAKE_ENGINE["binary_md5"]:
                rep.fail("record_engine", "ENGINE.json без md5 движка")
            if text.count(drv.MARK_BEGIN) != 1 or text.count(drv.MARK_END) != 1:
                rep.fail("record_engine", "блок версии размножился в SERIES.md")
            if "руками написано" not in text:
                rep.fail("record_engine", "ручной текст SERIES.md потерян")
            if "3000" not in text:
                rep.fail("record_engine", "параметры старта не попали в блок")
    finally:
        drv.engine_facts = real_facts
    return rep.dump()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true", help="проверить сам драйвер")
    ap.add_argument("--series", action="append", default=[], metavar="DIR")
    ap.add_argument("--all", action="store_true", help="все серии в experiments/dof-*")
    ap.add_argument("--shallow", action="store_true", help="не проверять разделы партий")
    args = ap.parse_args()

    ok = True
    if args.self_test:
        ok &= self_test()
    dirs = list(args.series)
    if args.all:
        dirs += sorted(p for p in glob.glob(os.path.join(HERE, "dof-*")) if os.path.isdir(p))
    for d in dirs:
        ok &= check_series(d, deep=not args.shallow)
    if not (args.self_test or dirs):
        ap.error("нечего проверять: --self-test, --series DIR или --all")
    print("\nИТОГ:", "ПРОВЕРКИ ПРОЙДЕНЫ" if ok else "ЕСТЬ НАРУШЕНИЯ")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
