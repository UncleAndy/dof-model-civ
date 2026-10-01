# Как устроены игровые агенты в комплексе CivRealm (разбор, 2026-10-01)

Назначение: сохранить знание о том, **где в CivRealm находится «вилка» для оценки действий**, чтобы
в будущем не переоткрывать её. Разбор сделан по локальному дереву
`civrealm/` (ветка dev, коммит `1b144d6`) и по репозиториям-спутникам.

---

## 1. Из чего состоит комплекс

* **Freeciv** — движок игры (C), внутри образа `civrealm/freeciv-web:1.4`. Его встроенный ИИ —
  **серверный**, исходников в дереве нет, наружу отдаётся только как игрок
  (`/set aifill N`, `/create X`, `/ai X` — см. `src/civrealm/freeciv/connectivity/client_state.py:229,244,253`).
  Оценок своих вариантов он не публикует.
* **CivRealm** — обёртка-комплекс: Gymnasium-среда, контроллеры, обёртки, базовые агенты.
* **freeciv-bot** (`chris1869/freeciv-bot`) — предок CivRealm; задал форму агента (см. §3).
* **Репозитории-спутники:** `civrealm-llm-baseline` (BaseLang, Mastaba),
  `civrealm-tensor-baseline` (PPO/RL + мини-задачи).

## 2. Скелет агента в самом CivRealm — и точка расширения

`src/civrealm/agents/`:

| файл | что это |
|---|---|
| `base_agent.py` | `BaseAgent(ABC)`: `act(observation, info)`, `get_next_valid_actor(...)` |
| `controller_agent.py` | `ControllerAgent(BaseAgent)`: диспетчер по контроллерам |
| `random_agent.py`, `no_op_agent.py`, `random_language_agent.py` | тривиальные реализации |

`ControllerAgent.act()` на каждом шаге берёт **одного** актора и спрашивает у оценки, что делать:

```python
valid_actor_id, valid_action_dict = self.get_next_valid_actor(observations, info, ctrl_type)
calculate_func = getattr(self, f'calculate_{ctrl_type}_actions')   # unit | city | tech | gov | dipl | player
action_name = calculate_func(valid_action_dict)                    # ← ВИЛКА ДЛЯ ОЦЕНКИ
```

`get_next_valid_actor` перебирает `info['available_actions']` по типам контроллеров, выбрасывает
варианты с флагом `False`, помнит, кому уже назначено действие в этом ходу
(«одно действие на актора за ход»). Есть и вероятностный путь:
`sample_action_by_prob(action_probabilities)` и `sample_desired_actions(action_dict, desired_actions)` —
то есть оценка может быть **таблицей весов**, а не одним именем.

**Вывод:** агент по замыслу отвечает только за «желательность» действия. Чтобы вставить принцип DoF,
достаточно подменить тело `calculate_*_actions` (или подать веса из нашего calculus).

## 3. Родоначальник: freeciv-bot и `action_wants`

freeciv-bot формализует ту же идею ещё прямее:

```python
class SimpleBot(BaseBot):
    def calculate_unit_actions(self, turn_no, full_state, a_options):
        action_wants = {}                       # actor -> {action -> want}
        ...
        if action_key == "explore":  action_wants[uid][action_key] = ACTION_WANTED
        elif "goto" in action_key:   action_wants[uid][action_key] = ACTION_WANTED * random() * 0.25
        elif action_key == "build":  action_wants[uid][action_key] = ACTION_WANTED * random() * 0.75
        else:                        action_wants[uid][action_key] = ACTION_UNWANTED
```

То есть это **таблица оценок на каждое действие каждого актора**. Но по сути это шаблон-заглушка
(константы × `random()`), а не сильный игрок. Ценность — в каркасе: словарь действий, обход акторов,
клиентская обвязка.

## 4. Спутники

* **`civrealm-llm-baseline`** — два LLM-агента:
  * **BaseLang** — параллельный контроллер на каждый юнит;
  * **Mastaba** — «советник» (advisor), который ведёт всех остальных.
  Требует внешних сервисов: OpenAI (или Azure) и **Pinecone** (векторная память). Промпты лежат в
  `prompt_collections/`, агенты — в `agents/`.
* **`civrealm-tensor-baseline`** — PPO на Gymnasium API; мини-задачи 12 типов × 3 уровня = 36
  (`development_build_city`, `development_citytile_wonder`, `battle_*`, `diplomacy_trade_tech`),
  обучение через `n_rollout_threads`, `num_env_steps`, `episode_length`. Награда — из среды
  (`reward_wrapper.py`: плотная по `mini_score`, отложенная по `success`).

## 5. Где здесь место принципу DoF (вывод обсуждения)

1. **Вживлять DoF в C-ИИ движка нельзя** без потери аудита: он решает серверно, вариантов не отдаёт,
   воспроизводимость ломается (свой образ).
2. **Можно взять каркас** (`calculate_*_actions` / `action_wants`) и подменить оценку на
   `NetDelta = Δ Σ ln(DoF)` из замеров. Но их цикл выбирает **первого попавшегося актора** — сравнения
   между акторами нет, поэтому всё равно нужен наш слой арбитража (индекс, коридор, протокол).
3. **Сильного игрока в каркасе нет:** `ControllerAgent` — заглушка, `SimpleBot` — шаблон. Сильно играет
   только серверный ИИ, чью оценку не отдают. Значит «взять ИИ за основу» = взять **каркас**, а не ум.
4. **Естественные места для DoF:** `calculate_*_actions` (CivRealm) либо роль «советника» в Mastaba
   (каркас и планы от неё, числа — от наших замеров). RL-базовая даёт shaping награды, но веса не
   измеримы — расходится с правилом «числа добывает мир».
5. **Как мера исхода** встроенный ИИ годится уже сейчас: он и так в каждой партии (`aifill`), и это
   наша объявленная мера («относительный исход против ИИ на парных картах»). Полезное дополнение —
   «эталонная траектория»: тот же сид, одного игрока ведёт серверный ИИ (`/create X` + `/ai X`).

## 6. Полезные факты для будущего

* Оценка действия может быть **весами**, а не одним вариантом (`sample_action_by_prob`) — значит наш
  calculus можно подавать туда как распределение.
* `info['available_actions']` — тот же канал, которым пользуемся мы; контроллеры: `unit`, `city`,
  `tech`, `gov`, `dipl`, `player`.
* Мини-задачи tensor-базовой (`battle_defend_city`, `development_build_city`) — готовые полигоны для
  проверки отдельных гипотез DoF (например, цены защитника) без полной партии.
* Наш агент (`brain/v2`) уже имеет ту же форму (сенсоры → граф → кандидаты → calculus → исполнитель),
  поэтому «взять каркас» — это в основном рефакторинг в их конвенции, а не новая возможность.

## 7. Источники

* Локально: `civrealm/src/civrealm/agents/{base_agent,controller_agent,random_agent,no_op_agent}.py`,
  `civrealm/src/civrealm/envs/freeciv_wrapper/*`, `civrealm/src/civrealm/game_ai_assistant.py`,
  `civrealm/src/civrealm/freeciv/connectivity/client_state.py`.
* Онлайн: `github.com/bigai-ai/civrealm`, `.../civrealm-llm-baseline`, `.../civrealm-tensor-baseline`,
  `github.com/chris1869/freeciv-bot`, `bigai-ai.github.io/civrealm`, статья arXiv:2401.10568.