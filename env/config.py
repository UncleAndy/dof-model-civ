"""
DOF-MODEL-CIV configuration.

Parameters for mapping game state to DOF SystemStateMatrix.

The DoF model here is the calibration approved on 2026-09-26; the derivation,
the measured limits of every field it reads, and the alternatives that were
considered but not chosen are documented in ``drafts/DOF_CALIBRATION.md``
(§3 unit, §3.1 current/future split, §4 city, §5.1 technology, §8 formulas).

**Everything is expressed in "options"** — the DOF-Core toolkit defines a
degree of freedom as a COUNT of independent options (>= 1), so a per-entity
value below 1 means the entity has lost option space and a value of 0 means
collapse. ``DOF_SCALE`` is the conversion between the normalised score used by
the extractor and that count.
"""
from dataclasses import dataclass, field


# ── DOF-Core spec constants ──────────────────────────────────────────────────

#: Smallest DoF value (entity is at collapse)
EPSILON: float = 1e-6

#: Fast-pass threshold in microseconds (5s)
FAST_PASS_THRESHOLD_MKS: float = 5_000_000.0


# ── Time ─────────────────────────────────────────────────────────────────────

#: Duration of one game turn in microseconds
TURN_DURATION_MKS: float = 5_000_000.0  # 5s per turn

#: Maximum turns in a game
MAX_TURNS: int = 150


# ── Scale ────────────────────────────────────────────────────────────────────

#: Normalised score → option count. A "0.45 entity" is 4.5 options.
DOF_SCALE: float = 10.0

#: Hard ceiling on a city's options (§8): population × modifiers saturate here.
#: Поднят с 20 до 100 вместе с весом зданий (§10.25.4): при `CITY_M1_IMPROV = 1.0`
#: и потолке `m1` 3.0 развитый город (размер 6, три здания) даёт 48 опций, а
#: размер 10 — 72; при старом потолке 20 оба упирались в 20, и потолок снова
#: выравнивал города, только на другом уровне (это вскрыл тест
#: `test_city_dof_grows_with_population`: средний и большой город совпали).
#: 100 не режет ни один город, до которого игра реально доходит; потолок остаётся
#: как граница §8, но границей для обычной игры больше не работает.
CITY_CEIL: float = 100.0

#: The Rust core (`brain/core`) carries `current_dof` in the DOF-SPEC field
#: range [0, 1] (`apply_action` clamps at 1.0), so the bridge divides option
#: counts by this reference before calling it. Σ ln(x) is only ever compared
#: between states holding the SAME entity count (the bridge patches entities,
#: it does not add or remove them), so scaling every value by one constant
#: preserves both the ordering and the sign of every net delta exactly.
#:
#: РАСЦЕПЛЕНО с `CITY_CEIL` (2026-09-28): раньше здесь стояло `= CITY_CEIL`, и
#: подъём потолка города тянул за собой нормировку моста — а она делит и штраф
#: Аксиомы 4 (`AXIOM4_PENALTY_OPTIONS / CORE_DOF_SCALE`), то есть молча меняла бы
#: цену необратимых действий. Значение зафиксировано на том, каким оно было
#: (20.0), чтобы правка потолка не трогала мост.
CORE_DOF_SCALE: float = 20.0

#: Irreversibility penalty (Axiom 4 context-switch entropy), in options.
#: The bridge converts it into the core's own units with CORE_DOF_SCALE, so
#: this number stays comparable to the deltas the bridge projects — an
#: irreversible action must gain more than half an option to be worth it.
AXIOM4_PENALTY_OPTIONS: float = 0.5

#: Надбавка за действие с неизмеренным эффектом («цена снятия неопределённости»,
#: см. env/experiments.py). Выключается для A/B-прогона: единственный способ
#: показать, что механизм не декоративен, — сравнить агента с ним и без него на
#: одних и тех же слотах. Читается при каждом обращении, поэтому переключается
#: между матчами без перезапуска процесса.
CURIOSITY_ENABLED: bool = True


# ── Unit DoF (§3.1, §8) ──────────────────────────────────────────────────────
# Two components, because a unit's economics are two different things:
#   * s_current  — what it can do NOW (attack, defence, movement, vision);
#   * s_future   — what it can BECOME or CREATE (found a city, change terrain,
#                  convert, carry others).
# Weapons/armour units have a high current and a small future; population
# carriers are the exact opposite. W_FUTURE_UNIT is deliberately smaller than
# the city's future weight: a unit's potential is a *possibility*, a city's is
# already-realised capacity that also grows.

UNIT_EXISTENCE_W: float = 0.05          # for being a live, ordered entity
UNIT_HEALTH_W: float = 0.20             # vitality of a combat unit
UNIT_ATTACK_W: float = 0.15
UNIT_ATTACK_REF: float = 10.0
UNIT_DEFENSE_W: float = 0.15
UNIT_DEFENSE_REF: float = 8.0
UNIT_FIREPOWER_W: float = 0.05
UNIT_FIREPOWER_REF: float = 2.0
UNIT_MOVE_W: float = 0.10
UNIT_MOVE_REF: float = 3.0
UNIT_VISION_W: float = 0.05
UNIT_VISION_REF: float = 8.0
UNIT_VETERAN_W: float = 0.05
UNIT_VETERAN_REF: float = 4.0
UNIT_CURRENT_CAP: float = 0.80          # s_current cannot exceed this

UNIT_FUTURE_SETTLE_W: float = 0.30      # can found a city
UNIT_FUTURE_WORKER_W: float = 0.10      # can change terrain
UNIT_FUTURE_CONVERT_W: float = 0.10     # has a conversion path
UNIT_FUTURE_TRANSPORT_W: float = 0.20   # multiplies other units' options
W_FUTURE_UNIT: float = 0.35             # discount on the future component

#: A population carrier's hit points ARE its population, and its population is
#: already counted — with its decay and its risk — in the future term. Counting
#: `health/type_hp` again in s_current would double-count it, and on real
#: civ2civ3 data it inverts the ordering the calibration is built on: Settlers
#: have 20 HP and move 3, Warriors have 10 HP and move 1, so a literal reading
#: of the formula makes a Settler look like the *better soldier* (measured on
#: the live start state, 2026-09-26). With this flag False a Warrior's current
#: DoF exceeds a Settler's, as required, while a Settler's total DoF still
#: exceeds a Warrior's through its (city-founding) future component.
POP_CARRIER_COUNTS_HEALTH_IN_CURRENT: bool = False

#: Population-carrying unit types. Names come from the real ruleset and are
#: PLURAL ("Settlers", "Engineers"), matched case-insensitively.
POPULATION_UNIT_TYPES: frozenset = frozenset(
    {"settler", "settlers", "engineer", "engineers"}
)

#: A carried population is FIXED — it can never grow — and it erodes while the
#: unit wanders, discounted by the unit's health (a settler in the field is
#: capturable). Floored: people remain even after a very long walk.
#:
#: Rate and floor are a *proxy for the price of time*, not a game mechanic: the
#: ruleset does not erode a settler's population while it walks. The approved
#: setting (2026-09-26) is deliberately fast so that the window in which a
#: settler is worth carrying is short — erosion is complete after 15 turns
#: (1 − 0.05 × 15 = 0.25), matching the intended tempo "the first city within
#: the first five to ten turns". Measured effect: a fresh settler is 3.81
#: options, at 5 turns 3.38, at 10 turns 2.94, at 15+ turns 2.50 and it stops.
CARRIER_DECAY_PER_TURN: float = 0.05
CARRIER_DECAY_FLOOR: float = 0.25

#: The actual, permanent price of delay: every turn a population carrier exists
#: without founding a city is a turn the empire does not get the population
#: engine. Unlike the decay above this is *not* recoverable and it accumulates
#: without saturation, so waiting is monotonically punished in the system index.
#: It is a system sink (§7), not a deduction from the carrier: its bite depends
#: on the treasury, exactly like unit upkeep.
UNDEPLOYED_CARRIER_SINK_PER_TURN: float = 0.02

#: Minimum food potential of a founding site, in food per turn summed over the
#: workable tiles. A citizen eats `food_cost` (2, confirmed by the stand's own
#: rules) so a site that cannot feed at least two citizens with a surplus can
#: only ever be a one-day town: those are forbidden rather than penalised — an
#: unviable option is excised from the candidate set, not scored low (doc §3).
SITE_MIN_FOOD: float = 6.0

#: ── ПОРОГ ДЛЯ ПЕРВОГО ГОРОДА ПАДАЕТ (решение Andy 2026-09-28, разбор §10.27) ──
#: Пока у нас НЕТ ни одного города, держать порог 6.0 нельзя: при бедном старте ни одна
#: достижимая площадка не годна, кандидата «основать» не существует, и сторона стоит
#: вечно (измерено: 6 игроков, 60 ходов, 0 действий, цена раскрытия 0.000). Поэтому для
#: ПЕРВОГО города порог падает на `SITE_MIN_FOOD_FIRST_DECAY` за ход до пола
#: `SITE_MIN_FOOD_FIRST_FLOOR`. Для ВСЕХ последующих городов порог остаётся
#: `SITE_MIN_FOOD` — правило «городов-однодневок нет» не смягчается.
#: Числа выбраны Andy'ем по таблице §10.27: оценка еды 5.0 годна с хода 4, 4.0 — с 6,
#: 3.0 — с 9, 2.0 — с 11, 1.0 — с 14.
SITE_MIN_FOOD_FIRST: float = 6.0
SITE_MIN_FOOD_FIRST_DECAY: float = 0.4
SITE_MIN_FOOD_FIRST_FLOOR: float = 1.0


def first_city_food_gate(turn: int) -> float:
    """Порог годности площадки для ПЕРВОГО города на данном ходу.

    Одно место для правила: и прогноз, и диагностика обязаны брать порог отсюда,
    иначе «почему площадка не годна» будет отвечать не та формула, которой агент
    руководствуется. Формула линейная и объявленная, а не подобранная:
    `max(пол, 6.0 − шаг · (ход − 1))`.
    """
    try:
        t = max(1, int(turn))
    except (TypeError, ValueError):
        t = 1
    return max(SITE_MIN_FOOD_FIRST_FLOOR,
               SITE_MIN_FOOD_FIRST - SITE_MIN_FOOD_FIRST_DECAY * (t - 1))

#: Размер, на котором проверяется гейт качества. `SITE_MIN_FOOD` определён как
#: «прокормить двух жителей + запас», то есть проверять надо площадку НЕ на
#: первом размере (1 житель), а на втором: два жителя съедают 2 × 2 = 4 еды, плюс
#: запас 2 на рост. Поэтому гейт берёт лучшие `SITE_GATE_SIZE + 1 = 3` клетки.
SITE_GATE_SIZE: int = 2

#: ОПЦИИ площадки: берег и ресурсы — не выход клетки, а дополнительные пути
#: развития, поэтому они входят в ценность города как опции, а не как еда/щиты.
#: Значения согласованы с предложением от 2026-09-26 (бонусы по 0.10).
#:
#: * `SITE_COAST_BONUS` — гавань, морские юниты, морская торговля: берег открывает
#:   целый класс сущностей, которого у inland-города нет вовсе;
#: * `SITE_RESOURCE_BONUS` — за каждый **различный** измеренный ресурс в области
#:   города (ресурсность определяется измерением: экстра с ненулевым эффектом);
#: * `SITE_OPTION_BONUS_CAP` — потолок суммы этих опций, чтобы богатая земля не
#:   перевешивала существование города (Axiom 1: опции — не инвентарь).
SITE_COAST_BONUS: float = 0.10
SITE_RESOURCE_BONUS: float = 0.10
SITE_OPTION_BONUS_CAP: float = 0.30

#: ── НАБИВКА ПОЛНОСТЬЮ НЕРАСКРЫТОГО ОКНА (§10.27.1, решение Andy 2026-09-28) ──
#: Формула площадки ОБЪЯВЛЯЕТ правило «неизвестные клетки не считаются нулём:
#: набивка средним по видимым + оптимистичная граница» (Axiom 5/7), но когда в окне
#: не видно НИ ОДНОЙ клетки, брала `(0,0,0)`. Измерено (`--sample-sites`, 12 996
#: строк): такое окно — **80.9 %** клеток вокруг старта, и все они получают оценку
#: 0.00 и границу 0.00, то есть годными не бывают НИКОГДА (0 из 10 512), тогда как на
#: видимой земле годны 73.4 % площадок при средней оценке 5.36. Здесь — запасной
#: источник, когда не раскрыто вообще ничего: измеренная легенда террейнов
#: (Grassland 2/0/0, Plains 1/1/0, Forest 1/2/0, Hills 1/0/0, Mountains 0/1/0,
#: Swamp 1/0/0, Ocean/Lake 1/0/2). Среднее по семи террейнам: еда 1.00, щиты 0.57,
#: торговля 0.29; лучшие клетки: еда 2 (Grassland), щиты 2 (Forest), торговля 2.
#: Ноль здесь запрещён: «незнание — это не отсутствие возможностей» (правило Andy).
UNKNOWN_FILL_FOOD: float = 1.00
UNKNOWN_FILL_SHIELDS: float = 0.57
UNKNOWN_FILL_TRADE: float = 0.29
UNKNOWN_BEST_FOOD: float = 2.00
UNKNOWN_BEST_SHIELDS: float = 2.00
UNKNOWN_BEST_TRADE: float = 2.00

#: ── ПОЛ ЦЕНЫ РАСКРЫТИЯ (§10.27.1) ────────────────────────────────────────────
#: Когда раскрытых клеток мало и они ОДИНАКОВЫ, разброс по ним равен нулю, и цена
#: раскрытия выходит 0.000 — модель заявляет, что знать больше нечего, хотя 80.9 %
#: окна под туманом (измерено). Разброс берётся из ИЗМЕРЕННОГО несмещённым забором:
#: ст.откл оценки площадки **1.77 еды** (в границах 2.87). Перевод в опции —
#: формулой города, а не подбор: `base 3 × m2 1.2 × CITY_M1_FOOD 0.2 × 1.77 ≈ 1.27`
#: опции. Это перевод ЗАМЕРА; после правки — своя предрегистрированная серия.
INFO_GAP_FLOOR_OPTIONS: float = 1.27

#: Террейны, дающие выход к морю.
WATER_TERRAINS: tuple[str, ...] = ("Lake", "Ocean", "Deep Ocean")

#: Цена задержки как **контрфактический рост** (фактор (б), утверждён
#: 2026-09-26). Плоское 0.02/ход выше — прокси; здесь цена выводится из
#: площадки: основать раньше значит получить N ходов роста города (Axiom 6),
#: поэтому сток за ход = прирост DoF контрфактического города за этот ход:
#:
#:     сток/ход = W_GROWTH × CITY_POP × DOF_SCALE × (surplus / амбар(size))
#:
#: где `surplus = Σ еды лучших (size+1) клеток − food_cost × size`, а
#: `амбар = 10 × (size + 1)` (правило стенда). `W_GROWTH` равен
#: `W_FUTURE_UNIT`: рост — *будущая* возможность, а не наличная, и потому
#: дисконтируется так же, как потенциал юнита. Замер: на хорошей площадке
#: (Forest+Pheasant+Grassland, surplus +3) задержка стоит 0.525 опт./ход,
#: то есть 7.9 опции за 15 ходов — дороже разового выигрыша от основания
#: (+5.1), поэтому «основать сейчас» доминирует; на бедной (surplus +1) —
#: 0.175/ход, 2.6 за 15 ходов, так что медлить там не запрещено.
W_GROWTH: float = 0.35

#: Горизонт прогноза роста (ходов) — совпадает с окном переноски
#: (`CARRIER_DECAY_PER_TURN × 15 = CARRIER_DECAY_FLOOR`).
GROWTH_HORIZON_TURNS: int = 15

#: Еда, которую съедает один житель за ход. Модель читает это из правил
#: стенда (`rules.food_cost`, подтверждено = 2); значение здесь — только
#: запасное, если правила не пришли.
FOOD_COST: float = 2.0

#: ИЗМЕРЕННЫЕ эффекты экстр на клетку: выход клетки с экстрой минус выход того же
#: террейна без неё, Δ(еда, щиты, торговля). Заполняется ТОЛЬКО замерами на живом
#: стенде (`scripts/inspect_terrain_live.py` — сбор по раскрытой карте,
#: `scripts/measure_terrain_effect.py` — после завершения работы), поэтому у
#: каждой записи здесь есть источник. Ключ `"<экстра>@<террейн>"` уточняет
#: эффект до террейна, ключ `"<экстра>"` — общий замер.
#:
#: Замерено 2026-09-26 (слоты 6316-6322, сбор по раскрытой карте):
#:   Hills+Coal    -> (1, 2, 0) против Hills     (1, 0, 0) => Coal     (+0, +2, 0)
#:   Mountains+Iron-> (0, 4, 0) против Mountains (0, 1, 0) => Iron     (+0, +3, 0)
#:   Desert+Oasis  -> (3, 1, 0) против Desert    (0, 1, 0) => Oasis    (+3, +0, 0)
#:   Desert+Oil    -> (0, 4, 0) против Desert    (0, 1, 0) => Oil      (+0, +3, 0)
#:   Plains+Wheat  -> (3, 1, 0) против Plains    (1, 1, 0) => Wheat    (+2, +0, 0)
#:   Ocean+Fish    -> (3, 0, 2) против Ocean     (1, 0, 2) => Fish     (+2, +0, 0)
#:   Forest+Silk   -> (1, 2, 3) против Forest    (1, 2, 0) => Silk     (+0, +0, +3)
#:   Ocean+Whales  -> (2, 1, 2) против Ocean     (1, 0, 2) => Whales   (+1, +1, +0)
#:   Hills+Wine    -> (1, 0, 4) против Hills     (1, 0, 0) => Wine     (+0, +0, +4)
#:   Plains+Buffalo-> (1, 3, 0) против Plains    (1, 1, 0) => Buffalo  (+0, +2, +0)
#:   Forest+Pheasant->(3, 2, 0) против Forest    (1, 2, 0) => Pheasant (+2, +0, 0)
#:   Grassland+Resources -> (2,1,0) против Grassland (2,0,0) => Resources (+0,+1,0)
#:   River: выход НЕ меняет на всех шести проверенных террейнах (Grassland,
#:     Plains, Forest, Jungle, Desert, Swamp) => (0, 0, 0)
#:   Minor Tribe Village: не меняет (хижина, не ресурс) => (0, 0, 0)
#:
#: Оговорка: если на клетке несколько экстр, замер относит эффект к каждой из них
#: (клетка Forest+River+Pheasant показывается и под River, и под Pheasant).
#: Поэтому в таблицу попадают только записи, подтверждённые клетками с ОДНОЙ
#: экстрой; река проверена именно так и во всех шести случаях дала ноль.
#:
#: ЗАМЕРЫ РАБОТ (ставятся рабочим и отслеживаются по слою экстр):
#:   irrigation на Grassland+Resources и на Plains: экстра Irrigation появилась
#:     за 3 хода, а выход НЕ изменился ((2,1,0) и (1,1,0) соответственно)
#:     => Δ(0, 0, 0). Замер воспроизведён на двух разных террейнах. Это ПРОТИВОРЕЧИТ тексту
#:     upstream-правилсета (`irrigation_food_incr = 1`), но соответствует миру:
#:     бонус ирригации управляется эффектом `Irrigation_Pct`, которого здесь нет.
#:     Смысл ирригации в этой версии — не еда, а ЦЕПОЧКА (ирригация открывает
#:     ферму), поэтому цена «за выход» честно равна нулю.
#:   `cultivate`/`plant`: не экстра, а смена террейна — измерено Forest ⇄ Swamp
#:     за 4 хода (см. `MEASURED_WORK_TURNS`), в таблицу эффектов не входит.
#:   build_road: экстра Road появилась, а выход НЕ изменился — на Grassland
#:     (2,1,0), на Plains (1,1,0) и на Hills (1,0,0) => Δ(0, 0, 0) на трёх
#:     террейнах. Это тоже ПРОТИВОРЕЧИТ upstream-правилсету (`road_road.trade_incr
#:     = 1` × terrain.road_trade_incr_pct), где дорога дала бы +1 торговли;
#:     в этой версии стенда дорога — только перемещение.
#:   Ирригация дополнительно проверена на Hills: выход тоже не изменился.
#: ИТОГ по работам в этой версии стенда: они СТАВЯТ экстры (Irrigation/Road), но
#: выхода клетки не меняют. Ценность работы здесь — не выход, а ЦЕПОЧКА (ирригация
#: открывает ферму) и перемещение (дорога), поэтому «цена за выход» равна нулю.
#: Mine/Railroad пока НЕ измерены (валидность по клетке + подвисание контроллера
#: при постановке работы), их цена 0 с явной причиной. Ключ `"<экстра>@<террейн>"`
#: уточняет эффект до террейна (пустыня по правилсету — исключение, не проверена).
MEASURED_EXTRA_EFFECTS: dict[str, tuple[float, float, float]] = {
    "Irrigation@Grassland": (0.0, 0.0, 0.0),
    "Irrigation@Plains": (0.0, 0.0, 0.0),
    "Irrigation@Hills": (0.0, 0.0, 0.0),
    "Road@Grassland": (0.0, 0.0, 0.0),
    "Road@Plains": (0.0, 0.0, 0.0),
    "Road@Hills": (0.0, 0.0, 0.0),
    "Coal": (0.0, 2.0, 0.0),
    "Iron": (0.0, 3.0, 0.0),
    "Oasis": (3.0, 0.0, 0.0),
    "Oil": (0.0, 3.0, 0.0),
    "Wheat": (2.0, 0.0, 0.0),
    "Fish": (2.0, 0.0, 0.0),
    "Silk": (0.0, 0.0, 3.0),
    "Whales": (1.0, 1.0, 0.0),
    "Wine": (0.0, 0.0, 4.0),
    "Buffalo": (0.0, 2.0, 0.0),
    "Pheasant": (2.0, 0.0, 0.0),
    "Resources": (0.0, 1.0, 0.0),
    "River": (0.0, 0.0, 0.0),
    "Minor Tribe Village": (0.0, 0.0, 0.0),
}

#: Unit health in CivRealm observations is HIT POINTS, whose ceiling differs per
#: type; the observation carries it as `type_hp` (real field, verified). These
#: are fallbacks for synthetic fixtures and for captures that lack `type_hp`.
UNIT_TYPICAL_MAX_HP: float = 10.0
UNIT_MAX_HP_BY_TYPE: dict = {
    "settler": 20.0, "settlers": 20.0,
    "worker": 10.0, "workers": 10.0,
    "explorer": 10.0,
}
HEALTH_PERCENT_THRESHOLD: float = 100.0
#: Below this fraction of full health a unit counts as collapsing.
HEALTH_COLLAPSE_RATIO: float = 0.1


# ── City DoF (§4, §8) ────────────────────────────────────────────────────────
# Three multiplicative factors with a cap on each (the approved "three-multiplier"
# scheme), so a city in disorder or starving has its options GATED (near zero),
# not merely reduced. The alternative — a linear sum — was considered and is
# recorded in §8 of the calibration document.

CITY_BASE: float = 2.0                  # a settlement of one citizen is not nothing
CITY_POP: float = 1.0                   # options per citizen
CITY_CAP_M1: float = 3.0                 # food/base-infrastructure factor ceiling
CITY_CAP_M2: float = 2.0                # economy (shields/trade/gold/science) ceiling

CITY_M1_FOOD: float = 0.20              # positive food surplus = growth capacity
CITY_M1_GRANARY: float = 0.30           # filled food box = resilience
CITY_M1_IMPROV: float = 1.00            # each standing improvement
CITY_M2_SHIELD: float = 0.05
CITY_M2_TRADE: float = 0.05
CITY_M2_GOLD: float = 0.10
CITY_M2_SCIENCE: float = 0.05
CITY_M2_LUXURY: float = 0.05

# ── Строительство (§10.25.4, решение Andy 2026-09-28) ────────────────────────
#: Объявленный (НЕ измеренный) бонус за постройку. Нужен потому, что здание на
#: этом стенде копится 1 щит/ход (`IMPROVEMENT_SHIELD_RATE`), то есть Temple —
#: 30 ходов при игре в 50; без бонуса ни одно разумное правило времени не даёт
#: постройке перевесить производство юнита (для γ^T понадобилось бы K ≈ 1200,
#: для доли горизонта — K ≈ 3.6). Величина выбрана Andy'ем по числам §10.25.4:
#: при весе здания 1.0 и доле горизонта K = 4.0 даёт Temple 0.862 против воина
#: 0.777. Это НАСТРОЙКА с оговоркой, а не замер; серия после неё — проверка,
#: окупается ли она в счёте.
IMPROVEMENT_BUILD_BONUS: float = 4.0
#: Измеренная скорость накопления улучшений: ровно 1 щит за ход (`Δstock = 1`,
#: 15 наблюдений, два улучшения), при публикуемом `prod_shield = 5`. Срок
#: сервера совпал с `стоимость − stock`. Формула юнитов обещала бы улучшение
#: в 5 раз быстрее, чем оно будет.
IMPROVEMENT_SHIELD_RATE: float = 1.0
#: Горизонт игры, на котором считается доля полезной жизни постройки:
#: множитель времени = max(0, (H − срок) / H). H = 50 — длина серии, на которой
#: числа показывались Andy'ю. City Walls (60 ходов, срок > H) получает ровно 0
#: и никогда не строится — это и есть честная сторона правила.
IMPROVEMENT_HORIZON_TURNS: int = 50

#: Действия перевода жителя между клетками (`city_work_<id>_<dx>_<dy>` /
#: `city_unwork_...`): цена — формулой города (Δ опций), задержки нет. Проверено
#: замером 2026-09-27 (§10.25.4): предсказание ±0.60/+1.20 против наблюдения
#: ∓0.63/+0.78 — знаки совпали во всех шести парах.
CITY_TILE_FAMILY: bool = True

CITY_CORRUPTION_W: float = 0.05         # cesspool per unit of corruption/waste/pollution
CITY_POLLUTION_THRESHOLD: float = 20.0  # above this, tiles start dying (§6)
CITY_HAPPY_W: float = 0.10
CITY_UNHAPPY_W: float = 0.15
CITY_ANGRY_W: float = 0.30

#: A garrison is how a military unit protects the city's option space — the
#: contribution the calibration assigns to warriors (2026-09-26 decision).
GARRISON_W: float = 0.05                # per defending unit, on the city

#: Unit upkeep is a SINK OF THE SYSTEM, not a deduction from the unit: it bites
#: when the treasury is small and is irrelevant when it is large. It is summed
#: over all units into a separate sink quantity (§7, §8) instead of being
#: attached to the unit that costs it. Swap to the alternative accounting —
#: subtract `UNIT_UPKEEP_SINK_W * upkeep` from the unit itself — by changing
#: only the flag below.
UNIT_UPKEEP_SINK_W: float = 0.05
#: Цена ОДНОГО пункта содержания в ОПЦИЯХ — из формулы города, замер §10.35 на
#: реальной записи города (`city_options`): +1 золота → +0.570 опций, +1 щита →
#: +0.285, +1 еды → +0.969, +1 жителя → +3.230. Живая цена считается на записи
#: НАШЕГО города в этом же наблюдении (мир первичен); значения ниже — запасные,
#: они же объявленный нижний ориентир, если города в наблюдении нет.
UPKEEP_PRICE_GOLD: float = 0.570
UPKEEP_PRICE_SHIELD: float = 0.285
UPKEEP_PRICE_FOOD: float = 0.969
#: Считать цену содержания ЖИВОЙ (по формуле города) вместо плоского веса выше.
UPKEEP_PRICE_LIVE: bool = True
UNIT_UPKEEP_AS_UNIT_PENALTY: bool = False

#: Радиус поиска ЦЕЛИ для шага юнита (§10.38, V2): ближайшая годная площадка вокруг
#: носителя в этих клетках получает цену простоя, и шаг к ней — долю `R / N`.
CARRIER_GOAL_RADIUS: int = 6


# ── Technology DoF (§5.1) ────────────────────────────────────────────────────
# A technology is a GATE: while it is unknown it offers exactly 1 option (the
# possibility itself), and once known it is worth 1 + everything it unlocks.
# That is what makes `research_tech` measurable instead of a 0.0000 action.

TECH_BASE_OPTIONS: float = 1.0
#: What one newly-applicable improvement adds to the option count: the same
#: weight it will carry inside a city's first multiplier (CITY_M1_IMPROV).
TECH_IMPROVEMENT_OPTIONS: float = 1.0 + CITY_M1_IMPROV
#: Fallback horizon for "how many turns until this technology arrives" when the
#: technology is not the one currently being researched. The observation carries
#: `researching_cost` / `bulbs_researched` for the CURRENT research only, so for
#: every other technology the time is an estimate, and it is marked as such.
TECH_NOMINAL_TURNS: float = 10.0
#: Normalisation reference for a technology's [0, 1] score field.
TECH_DOF_REF: float = 10.0


# ── Population economics notes ───────────────────────────────────────────────
# Population is the primary DoF engine of a 4X game: every extra citizen adds
# options (to work tiles, to build, to defend, to grow further). Consequences the
# model must respect, on pain of getting the incentives exactly backwards:
#   * a City is worth MORE than a Settler — the city is where population grows,
#     the settler carries a fixed number of people that can never increase;
#   * a Settler is not a small city: it is a fixed population with a movement
#     bonus, an elevated risk of loss, and its people only erode with time.
# A first attempt scored a fresh size-1 city at 0.105 against a Settler's 0.145,
# i.e. founding a city looked like a DoF LOSS (-0.3228 measured), and the agent
# refused to expand.


# ── Collapse thresholds ─────────────────────────────────────────────────────

#: City population below which city is considered near collapse
CITY_COLLAPSE_POP_THRESHOLD: int = 1

#: Unit health ratio below which unit is considered near collapse
UNIT_COLLAPSE_HEALTH_THRESHOLD: float = 0.1

#: Happiness below which city starts losing population
CITY_UNHAPPY_THRESHOLD: int = 0


# ── Diplomacy ────────────────────────────────────────────────────────────────

@dataclass
class DiplomacyWeights:
    """Weights for computing diplomacy current_dof from game metrics."""
    relationship: float = 0.40
    alliance_options: float = 0.30
    trade_options: float = 0.30


# ── Правило F: еда необратима (`env/food_gate.py`, §10.30) ───────────────────
#: Включено ли правило. Выключатель нужен не для «результатов», а для контроля:
#: без него нельзя отличить «правило помогло» от «серия была мягче».
FOOD_GATE_ENABLED: bool = True

# ── Entity mapping configuration ─────────────────────────────────────────────

@dataclass
class MappingConfig:
    """Complete configuration for game-state → DOF-entity mapping.

    The per-entity weights now live in the module constants above (they are the
    approved calibration and are shared by units, cities and technologies); this
    object keeps the connection settings and the diplomatic weights.
    """

    diplomacy_weights: DiplomacyWeights = field(default_factory=DiplomacyWeights)

    # Player ID for the acting agent
    my_player_id: int = 0

    # CivRealm connection settings
    host: str = "localhost"
    port: int = 8989  # mapped to container's 8080

    # Docker compose file path
    docker_compose_path: str = "civrealm/src/civrealm/configs/docker-compose.yaml"


# Singleton config instance
CONFIG = MappingConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# DOF-Core v0.11 §4.6 — объявление слоя измерения (линзы ψ_var · ψ_opt · ψ_con)
# ═══════════════════════════════════════════════════════════════════════════════
# Всё в этом блоке — ХЕШИРУЕМОЕ содержимое объявления (§3.4.1), а не «настройки
# стиля»: две реализации, разошедшиеся здесь, — разные линейки, и их числа
# несравнимы (§3.4.4). Меняете значение — меняется `ruler_digest`.
#
# Значения утверждены 2026-10-06 (см. drafts/DOF_CALIBRATION.md).
# `energy` — нормативный обязательный ресурс §3.3 (`MUST` присутствовать в каждой
# опции, даже нулём). В этой игре он измеряется щитами, поэтому объявленная
# единица — `shields`: имя нормативно, единица говорит правду.

SPEC_PSI_ID: str = "dof-model-civ-spec-v011"

#: Замороженный набор линз и их канонический порядок (§4.6).
SPEC_LENS_ORDER: tuple[str, ...] = ("variety", "options", "constraint")

#: Горизонт счёта V и V_env, в ходах (§4.6). Два счёта за разные горизонты —
#: несравнимые числа, поэтому горизонт объявляется, а не подразумевается.
SPEC_COUNTING_HORIZON_TURNS: int = 1

#: Правило счёта векторов реакции: `per_action_name` — каждое имя действия в меню
#: есть отдельный вектор (`goto_0`…`goto_7` — восемь разных реакций).
SPEC_RESPONSE_VECTOR_RULE: str = "per_action_name"

#: Правило свёртки требований переходов в `c_g` (§4.6): `min` — требование самого
#: дешёвого доступного перехода («хватает на что-то одно ⇒ канал открыт»).
#: Альтернативы: `mean`, `selected`.
SPEC_REQUIREMENT_REDUCTION: str = "min"

#: Обязательный ресурс §3.3 и его объявленная единица/масштаб (§3.4.1).
SPEC_ENERGY_RESOURCE: str = "energy"
SPEC_ENERGY_UNIT: str = "shields"
SPEC_ENERGY_SCALE: float = 1.0

#: Объявленные единицы ресурсов (имя → единица). Входит в дайджест: один и тот же
#: ресурс с разным масштабом — разные линейки.
SPEC_RESOURCE_UNITS: dict[str, str] = {
    "energy": SPEC_ENERGY_UNIT,   # производство, измеряемое щитами
    "food": "food",
    "gold": "gold",
    "tech": "beakers",
}

#: Производные группы обмениваемых ресурсов (§4.6/§4.8). Ресурс, названный в
#: требованиях или средствах и не попавший ни в одну группу, образует свою
#: группу-одиночку — эталон делает это сам (`canonical_groups`).
SPEC_RESOURCE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("energy", "food"),
    ("gold",),
    ("tech",),
)

#: Наблюдённые курсы членов группы к нумэрайру (§4.6: `w_j`), ключ — пара
#: (ресурс, нумэрайр). ПУСТО — значит «курс ещё не измерен миром»; эталон
#: подставляет 1.0. Заполняется замером, не догадкой.
SPEC_OBSERVED_RATES: dict[tuple[str, str], float] = {}

#: Нумэрайр каждой группы — какую единицу выражают `c_g` и `C_g`. Ключ — члены
#: группы, отсортированные по алфавиту и соединённые запятой (как в объявлении).
SPEC_GROUP_NUMERAIRE: dict[str, str] = {
    "energy,food": SPEC_ENERGY_UNIT,
    "gold": "gold",
    "tech": "beakers",
}

#: Объявленный мандат: потолок того, что разрешено тратить (§4.6/§4.8, `cap`
#: в `C_g = min(средства, лимиты, мандат)`). None — мандат не ограничивает.
SPEC_MANDATE_CAP: float | None = None

#: Источники возмущений, считаемые в `V_env` (§4.6). Возмущение СНИМАЕТ вектор
#: реакции; запрет или лимит, морозящий размерность, сюда НЕ входит — он в `F_env`.
SPEC_V_ENV_SOURCES: tuple[str, ...] = (
    "hostile_in_strike_range",
    "siege",
    "barbarian_source_in_radius",
    "hostile_diplo",
)

#: Считать ли **чужие державы** возмущением внешнего мира (§4.6). Владелец модели
#: решил считать (2026-10-06): среда — это то, что она **может**, а не только то, что
#: уже случилось; существование державы — наблюдаемое свойство мира, а нейтралитет —
#: состояние, а не способность. Одна держава — одно возмущение, без весов: числа
#: добывает мир (`obs["player"]`), а не коэффициент. Это **расширение** объявления за
#: букву §4.6 («disturbances only»), поэтому оно объявлено отдельно и входит в дайджест.
SPEC_V_ENV_COUNTS_FOREIGN_POWERS: bool = True

#: Длительности процедуры измерения `t_m`, `t_v` (§4.7) — хешируемое содержимое
#: линейки. None — процедура не объявлена, окно неизмеримо: это сообщается, а не
#: подставляется нулём (§3.4.3).
SPEC_T_MEAS_MKS: tuple[float, float] | None = None

#: Входы, которых мир не публикует (объявлено честно, а не умолчано). Цена технологии:
#: в наблюдении есть цель исследования (`tech`) и накопленные колбы (`bulbs_researched`),
#: но не цена, поэтому гейт платежа (§4.8) для исследования нечем проверить. По §4.8
#: неизвестное без оценки — недопустимый вход для гейта, а не режим вычисления, иначе
#: «решение неполно (§6.2)». Числа от объявления не двигаются: `incomplete` — поле
#: отчёта, а не вход в счёт. Разрешает вход только кандидат, назвавший его в `discovers`.
SPEC_UNKNOWN_INPUTS: tuple[dict, ...] = (
    {
        "id": "tech_price",
        "unit": "колбы (bulbs)",
        "why": "цена технологии мир не публикует: наблюдение даёт цель исследования и "
               "накопленные колбы, но не цену",
        "measurable_on": "стенд: скорость колб против остатка цели за несколько ходов",
        "used_estimated": False,
        "has_fallback": False,
    },
)

#: Приор `u₀` (§4.7). None — точечное значение 0.5 по умолчанию.
SPEC_U0_PRIOR: float | None = None

#: Объявленный набор различаемых переменных по типу сущности (§3.4.1, §4.6).
#: Набор — часть объявления, а не вывод из кода: два счёта `F` по разным наборам
#: несравнимы. Заморозка (`F_env`) — наблюдаемая величина, считается по правилам
#: в `env/spec_lenses.py`; здесь объявлено только то, ЧТО вообще считается.
SPEC_VARIABLE_SET_BY_TYPE: dict[str, tuple[str, ...]] = {
    # Юнит: куда идти, что делать, за кем идти.
    "unit": ("position", "activity", "target"),
    # Город: что строить, какие клетки обрабатывать, кем работать, расти ли.
    "city": ("production", "tile_assignment", "specialist", "growth"),
    # Технология: единственная переменная — исследовать её или нет.
    "tech": ("research",),
    # Дипломатия: каким будет договор.
    "diplomacy": ("treaty",),
    # Игрок: что исследовать и какая форма правления. Технология — не сущность:
    # её номер называет лишь предмет действия, а действует игрок (`tech/cur_player`).
    "player": ("research", "government"),
}

#: Окно платёжеспособности (§4.6): какие средства считаются доступными группе —
#: `C_g = min(запас + доход · H, мандат)`. Игра платит за постройку из дохода, а не
#: из запаса, поэтому сравнение полной цены с одним запасом объявляло бы город без
#: щитов неспособным ни на что. H = 0 — только запас; H = 1 — запас плюс ход дохода.
SPEC_MEANS_HORIZON_TURNS: float = 1.0

#: Наблюдаемые поля дохода по ресурсу — то, чем пополняется запас за ход.
SPEC_INCOME_FIELDS: dict[str, tuple[str, ...]] = {
    "energy": ("surplus_shield",),
    "food": ("surplus_food",),
    "gold": ("surplus_gold",),
    "tech": ("science",),
}

#: Дипломатические состояния, которые считаются враждебными (`diplomatic_state`).
#: Наблюдённые значения freeciv: 5 — союз, 3 — война. Война снимает векторы
#: реакции и потому есть возмущение; союз — нет.
SPEC_HOSTILE_DIPLOMATIC_STATES: tuple[int, ...] = (3,)

# ── §4.9/§4.2: достижимость и множество счёта ────────────────────────────────

#: Класс допустимых средств `M(S)` — категории актов, по которым вообще строится
#: путь восстановления. Категория есть свойство **акта**, а не опции (§4.9).
SPEC_MEANS_CLASS: tuple[str, ...] = (
    "movement", "terrain", "production", "city_work",
    "research", "diplomacy", "government",
)

#: Объявленное действие акта на DoF своей цели (§4.9). Это **не измерение**, а
#: объявление: акт, завершение которого прибавляет способность (исследование,
#: производство, улучшение земли), поднимает цель на одну способность; акт
#: перемещения или дипломатии — нет. Когда появится измеренная таблица приростов
#: (§4.5), эти значения заменяются ею, и тогда вердикт перестанет опираться на
#: объявление.
#:
#: `research` объявлен нулём намеренно: исследование не поднимает DoF того, кто его
#: ведёт, — оно **сужает** его меню (дверь закрывается), а поднимает DoF тех, кому
#: открывает. Вторая половина пока не связана с данными: какую технологию что
#: открывает, известно (`sup_units`/`sup_improvements`), но мост «технология →
#: сущности, чьё меню она расширяет» ещё не построен. Пока его нет, вердикт не
#: имеет права объявлять восстановление через исследование — и не объявляет.
SPEC_ACT_EFFECT: dict[str, float] = {
    "research": 0.0,
    "production": 1.0,
    "terrain": 1.0,
    "city_work": 0.0,
    "movement": 0.0,
    "diplomacy": 0.0,
    "government": 0.0,
}

#: Категория акта по имени действия (сопоставление по самому длинному префиксу).
#: Порядок здесь не важен: важна длина совпавшего префикса.
SPEC_ACTION_CATEGORY: tuple[tuple[str, str], ...] = (
    ("goto", "movement"),
    ("move", "movement"),
    ("paradrop", "movement"),
    ("board", "movement"),
    ("deboard", "movement"),
    ("airlift", "movement"),
    ("disembark", "movement"),
    ("irrigation", "terrain"),
    ("mine", "terrain"),
    ("cultivate", "terrain"),
    ("plant", "terrain"),
    ("transform_terrain", "terrain"),
    ("fortress", "terrain"),
    ("airbase", "terrain"),
    ("build_road", "terrain"),
    ("road", "terrain"),
    ("railroad", "terrain"),
    ("pillage", "terrain"),
    ("city_buy_production", "production"),
    ("produce_", "production"),
    ("build_city", "production"),
    ("city_change_specialist", "city_work"),
    ("city_work", "city_work"),
    ("city_unwork", "city_work"),
    ("research_tech", "research"),
    ("set_tech_goal", "research"),
    ("add_clause", "diplomacy"),
    ("remove_clause", "diplomacy"),
    ("accept_treaty", "diplomacy"),
    ("cancel_treaty", "diplomacy"),
    ("cancel_vision", "diplomacy"),
    ("stop_negotiation", "diplomacy"),
    ("change_gov", "government"),
    ("set_sci_lux_tax", "government"),
    ("set_tax", "government"),
    ("set_luxury", "government"),
)

#: Переменная, которую меняет категория (§4.6). Акт существует, только пока его
#: переменная не заморожена: у известной технологии `research` заморожен — дверь
#: уже открыта, и акта у неё нет. `None` — категория системная, своей переменной
#: у неё нет.
SPEC_VARIABLE_BY_CATEGORY: dict[str, str | None] = {
    "movement": "position",
    "terrain": "position",
    "production": "production",
    "city_work": "tile_assignment",
    "research": "research",
    "diplomacy": "treaty",
    "government": None,
    "misc": None,
}

#: Горизонт восстановления `T_rec(X)` по типу сущности, в ходах (§4.9). Величина
#: выводится из типа, а не из состояния: она обязана быть одинаковой для всех
#: гипотез одного цикла.
SPEC_RECOVERY_HORIZON_TURNS: dict[str, float] = {
    "unit": 5.0,
    "city": 20.0,
    "tech": 60.0,
    "diplomacy": 10.0,
    "player": 30.0,
}

# ── §3.5/§4.9: мост «технология → кому она открывает дверь» ──────────────────

#: Вид требования предмета, означающий «нужна технология» (`build_reqs` у юнита,
#: `reqs` у улучшения). Требования прочих видов (правительство, местность) мы не
#: умеем оценить и **не оцениваем** — они считаются отдельно и попадают в отчёт.
SPEC_ITEM_REQ_KIND_ADVANCE: int = 1

#: Префикс действия, которым город объявляет постройку. Меню города — **каталог**
#: (в нём перечислено всё, что в принципе можно построить: на первом ходу там
#: «AEGIS Cruiser»), поэтому доступность решает не меню, а требования предмета.
SPEC_PRODUCTION_ACTION_PREFIX: str = "produce_"

#: Префикс действия исследования. Именно оно, в отличие от `set_tech_goal`,
#: открывает дверь: цель лишь объявляет намерение.
SPEC_RESEARCH_ACTION_PREFIX: str = "research_tech_"

#: Префикс действия «цель исследования». Технологию оно не даёт, дверь не
#: открывает, но исчезает из меню вместе с ней — поэтому его и снимает проекция.
SPEC_TECH_GOAL_ACTION_PREFIX: str = "set_tech_goal_"

#: Действия, тратящие **саму** сущность: поселенец уходит в город, юнит вливается
#: или распускается. Потеря называема — исчезает всё меню юнита, то есть все его
#: акты, кроме исполняемого.
SPEC_ENTITY_CONSUMING_ACTIONS: tuple = ("build_city", "join_city", "disband")

#: Действия, тратящие **средство**: покупка постройки платит золотом. Потеря тоже
#: называема — уходит средство `gold` из объявленных групп.
SPEC_MEAN_CONSUMING_ACTIONS: dict = {"city_buy_production": "gold"}

#: Объявленно необратимые действия. Необратимость в §4.4 — это **названная**
#: потеря: ядро отказывает опции, которая объявлена необратимой, но не говорит,
#: что именно теряется (охранник 2), и опции, которая называет потерянным свой
#: собственный путь (охранник 1). `pillage` и `transform_terrain` в список **не
#: входят** ровно поэтому: улучшение местности не является в нашем объявлении ни
#: актом, ни средством, и назвать потерю нечем. Это названный пробел, а не
#: утверждение, что они откатываются.
SPEC_IRREVERSIBLE_ACTIONS: tuple = (
    SPEC_ENTITY_CONSUMING_ACTIONS + tuple(SPEC_MEAN_CONSUMING_ACTIONS)
)
