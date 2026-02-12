"""
CAT Agent Shipment Skills.

Skills are self-contained analysis modules executed in phases.
Each skill follows the pattern:
- SKILL.md: Instructions with YAML frontmatter
- execute.py: Python execution logic
- references/: Supporting documentation and data dictionaries

Skills are organized into 4 phases:
  Phase 1: 12 independent/base skills (run in parallel)
  Phase 2: 2 skills dependent on Phase 1 (signal_generator, current_order)
  Phase 3: 2 skills dependent on Phase 2 (delay_predictor, signal_decoder)
  Phase 4: 1 consolidation skill (depends on all above)
"""

from .loader import (
    get_skill_catalog,
    get_skills_by_domain,
    load_skill,
    load_skill_reference,
    load_shared_context,
    get_skill_executor,
    get_available_skills,
    validate_skill,
    load_skill_instructions,
    load_reference_docs,
)

__all__ = [
    "get_skill_catalog",
    "get_skills_by_domain",
    "load_skill",
    "load_skill_reference",
    "load_shared_context",
    "get_skill_executor",
    "get_available_skills",
    "validate_skill",
    "load_skill_instructions",
    "load_reference_docs",
]
