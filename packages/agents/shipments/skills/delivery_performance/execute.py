"""
Delivery Performance Skill - Analyzes CTD patterns and identifies delayed shipments.
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
    """Compute baseline metrics from shipment records (deterministic)."""
    ctd_values = []
    ctd_sources = []
    delayed_shipments = []
    carrier_stats = {}
    fc_stats = {}
    total = len(records)
    
    for record in records:
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        ctd_source = "actual"

        if ctd is None:
            # Estimated CTD fallback: compute from available dates
            order_dt = _parse_date(record.get("ORDER_PLACED_DTTM"))
            delivery_proxy = _parse_date(
                record.get("BULK_TRACK_DELIVERY_DTTM")
                or record.get("SHIPMENT_ESTIMATED_DELIVERY_DATE")
                or record.get("WIZMO_CURRENT_ARRIVAL_DATE")
                or record.get("LAST_EXPECTED_DELIVERY_DATE")
            )
            if order_dt and delivery_proxy:
                ctd = (delivery_proxy - order_dt).days
                ctd_source = "estimated"

        if ctd is not None:
            try:
                ctd_val = float(ctd)
                ctd_values.append(ctd_val)
                ctd_sources.append(ctd_source)
                
                # Delayed = CTD exceeds threshold (pure CTD logic)
                if ctd_val > ctd_threshold:
                    delayed_shipments.append({
                        "order_id": record.get("ORDER_ID"),
                        "tracking_number": record.get("SHIPMENT_TRACKING_NUMBER"),
                        "ctd_days": ctd_val,
                        "ctd_source": ctd_source,
                        "carrier": record.get("WAREHOUSE_CARRIER"),
                        "fc": record.get("FFMCENTER_NAME"),
                        "reason": f"CTD {ctd_val} > threshold {ctd_threshold}"
                    })
                
                # Carrier stats
                carrier = record.get("WAREHOUSE_CARRIER", "Unknown")
                if carrier not in carrier_stats:
                    carrier_stats[carrier] = {"ctd_values": [], "count": 0, "delayed": 0}
                carrier_stats[carrier]["ctd_values"].append(ctd_val)
                carrier_stats[carrier]["count"] += 1
                if ctd_val > ctd_threshold:
                    carrier_stats[carrier]["delayed"] += 1
                
                # FC stats
                fc = record.get("FFMCENTER_NAME", "Unknown")
                if fc not in fc_stats:
                    fc_stats[fc] = {"ctd_values": [], "count": 0}
                fc_stats[fc]["ctd_values"].append(ctd_val)
                fc_stats[fc]["count"] += 1
                    
            except (ValueError, TypeError):
                pass
    
    avg_ctd = round(statistics.mean(ctd_values), 2) if ctd_values else 0
    median_ctd = round(statistics.median(ctd_values), 1) if ctd_values else 0
    min_ctd = min(ctd_values) if ctd_values else 0
    max_ctd = max(ctd_values) if ctd_values else 0
    delayed_count = len(delayed_shipments)
    delayed_pct = round((delayed_count / total) * 100, 1) if total > 0 else 0
    
    # Calculate carrier summary
    carrier_summary = {}
    for carrier, stats in carrier_stats.items():
        carrier_summary[carrier] = {
            "count": stats["count"],
            "percentage": round((stats["count"] / total) * 100, 1),
            "avg_ctd": round(statistics.mean(stats["ctd_values"]), 2),
            "delayed_count": stats["delayed"],
            "delayed_pct": round((stats["delayed"] / stats["count"]) * 100, 1) if stats["count"] > 0 else 0
        }
    
    # Calculate FC summary
    fc_summary = {}
    for fc, stats in fc_stats.items():
        fc_summary[fc] = {
            "count": stats["count"],
            "avg_ctd": round(statistics.mean(stats["ctd_values"]), 2)
        }
    
    # Trend analysis - compare first half vs second half
    if len(ctd_values) >= 4:
        mid = len(ctd_values) // 2
        first_half_avg = statistics.mean(ctd_values[:mid])
        second_half_avg = statistics.mean(ctd_values[mid:])
        trend_change = round(second_half_avg - first_half_avg, 2)
        trend_direction = "IMPROVING" if trend_change < -0.2 else "STABLE" if abs(trend_change) <= 0.2 else "DECLINING"
    else:
        trend_change = 0
        trend_direction = "INSUFFICIENT_DATA"
    
    # Count CTD coverage
    actual_ctd_count = ctd_sources.count("actual")
    estimated_ctd_count = ctd_sources.count("estimated")
    no_ctd_count = total - len(ctd_values)

    return {
        "total_shipments": total,
        "avg_ctd": avg_ctd,
        "median_ctd": median_ctd,
        "min_ctd": min_ctd,
        "max_ctd": max_ctd,
        "ctd_threshold": ctd_threshold,
        "delayed_count": delayed_count,
        "delayed_pct": delayed_pct,
        "on_time_pct": round(100 - delayed_pct, 1),
        "trend_change": trend_change,
        "trend_direction": trend_direction,
        "by_carrier": carrier_summary,
        "by_fc": fc_summary,
        "actual_ctd_count": actual_ctd_count,
        "estimated_ctd_count": estimated_ctd_count,
        "no_ctd_count": no_ctd_count,
        "delay_definition": f"CTD > {ctd_threshold} days",
        "delayed_shipments": delayed_shipments
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    ctd_threshold = baseline.get("ctd_threshold", 3.0)
    metrics = _compute_baseline_metrics(records, ctd_threshold)
    
    delayed_shipments = metrics.pop("delayed_shipments")
    health = "HEALTHY" if metrics["delayed_pct"] <= 5 else "ATTENTION" if metrics["delayed_pct"] <= 15 else "CRITICAL"
    
    # Build observations
    ctd_coverage = f"{metrics['actual_ctd_count']} actual"
    if metrics['estimated_ctd_count'] > 0:
        ctd_coverage += f", {metrics['estimated_ctd_count']} estimated"
    if metrics['no_ctd_count'] > 0:
        ctd_coverage += f", {metrics['no_ctd_count']} without CTD"
    
    observations = [
        f"Total shipments processed: {metrics['total_shipments']} ({ctd_coverage}).",
        f"Average Click-to-Deliver (CTD) time is {metrics['avg_ctd']} days, with a maximum of {metrics['max_ctd']} days.",
        f"{metrics['delayed_pct']}% of shipments ({metrics['delayed_count']} out of {metrics['total_shipments']}) exceeded the {ctd_threshold}-day CTD threshold."
    ]
    
    return {
        "skill": "delivery_performance",
        "observations": observations,
        "summary": {
            "overall_health": health,
            "primary_finding": f"CTD averaging {metrics['avg_ctd']} days",
            "trend_direction": metrics["trend_direction"]
        },
        "continued_analysis": f"Delivery performance analysis (deterministic fallback): {metrics['delayed_count']} delayed shipments, trend is {metrics['trend_direction'].lower()}.",
        "enhanced_next_steps": "Monitor shipment performance." if health == "HEALTHY" else "Monitor delayed shipments closely.",
        "flagged_shipments": delayed_shipments,
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the delivery performance skill with LLM analysis."""
    customer_id = state.get("customer_id", "unknown")
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    baseline = shipment_data.get("baseline", {})
    
    if not records:
        return {
            "skill": "delivery_performance",
            "error": "No shipment data available",
            "grounded_metrics": {"total_shipments": 0}
        }
    
    ctd_threshold = baseline.get("ctd_threshold", 3.0)
    baseline_metrics = _compute_baseline_metrics(records, ctd_threshold)
    delayed_shipments = baseline_metrics.pop("delayed_shipments")
    
    context = {
        "customer_id": customer_id,
        "delayed_shipments": delayed_shipments
    }
    
    executor = LLMSkillExecutor(skill_name="delivery_performance", reasoning_effort="medium")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

