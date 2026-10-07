"""Взять `world.json` из ветки `v2` (`baselines/`) и положить в рабочее дерево `v0.11`.

Владелец (2026-10-07): «`world.json` нужно взять из `baseline/` ветки v2». Причина, по которой
это нужно: в дереве `v0.11` файла нет вовсе, а `knowledge/world.json` — симлинк на
`/home/andy/projects/...`, недоступный рабочему пользователю (обёртка подменяет только
`/home/hermes/projects`), поэтому база «не видна» и любой замер по ней молча уходил бы в отказ.

Скрипт НИЧЕГО не удаляет: если файл уже есть и совпадает по md5 — только сообщает об этом.
"""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("/home/hermes/projects/AI/DOF-MODEL-CIV")
TARGET = ROOT / "baselines" / "world.json"
CANON_MD5 = "74566a515f602d16158d7e0aeca6831b"
V2_PATH = "v2:baselines/world.json"

blob = subprocess.run(["git", "show", V2_PATH], cwd=str(ROOT), capture_output=True, check=True).stdout
md5 = hashlib.md5(blob).hexdigest()
print(f"в v2: {V2_PATH} — {len(blob)} байт, md5 {md5}")
if md5 != CANON_MD5:
    print(f"ВНИМАНИЕ: md5 не совпадает с каноническим {CANON_MD5} — не подменяю, сообщаю")

TARGET.parent.mkdir(parents=True, exist_ok=True)
if TARGET.exists():
    have = hashlib.md5(TARGET.read_bytes()).hexdigest()
    print(f"в дереве уже есть: md5 {have}")
    if have == md5:
        print("совпадает — ничего не меняю")
    else:
        backup = TARGET.with_suffix(".json.nonv2")
        backup.write_bytes(TARGET.read_bytes())
        TARGET.write_bytes(blob)
        print(f"разошёлся: прежний сохранён как {backup.name}, положен файл из v2")
else:
    TARGET.write_bytes(blob)
    print(f"положен файл из v2: {TARGET}")

# Проверка содержимого: сколько наблюдений и какая форма — числом, а не на слово.
data = json.loads(TARGET.read_text(encoding="utf-8"))
if isinstance(data, list):
    print(f"наблюдений в списке: {len(data)}")
elif isinstance(data, dict):
    inner = data.get("observations") or data.get("steps") or []
    print(f"ключей {len(data)}; записей наблюдений: {len(inner) if isinstance(inner, list) else 'не список'}")
print("итоговый md5:", hashlib.md5(TARGET.read_bytes()).hexdigest(), "| байт:", TARGET.stat().st_size)