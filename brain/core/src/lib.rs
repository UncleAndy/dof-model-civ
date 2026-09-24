//! DOF-Core — Rust calculus core (PyO3) for 4X strategy game.
//!
//! Universal decision engine that works with any entity types:
//! cities, units, technologies, diplomacy — anything with a DoF value.
//!
//! Implements the DOF-Core spec mathematics:
//! - TotalDoF_index(S) = Σ ln(max(DoF(e), ε))  over non-aggressor entities
//! - NetDelta = leaf_index − root_index − ΔT
//! - Axiom 3 (Non-Compensation): collapse penalty for irreversible destruction
//! - Axiom 5 (Uncertainty): DoF floored at ε inside logarithm
//!
//! The core performs a recursive lookahead tree-search over candidate actions,
//! scoring leaves with the Nash log-product index, and returns the action
//! that maximizes total future DoF.

use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Smallest DoF value (entity at collapse)
const EPSILON: f64 = 1e-6;
/// Axiom-3 veto penalty for irreversible collapse
const COLLAPSE_PENALTY: f64 = 1.0e6;

// ---------------------------------------------------------------------------
// PyO3 data model
// ---------------------------------------------------------------------------

/// Per-entity state for decision-making.
#[pyclass]
#[derive(Clone, Debug)]
pub struct CoreEntity {
    #[pyo3(get, set)]
    pub entity_id: String,
    #[pyo3(get, set)]
    pub current_dof: f64,
    #[pyo3(get, set)]
    pub is_collapse_source: bool,
    #[pyo3(get, set)]
    pub is_reversible: bool,  // false = cannot be revived once collapsed
}

#[pymethods]
impl CoreEntity {
    #[new]
    #[pyo3(signature = (entity_id, current_dof, is_collapse_source=false, is_reversible=true))]
    fn new(entity_id: String, current_dof: f64, is_collapse_source: bool, is_reversible: bool) -> Self {
        Self { entity_id, current_dof, is_collapse_source, is_reversible }
    }
}

/// One candidate action with projected DoF deltas.
#[pyclass]
#[derive(Clone, Debug)]
pub struct CoreAction {
    #[pyo3(get, set)]
    pub action_id: String,
    #[pyo3(get, set)]
    pub description: String,
    /// entity_id -> projected DoF change
    #[pyo3(get, set)]
    pub dof_delta: Vec<(String, f64)>,
    #[pyo3(get, set)]
    pub is_reversible: bool,
    #[pyo3(get, set)]
    pub duration_turns: f64,
}

#[pymethods]
impl CoreAction {
    #[new]
    #[pyo3(signature = (action_id, description, dof_delta=vec![], is_reversible=true, duration_turns=1.0))]
    fn new(action_id: String, description: String, dof_delta: Vec<(String, f64)>, is_reversible: bool, duration_turns: f64) -> Self {
        Self { action_id, description, dof_delta, is_reversible, duration_turns }
    }
}

/// Result of a decision cycle.
#[pyclass]
#[derive(Clone, Debug)]
pub struct CoreDecision {
    #[pyo3(get)]
    pub chosen_action_id: Option<String>,
    #[pyo3(get)]
    pub net_delta: f64,
    #[pyo3(get)]
    pub root_index: f64,
    #[pyo3(get)]
    pub leaf_index: f64,
    /// (action_id, net_delta, vetoed)
    #[pyo3(get)]
    pub audit: Vec<(String, f64, bool)>,
}

// ---------------------------------------------------------------------------
// Internal simulation
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct Entity {
    id: String,
    dof: f64,
    root_dof: f64,
    collapse_source: bool,
    reversible: bool,
}

impl Entity {
    fn from_core(e: &CoreEntity) -> Self {
        Self {
            id: e.entity_id.clone(),
            dof: e.current_dof,
            root_dof: e.current_dof,
            collapse_source: e.is_collapse_source,
            reversible: e.is_reversible,
        }
    }
}

/// Nash log-product index: Σ ln(max(DoF, ε)) over non-collapse-source entities
fn total_dof_index(entities: &[Entity]) -> f64 {
    entities.iter()
        .filter(|e| !e.collapse_source)
        .map(|e| e.dof.max(EPSILON).ln())
        .sum()
}

/// Apply a candidate action's projected DoF deltas to a state.
fn apply_action(entities: &mut [Entity], action: &CoreAction) {
    for (entity_id, delta) in &action.dof_delta {
        if let Some(e) = entities.iter_mut().find(|e| &e.id == entity_id) {
            e.dof = (e.dof + *delta).max(EPSILON).min(1.0);
        }
    }
}

/// Recursive lookahead: returns the best net delta achievable from this state.
fn lookahead(
    entities: &mut [Entity],
    candidates: &[CoreAction],
    horizon: u32,
    context_switch_penalty: f64,
) -> f64 {
    if horizon == 0 {
        return 0.0;
    }

    let mut best_delta: f64 = 0.0;

    for action in candidates {
        let mut branch_entities: Vec<Entity> = entities.to_vec();
        apply_action(&mut branch_entities, action);

        let branch_index = total_dof_index(&branch_entities);

        // Axiom 3 veto: if a reversible entity was pushed to collapse
        let mut vetoed = false;
        for (orig, branch) in entities.iter().zip(branch_entities.iter()) {
            if orig.reversible && !orig.collapse_source && branch.dof <= EPSILON && orig.root_dof > EPSILON {
                vetoed = true;
                break;
            }
        }

        let sub_delta = if horizon > 1 {
            lookahead(&mut branch_entities, candidates, horizon - 1, context_switch_penalty)
        } else {
            0.0
        };

        let delta = branch_index - total_dof_index(entities) + sub_delta
            - if action.is_reversible { 0.0 } else { context_switch_penalty };

        let final_delta = if vetoed { delta - COLLAPSE_PENALTY } else { delta };
        best_delta = best_delta.max(final_delta);
    }

    best_delta
}

// ---------------------------------------------------------------------------
// PyO3 module
// ---------------------------------------------------------------------------

/// DOFCalculusCore — the main decision engine exposed to Python.
#[pyclass]
pub struct DOFCalculusCore {
    #[pyo3(get, set)]
    lookahead_horizon: u32,
    #[pyo3(get, set)]
    context_switch_penalty: f64,
}

#[pymethods]
impl DOFCalculusCore {
    #[new]
    #[pyo3(signature = (lookahead_horizon=3, context_switch_penalty=0.5))]
    fn new(lookahead_horizon: u32, context_switch_penalty: f64) -> Self {
        Self { lookahead_horizon, context_switch_penalty }
    }

    /// Select the best action from candidates given the current state.
    fn select_best(
        &self,
        state: Vec<CoreEntity>,
        candidates: Vec<CoreAction>,
    ) -> PyResult<CoreDecision> {
        if candidates.is_empty() {
            return Ok(CoreDecision {
                chosen_action_id: None,
                net_delta: 0.0,
                root_index: 0.0,
                leaf_index: 0.0,
                audit: vec![],
            });
        }

        let entities: Vec<Entity> = state.iter().map(Entity::from_core).collect();
        let root_index = total_dof_index(&entities);

        let mut best_idx = None;
        let mut best_net_delta = f64::NEG_INFINITY;
        let mut audit: Vec<(String, f64, bool)> = Vec::with_capacity(candidates.len());

        for (i, action) in candidates.iter().enumerate() {
            let mut branch_entities = entities.clone();
            apply_action(&mut branch_entities, action);

            let branch_index = total_dof_index(&branch_entities);

            // Axiom 3 veto check
            let mut vetoed = false;
            for (orig, branch) in entities.iter().zip(branch_entities.iter()) {
                if orig.reversible && !orig.collapse_source && branch.dof <= EPSILON && orig.root_dof > EPSILON {
                    vetoed = true;
                    break;
                }
            }

            let lookahead_delta = if self.lookahead_horizon > 1 {
                lookahead(&mut branch_entities, &candidates, self.lookahead_horizon - 1, self.context_switch_penalty)
            } else {
                0.0
            };

            let net_delta = branch_index - root_index + lookahead_delta
                - if action.is_reversible { 0.0 } else { self.context_switch_penalty };

            let final_delta = if vetoed { net_delta - COLLAPSE_PENALTY } else { net_delta };

            audit.push((action.action_id.clone(), final_delta, vetoed));

            if final_delta > best_net_delta {
                best_net_delta = final_delta;
                best_idx = Some(i);
            }
        }

        // If all actions are vetoed or negative, stay put (return None)
        if best_net_delta < 0.0 {
            return Ok(CoreDecision {
                chosen_action_id: None,
                net_delta: best_net_delta,
                root_index,
                leaf_index: root_index,
                audit,
            });
        }

        let chosen = &candidates[best_idx.unwrap()];
        let mut final_entities = entities.clone();
        apply_action(&mut final_entities, chosen);
        let leaf_index = total_dof_index(&final_entities);

        Ok(CoreDecision {
            chosen_action_id: Some(chosen.action_id.clone()),
            net_delta: best_net_delta,
            root_index,
            leaf_index,
            audit,
        })
    }

    /// Compute the Nash log-product index for a state.
    fn compute_index(&self, state: Vec<CoreEntity>) -> f64 {
        let entities: Vec<Entity> = state.iter().map(Entity::from_core).collect();
        total_dof_index(&entities)
    }
}

/// Python module definition.
#[pymodule]
fn dof_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CoreEntity>()?;
    m.add_class::<CoreAction>()?;
    m.add_class::<CoreDecision>()?;
    m.add_class::<DOFCalculusCore>()?;
    Ok(())
}
