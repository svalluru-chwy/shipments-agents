"""
Skill Loader - Progressive loading of skill metadata and executors.

Implements three-level progressive loading:
- Level 1: Metadata only (name + description) - always loaded for catalog/API
- Level 2: Full SKILL.md content - loaded when skill details are requested
- Level 3: Execute function - loaded when skill needs to run

Adapted from cat-agents skills/loader.py for the standalone shipments platform.
"""

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from packages.shared.logging import get_logger

logger = get_logger(__name__)

# Base path for skills folder
SKILLS_DIR = Path(__file__).parent


def _parse_skill_frontmatter(skill_path: Path) -> Dict[str, Any]:
    """
    Parse YAML frontmatter from SKILL.md file.

    Args:
        skill_path: Path to skill folder

    Returns:
        Dict with 'name', 'description', 'domain', and 'enhances' keys
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return {
            "name": skill_path.name,
            "description": "No description available",
            "domain": "general",
        }

    with open(skill_md, "r") as f:
        content = f.read()

    # Parse YAML frontmatter (between --- markers)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1])
                return {
                    "name": frontmatter.get("name", skill_path.name),
                    "description": frontmatter.get("description", "No description available"),
                    "domain": frontmatter.get("domain", "general"),
                    "skill_type": frontmatter.get("skill_type", "enhancement"),
                    "enhances": frontmatter.get("enhances", []),
                }
            except yaml.YAMLError:
                pass

    return {
        "name": skill_path.name,
        "description": "No description available",
        "domain": "general",
    }


def get_skill_catalog() -> Dict[str, Dict[str, Any]]:
    """
    Level 1: Get catalog of all available skills with metadata only.

    Returns:
        Dict mapping skill_name -> {"name": str, "description": str, "domain": str, ...}
    """
    catalog = {}

    for item in SKILLS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("_") and not item.name.startswith("."):
            skill_md = item / "SKILL.md"
            if skill_md.exists():
                metadata = _parse_skill_frontmatter(item)
                catalog[item.name] = metadata

    return catalog


def get_skills_by_domain(domain: str) -> Dict[str, Dict[str, Any]]:
    """
    Get skills filtered by domain.

    Args:
        domain: Domain to filter by (e.g., 'shipments')

    Returns:
        Filtered skill catalog
    """
    catalog = get_skill_catalog()
    return {name: meta for name, meta in catalog.items() if meta.get("domain") == domain or meta.get("domain") == "general"}


def load_skill(skill_name: str) -> Optional[str]:
    """
    Level 2: Load full SKILL.md content for a specific skill.

    Args:
        skill_name: Name of the skill folder

    Returns:
        Full SKILL.md content as string, or None if not found
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"

    if not skill_path.exists():
        return None

    with open(skill_path, "r") as f:
        return f.read()


def load_skill_reference(skill_name: str, reference_name: str) -> Optional[str]:
    """
    Load a reference document from a skill's references folder.

    Args:
        skill_name: Name of the skill folder
        reference_name: Name of the reference file (e.g., "data_dictionary.md")

    Returns:
        Reference content as string, or None if not found
    """
    ref_path = SKILLS_DIR / skill_name / "references" / reference_name

    if not ref_path.exists():
        return None

    with open(ref_path, "r") as f:
        return f.read()


def load_shared_context() -> Optional[str]:
    """
    Load the shared CONTEXT.md file that provides workflow context for all skills.

    Returns:
        CONTEXT.md content as string, or None if not found
    """
    context_path = SKILLS_DIR / "CONTEXT.md"

    if not context_path.exists():
        return None

    with open(context_path, "r") as f:
        return f.read()


def get_skill_executor(skill_name: str) -> Optional[Callable]:
    """
    Level 3: Get the execute function for a specific skill.

    Dynamically imports the skill's execute.py module and returns
    the execute function.

    Args:
        skill_name: Name of the skill folder

    Returns:
        The execute function from the skill's execute.py, or None if not found
    """
    try:
        module = importlib.import_module(f"packages.agents.shipments.skills.{skill_name}.execute")

        if hasattr(module, "execute"):
            return module.execute
        else:
            logger.warning(f"Skill {skill_name} has no execute function")
            return None

    except ImportError as e:
        logger.warning(f"Could not import skill {skill_name}: {e}")
        return None


def get_available_skills() -> List[str]:
    """
    Get list of available skill names (those with both SKILL.md and execute.py).

    Returns:
        List of skill folder names
    """
    skills = []
    for item in SKILLS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("_") and not item.name.startswith("."):
            skill_md = item / "SKILL.md"
            execute_py = item / "execute.py"
            if skill_md.exists() and execute_py.exists():
                skills.append(item.name)
    return sorted(skills)


def validate_skill(skill_name: str) -> Dict[str, bool]:
    """
    Validate that a skill has all required components.

    Args:
        skill_name: Name of the skill to validate

    Returns:
        Dict with validation results
    """
    skill_path = SKILLS_DIR / skill_name

    return {
        "exists": skill_path.exists(),
        "has_skill_md": (skill_path / "SKILL.md").exists(),
        "has_execute_py": (skill_path / "execute.py").exists(),
        "has_references": (skill_path / "references").exists(),
        "has_data_dictionary": (skill_path / "references" / "data_dictionary.md").exists(),
    }


def load_skill_instructions(skill_name: str) -> str:
    """
    Load the full SKILL.md content with shared context prepended.

    Args:
        skill_name: Name of the skill

    Returns:
        Complete instruction string
    """
    context = load_shared_context() or ""
    skill_md = load_skill(skill_name) or ""

    return f"{context}\n\n{skill_md}"


def load_reference_docs(skill_name: str) -> str:
    """
    Load all reference documents for a skill.

    Args:
        skill_name: Name of the skill

    Returns:
        Combined reference documentation string
    """
    references = []

    data_dict = load_skill_reference(skill_name, "data_dictionary.md")
    if data_dict:
        references.append(f"## Data Dictionary\n\n{data_dict}")

    ref_path = SKILLS_DIR / skill_name / "references"
    if ref_path.exists():
        for ref_file in ref_path.iterdir():
            if ref_file.name != "data_dictionary.md" and ref_file.suffix == ".md":
                with open(ref_file, "r") as f:
                    content = f.read()
                references.append(f"## {ref_file.stem.replace('_', ' ').title()}\n\n{content}")

    return "\n\n---\n\n".join(references)
