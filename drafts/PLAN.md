# DOF-MODEL-CIV — План работ для автоматического игрока на базе DOF-Core

> **Статус:** DRAFT v0.1.0
> **Цель:** Создать работающий автоматический игрок для Civilization-подобной 4X-стратегии, реализующий принципы DOF-Core, с возможностью запуска, тестирования и валидации на практике.

---

## 1. Архитектурный выбор базовой игры

### 1.1 Почему CivRealm (Freeciv-web), а не Unciv или CivAgent

| Критерий | Unciv | CivAgent | CivRealm (выбран) |
|---|---|---|---|
| **API для агентов** | Нет (нужен reverse-engineering) | Нет (только через game UI) | **Gym API** (стандарт RL) |
| **Стандартизация** | Низкая | Низкая | **Gymnasium-compatible** |
| **Изоляция состояния** | Сложная | Сложная | **Docker-контейнер** |
| **Мультиагентность** | Нет | Нет (UI-driven) | **Да, от 2 игроков** |
| **Обратимость действий** | Ручной анализ | Ручной анализ | **Встроено в engine** |
| **Источники коллапса** | Нет явных | Нет явных | **fog of war, потеря городов** |

### 1.2 Интеграция через Gym API

CivRealm предоставляет:
- `observation` — полное состояние игры (города, юниты, ресурсы, технологии, дипломатия)
- `action` — управляющие команды (move unit, build city, research tech, diplomatic action)
- `reward` — civilization score (разреженный, в конце эпизода)
- `terminated/truncated` — конец игры / лимит ходов

Это позволяет **разделить concerns**:
- **Environment** = CivRealm (Freeciv-web) — ground truth, physics, game rules
- **Brain** = DOFCalculusCore — DOF-Core decision logic, независимая от игры
- **Bridge** = adapter, который маппит game state → `SystemStateMatrix` и `ActionOption` → game actions

---

## 2. Структура проекта

```
AI/DOF-MODEL-CIV/
├── drafts/                          # Этот план и проектные заметки
│   └── PLAN.md
├── env/                             # Game environment (CivRealm integration)
│   ├── civrealm_adapter.py          # Bridge: CivRealm ↔ DOF-SPEC
│   ├── entity_extractor.py          # Game state → EntityState[]
│   ├── action_mapper.py             # ActionOption → CivRealm action
│   └── config.py                    # Параметры среды, пути, порты
├── brain/                           # DOF-Core decision core
│   ├── core/                        # Порт DOFCalculusCore (Rust/PyO3)
│   │   ├── Cargo.toml
│   │   └── src/lib.rs               # Модифицированный из DOF-MODEL-1
│   └── generator/                   # ActionOption generator
│       ├── game_generator.py        # LLM-based candidate generation
│       └── heuristics.py            # Детерминичные fallback-стратегии
├── metrics/                         # Мониторинг и аналитика
│   ├── dof_tracker.py               # TotalDoF_index по ходам
│   ├── entity_lifecycle.py          # Рождение/гибель/возрождение сущностей
│   └── collapse_detector.py         # Поиск Collapse Sources
├── tests/
│   ├── unit/                        # Моки без игры
│   ├── integration/                 # С реальным CivRealm (Docker)
│   └── fixtures/                    # Сохранённые game states
├── scripts/
│   ├── setup.sh                     # Запуск CivRealm Docker
│   ├── run_match.sh                 # Один матч
│   └── run_tournament.sh            # N матчей с базлайнами
├── baselines/                       # Базовые стратегии для сравнения
│   ├── random_agent.py
│   ├── greedy_agent.py              # Максимизация score
│   └── freeciv_builtin.py           # Встроенный AI Freeciv
├── pub/                             # Публикации, графики, отчёты
├── pyproject.toml                   # Python-зависимости
├── Cargo.toml                       # Rust-core (PyO3)
└── README.md
```

---

## 3. Фазы реализации

### Фаза 0: Инфраструктура и окружение (1–2 дня)

**Цель:** Запустить CivRealm в Docker, получить работающий Gym-интерфейс.

- [ ] 0.1 — Создать `scripts/setup.sh`: запуск Freeciv-web Docker, проверка здоровья
- [ ] 0.2 — Установить `civrealm` (`pip install -e .` из локального клона)
- [ ] 0.3 — Проверить `test_civrealm` (single player) — убедиться, что работает
- [ ] 0.4 — Создать `env/config.py`: порты, пути, параметры подключения
- [ ] 0.5 — Написать smoke-test: `env.civrealm_adapter.connect()`, `step()`, `reset()`

**Критерий готовности:** `civrealm` отдаёт `(observation, reward, terminated, info)` без ошибок.

---

### Фаза 1: Entity Extraction — Game State → DOF State (2–3 дня)

**Цель:** Преобразовать CivRealm observation в нормализованный `SystemStateMatrix`.

- [ ] 1.1 — Описать типы сущностей в игре:
  - `city` — основная единица (population, production, food, gold, happiness)
  - `unit` — военный/рабочий/торговый юнит (position, health, type, orders)
  - `tech` — исследование (progress, prerequisites)
  - `diplomacy` — отношения с другими игроками (ally, war, trade, pact)
  - `economy` — золото, налоги, торговые пути
  - `territory` — контроль тайлов, границы

- [ ] 1.2 — Реализовать `EntityState` для каждого типа:
  - `city`: `current_dof` = f(population_growth, happiness, production_stability, defense_coverage)
  - `unit`: `current_dof` = f(health_ratio, can_retreat, strategic_value)
  - `tech`: `current_dof` = f(progress, prerequisite_saturation)
  - `diplomacy`: `current_dof` = f(relationship_score, optionality_of_alliances)

- [ ] 1.3 — Реализовать `entity_extractor.py`:
  - Парсинг CivRealm observation (dict → typed structures)
  - Вычисление `current_dof` для каждой сущности
  - Определение `is_collapse_source` (вражеские юниты, города под осадой)
  - Вычисление `time_to_collapse_mks` (для городов — turns_to_starvation * turn_duration)

- [ ] 1.4 — Реализовать `psi` declaration:
  - Замер начального состояния
  - Вычисление lens counters (V, V_env, F, F_env) для каждой сущности
  - Каноническая сериализация → SHA-256 digest

**Критерий готовности:** Для любого game state получаем `SystemStateMatrix` с `psi.digest`.

---

### Фаза 2: ActionOption Generator — Генерация кандидатов (2–3 дня)

**Цель:** Генерировать 3–5 различных `ActionOption` на каждом ходу.

- [ ] 2.1 — Описать пространство действий:
  - `city_actions`: build, production_change, disband, sell
  - `unit_actions`: move, attack, fortify, sentry, build_city, improve_tile
  - `diplomacy_actions`: declare_war, peace_treaty, trade_agreement, research_pact, gold_gift
  - `tech_actions`: research, tech_trade
  - `economy_actions`: tax_rate, luxury_rate, trade_route

- [ ] 2.2 — Реализовать `action_mapper.py`:
  - Из `ActionOption.option_id` + параметров → конкретный CivRealm action
  - Обратимость: `city_actions` (build) = частично обратима, `unit_actions` (attack) = необратима
  - `estimated_duration_mks`: время выполнения в микросекундах (для τ-gate)

- [ ] 2.3 — Реализовать эвристический генератор `heuristics.py`:
  - **Defensive**: укрепление границ, усиление городов
  - **Expansionist**: строительство новых городов, захват территорий
  - **Economic**: торговля, накопление, инвестиции в инфраструктуру
  - **Diplomatic**: альянсы, торговля технологиями, сдерживание
  - **Technological**: прорыв в ключевых технологиях

- [ ] 2.4 — (Опционально) LLM-based generator `game_generator.py`:
  - System prompt с DOF-Core аксиомами
  - Генерация 3–5 кандидатов в формате `ActionOption`
  - Fallback на эвристики при ошибке LLM

**Критерий готовности:** На каждом ходу генерируются 3–5 валидных `ActionOption` с `projected_dof_delta`.

---

### Фаза 3: DOFCalculusCore — Порт и адаптация (2–3 дня)

**Цель:** Адаптировать Rust-core из DOF-MODEL-1 под игровой контекст.

- [ ] 3.1 — Создать `brain/core/Cargo.toml` с PyO3, зависимостями из DOF-MODEL-1

- [ ] 3.2 — Портировать `src/lib.rs`:
  - `DOFCalculusCore` — основная логика (Nash product, lookahead, veto)
  - `evaluate_option()` — вычисление `TotalDoF_index(S') - TotalDoF_index(S) - ΔT`
  - `select_best()` — выбор опции с учётом structural admissibility (v0.8)

- [ ] 3.3 — Адаптировать под игровые времена:
  - DOF-MODEL-1: μs (микросекунды), агент принимает решения в реальном времени
  - DOF-MODEL-CIV: turns (ходы), один ход = ~N секунд симуляции
  - Пересчёт: `estimated_duration_mks` = `turn_duration * action_cost_factor`

- [ ] 3.4 — Реализовать игровые специфики:
  - **Axiom 3 (Non-Compensation)**: город с population→0 = collapse → −∞ penalty
  - **Axiom 4 (Reversibility)**: мирный договор > объявление войны
  - **Axiom 5 (Uncertainty)**: fog of war → `dof_known=false` для неизвестных юнитов
  - **Axiom 6 (Autocatalysis)**: технологии, умножающие возможности других сущностей
  - **Axiom 7 (Architectural Neutrality)**: не игнорировать вражеских агентов с неизвестной логикой

- [ ] 3.5 — Построить Python wrapper через PyO3:
  ```python
  from brain_core import DOFCalculusCore, SystemStateMatrix, ActionOption
  
  core = DOFCalculusCore(lookahead_horizon=4, epsilon=1e-6)
  best_option = core.select_best(state, candidates)
  ```

**Критерий готовности:** `DOFCalculusCore` собирается, принимает `SystemStateMatrix`, возвращает `selected_option` с audit report.

---

### Фаза 4: Игровой цикл и интеграция (2–3 дня)

**Цель:** Собрать всё вместе — агент играет полную партию.

- [ ] 4.1 — Реализовать `brain/agent.py`:
  ```
  loop:
      observation = env.step(action)
      state = extractor.extract(observation)
      candidates = generator.generate(state, observation)
      selected = core.select_best(state, candidates)
      actions = action_mapper.map(selected)
      log_audit(state, selected, candidates)
  ```

- [ ] 4.2 — Реализовать `metrics/dof_tracker.py`:
  - Запись `TotalDoF_index` по каждому ходу
  - Отслеживание рождения/гибели сущностей
  - Детекция Collapse Sources (кто кого уничтожает)

- [ ] 4.3 — Реализовать логирование:
  - Сохранение каждого `SystemStateMatrix` (JSON)
  - Лог выбора `ActionOption` с audit report
  - Итоговый отчёт: длительность, score, максимальный/минимальный DoF

- [ ] 4.4 — Интеграция с CivAgent's `civsim` (опционально):
  - Использовать 10-мерные метрики CivAgent (population, food, production, gold, territory, military, happiness, technology, culture, civilization score) как дополнительный источник `current_dof`

**Критерий готовности:** Агент играет полную партию (150 ходов) без крэшей, логирует все решения.

---

### Фаза 5: Тестирование и валидация (3–5 дней)

**Цель:** Доказать, что DOF-Core работает лучше базлайнов.

- [ ] 5.1 — **Unit tests** (без игры):
  - Тест `entity_extractor` на синтетических game states
  - Тест `action_mapper` на всех типах действий
  - Тест `DOFCalculusCore` на фикстурах из DOF-MODEL-1 (hospital/factory/relay)
  - Тест structural admissibility (Axiom 3: не жертвуем городом ради score)

- [ ] 5.2 — **Integration tests** (с CivRealm):
  - Short game (30 turns): проверить, что агент строит города, исследует технологии
  - Disaster scenario: потеря города → проверить, что агент адаптируется
  - Diplomacy scenario: проверить, что агент предпочитает мирные договоры войне

- [ ] 5.3 — **Baseline comparison**:
  - Реализовать `baselines/random_agent.py` (случайные действия)
  - Реализовать `baselines/greedy_agent.py` (максимизация score без DOF)
  - Реализовать `baselines/freeciv_builtin.py` (встроенный AI Freeciv)
  - Запустить 10 матчей каждого baseline против DOF-Core агента
  - Метрики: civilization score, количество городов, средний DoF, время до первого коллапса

- [ ] 5.4 — **Ablation study** (как DOF-MODEL-1):
  - Без Axiom 3 (Non-Compensation): агент жертвует слабыми сущностями
  - Без Axiom 4 (Reversibility): агент предпочитает необратимые действия
  - Без Axiom 5 (Uncertainty): агент игнорирует fog of war
  - Полная модель vs каждая абляция

- [ ] 5.5 — **Статистическая значимость**:
  - Минимум 30 матчей каждого варианта
  - Bootstrap 95% CI для всех метрик
  - Критерий: DOF-Core должен иметь меньшую дисперсию score и большее среднее DoF

**Критерий готовности:** DOF-Core статистически значимо лучше хотя бы одного бейзлайна по `TotalDoF_index` и/или меньше коллапсов.

---

### Фаза 6: Публикация и отчёт (1–2 дня)

- [ ] 6.1 — Сгенерировать графики:
  - `TotalDoF_index` по ходам (DOF-Core vs baselines)
  - Количество живых сущностей по ходам
  - Heatmap: какие действия выбирает DOF-Core vs базлайны

- [ ] 6.2 — Написать `pub/report.md`:
  - Результаты ablation study
  - Сравнение с baselines
  - Примеры решений, где DOF-Core отказался от локально оптимального ради сохранения DoF
  - Ограничения и future work

- [ ] 6.3 — Опубликовать артефакты:
  - GitHub release с бинарниками core
  - Docker image с готовой средой
  - Скрипты для воспроизводимости

---

## 4. Ключевые метрики успеха

| Метрика | Описание | Целевое значение |
|---|---|---|
| **TotalDoF_index** | `Σ ln(DoF(e))` за игру | Выше базлайнов на 20%+ |
| **Collapse count** | Количество сущностей с DoF→0 | Ниже базлайнов на 30%+ |
| **Recovery events** | Количество возрождённых сущностей | > 0 (доказательство Axiom 6) |
| **Irreversible actions ratio** | Доля необратимых действий | Ниже 50% |
| **City survival rate** | Доля городов, доживших до конца | Выше 80% |
| **Diplomatic success** | Доля успешных переговоров | Выше случайного базлайна |

---

## 5. Риски и митигация

| Риск | Митигация |
|---|---|
| CivRealm Docker не запустится на NixOS | Использовать `docker-compose` + проверить порты |
| Слишком большое пространство действий | Ограничить топ-100 кандидатов эвристиками |
| LLM-генератор слишком медленный | Fallback на эвристики при таймауте |
| Агент делает ничего (stay put) | Минимальная частота действий: min 1 action / turn |
| Collapse detection ложнсрабатывает | Настраивать threshold `current_dof < ε` вручную |

---

## 6. Зависимости и стек

- **Python 3.10+**: `civrealm`, `numpy`, `matplotlib`, `pydantic` (для DOF-SPEC)
- **Rust**: `PyO3`, `serde`, `serde_json` (для core)
- **Docker**: `freeciv-web` контейнер (CivRealm)
- **LLM** (опционально): `anthropic`, `openai` — только для `game_generator.py`

---

## 7. Следующие шаги (после этого плана)

1. **Создать `drafts/PLAN.md`** ← этот документ
2. **Фаза 0**: Написать `scripts/setup.sh`, проверить CivRealm
3. **Фаза 1**: Начать `env/entity_extractor.py` с синтетических данных
4. **Фаза 3**: Портировать `brain/core/src/lib.rs` из DOF-MODEL-1
5. **Параллельно**: Unit tests на фикстурах DOF-MODEL-1

---

*План является живым документом. Обновлять по мере прогресса.*
