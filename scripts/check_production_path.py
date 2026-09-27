#!/usr/bin/env python
"""Проводка производства целиком, офлайн, на реальной фикстуре.

Вопрос: доходят ли до поиска кандидаты по производству? Три возможных отказа
выглядят одинаково («нет улучшения»), и различить их можно только по составу
кандидатов:

* тип не предложен сервером (нет `produce_<тип>` с непустыми параметрами);
* предложен, но нет опций типа (каталог извлекателя) или нет ИЗМЕРЕННОЙ стоимости
  (склад `env/measured_facts.py`) — тогда тип честно не предлагается;
* кандидат есть, но его выигрыш не проходит правило «строго > 0».

Стенд не нужен: берётся сохранённое наблюдение и подставляется структура
предложений, снятая с живого сервера (у города валидны 3 из 120 `produce_*`).

    python scripts/check_production_path.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "civrealm", "src"))
sys.path.insert(0, HERE)


def main() -> int:
    import warnings
    warnings.filterwarnings("ignore")

    from brain.forecast.live import build_context
    from brain.forecast.search import choose
    from env.entity_extractor import GameStateExtractor
    from env.measured_facts import default_facts

    with open(os.path.join(HERE, "tests", "fixtures", "real_obs_01.json"),
              encoding="utf-8") as handle:
        obs = json.load(handle)[0]["observation"]

    cities = obs.get("city") or {}
    if not cities:
        print("в фикстуре нет города — проверять нечего")
        return 1
    city_key = str(next(iter(cities)))

    # Предложения, как их отдаёт живой сервер: у города валидны три типа.
    info = {"available_actions": {
        "city": {city_key: {"produce_Settlers": True, "produce_Workers": True,
                            "produce_Warriors": False, "produce_Knights": False}},
        "unit": {}, "tech": {}}}

    extractor = GameStateExtractor(my_player_id=0)
    dof = extractor.extract(obs, info, turn=1)
    facts = default_facts()
    print("склад измеренных фактов:", json.dumps(facts.summary(), ensure_ascii=False))

    ctx = build_context(obs, info, dof, extractor, world_model=facts)
    city_id = f"city_{city_key}"
    priced = ctx.vals.productions(city_id)
    print(f"\nпроизводство по {city_id}: {priced}")
    print(f"типы без цены: {sorted(ctx.unpriced)}")

    from brain.forecast.options import candidates
    kinds: dict[str, int] = {}
    for cand in candidates(ctx.state, ctx.vals):
        kinds[cand.kind] = kinds.get(cand.kind, 0) + 1
    print(f"состав кандидатов: {kinds}")
    for note in ctx.notes:
        print(f"примечание: {note}")

    choice = choose(ctx.state, ctx.vals)
    print(f"\nвыбор: {choice.action} ({choice.reason})")

    # Проверка правила «один актёр — одно решение за ход»: с уже решившим городом
    # производство не должно предлагаться вовсе.
    used = {("city", city_key)}
    again = build_context(obs, info, dof, extractor, world_model=facts,
                          exclude_actors=used)
    reply = again.vals.productions(city_id)
    print(f"с исключённым актёром {used}: производство {reply}, "
          f"исключён('city','{city_key}')="
          f"{again.vals.excluded('city', city_id)}")
    choice2 = choose(again.state, again.vals)
    print(f"выбор при исключении: {choice2.action} "
          f"(кандидатов {sum(choice2.candidate_kinds.values())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
