#!/usr/bin/env python
"""Короткий парный замер irrigation по серверному city map, не map.output.

Ничего не записывает в модель. Один матч, один рабочий, одна клетка;
нулевой дельте можно доверять только в сохранённом контексте этого города.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / "civrealm" / "src")]

from env.terrain_output import paired_output_deltas, server_tile_outputs
from scripts.measure_terrain_effect import tile_of, units_by_key

DIRECTIONS = ((-1, -1), (0, -1), (1, -1), (-1, 0),
              (1, 0), (-1, 1), (0, 1), (1, 1))


def timeout(signum, frame):
    raise TimeoutError("tile output probe exceeded its time budget")


def city_actions(env):
    return env.unwrapped.civ_controller.city_ctrl.prop_actions._action_dict


def snapshot(env, obs, info, x, y):
    terrain, extras, base = tile_of(obs, x, y)
    controller = env.unwrapped.civ_controller
    player = controller.player_ctrl.players[env.unwrapped.get_playerid()]
    return {"turn": info.get("turn"), "tile": [x, y], "terrain": terrain,
            "extras": extras, "base_map_output": base,
            "server_output_by_city": server_tile_outputs(city_actions(env), x, y),
            "government": int(player["government"])}


def step(env, action):
    signal.alarm(35)
    obs, _, terminated, truncated, info = env.step(action)
    signal.alarm(0)
    if terminated or truncated:
        raise RuntimeError(f"match ended during {action!r}")
    return obs, info


def found_city(env, obs, info):
    for actor, actions in info["available_actions"]["unit"].items():
        if actions.get("build_city"):
            obs, info = step(env, ("unit", actor, "build_city"))
            if not obs.get("city"):
                raise RuntimeError("build_city returned without an observed city")
            return step(env, None)
    raise RuntimeError("no valid founding action")


def centres(obs):
    return {(int(city["x"]), int(city["y"])) for city in obs["city"].values()}


def find_job(env, obs, info):
    units = units_by_key(obs)
    for actor, actions in info["available_actions"]["unit"].items():
        unit = units.get(actor) or units.get(str(actor))
        if unit is None or not actions.get("irrigation"):
            continue
        x, y = int(unit["x"]), int(unit["y"])
        if (x, y) not in centres(obs) and server_tile_outputs(city_actions(env), x, y):
            return actor, x, y
    return None


def move_worker(env, obs, info):
    units = units_by_key(obs)
    shape = obs["map"]["terrain"].shape
    for actor, actions in info["available_actions"]["unit"].items():
        if not any(actions.get(work) for work in ("irrigation", "mine", "build_road", "plant", "cultivate", "transform_terrain")):
            continue
        unit = units.get(actor) or units.get(str(actor))
        x, y = int(unit["x"]), int(unit["y"])
        for direction, (dx, dy) in enumerate(DIRECTIONS):
            name = f"goto_{direction}"
            tx, ty = (x + dx) % shape[0], (y + dy) % shape[1]
            if not actions.get(name) or (tx, ty) in centres(obs):
                continue
            terrain, extras, _ = tile_of(obs, tx, ty)
            if terrain not in ("Plains", "Grassland", "Hills", "Desert", "Tundra"):
                continue
            if "Irrigation" not in extras and server_tile_outputs(city_actions(env), tx, ty):
                return step(env, ("unit", actor, name))
    return step(env, None)


def prepare_job(env, obs, info):
    obs, info = found_city(env, obs, info)
    for _ in range(6):
        print(json.dumps({"kind": "prepare", "turn": info.get("turn"),
                          "unit_actions": {str(k): [a for a, p in v.items() if p]
                                           for k, v in info["available_actions"]["unit"].items()}}), flush=True)
        job = find_job(env, obs, info)
        if job is not None:
            return obs, info, job
        obs, info = move_worker(env, obs, info)
    raise RuntimeError("no irrigation job with an authoritative off-centre sensor")


def measure(env, obs, info, job, turns):
    actor, x, y = job
    before = snapshot(env, obs, info, x, y)
    print(json.dumps({"kind": "before", **before}), flush=True)
    obs, info = step(env, ("unit", actor, "irrigation"))
    samples = []
    for _ in range(turns):
        obs, info = step(env, None)
        after = snapshot(env, obs, info, x, y)
        samples.append(after)
        print(json.dumps({"kind": "watch", **after}), flush=True)
        if "Irrigation" in after["extras"] and "Irrigation" not in before["extras"]:
            deltas = paired_output_deltas(before["server_output_by_city"], after["server_output_by_city"])
            valid = bool(deltas) and before["government"] == after["government"]
            return {"valid": valid, "before": before, "after": after,
                    "server_delta_by_city": deltas, "samples": samples}
    return {"valid": False, "error": "irrigation did not complete", "before": before,
            "samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, choices=(6001, 6003), default=6001)
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import gymnasium as gym
    from civrealm.configs import fc_args
    os.environ["PYTHONWARNINGS"] = "ignore"
    fc_args["username"] = f"TileSensor{time.time_ns()}"
    fc_args["client_port"] = args.port
    env = gym.make("civrealm/FreecivBase-v0", username=fc_args["username"])
    signal.signal(signal.SIGALRM, timeout)
    try:
        signal.alarm(90)
        obs, info = env.reset(client_port=args.port)
        signal.alarm(0)
        obs, info, job = prepare_job(env, obs, info)
        result = measure(env, obs, info, job, args.turns)
        result.update(port=args.port, username=fc_args["username"])
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0 if result["valid"] else 2
    finally:
        signal.alarm(20)
        env.close()
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
