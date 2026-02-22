"""
Carrier Analysis Skill - Analyzes carrier performance patterns.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import statistics

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _parse_date(val: Any) -> Optional[datetime]:
    """Parse a date value (string or datetime) into a naive datetime."""
    if val is None:
        return None
    try:
        s = str(val)
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _compute_baseline_metrics(records: List[Dict[str, Any]], ctd_threshold: float) -> Dict[str, Any]:
    """Compute baseline carrier metrics (deterministic)."""
    carrier_stats = {}
    total = len(records)
    flagged_shipments = []
    
    for record in records:
        carrier = record.get("WAREHOUSE_CARRIER", "Unknown")
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        
        if carrier not in carrier_stats:
            carrier_stats[carrier] = {
                "count": 0,
                "ctd_values": [],
                "delayed": 0,
                "exceptions": 0
            }
        
        carrier_stats[carrier]["count"] += 1

        # Estimated CTD fallback for records without CLICK_TO_DELIVER_DAYS
        if ctd is None:
            order_dt = _parse_date(record.get("ORDER_PLACED_DTTM"))
            delivery_proxy = _parse_date(
                record.get("BULK_TRACK_DELIVERY_DTTM")
                or record.get("SHIPMENT_ESTIMATED_DELIVERY_DATE")
                or record.get("WIZMO_CURRENT_ARRIVAL_DATE")
                or record.get("LAST_EXPECTED_DELIVERY_DATE")
            )
            if order_dt and delivery_proxy:
                ctd = (delivery_proxy - order_dt).days
        
        if ctd is not None:
            try:
                ctd_val = float(ctd)
                carrier_stats[carrier]["ctd_values"].append(ctd_val)
                # Delayed = CTD exceeds threshold (pure CTD logic)
                if ctd_val > ctd_threshold:
                    carrier_stats[carrier]["delayed"] += 1
            except (ValueError, TypeError):
                pass
        
        # S3 uses BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION (not EXCEPTION_FLAG)
        exc_desc = str(record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION", "") or "")
        if exc_desc and exc_desc.lower() not in ("no exception", "", "none"):
            carrier_stats[carrier]["exceptions"] += 1
            
            # Flag shipments with exceptions for detailed analysis
            if ctd_val and ctd_val > ctd_threshold:
                flagged_shipments.append({
                    "order_id": record.get("ORDER_ID"),
                    "tracking_number": record.get("SHIPMENT_TRACKING_NUMBER"),
                    "carrier": carrier,
                    "issue": f"Delayed - {ctd_val} day CTD",
                    "fc": record.get("FFMCENTER_NAME")
                })
    
    # Build carrier summary
    carriers = {}
    for carrier, stats in carrier_stats.items():
        count = stats["count"]
        ctd_vals = stats["ctd_values"]
        carriers[carrier] = {
            "count": count,
            "percentage": round((count / total) * 100, 1),
            "avg_ctd": round(statistics.mean(ctd_vals), 2) if ctd_vals else 0,
            "min_ctd": min(ctd_vals) if ctd_vals else 0,
            "max_ctd": max(ctd_vals) if ctd_vals else 0,
            "delayed_count": stats["delayed"],
            "delayed_pct": round((stats["delayed"] / count) * 100, 1) if count > 0 else 0,
            "on_time_pct": round(100 - (stats["delayed"] / count) * 100, 1) if count > 0 else 100,
            "exception_count": stats["exceptions"],
            "exception_rate": round((stats["exceptions"] / count) * 100, 1) if count > 0 else 0
        }
    
    # Identify primary carrier
    primary_carrier = max(carriers.items(), key=lambda x: x[1]["count"])[0] if carriers else "Unknown"
    
    # Identify best performer (lowest avg CTD with >1 shipment)
    valid_carriers = {k: v for k, v in carriers.items() if v["count"] > 1 and v["avg_ctd"] > 0}
    best_performer = min(valid_carriers.items(), key=lambda x: x[1]["avg_ctd"])[0] if valid_carriers else primary_carrier
    
    # Identify carrier with issues (highest delayed_pct > 15%)
    carriers_with_delays = {k: v for k, v in carriers.items() if v["delayed_pct"] > 15}
    carrier_with_issues = max(carriers_with_delays.items(), key=lambda x: x[1]["delayed_pct"])[0] if carriers_with_delays else None
    
    return {
        "total_shipments": total,
        "carriers": carriers,
        "primary_carrier": primary_carrier,
        "best_performer": best_performer,
        "carrier_with_issues": carrier_with_issues,
        "flagged_shipments": flagged_shipments
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    ctd_threshold = baseline.get("ctd_threshold", 3.0)
    metrics = _compute_baseline_metrics(records, ctd_threshold)
    
    flagged_shipments = metrics.pop("flagged_shipments")
    carriers = metrics["carriers"]
    primary_carrier = metrics["primary_carrier"]
    
    observations = []
    for carrier, stats in sorted(carriers.items(), key=lambda x: -x[1]["count"]):
        observations.append(
            f"{carrier} handled {stats['percentage']}% of shipments with an average CTD of {stats['avg_ctd']} days."
        )
    
    return {
        "skill": "carrier_analysis",
        "observations": observations,
        "summary": {
            "primary_carrier": primary_carrier,
            "best_performer": metrics["best_performer"],
            "carrier_with_issues": metrics["carrier_with_issues"],
            "key_finding": f"{primary_carrier} is the primary carrier"
        },
        "continued_analysis": f"Carrier analysis (deterministic fallback): {primary_carrier} handles {carriers[primary_carrier]['percentage']}% of shipments.",
        "enhanced_next_steps": "Monitor carrier performance.",
        "grounded_metrics": {k: v for k, v in metrics.items() if k != "flagged_shipments"},
        "flagged_shipments": flagged_shipments
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the carrier analysis skill with LLM analysis."""
    customer_id = state.get("customer_id", "unknown")
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    baseline = shipment_data.get("baseline", {})
    ctd_threshold = baseline.get("ctd_threshold", 3.0)
    
    if not records:
        return {
            "skill": "carrier_analysis",
            "error": "No shipment data available",
            "grounded_metrics": {"total_shipments": 0}
        }
    
    baseline_metrics = _compute_baseline_metrics(records, ctd_threshold)
    flagged_shipments = baseline_metrics.pop("flagged_shipments")
    
    context = {
        "customer_id": customer_id,
        "flagged_shipments": flagged_shipments
    }
    
    executor = LLMSkillExecutor(skill_name="carrier_analysis", reasoning_effort="medium")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

