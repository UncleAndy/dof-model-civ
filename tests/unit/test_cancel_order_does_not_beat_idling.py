"""`cancel_order` не смеет обходить простой: он УНИЧТОЖАЕТ вложенные ходы (§13.277).

Измерено (`/tmp/dof_workchk.log`, след включён, `--no-dof`):

```
turn 4: unit/117/irrigation
turn 5: unit/117/cancel_order      <- запасной ход, предпочтение 0.000
turn 6: unit/117/irrigation
turn 9: unit/117/cancel_order
```

Орошение требует нескольких ходов, а на следующем же ходу юнит получает `cancel_order`:
он отправляется как ЗАПАСНОЙ ход («если предпочтение не выбрало ничего — берём обратимое»),
потому что `cancel_order` обратим. В результате улучшение не доводится до конца, щиты не
растут, и выданные 67 работ клетки могут не дать ничего.

Правило — то же, что уже дважды применялось (13.271, 13.276), но вывернутое: простой ход
не смеет обойти вложение в позицию, значит УНИЧТОЖЕНИЕ вложения не смеет обойти простой.
Цена отмены не ноль, а минус: ноль выглядел бы как «эффекта нет» и позволял выбирать отмену
снова.

Специально НЕ даём надбавку простою: тогда простой обошёл бы и `goto`, и `fortify`, и агент
перестал бы ходить. Штраф получает только отмена.
"""
from __future__ import annotations

from brain.generator.heuristics import ALL_STRATEGIES, HeuristicGenerator

CANCEL = {"action_name": "cancel_order", "ctrl_type": "unit"}
IDLE = {"action_name": "keep_activity", "ctrl_type": "unit"}
MOVE = {"action_name": "goto_0", "ctrl_type": "unit"}
FORTIFY = {"action_name": "fortify", "ctrl_type": "unit"}


def test_cancel_order_scores_lower_than_idling_for_every_arm():
    bad: list[str] = []
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        cancel, idle = gen._preference_score(CANCEL), gen._preference_score(IDLE)
        if cancel >= idle:
            bad.append(f"{strategy.name}: отмена {cancel} не ниже простоя {idle}")
    assert not bad, "; ".join(bad)


def test_cancel_order_does_not_beat_movement_or_fortifying():
    """Штраф только отмене: движение и оборона не должны стать хуже простоя."""
    bad: list[str] = []
    for strategy in ALL_STRATEGIES:
        gen = HeuristicGenerator(strategy=strategy)
        cancel = gen._preference_score(CANCEL)
        for name, cand in (("goto_0", MOVE), ("fortify", FORTIFY)):
            if gen._preference_score(cand) <= cancel:
                bad.append(f"{strategy.name}: {name} не выше отмены")
    assert not bad, "; ".join(bad)
