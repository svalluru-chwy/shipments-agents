"""
Contact Correlation Skill - Correlates contacts with shipment issues.
"""

from typing import Dict, Any
from datetime import datetime, timedelta


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the contact correlation skill."""
    shipment_data = state.get("shipment_data", {})
    voc_data = state.get("voc_data", {})
    records = shipment_data.get("records", [])
    contacts = voc_data.get("contacts", [])
    
    if not records:
        return {"skill": "contact_correlation", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
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
    
    observations = [
        f"Contact rate: {contact_rate}% ({total_contacts} contacts for {total_shipments} shipments)",
        f"WISMO rate: {wismo_rate}%",
        f"Primary contact reason: {primary_reason}"
    ]
    
    result = {
        "skill": "contact_correlation",
        "observations": observations,
        "summary": {
            "contact_rate": contact_rate,
            "primary_reason": primary_reason,
            "wismo_rate": wismo_rate
        },
        "continued_analysis": f"Contact correlation shows {contact_rate}% contact rate with {wismo_rate}% WISMO inquiries.",
        "enhanced_next_steps": "Proactive tracking notifications may reduce WISMO contacts." if wismo_rate > 20 else "Contact rate is within normal range.",
        "grounded_metrics": {
            "total_shipments": total_shipments,
            "total_contacts": total_contacts,
            "contact_rate": contact_rate,
            "wismo_contacts": wismo_contacts,
            "wismo_rate": wismo_rate,
            "shipment_related_contacts": shipment_contacts,
            "primary_reason": primary_reason,
            "reason_distribution": reason_counts
        }
    }
    
    return result
