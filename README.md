# DOF-MODEL-CIV — Виртуальная песочница для проверки DOF-Core

> **Статус:** DRAFT — проект на стадии планирования и первых прототипов.
> **Автор:** Andrei Velikoredchanin

## Что это такое

DOF-MODEL-CIV — это экспериментальная среда для тестирования принципов [DOF-Core](https://github.com/NousResearch/DOF) на задаче управления виртуальным государством в классической 4X-стратегии.

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
| [DOF](https://github.com/NousResearch/DOF) | Математическая спецификация DOF-Core (DOF-SPEC v0.9.1) |
| [DOF-MODEL-1](https://github.com/NousResearch/DOF-MODEL-1) | Прототип на критической инфраструктуре (Hospital/Factory/Relay) — source of truth для core |
| [CivRealm](https://github.com/bigai-ai/civrealm) | Игровая среда (Freeciv-web + Gymnasium API) |
| [CivAgent](https://github.com/LeoLin990405/civagent) | Оркестрация 57 исторических режимов (вдохновение для генератора) |
| [Unciv](https://github.com/yairm210/Unciv) | Базовая игра (используется в CivAgent, не в нашем проекте) |

## Быстрый старт

### Предварительные требования

- Nix с поддержкой flakes
- Docker (для Freeciv-web)

### Установка

```bash
cd DOF-MODEL-CIV

# Запускаем Freeciv-web (отдельный терминал)
cd civrealm/src/civrealm/configs
docker compose up -d freeciv-web

# Собираем Rust core (один раз)
cd ../../../..
bash scripts/build_core.sh

# Входим в dev-окружение (direnv или nix develop)
nix develop --impure
```

### Использование

```bash
# Запуск всех тестов
pytest tests/

# Тесты Rust-ядра
pytest tests/unit/test_core.py -v

# Захват реальных данных из игры
python scripts/capture_obs.py --turns 10

# Интеграционные тесты (требует запущенный Docker)
pytest tests/integration/test_real_obs.py -v
```

## Фазы разработки

| Фаза | Статус | Описание |
|---|---|---|
| 0: Инфраструктура | ✅ Done | Запуск CivRealm Docker, проверка Gym API |
| 1: Entity Extraction | ✅ Done | Game state → SystemStateMatrix с psi.digest |
| 2: ActionOption Generator | ✅ Done | Эвристический + LLM-based генератор кандидатов |
| 3: DOFCalculusCore | ✅ Done | Порт Rust-ядра из DOF-MODEL-1 |
| 4: Игровой цикл | ⬜ To Do | Сборка агента, логирование |
| 5: Валидация | ⬜ To Do | Baseline comparison, ablation study |
| 6: Публикация | ⬜ To Do | Графики, отчёт |

## Ключевые метрики

| Метрика | Описание | Цель |
|---|---|---|
| **TotalDoF_index** | `Σ ln(DoF(e))` по ходам | Выше базлайнов на 20%+ |
| **Collapse count** | Сущности с DoF→0 | Ниже базлайнов на 30%+ |
| **Recovery events** | Возрождённые сущности | > 0 (доказательство Axiom 6) |
| **Irreversible actions ratio** | Доля необратимых действий | Ниже 50% |
| **City survival rate** | Города, дожившие до конца игры | Выше 80% |

## Лицензия

CC BY-SA 4.0 — см. [DOF-SPEC §2](https://github.com/NousResearch/DOF/blob/main/DOF-SPEC.md).

---

*Этот README является живым документом. Обновляется по мере прогресса проекта.*
