"""Debug: why does the synthetic sample observation give a negative index?

Extracts the `sample_observation` fixture straight from the test source (so the
two cannot drift) and prints the option count of every extracted entity.
"""
import ast
import math
import pathlib
import sys

from env.entity_extractor import GameStateExtractor, compute_total_dof_index

src = pathlib.Path('tests/unit/test_entity_extractor.py').read_text()
tree = ast.parse(src)
obs = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'sample_observation':
        for stmt in node.body:
            if isinstance(stmt, ast.Return):
                obs = ast.literal_eval(stmt.value)
assert obs is not None, 'sample_observation fixture not found'

extractor = GameStateExtractor(my_player_id=0)
result = extractor.extract(obs, {}, turn=10)
state = result.state
print(f'entities={len(state.entities)} index={compute_total_dof_index(state):.4f} '
      f'sink={state.dof_sink:.4f}')
for eid, ent in sorted(state.entities.items()):
    print(f'  {eid:<16} options={ent.dof_count:9.4f}  ln={math.log(max(ent.dof_count, 1e-6)):8.4f}'
          f'  current_dof={ent.current_dof:.4f}  ceiling={ent.dof_ceiling}')
bridge = state.bridge
print('bridge: new_city=%s improv_gain=%s unit_types=%d tech_gains=%d'
      % (bridge.new_city_options, bridge.improvement_gain,
         len(bridge.unit_type_options), len(bridge.tech_research_gain)))
sys.exit(0)
