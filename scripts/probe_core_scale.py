"""Offline check of the Rust core's constants against option-scale DoF.

DOFCalculusCore carries absolute constants (the 1.0 clamp in `apply_action`, the
COLLAPSE_PENALTY added on a veto), so it has to be fed values whose scale matches
those constants. This prints what the core does for a few scales.
"""
import sys

from dof_core import CoreAction, CoreEntity, DOFCalculusCore


def probe(scale: float, penalty: float, lookahead: int) -> None:
    ents = [
        CoreEntity(entity_id='city_1', current_dof=8.14 * scale, is_reversible=False),
        CoreEntity(entity_id='unit_113', current_dof=3.81 * scale),
        CoreEntity(entity_id='tech_2', current_dof=1.0 * scale),
    ]
    acts = [
        CoreAction(action_id='produce_Bomber', description='',
                   dof_delta=[('city_1', 6.54 * scale)], is_reversible=False),
        CoreAction(action_id='research_tech_X', description='',
                   dof_delta=[('tech_2', 2.07 * scale)], is_reversible=False),
        CoreAction(action_id='fortify', description='',
                   dof_delta=[('unit_113', 0.0)], is_reversible=True),
    ]
    core = DOFCalculusCore(lookahead_horizon=lookahead, context_switch_penalty=penalty)
    d = core.select_best(ents, acts)
    print(f'scale={scale:<8} penalty={penalty:<8} horizon={lookahead} '
          f'root={d.root_index:9.4f} chosen={d.chosen_action_id} net={d.net_delta:+.4f}')
    for aid, net, vetoed in d.audit:
        print(f'      {net:+.4f} vetoed={vetoed} {aid}')


if __name__ == '__main__':
    print('--- option scale (what the extractor now produces)')
    probe(1.0, 0.5, 1)
    probe(1.0, 0.5, 3)
    print('--- normalised scale (what the core was calibrated for)')
    probe(1.0 / 20.0, 0.025, 3)
    sys.exit(0)
