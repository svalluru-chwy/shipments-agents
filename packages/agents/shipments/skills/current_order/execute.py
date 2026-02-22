"""
Current Order Skill - Tracks active/in-progress orders and predicts delays.
NOTE: Simplified LLM-powered version. Active order tracking logic moved to baseline computation.
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]], contact_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline current order metrics (deterministic)."""
    active_orders = []
    at_risk = []
    now = datetime.now()
    total = len(records)
    
    for record in records:
        status = (
            record.get("BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION")
            or record.get("SHIPMENT_STATUS")
            or record.get("WIZMO_CURRENT_PKG_STATUS")
            or ""
        ).upper()
        
        delivered_dt = record.get("BULK_TRACK_DELIVERY_DTTM")
        is_delivered = delivered_dt is not None or "DELIVERED" in status
        
        if not is_delivered:
            active_orders.append({
                "order_id": record.get("ORDER_ID"),
                "tracking": record.get("SHIPMENT_TRACKING_NUMBER"),
                "status": status,
                "ctd": record.get("CLICK_TO_DELIVER_DAYS")
            })
            
            # At-risk if CTD > 3 and still in transit
            ctd = record.get("CLICK_TO_DELIVER_DAYS")
            if ctd and float(ctd) > 3:
                at_risk.append(active_orders[-1])
    
    # VOC context
    cutoff_date = now - timedelta(days=90)
    shipment_contacts_90d = 0
    for contact in contact_records:
        contact_date_str = contact.get("SESSION_START_DTTM")
        contact_reason = " ".join(filter(None, [
            str(contact.get("CATEGORY_LEVEL_1", "") or ""),
            str(contact.get("CATEGORY_LEVEL_2", "") or "")
        ])).lower()
        
        if any(kw in contact_reason for kw in ["ship", "deliver", "track", "delay"]):
            if contact_date_str:
                try:
                    contact_dt = datetime.fromisoformat(str(contact_date_str).replace("Z", "+00:00"))
                    if contact_dt.replace(tzinfo=None) >= cutoff_date:
                        shipment_contacts_90d += 1
                except:
                    pass
    
    return {
        "total_orders": total,
        "active_orders": len(active_orders),
        "at_risk_orders": len(at_risk),
        "voc_context": {"shipment_contacts_last_90_days": shipment_contacts_90d},
        "active_order_details": active_orders[:5],
        "at_risk_details": at_risk[:3]
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    contact_records = context.get("contact_records", [])
    metrics = _compute_baseline_metrics(records, contact_records)
    
    observations = [
        f"Active orders: {metrics['active_orders']}",
        f"At-risk orders: {metrics['at_risk_orders']}"
    ]
    
    return {
        "skill": "current_order",
        "observations": observations,
        "summary": {
            "active_orders": metrics["active_orders"],
            "at_risk_orders": metrics["at_risk_orders"]
        },
        "continued_analysis": f"Current order analysis (deterministic fallback): {metrics['active_orders']} active.",
        "enhanced_next_steps": "Monitor active orders.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the current order skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    customer_contacts = state.get("customer_contacts", {})
    contact_records = []
    if isinstance(customer_contacts, dict):
        contact_records = customer_contacts.get("data", [])
    elif isinstance(customer_contacts, list):
        contact_records = customer_contacts
    
    if not records:
        now = datetime.now()
        cutoff_date = now - timedelta(days=90)
        shipment_contacts_90d = 0
        
        for contact in contact_records:
            contact_date_str = contact.get("SESSION_START_DTTM")
            contact_reason = " ".join(filter(None, [
                str(contact.get("CATEGORY_LEVEL_1", "") or ""),
                str(contact.get("CATEGORY_LEVEL_2", "") or "")
            ])).lower()
            
            if any(kw in contact_reason for kw in ["ship", "deliver", "track", "delay"]):
                if contact_date_str:
                    try:
                        contact_dt = datetime.fromisoformat(str(contact_date_str).replace("Z", "+00:00"))
                        if contact_dt.replace(tzinfo=None) >= cutoff_date:
                            shipment_contacts_90d += 1
                    except:
                        pass
        
        return {
            "skill": "current_order",
            "error": "No shipment data",
            "observations": [
                "No shipment data available",
                f"Customer shipment-related contacts in last 90 days: {shipment_contacts_90d}"
            ],
            "grounded_metrics": {
                "total_orders": 0,
                "voc_context": {"shipment_contacts_last_90_days": shipment_contacts_90d}
            }
        }
    
    baseline_metrics = _compute_baseline_metrics(records, contact_records)
    context = {"customer_id": state.get("customer_id", "unknown"), "contact_records": contact_records}
    
    executor = LLMSkillExecutor(skill_name="current_order", reasoning_effort="medium")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result
