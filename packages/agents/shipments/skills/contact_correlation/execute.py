"""
Contact Correlation Skill - Correlates contacts with shipment issues.
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]], contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline contact correlation metrics (deterministic)."""
    total_shipments = len(records)
    total_contacts = len(contacts)
    
    # Calculate contact rate
    contact_rate = round((total_contacts / total_shipments) * 100, 1) if total_shipments > 0 else 0
    
    # Analyze contact reasons
    wismo_contacts = 0
    shipment_contacts = 0
    
    for contact in contacts:
        reason = ((contact.get("CATEGORY_LEVEL_1") or "") + " " + (contact.get("CATEGORY_LEVEL_2") or "")).lower()
        if "where is my order" in reason or "wismo" in reason or "tracking" in reason:
            wismo_contacts += 1
        if "shipment" in reason or "delivery" in reason or "order" in reason:
            shipment_contacts += 1
    
    wismo_rate = round((wismo_contacts / total_contacts) * 100, 1) if total_contacts > 0 else 0
    
    # Primary contact reason
    reason_counts = {}
    for contact in contacts:
        reason = contact.get("CATEGORY_LEVEL_1", "Unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    primary_reason = max(reason_counts.items(), key=lambda x: x[1])[0] if reason_counts else "Unknown"
    
    return {
        "total_shipments": total_shipments,
        "total_contacts": total_contacts,
        "contact_rate": contact_rate,
        "wismo_contacts": wismo_contacts,
        "wismo_rate": wismo_rate,
        "shipment_related_contacts": shipment_contacts,
        "primary_reason": primary_reason,
        "reason_distribution": reason_counts
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    contacts = context.get("contacts", [])
    metrics = _compute_baseline_metrics(records, contacts)
    
    observations = [
        f"Contact rate: {metrics['contact_rate']}%",
        f"WISMO rate: {metrics['wismo_rate']}%"
    ]
    
    return {
        "skill": "contact_correlation",
        "observations": observations,
        "summary": {
            "contact_rate": metrics["contact_rate"],
            "wismo_rate": metrics["wismo_rate"],
            "primary_reason": metrics["primary_reason"]
        },
        "continued_analysis": f"Contact analysis (deterministic fallback): {metrics['contact_rate']}% contact rate.",
        "enhanced_next_steps": "Monitor contact patterns.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the contact correlation skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    voc_data = state.get("voc_data", {})
    records = shipment_data.get("records", [])
    contacts = voc_data.get("contacts", [])
    
    if not records:
        return {"skill": "contact_correlation", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records, contacts)
    context = {"customer_id": state.get("customer_id", "unknown"), "contacts": contacts}
    
    executor = LLMSkillExecutor(skill_name="contact_correlation", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

