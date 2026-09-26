"""One-off, auditable rewiring of the extractor onto the world model.

Renames happen ONLY inside the four formula functions (the bodies are located by
`def ...` boundaries), so class methods and the legacy score fallback keep their
config constants. Every replacement asserts a unique match; the script either
applies all of them or fails loudly and prints every change it made.
"""
import pathlib
import sys

PATH = pathlib.Path('env/entity_extractor.py')
src = PATH.read_text()
changes: list[str] = []


def sub(old: str, new: str, count: int = 1) -> None:
    global src
    found = src.count(old)
    if found != count:
        print(f'FAIL: {old[:70]!r} matched {found}x, expected {count}')
        sys.exit(1)
    src = src.replace(old, new)
    changes.append(f'{old.strip()[:58]}  ->  {new.strip()[:58]}')


# ── 1. Imports ──────────────────────────────────────────────────────────────
OLD_IMPORT_START = "from .config import (\n    CONFIG,\n    EPSILON,"
END_OF_IMPORT = "    DiplomacyWeights,\n)"
start = src.index(OLD_IMPORT_START)
end = src.index(END_OF_IMPORT, start) + len(END_OF_IMPORT)
NEW_IMPORT = """from .config import (
    CONFIG,
    EPSILON,
    TURN_DURATION_MKS,
    MAX_TURNS,
    DOF_SCALE,        # mirrors world_model['DOF_SCALE']: used for the score field
    CITY_CEIL,        # mirrors world_model['CITY_CEIL']
    TECH_BASE_OPTIONS,
    POPULATION_UNIT_TYPES,
    UNIT_TYPICAL_MAX_HP,
    HEALTH_PERCENT_THRESHOLD,
    UNIT_MAX_HP_BY_TYPE,
    HEALTH_COLLAPSE_RATIO,
    TECH_DOF_REF,
    DiplomacyWeights,
)
from .world_model import Provenance, WorldModel, default_model"""
src = src[:start] + NEW_IMPORT + src[end:]
changes.append('import block trimmed; WorldModel imported')

# ── 2. Signatures + value snapshot inside the formula functions ─────────────
sub("def unit_options(unit_obs: dict[str, Any], age: int = 0) -> tuple[float, float, float]:",
    "def unit_options(unit_obs: dict[str, Any], age: int = 0,\n"
    "                 model: Optional[WorldModel] = None) -> tuple[float, float, float]:")
sub("def improvement_options(spec: dict[str, Any]) -> float:",
    "def improvement_options(spec: dict[str, Any],\n"
    "                        model: Optional[WorldModel] = None) -> float:")
sub("def city_options(city_obs: dict[str, Any], garrison: int = 0) -> float:",
    "def city_options(city_obs: dict[str, Any], garrison: int = 0,\n"
    "                 model: Optional[WorldModel] = None) -> float:")
sub("def tech_options(tech_obs: dict[str, Any], as_known: bool = False) -> float:",
    "def tech_options(tech_obs: dict[str, Any], as_known: bool = False,\n"
    "                 model: Optional[WorldModel] = None) -> float:")
sub('''    ``POP_CARRIER_COUNTS_HEALTH_IN_CURRENT``).
    """
    carrier = is_population_carrier(unit_obs)''',
    '''    ``POP_CARRIER_COUNTS_HEALTH_IN_CURRENT``).
    """
    vals = (model or default_model()).values()
    carrier = is_population_carrier(unit_obs)''')
sub('''    """DoF of a city in options — the approved three-multiplier scheme (§8)."""
    size = num(city_obs.get('size', city_obs.get('population', 1)), 1)''',
    '''    """DoF of a city in options — the approved three-multiplier scheme (§8)."""
    vals = (model or default_model()).values()
    size = num(city_obs.get('size', city_obs.get('population', 1)), 1)''')
sub('''    researching it.
    """
    options = TECH_BASE_OPTIONS''',
    '''    researching it.
    """
    vals = (model or default_model()).values()
    options = vals['TECH_BASE_OPTIONS']''')
sub("    return TECH_IMPROVEMENT_OPTIONS",
    "    vals = (model or default_model()).values()\n"
    "    # One improvement is worth the weight it carries inside the city's first\n"
    "    # factor, so the two can never drift apart.\n"
    "    return 1.0 + vals['CITY_M1_IMPROV']")


# ── 3. Renames, bounded to the four formula bodies ──────────────────────────
BOUNDS = {
    'unit_options': 'def improvement_options(',
    'improvement_options': 'def city_options(',
    'city_options': 'def tech_options(',
    'tech_options': '@dataclass\nclass ExtractionResult',
}

MODEL_KEYS = (
    'DOF_SCALE', 'CITY_CEIL', 'TECH_BASE_OPTIONS',
    'UNIT_EXISTENCE_W', 'UNIT_HEALTH_W', 'UNIT_ATTACK_W', 'UNIT_ATTACK_REF',
    'UNIT_DEFENSE_W', 'UNIT_DEFENSE_REF', 'UNIT_FIREPOWER_W', 'UNIT_FIREPOWER_REF',
    'UNIT_MOVE_W', 'UNIT_MOVE_REF', 'UNIT_VISION_W', 'UNIT_VISION_REF',
    'UNIT_VETERAN_W', 'UNIT_VETERAN_REF', 'UNIT_CURRENT_CAP',
    'UNIT_FUTURE_SETTLE_W', 'UNIT_FUTURE_WORKER_W', 'UNIT_FUTURE_CONVERT_W',
    'UNIT_FUTURE_TRANSPORT_W', 'W_FUTURE_UNIT', 'CARRIER_DECAY_PER_TURN',
    'CARRIER_DECAY_FLOOR', 'POP_CARRIER_COUNTS_HEALTH_IN_CURRENT',
    'CITY_BASE', 'CITY_POP', 'CITY_CAP_M1', 'CITY_CAP_M2', 'CITY_M1_FOOD',
    'CITY_M1_GRANARY', 'CITY_M1_IMPROV', 'CITY_M2_SHIELD', 'CITY_M2_TRADE',
    'CITY_M2_GOLD', 'CITY_M2_SCIENCE', 'CITY_M2_LUXURY', 'CITY_CORRUPTION_W',
    'CITY_HAPPY_W', 'CITY_UNHAPPY_W', 'CITY_ANGRY_W', 'GARRISON_W',
)

for fn, terminator in BOUNDS.items():
    i = src.index(f'def {fn}(')
    j = src.index(terminator, i)
    chunk = src[i:j]
    for key in MODEL_KEYS:
        hits = chunk.count(key)
        if hits:
            chunk = chunk.replace(key, f"vals['{key}']")
            changes.append(f'{fn}: {key} x{hits}')
    src = src[:i] + chunk + src[j:]

# ── 4. Call sites inside the extractor pass the agent's own model ───────────
sub("            options, _s_current, _s_future = unit_options(unit_obs, age=age)",
    "            options, _s_current, _s_future = unit_options(unit_obs, age=age,\n"
    "                                                          model=self.model)")
sub("            options = city_options(city_obs, garrison=garrison)",
    "            options = city_options(city_obs, garrison=garrison, model=self.model)")
sub("            options = tech_options(tech_obs)",
    "            options = tech_options(tech_obs, model=self.model)")
sub("        return UNIT_UPKEEP_SINK_W * total",
    "        return self.model.values()['UNIT_UPKEEP_SINK_W'] * total")
sub("                    unit_catalog[name] = unit_options(spec)[0]",
    "                    unit_catalog[name] = unit_options(spec, model=self.model)[0]")
sub("                    improvement_catalog[name] = improvement_options(spec)",
    "                    improvement_catalog[name] = improvement_options(spec,\n"
    "                                                                   model=self.model)")
sub("            best = max(best, city_options(probe, garrison=0))",
    "            best = max(best, city_options(probe, garrison=0, model=self.model))")
sub("            current = city_options(city_obs, garrison=garrison)",
    "            current = city_options(city_obs, garrison=garrison, model=self.model)")
sub("            gains[entity_id] = max(0.0, city_options(probe, garrison=garrison) - current)",
    "            gains[entity_id] = max(0.0, city_options(probe, garrison=garrison,\n"
    "                                                    model=self.model) - current)")
sub("            unlocked = tech_options(tech_obs, as_known=True) - TECH_BASE_OPTIONS",
    "            unlocked = (tech_options(tech_obs, as_known=True, model=self.model)\n"
    "                        - self.model.values()['TECH_BASE_OPTIONS'])")
sub("                turns = TECH_NOMINAL_TURNS",
    "                turns = self.model.values()['tech.nominal_turns']")
sub("            best = CITY_BASE + CITY_POP",
    "            best = (self.model.values()['CITY_BASE']\n"
    "                    + self.model.values()['CITY_POP'])")
# psi digest records the option counts, which the model owns
sub("                    'dof_options': f\"{ent.dof_count:.6f}\",",
    "                    'dof_options': f\"{ent.dof_count:.6f}\",")

PATH.write_text(src)
print(f'{len(changes)} changes applied')
for line in changes:
    print('  ' + line)
