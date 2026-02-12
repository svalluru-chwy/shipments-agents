"""
Skills Runner - Phased execution of shipment skills.

Runs skills in ordered phases per the SHIPMENTS_SKILL_PHASES definition.
Within each phase, skills run in parallel via ThreadPoolExecutor.
Between phases, results from earlier phases are injected into state
so dependent skills can access them.

Adapted from cat-agents src/nodes/skills_runner_node.py for standalone use.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from packages.shared.logging import get_logger

from .loader import get_skill_executor

logger = get_logger(__name__)

# =============================================================================
# Skill execution phases for shipments domain.
# Within each phase skills run in parallel. Phases run sequentially so that
# later phases can read results produced by earlier phases.
# =============================================================================

SHIPMENTS_SKILL_PHASES: List[List[str]] = [
    # Phase 1: Independent / base skills (12 skills)
    [
        "shipment_health_check",      # BASE - Customer CTD vs ZIP benchmark
        "delivery_performance",        # CTD analysis, trends, delayed shipments
        "carrier_analysis",           # Carrier performance breakdown
        "exception_analysis",         # Exception types and patterns
        "geographic_patterns",        # ZIP, FC, zone analysis
        "timing_patterns",            # Weekend/weekday, day of week, monthly
        "package_analysis",           # Weight, dimensions, multi-package
        "routing_efficiency",         # Arc distance, FC optimization
        "order_behavior",             # Autoship vs one-time, frequency
        "contact_correlation",        # Shipment-related contacts
        "current_order",              # Active orders, delay risk
        "shipment_signal_generator",  # Per-order signal detection
    ],
    # Phase 2: Depend on signal_generator, current_order (2 skills)
    [
        "shipment_delay_predictor",   # Predict future delays
        "shipment_signal_decoder",    # Root cause analysis (needs signal_generator)
    ],
    # Phase 3: Depend on delay_predictor, signal_decoder (2 skills)
    [
        "shipment_intervention",      # Intervention recommendations
        "shipment_action_prioritizer",  # Priority scoring
    ],
    # Phase 4: Consolidation - depends on all above (1 skill)
    [
        "shipment_consolidator",      # Executive summary
    ],
]

# Flat list of all shipment skill names
ALL_SHIPMENT_SKILLS: List[str] = [s for phase in SHIPMENTS_SKILL_PHASES for s in phase]

# Phase lookup: skill_name -> phase_number (1-indexed)
SKILL_PHASE_MAP: Dict[str, int] = {}
for _phase_idx, _phase_skills in enumerate(SHIPMENTS_SKILL_PHASES):
    for _skill in _phase_skills:
        SKILL_PHASE_MAP[_skill] = _phase_idx + 1


def run_skill(
    skill_name: str,
    state: Dict[str, Any],
    domain: str = "shipments",
    peer_level: str = "SEGMENT",
) -> Dict[str, Any]:
    """
    Run a single skill and return its result.

    Args:
        skill_name: Name of the skill to run.
        state: Current analysis state dict.
        domain: Domain identifier (default: "shipments").
        peer_level: Peer comparison level (default: "SEGMENT").

    Returns:
        Skill result dict with at minimum a "skill" key.
    """
    try:
        executor_fn = get_skill_executor(skill_name)
        if executor_fn is None:
            return {
                "skill": skill_name,
                "error": f"Could not load executor for {skill_name}",
                "grounded_metrics": {},
            }

        result = executor_fn(state, f"{domain}_result", peer_level)
        if result:
            result["skill"] = skill_name
            return result
        else:
            return {
                "skill": skill_name,
                "error": "No result returned",
                "grounded_metrics": {},
            }
    except Exception as e:
        logger.error(f"Skill {skill_name} failed: {e}")
        return {
            "skill": skill_name,
            "error": str(e),
            "grounded_metrics": {},
        }


def run_phase(
    skills: List[str],
    state: Dict[str, Any],
    domain: str = "shipments",
    peer_level: str = "SEGMENT",
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run a single phase of skills in parallel and return results.

    Args:
        skills: List of skill names to run in this phase.
        state: Current analysis state dict.
        domain: Domain identifier.
        peer_level: Peer comparison level.
        max_workers: Max parallel workers (defaults to min(len(skills), 12)).

    Returns:
        Dict with "skill_results" and "errors" keys.
    """
    results: Dict[str, Any] = {}
    errors: List[str] = []

    if not skills:
        return {"skill_results": results, "errors": errors}

    workers = max_workers or min(len(skills), 12)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_skill, skill, state, domain, peer_level): skill
            for skill in skills
        }

        for future in as_completed(futures):
            skill_name = futures[future]
            try:
                result = future.result()
                result_key = f"{skill_name}_result"
                results[result_key] = result

                if "error" in result and result.get("error"):
                    errors.append(f"{skill_name}: {result['error']}")
                    logger.warning(f"Skill {skill_name}: {result['error']}")
                else:
                    logger.info(f"Skill {skill_name} completed")

            except Exception as e:
                errors.append(f"{skill_name} failed: {e}")
                logger.error(f"Skill {skill_name} failed: {e}")
                results[f"{skill_name}_result"] = {
                    "skill": skill_name,
                    "error": str(e),
                    "grounded_metrics": {},
                }

    return {"skill_results": results, "errors": errors}


def run_skills_phased(
    state: Dict[str, Any],
    phases: Optional[List[List[str]]] = None,
    domain: str = "shipments",
    peer_level: str = "SEGMENT",
    max_workers: Optional[int] = None,
    phase_filter: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Run skills in ordered phases.

    Each phase runs its skills in parallel. Between phases, results from
    earlier phases are injected into the state so dependent skills can
    access them.

    Args:
        state: Current analysis state dict.
        phases: Phase definitions (defaults to SHIPMENTS_SKILL_PHASES).
        domain: Domain identifier.
        peer_level: Peer comparison level.
        max_workers: Max parallel workers per phase.
        phase_filter: Optional list of 1-indexed phase numbers to run.
                     If None, runs all phases.

    Returns:
        Dict with "skill_results" and "errors" keys.
    """
    if phases is None:
        phases = SHIPMENTS_SKILL_PHASES

    all_results: Dict[str, Any] = {}
    all_errors: List[str] = []

    # Build a mutable copy of state so we can augment it between phases.
    augmented_state: Dict[str, Any] = dict(state)

    for phase_idx, skills in enumerate(phases):
        phase_num = phase_idx + 1

        # Skip phases not in filter
        if phase_filter and phase_num not in phase_filter:
            continue

        if not skills:
            continue

        logger.info(f"Phase {phase_num}/{len(phases)}: {len(skills)} skills: {', '.join(skills)}")

        phase_result = run_phase(skills, augmented_state, domain, peer_level, max_workers)

        # Merge phase results into cumulative results
        all_results.update(phase_result["skill_results"])
        all_errors.extend(phase_result["errors"])

        # Inject cumulative results into augmented state so the next phase
        # can access them via state.get("skill_results") or direct key lookup
        augmented_state["skill_results"] = dict(all_results)
        for key, value in phase_result["skill_results"].items():
            augmented_state[key] = value

    return {"skill_results": all_results, "errors": all_errors}


def run_single_skill_with_state(
    skill_name: str,
    state: Dict[str, Any],
    domain: str = "shipments",
    peer_level: str = "SEGMENT",
) -> Dict[str, Any]:
    """
    Run a single skill with the given state. Used by the /skills/{name}/run API.

    Args:
        skill_name: Name of the skill to run.
        state: Pre-loaded state dict with customer data.
        domain: Domain identifier.
        peer_level: Peer comparison level.

    Returns:
        Skill result dict.
    """
    return run_skill(skill_name, state, domain, peer_level)


def get_phase_skills(phase_number: int) -> List[str]:
    """
    Get the list of skills in a specific phase.

    Args:
        phase_number: 1-indexed phase number.

    Returns:
        List of skill names, or empty list if phase doesn't exist.
    """
    if 1 <= phase_number <= len(SHIPMENTS_SKILL_PHASES):
        return SHIPMENTS_SKILL_PHASES[phase_number - 1]
    return []


def get_skill_phase(skill_name: str) -> int:
    """
    Get the phase number for a skill.

    Args:
        skill_name: Name of the skill.

    Returns:
        1-indexed phase number, or 0 if skill not found.
    """
    return SKILL_PHASE_MAP.get(skill_name, 0)
