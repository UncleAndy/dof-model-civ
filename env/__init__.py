"""DOF-MODEL-CIV bridge: game state ↔ DOF SystemStateMatrix."""

from .entity_extractor import GameStateExtractor, ExtractionResult, compute_total_dof_index
from .config import CONFIG, MappingConfig

__all__ = [
    'GameStateExtractor',
    'ExtractionResult',
    'compute_total_dof_index',
    'CONFIG',
    'MappingConfig',
]
