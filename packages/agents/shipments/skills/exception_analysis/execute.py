"""
Exception Analysis Skill - Analyzes carrier exceptions and delivery issues.
"""

from typing import Dict, Any, List

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline exception metrics (deterministic)."""
    exceptions = []
    exception_by_carrier = {}
    exception_by_type = {}
    total = len(records)
    
    for record in records:
        # S3 uses BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION (not EXCEPTION_FLAG)
        # and boolean true/null for SHIPMENT_WAS_DELAYED (not "Y" string)
        exc_desc = str(record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION", "") or "")
        has_exception = exc_desc and exc_desc.lower() not in ("no exception", "", "none")
        is_delayed = record.get("SHIPMENT_WAS_DELAYED") is True
        # Check for lost shipments
        is_lost = record.get("SHIPMENT_WAS_LOST") is True

        if has_exception or is_delayed or is_lost:
            # Determine exception type with priority:
            #   1. Actual exception code/description (only when has_exception is True)
            #   2. Lost shipment flag
            #   3. Delayed flag
            exc_type = ""
            if has_exception:
                exc_type = record.get("INITIAL_DELIVERY_ATTEMPT_EXCEPTION_CD") or exc_desc
            if not exc_type:
                if is_lost:
                    exc_type = "Lost shipment"
                elif is_delayed:
                    exc_type = "Delayed (SHIPMENT_WAS_DELAYED)"
                else:
                    exc_type = "Unknown"

            exc = {
                "order_id": record.get("ORDER_ID") or record.get("ORDERS_ORDER_ID"),
                "tracking": record.get("SHIPMENT_TRACKING_NUMBER"),
                "carrier": record.get("WAREHOUSE_CARRIER"),
                "type": exc_type,
                "ctd": record.get("CLICK_TO_DELIVER_DAYS"),
                "is_lost": is_lost
            }
            exceptions.append(exc)
            
            carrier = exc["carrier"] or "Unknown"
            exception_by_carrier[carrier] = exception_by_carrier.get(carrier, 0) + 1
            
            exc_type = exc["type"] or "Unknown"
            exception_by_type[exc_type] = exception_by_type.get(exc_type, 0) + 1
    
    exception_count = len(exceptions)
    exception_rate = round((exception_count / total) * 100, 1) if total > 0 else 0
    lost_count = len([e for e in exceptions if e.get("is_lost")])
    
    return {
        "total_shipments": total,
        "exception_count": exception_count,
        "exception_rate": exception_rate,
        "lost_shipment_count": lost_count,
        "by_carrier": exception_by_carrier,
        "by_type": exception_by_type,
        "exception_details": exceptions[:10],
        "exception_definition": "BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION or SHIPMENT_WAS_DELAYED=true or SHIPMENT_WAS_LOST=true"
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    exception_count = metrics["exception_count"]
    lost_count = metrics["lost_shipment_count"]
    
    observations = [
        f"Total exceptions: {exception_count} out of {metrics['total_shipments']} shipments ({metrics['exception_rate']}%)"
    ]
    if lost_count > 0:
        observations.append(f"Lost shipments identified: {lost_count}")
    
    return {
        "skill": "exception_analysis",
        "observations": observations,
        "exception_summary": {
            "total_exceptions": exception_count,
            "exception_rate": metrics["exception_rate"],
            "by_carrier": metrics["by_carrier"],
            "by_type": metrics["by_type"]
        },
        "continued_analysis": f"Exception analysis (deterministic fallback): {exception_count} exceptions ({metrics['exception_rate']}% rate).",
        "enhanced_next_steps": "Monitor carriers with high exception rates." if exception_count > 0 else "No exceptions to address.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the exception analysis skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "exception_analysis", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="exception_analysis", reasoning_effort="medium")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

