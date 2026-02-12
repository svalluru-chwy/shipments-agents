"""
Skills routes for Shipments Gateway.

GET /skills - list all skills with metadata
GET /skills/{skill_name} - get skill SKILL.md content
POST /skills/{skill_name}/run - run a single skill for a customer_id
POST /skills/phase/{phase_number}/run - run all skills in a phase
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from packages.agents.shipments.skills.loader import get_skill_catalog, load_skill
from packages.agents.shipments.skills.runner import (
    SHIPMENTS_SKILL_PHASES,
    get_phase_skills,
    run_single_skill_with_state,
    run_skills_phased,
)

skills_router = APIRouter(prefix="/skills", tags=["skills"])


def _get_s3_client(request: Request):
    """Get S3Client from app state."""
    return getattr(request.app.state, "s3_client", None)


def _load_customer_data(s3_client, customer_id: str, base_path: str) -> Dict[str, Any]:
    """
    Load all customer shipment data from S3 and construct state dict for skills.

    Mirrors the state construction in ShipmentSignalsAgent.
    """
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    def _load_json(folder: str) -> Optional[Dict[str, Any]]:
        key = s3_client.find_latest_customer_file(
            customer_id, f"data/{folder}", base_path=base_path, suffix=".json"
        )
        return s3_client.download_json(key) if key else None

    def _extract_records(data: Optional[Dict[str, Any]]) -> list:
        if not data:
            return []
        if isinstance(data, list):
            return data
        records = data.get("records") or data.get("data") or []
        return records if isinstance(records, list) else []

    main_shipment = _load_json("main_shipment_query")
    customer_contacts = _load_json("customer_contacts_query")
    customer_zip = _load_json("customer_zip_performance")
    benchmark_zip = _load_json("benchmark_zip_performance")
    shipment_inspector = _load_json("shipment_inspector_query")
    summary_stats = _load_json("order_shipment_summary_stats")

    records = _extract_records(main_shipment)
    shipment_data: Dict[str, Any] = {"records": records}

    if customer_zip:
        zp_data = customer_zip.get("data")
        shipment_data["customer_zip_performance"] = (
            zp_data[0] if isinstance(zp_data, list) and zp_data else customer_zip
        )
    if benchmark_zip:
        bm_data = benchmark_zip.get("data")
        shipment_data["benchmark_zip_performance"] = (
            bm_data[0] if isinstance(bm_data, list) and bm_data else benchmark_zip
        )

    inspector_records = _extract_records(shipment_inspector) if shipment_inspector else records

    state: Dict[str, Any] = {
        "customer_id": customer_id,
        "shipment_data": shipment_data,
        "shipment_inspector": {"data": inspector_records} if inspector_records else {},
        "customer_contacts": customer_contacts or {},
    }
    return state


def _load_prior_phase_results(s3_client, customer_id: str, base_path: str, phase: int) -> Dict[str, Any]:
    """
    Load prior phase results from S3 if available (signals output for phase 2+).
    """
    if phase < 2:
        return {}

    key = s3_client.find_latest_customer_file(
        customer_id,
        "shipment_agency_revised/signals",
        base_path=base_path,
        suffix=".json",
    )
    if not key:
        return {}

    try:
        data = s3_client.download_json(key)
        return data.get("skill_results", {})
    except Exception:
        return {}


@skills_router.get("")
async def list_skills(request: Request):
    """
    List all skills with metadata (name, description, domain, phase, skill_type).
    """
    catalog = get_skill_catalog()

    # Enrich with phase from runner
    from packages.agents.shipments.skills.runner import SKILL_PHASE_MAP

    skills_list = []
    for skill_name, meta in catalog.items():
        entry = {
            "skill_name": skill_name,
            "name": meta.get("name", skill_name),
            "description": meta.get("description", ""),
            "domain": meta.get("domain", "general"),
            "phase": SKILL_PHASE_MAP.get(skill_name, 0),
            "skill_type": meta.get("skill_type", "enhancement"),
        }
        skills_list.append(entry)

    return {"skills": skills_list, "count": len(skills_list)}


@skills_router.get("/{skill_name}")
async def get_skill_content(request: Request, skill_name: str):
    """Get the full SKILL.md content for a skill."""
    content = load_skill(skill_name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Skill {skill_name} not found")
    return {"skill_name": skill_name, "content": content}


@skills_router.post("/{skill_name}/run")
async def run_skill(
    request: Request,
    skill_name: str,
    customer_id: str = Body(..., embed=True),
):
    """
    Run a single skill for a customer.

    Loads customer data from S3, constructs state, runs the skill, returns result.
    """
    s3_client = _get_s3_client(request)
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    from packages.shared.config import get_settings
    settings = get_settings()
    base_path = settings.s3.base_path

    state = _load_customer_data(s3_client, customer_id, base_path)

    result = run_single_skill_with_state(skill_name, state)
    return result


@skills_router.post("/phase/{phase_number}/run")
async def run_phase(
    request: Request,
    phase_number: int,
    customer_id: str = Body(..., embed=True),
):
    """
    Run all skills in a phase for a customer.

    For phase 2+, also loads prior phase results from S3 if available.
    """
    s3_client = _get_s3_client(request)
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    from packages.shared.config import get_settings
    settings = get_settings()
    base_path = settings.s3.base_path

    state = _load_customer_data(s3_client, customer_id, base_path)

    # Load prior phase results for phase 2+
    prior_results = _load_prior_phase_results(s3_client, customer_id, base_path, phase_number)
    if prior_results:
        state["skill_results"] = prior_results
        for k, v in prior_results.items():
            state[k] = v

    result = run_skills_phased(state, phase_filter=[phase_number])
    return result
