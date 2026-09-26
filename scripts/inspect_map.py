"""Determine the map array indexing and read the settler's tile yields."""
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')

import gymnasium
from civrealm.configs import fc_args
from civrealm.freeciv.utils.port_utils import Ports

fc_args['port'] = Ports.get()
env = gymnasium.make('civrealm/FreecivBase-v0', client_port=fc_args['port'])
obs, info = env.reset()
mp = obs['map']
print('shapes:', {k: getattr(v, 'shape', None) for k, v in mp.items()})
print('my_player_id =', env.get_playerid())
units = obs.get('unit') or {}
for uid, u in list(units.items())[:3]:
    x, y = int(u.get('x')), int(u.get('y'))
    print(f'\nunit {uid} {u.get("type_rule_name")} at (x={x},y={y})')
    for label, i, j in (('[y][x]', y, x), ('[x][y]', x, y)):
        print(f'  {label}: unit={mp["unit"][i][j]} unit_owner={mp["unit_owner"][i][j]} '
              f'terrain={mp["terrain"][i][j]} output={mp["output"][i][j]}')
print('\nunits flagged in map["unit"]:', [tuple(p) for p in
      __import__('numpy').argwhere(mp['unit'] > 0)[:10]])
print('owned tiles flagged in map["unit_owner"]:',
      [tuple(p) for p in __import__('numpy').argwhere(mp['unit_owner'] != 255)[:10]])
env.close()
