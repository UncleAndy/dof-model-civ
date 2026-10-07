"""Подключить вызов записи открытий и передать свой player id оснастке.

Два дефекта, найденных по отчёту предыдущего скрипта:
1. вызов `_record_reveals` НЕ встал (якорь `_LAST_TURN = turn` не совпал) — инструмент был бы немым:
   файлы «что открылось» не появились бы вовсе;
2. `_own_city_count` брал id из переменной окружения с догадкой по умолчанию 0 — при другом id
   `settler-first` считал бы чужие города своими. Теперь id кладёт сам прогон, из уже прочитанного
   `own_id`, а не из догадки.
"""
from pathlib import Path

RUN = Path("/home/hermes/projects/AI/DOF-MODEL-CIV/scripts/v011_live_run.py")
text = RUN.read_text(encoding="utf-8")
done: list[str] = []

# 1. Вызов записи: ищем место там, где ход уже известен (_DRIVER.new_turn() или строка с _LAST_TURN).
if "_record_reveals(obs, turn" not in text:
    cand = [i for i, l in enumerate(text.split("\n")) if "_LAST_TURN = turn" in l or "_DRIVER.new_turn()" in l]
    lines = text.split("\n")
    if not cand:
        raise SystemExit("место для вызова записи не найдено — правка не применена")
    i = cand[0]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    call = f"{indent}_record_reveals(obs, (info or {{}}).get(\"turn\"), V.RUN_TAG)"
    if "_LAST_TURN = turn" in lines[i]:
        lines.insert(i + 1, call)
    else:
        lines.insert(i, call)
    text = "\n".join(lines)
    done.append("вызов записи открытий подключён")

# 2. Свой id — из прогона, а не из догадки.
if 'os.environ["V011_OWN_ID"]' not in text:
    anchor = """    extractor = GameStateExtractor(my_player_id=own_id)"""
    if anchor in text:
        text = text.replace(anchor, """    os.environ["V011_OWN_ID"] = str(own_id)  # оснастка берёт id отсюда, а не угадывает
""" + anchor, 1)
        done.append("own_id передаётся оснастке")
    else:
        print("якорь для own_id не найден — id остаётся из догадки, сообщаю как есть")

RUN.write_text(text, encoding="utf-8")
print("правки:", "; ".join(done) or "нечего делать")

import py_compile  # noqa: E402
py_compile.compile(str(RUN), doraise=True)
print("компиляция: ок")
for i, l in enumerate(RUN.read_text(encoding="utf-8").split("\n"), 1):
    if "_record_reveals(obs" in l or "V011_OWN_ID" in l:
        print(f"{i:>4}|{l}")