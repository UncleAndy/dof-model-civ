# DOF-MODEL-CIV — Виртуальная песочница для проверки DOF-Core

> **Статус:** DRAFT — проект на стадии планирования и первых прототипов.
> **Автор:** Andrei Velikoredchanin

## Что это такое

DOF-MODEL-CIV — это экспериментальная среда для тестирования принципов [DOF-Core](https://github.com/UncleAndy/dof-core) на задаче управления виртуальным государством в классической 4X-стратегии.

Мы берём [CivRealm](https://github.com/bigai-ai/civrealm) (обёртку над Freeciv-web с Gymnasium API) и подключаем к ней «мозг» на базе DOFCalculusCore — детерминированный математический аппарат, который оценивает каждое решение через призму **Degrees of Freedom**: сколько будущих возможностей сохраняет или уничтожает данное действие.

Цель — проверить, может ли агент, реализующий аксиомы DOF-Core, эффективнее классических базлайнов управлять цивилизацией в условиях неполной информации, конкурирующих агентов и необратимых решений.

## Мотивация

DOF-Core — это формальный фреймворк для принятия решений в системах с несколькими сущностями, имеющими собственные будущие состояния. Его аксиомы (Non-Compensation, Reversibility, Uncertainty и др.) хорошо работают в статических моделях, но не проверены на **сложных динамических средах** с:

- десятками и сотнями сущностей (города, юниты, технологии, дипломатические отношения)
- необратимыми действиями (потеря города, объявление войны, сжигание ресурсов)
- неполной информацией (fog of war)
- конкурирующими агентами (другие цивилизации со своими целями)

4X-стратегия идеальна для такой проверки: в ней есть всё вышеперечисленное, плюс понятная метрика успеха (civilization score) и возможность сравнения с классическими AI.

## Архитектура

```
┌─────────────────────────────────────────────────────┐
│  Environment (CivRealm / Freeciv-web)               │
│  ─ ground truth, physics, game rules                │
│  ─ Gymnasium API: (obs, reward, done, info)         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  Bridge (env/*)                                     │
│  ─ entity_extractor: obs → SystemStateMatrix        │
│  ─ action_mapper: ActionOption → civrealm action    │
│  ─ маппинг игровых сущностей в DOF-EntityState      │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  Brain (brain/*)                                    │
│  ─ generator: 3-5 ActionOption candidates           │
│  ─ core (Rust/PyO3): DOFCalculusCore               │
│    · Nash log-product index Σ ln(DoF(e))           │
│    · lookahead tree-search                          │
│    · Axiom-3 veto (Non-Compensation)                │
│    · structural admissibility (D1=D2=D3=0)         │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  Metrics & Audit                                    │
│  ─ TotalDoF_index по ходам                         │
│  ─ entity lifecycle (рождение/гибель/возрождение)   │
│  ─ collapse detection                              │
│  ─ audit report (JSON, каждый цикл)                 │
└─────────────────────────────────────────────────────┘
```

Ключевой принцип: **environment ничего не знает о DOF-Core, а core ничего не знает об игре**. Они общаются через строго определённый контракт (`SystemStateMatrix`, `ActionOption`), что позволяет заменить игру или core независимо.

## Связанные проекты

| Проект | Роль |
|---|---|
| [DOF](https://github.com/UncleAndy/dof-core) | Математическая спецификация DOF-Core (DOF-SPEC v0.9.1) |
| [DOF-MODEL-1](https://github.com/UncleAndy/dof-model-1) | Прототип на критической инфраструктуре (Hospital/Factory/Relay) — source of truth для core |
| [CivRealm](https://github.com/bigai-ai/civrealm) | Игровая среда (Freeciv-web + Gymnasium API) |
| [CivAgent](https://github.com/LeoLin990405/civagent) | Оркестрация 57 исторических режимов (вдохновение для генератора) |
| [Unciv](https://github.com/yairm210/Unciv) | Базовая игра (используется в CivAgent, не в нашем проекте) |

## Фазы разработки

См. [drafts/PLAN.md](drafts/PLAN.md) для детального плана. Текущий прогресс:

| Фаза | Статус | Описание |
|---|---|---|
| 0: Инфраструктура | ⬜ To Do | Запуск CivRealm Docker, проверка Gym API |
| 1: Entity Extraction | ⬜ To Do | Game state → SystemStateMatrix с psi.digest |
| 2: ActionOption Generator | ⬜ To Do | Эвристический + LLM-based генератор кандидатов |
| 3: DOFCalculusCore | ⬜ To Do | Порт Rust-ядра из DOF-MODEL-1 |
| 4: Игровой цикл | ⬜ To Do | Сборка агента, логирование |
| 5: Валидация | ⬜ To Do | Baseline comparison, ablation study |
| 6: Публикация | ⬜ To Do | Графики, отчёт |

## Установка

> **Примечание:** Проект в стадии активной разработки. Ниже — целевые инструкции.

### Предварительные требования

- Python 3.10+
- Rust (с PyO3 support)
- Docker и docker-compose

### Шаги

```bash
# 1. Клонировать репозиторий
git clone <url> DOF-MODEL-CIV
cd DOF-MODEL-CIV

# 2. Установить Python-зависимости
pip install -e .

# 3. Собрать Rust-core (PyO3)
cd brain/core
maturin develop --release
cd ../..

# 4. Запустить Freeciv-web (CivRealm)
bash scripts/setup.sh

# 5. Проверить установку
python -m pytest tests/unit/
python -m pytest tests/integration/  # требует запущенный Docker
```

## Использование

> **Примечание:** Будет доступно после завершения фазы 4.

```bash
# Запустить один матч (DOF-Core vs встроенный AI)
bash scripts/run_match.sh

# Запустить турнир (DOF-Core vs baselines)
bash scripts/run_tournament.sh --games 30 --baselines random,greedy,freeciv_builtin
```

## Ключевые метрики

| Метрика | Описание | Цель |
|---|---|---|
| **TotalDoF_index** | `Σ ln(DoF(e))` по ходам | Выше базлайнов на 20%+ |
| **Collapse count** | Сущности с DoF→0 | Ниже базлайнов на 30%+ |
| **Recovery events** | Возрождённые сущности | > 0 (доказательство Axiom 6) |
| **Irreversible actions ratio** | Доля необратимых действий | Ниже 50% |
| **City survival rate** | Города, дожившие до конца игры | Выше 80% |

## Лицензия

CC BY-SA 4.0 — см. [DOF-SPEC §2](https://github.com/UncleAndy/dof-core/blob/main/DOF-SPEC.md).

---

*Этот README является живым документом. Обновляется по мере прогресса проекта.*
