"""Что мир реально отдаёт про город: смотрю по фикстуре, а не по памяти.

Нужно, чтобы выбрать поля для метрики КАЧЕСТВА города (метрика мест, а не
состава): только те поля, которые мир действительно публикует, и только те,
что различают города между собой.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env.entity_extractor import as_dict  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else 'tests/fixtures/real_obs_01.json'
    payload = json.load(open(path))
    # Фикстура может быть списком записей наблюдений — беру последнюю, она полнее.
    if isinstance(payload, list):
        print(f'фикстура: список из {len(payload)} записей, беру последнюю')
        payload = payload[-1]
    obs = payload.get('observation', payload.get('obs', payload)) \
        if isinstance(payload, dict) else payload
    layer = as_dict(obs)
    print('ключи наблюдения:', list(layer)[:24])
    for key in ('city', 'unit'):
        records = as_dict(obs.get(key)) or {}
        print(f'\n=== {key}: записей {len(records)}')
        if not records:
            continue
        first = records[list(records)[0]]
        for field in sorted(first):
            value = first[field]
            if isinstance(value, (int, float, bool, str)) or value is None:
                print(f'    {field} = {value!r}')
            else:
                print(f'    {field} = <{type(value).__name__}>')
        # Какие поля РАЗЛИЧАЮТ записи — именно они годятся для метрики.
        if len(records) > 1:
            varying = [f for f in sorted(first)
                       if len({repr(as_dict(r).get(f)) for r in records.values()}) > 1]
            print('    различают записи:', varying)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
