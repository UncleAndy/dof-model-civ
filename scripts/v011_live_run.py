"""Живой прогон `v0.11` на стенде: наблюдение партии + запись видео параллельно.

Один процесс, одна партия: кадры снимает **мир** (headless-браузер, отдельный поток внутри CivRealm),
а мы в это время мерим каждый ход **тем же кодом**, что и прогон на записанных наблюдениях
(`env/spec_obs.measure_step`), и наносим состояние на кадры. Отсюда «параллельная генерация видео»:
кадры идут своим чередом, замер — своим, и видео собирается по окончании.

Что пишется в трассу по каждому ходу: индекс, счёт векторов `V` по сущностям, свои города и юниты,
наблюдённые нападения, метки источников коллапса, строки канала смены производства и цена смены.
Если нападать и менять стройку некому (мирные ходы, аifill играет сам), это видно прямо в трассе —
и ноль **не выглядит** как «опасности нет»: он идёт с причиной.

Запуск (порт занимает стенд — брать свежий и свободный):

    P=$PWD; SP=$(ls -d /nix/store/*-python3.12-*/lib/python3.12/site-packages | tr '\n' ':')
    PYTHONPATH="$P/civrealm/src:$P:$P/.venv/lib/python3.12/site-packages:$SP" PYTHONWARNINGS=ignore \
    V011_TURNS=80 V011_FPS=6 DOF_RUN_TAG=live1 \
    .venv/bin/python scripts/v011_live_run.py --port 6001 --seed 9200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env import spec_obs as SO  # noqa: E402
from env import spec_risk as SK  # noqa: E402
from env import video as V  # noqa: E402
from env.entity_extractor import GameStateExtractor  # noqa: E402


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Живой прогон v0.11 + запись видео")
    ap.add_argument("--port", type=int, default=int(os.environ.get("V011_PORT", "6001")))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("V011_SEED", "9200")))
    ap.add_argument("--turns", type=int, default=int(os.environ.get("V011_TURNS", "80")))
    ap.add_argument("--fps", type=int, default=int(os.environ.get("V011_FPS", "6")))
    ap.add_argument("--no-fog", action="store_true", help="снимать наблюдателем (вся карта)")
    return ap.parse_args()


def live(port: int, seed: int, turns: int, fps: int, fog: bool) -> dict[str, Any]:
    import gymnasium  # noqa: E402
    from civrealm.configs import fc_args  # noqa: E402
    from civrealm.freeciv.utils.freeciv_logging import log_dir  # noqa: E402

    fc_args["client_port"] = port
    fc_args["debug.take_screenshot"] = True      # кадры снимает МИР, мы их только собираем
    fc_args["debug.headless"] = True
    fc_args["debug.global_view_screenshot"] = not fog

    shots_root = Path(log_dir) / "screenshots"
    before = set(shots_root.rglob("*.png")) if shots_root.exists() else set()
    trace_path = ROOT / "knowledge" / f"live_trace_{seed}_port{port}{'_' + V.RUN_TAG if V.RUN_TAG else ''}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace = trace_path.open("w", encoding="utf-8")

    env = gymnasium.make("civrealm/FreecivBase-v0")
    V.install_signal_handlers()
    obs, info = env.reset(client_port=port, seed=seed)
    V._ACTIVE["env"] = env
    V.start_ui_hiding(env)
    try:
        own_id = int(env.get_playerid() or 0)
    except Exception:  # noqa: BLE001
        own_id = 0
    extractor = GameStateExtractor(my_player_id=own_id)
    guard = V.install_step_timeout(float(os.environ.get("V011_STEP_TIMEOUT", "60")))
    states: dict[str, tuple[list[str], list[str]]] = {}
    rows: list[dict[str, Any]] = []
    prev_obs = obs
    played = 0
    outcome = "партия_окончена"

    def capture(o: dict, turn: Any, index: float, counts: dict) -> None:
        for p in V.frames_since(before | set(states), shots_root):
            if p.name in states:
                continue
            left, right = V.state_lines(o or {}, turn, own_id,
                                        dof_lookup=lambda eid: counts.get(eid), index=index)
            states[p.name] = (left, right)

    def marks_like() -> Any:
        """Метки источников коллапса: у извлекателя они внутри трекера наблюдения нападения."""
        tr = getattr(extractor, "attack_tracker", None)
        return getattr(tr, "marks", tr)

    try:
        for _ in range(turns):
            with guard():
                obs, _r, terminated, truncated, info = env.step(None)   # пассивный ход: решаем не мы
            played += 1
            if not obs:
                outcome = "обрыв"                     # мир отдал {} при серверной проблеме
                break
            turn = (info or {}).get("turn")
            m = SO.measure_step(obs, info, turn, extractor, prev_obs=prev_obs, my_player_id=own_id)
            counts = m["counts"]
            try:
                risk, _detail, why = SK.risk_with_reason(obs, marks_like(), turn, own_id, counts)
            except Exception as exc:  # noqa: BLE001
                risk, why = 0.0, f"цена риска не посчитана: {type(exc).__name__}: {str(exc)[:80]}"
            try:
                # Форма возврата: (величина, число строк канала, причина) — строки только этого прогона.
                loss, n_rows, loss_why = extractor.switch_loss_shields()
            except Exception as exc:  # noqa: BLE001
                loss, n_rows = 0.0, 0
                loss_why = f"цена смены не измерена: {type(exc).__name__}: {str(exc)[:80]}"
            marks = getattr(extractor, "marked_collapse_sources", None) or {}
            row = {"ход": turn, "индекс": round(float(m["index"]), 4),
                   "сущностей": len(m["measured"]),
                   "V_всего": round(sum(counts.values()), 1),
                   "нападение": getattr(extractor, "last_attack_event", None),
                   "меток": len(marks),
                   "строк_смены": n_rows,
                   "цена_смены": loss, "почему_смены": loss_why,
                   "риск": round(float(risk), 4), "почему_риска": why}
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            capture(obs, turn, m["index"], counts)
            if played % 5 == 0 or row["нападение"] or risk > 0:
                _f = lambda v: f"{v:g}" if isinstance(v, (int, float)) else "не измерено"  # noqa: E731
                print(f"  ход {turn}: индекс {row['индекс']:+.3f}, сущностей {row['сущностей']}, "
                      f"V {row['V_всего']:.0f}, нападение {row['нападение']}, меток {row['меток']}, "
                      f"риск {_f(row['риск'])}, смена {_f(row['цена_смены'])}", flush=True)
            prev_obs = obs
            if terminated or truncated:
                outcome = "партия_окончена_миром"
                break
    except V.StepTimeout:
        outcome = "обрыв_шага"
        print("  [клин] шаг не вернулся — партия прервана", flush=True)
    finally:
        trace.close()
        V.cleanup_env(env)
        V._ACTIVE["env"] = None

    frames = V.frames_since(before, shots_root)
    frames = V.draw_state(frames, states, ROOT / "knowledge" / "frames_text" / f"port{port}")
    out = ROOT / "knowledge" / V.video_name(seed, port, ext="mp4")
    ok = V.to_video(frames, out, fps)

    attacks = [r for r in rows if isinstance(r["нападение"], dict) and r["нападение"].get("attacked")]
    risks = [r["риск"] for r in rows]
    summary = {
        "сид": seed, "порт": port, "итог": outcome, "ходов": played,
        "кадров": len(frames), "кадров_с_состоянием": len(states),
        "видео": str(out) if ok else None,
        "трасса": str(trace_path),
        "нападений_наблюдено": len(attacks),
        "меток_максимум": max((r["меток"] for r in rows), default=0),
        "риск_максимум": round(max(risks), 4) if risks else None,
        "цена_смены": max((r["цена_смены"] or 0.0 for r in rows), default=0.0),
        "индекс_от": rows[0]["индекс"] if rows else None,
        "индекс_до": rows[-1]["индекс"] if rows else None,
        "туман": bool(fog),
    }
    return summary


def main() -> int:
    a = _args()
    print(f"[прогон] туман: {'наш вид агента' if (V.FOG and not a.no_fog) else 'наблюдатель'}; "
          f"окно {V.WINDOW}; метка {V.RUN_TAG or '—'}", flush=True)
    r = live(a.port, a.seed, a.turns, a.fps, fog=(V.FOG and not a.no_fog))
    print("\n===== итог =====")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
