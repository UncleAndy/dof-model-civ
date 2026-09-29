"""Прогноз площадки против факта города: корпус, который может опровергнуть модель.

Что здесь проверяется. Пространственная часть модели (`env/site_eval.py`) берётся
предсказывать выход города по карте: суммарную еду/щиты/торговлю лучших
`size+1` клеток площадки. Мир же публикует ФАКТИЧЕСКИЙ выход города:
`prod_food`, `prod_shield`, `prod_trade` в `obs['city']`. Значит, их можно
сравнить на одном городе, одном размере и одном месте — и получить честную
ошибку прогноза.

Почему это записано отдельным корпусом, а не живёт внутри матча. Модель мира
умирает вместе с матчем, а ошибку прогноза надо мерить по многим городам из
разных матчей и разных стартов. Поэтому строки дописываются в файл (JSONL) и
корпус растёт от прогона к прогону.

Чем это может кончиться. Если корреляция прогноза с фактом окажется нулевой,
модель площадок неверна — и это надо будет сказать прямо, а не «уточнить
коэффициент». Поэтому же здесь считается ошибка по каждому каналу отдельно:
еда, щиты и торговля могут вести себя по-разному.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

#: Сколько ходов городу нужно прожить, прежде чем сверять прогноз с фактом.
#: Слишком рано — город ещё не развернул площадку (работает 1-2 клетки), слишком
#: поздно — успевают вмешаться улучшения и жители.
OUTCOME_AGE_TURNS = 5

#: Через сколько ходов после первого промаха считать город потерянным.
#: Слой городов приходит пакетами (по изменению), поэтому «нет города в этом
#: наблюдении» — это чаще всего «пакет не пришёл», а не «город исчез». Первый
#: промах записывать как потерю означало бы выдумывать факт: в первом прогоне
#: так «потерялись» все 30 городов подряд.
LOST_AFTER_TURNS = 15

OUTCOMES_FILE = Path(
    os.environ.get("DOF_SITE_OUTCOMES",
                   Path(__file__).resolve().parents[1] / "site_outcomes.jsonl")
)

CHANNELS = ("food", "shield", "trade")


def record(rows: Iterable[dict], path: Optional[Path] = None) -> int:
    """Дописать строки-сверки в корпус. Возвращает число записанных."""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    target = Path(path or OUTCOMES_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Метка прогона: по ней в корпусе видно, чьи это города (агент или no-op),
    # иначе строки разных экспериментов свалятся в одну кучу.
    tag = os.environ.get("DOF_RUN_TAG", "")
    if tag:
        rows = [dict(r, tag=tag) for r in rows]
    try:
        with open(target, "a") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        # Корпус — не критичный путь матча: не записали сверку, матч продолжаем.
        return 0
    return len(rows)


def load(path: Optional[Path] = None) -> list[dict[str, Any]]:
    target = Path(path or OUTCOMES_FILE)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # битая строка не должна портить весь корпус
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ошибка прогноза по каналам и корреляция прогноза с фактом.

    Ошибка считается **относительной** (|прогноз − факт| / факт) и только там,
    где факт не ноль: делить на ноль — выдумывать число. Корреляция — Пирсон по
    парам (прогноз, факт) на непустых парах.

    Считаются **два** сравнения, и это принципиально: модель предсказывает
    валовой выход, а мир публикует чистый (за вычетом отходов и коррупции).
    «Чистое» сравнение честно к миру, «валовое» — к модели, и если разница
    большая, значит спор не о модели, а о том, что с чем сравнивают.
    """
    out: dict[str, Any] = {"n": len(rows), "channels": {}}
    for channel in CHANNELS:
        observed_key = {"food": "obs_food", "shield": "obs_shield",
                        "trade": "obs_trade"}[channel]
        losses_key = {"food": None, "shield": "obs_waste",
                      "trade": "obs_corruption"}[channel]
        net_pairs: list[tuple[float, float]] = []
        gross_pairs: list[tuple[float, float]] = []
        for r in rows:
            pred = r.get(f"pred_{channel}")
            obs = r.get(observed_key)
            if pred is None or obs is None:
                continue
            pred, obs = float(pred), float(obs)
            if obs:
                net_pairs.append((pred, obs))
            losses = float(r.get(losses_key) or 0.0) if losses_key else 0.0
            if obs + losses:
                gross_pairs.append((pred, obs + losses))
        if not net_pairs:
            out["channels"][channel] = {"n_usable": 0}
            continue
        out["channels"][channel] = {
            "n_usable": len(net_pairs),
            "error_mean": sum(abs(p - o) / o for p, o in net_pairs) / len(net_pairs),
            "error_max": max(abs(p - o) / o for p, o in net_pairs),
            "exact_share": sum(1 for p, o in net_pairs
                               if abs(p - o) < 1e-9) / len(net_pairs),
            "corr": _pearson([p for p, _ in net_pairs], [o for _, o in net_pairs]),
            "pred_mean": sum(p for p, _ in net_pairs) / len(net_pairs),
            "obs_mean": sum(o for _, o in net_pairs) / len(net_pairs),
            "gross_n": len(gross_pairs),
            "gross_error_mean": (sum(abs(p - o) / o for p, o in gross_pairs)
                                 / len(gross_pairs)) if gross_pairs else None,
            "gross_corr": _pearson([p for p, _ in gross_pairs],
                                   [o for _, o in gross_pairs]) if gross_pairs else None,
        }
    return out


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:  # нет разброса — корреляция не определена
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy)


def clear(path: Optional[Path] = None) -> None:
    """Очистить корпус (нужно тестам и новым сериям прогонов)."""
    target = Path(path or OUTCOMES_FILE)
    if target.exists():
        _atomic_write(target, "")
    elif tempfile.gettempdir():
        pass


def _atomic_write(target: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
