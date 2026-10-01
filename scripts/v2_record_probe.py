"""Диагностика съёмки: доступен ли драйвер наблюдения и какие элементы есть в клиенте.

Нужно, чтобы понять: (а) доходит ли наш поток до `driver`, (б) есть ли в клиенте обзорная карта
(`#overview_map`) и в каком она состоянии, (в) какие окна надо прятать.
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gymnasium  # noqa: E402
import civrealm  # noqa: E402,F401
from civrealm.configs import fc_args  # noqa: E402

PORT = int(os.environ.get("V2_PORT", "6304"))
SEED = int(os.environ.get("V2_SEED", "9057"))

fc_args["debug.take_screenshot"] = True
fc_args["debug.headless"] = True
fc_args["debug.global_view_screenshot"] = True
fc_args["client_port"] = PORT

env = gymnasium.make("civrealm/FreecivBase-v0")
obs, info = env.reset(client_port=PORT, seed=SEED)
print("reset ok; turn:", (info or {}).get("turn"))

base = getattr(env, "unwrapped", env)
ctrl = getattr(base, "civ_controller", None)
print("civ_controller:", type(ctrl).__name__ if ctrl is not None else None)

driver = None
for i in range(40):
    time.sleep(2)
    mon = getattr(ctrl, "monitor", None) if ctrl is not None else None
    d = getattr(mon, "_driver", None) if mon is not None else None
    state = getattr(mon, "state", None) if mon is not None else None
    if d is not None:
        driver = d
        print(f"  t={2 * (i + 1)}s: драйвер есть, состояние наблюдения={state}")
        if state == "view_game":
            break
    else:
        print(f"  t={2 * (i + 1)}s: драйвера нет (monitor={mon is not None})")

if driver is None:
    print("ДРАЙВЕР НЕ ПОЛУЧЕН — съёмка обзора невозможна")
else:
    js = """
    var ids = ['overview_map','overview_panel','overview_dialog','map_tab','mapview_canvas_div',
               'game_chatbox_panel','messages_panel','city_dialog','tech_dialog'];
    var out = {};
    ids.forEach(function(id){var e=document.getElementById(id);
      out[id] = e ? {w: e.offsetWidth, h: e.offsetHeight,
                     vis: (e.offsetParent!==null || e.style.display!=='none')} : null;});
    return out;
    """
    print("элементы клиента:", driver.execute_script(js))
    try:
        el = driver.find_element("id", "overview_map")
        print("overview_map найден:", el.size)
        el.screenshot(str(ROOT / "knowledge" / "ov_test.png"))
        print("снимок обзора сохранён: knowledge/ov_test.png")
    except Exception as exc:  # noqa: BLE001
        print("overview_map не снят:", type(exc).__name__, str(exc)[:200])
    print("заголовок страницы:", driver.title[:80])

try:
    env.close()
except Exception:  # noqa: BLE001
    pass