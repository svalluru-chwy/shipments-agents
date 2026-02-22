"""
Timing Patterns Skill - Analyzes weekend/weekday and day-of-week patterns.
"""

from typing import Dict, Any, List
from datetime import datetime
import statistics

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline timing metrics (deterministic)."""
    day_stats = {i: {"count": 0, "ctd_values": []} for i in range(7)}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekend_ctd = []
    weekday_ctd = []
    total = len(records)
    
    for record in records:
        order_date = record.get("ORDER_PLACED_DTTM")
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        
        if order_date and ctd:
            try:
                if isinstance(order_date, str):
                    dt = datetime.fromisoformat(order_date.replace("Z", "+00:00"))
                else:
                    dt = order_date
                    
                day_of_week = dt.weekday()
                ctd_val = float(ctd)
                
                day_stats[day_of_week]["count"] += 1
                day_stats[day_of_week]["ctd_values"].append(ctd_val)
                
                if day_of_week >= 5:  # Weekend
                    weekend_ctd.append(ctd_val)
                else:
                    weekday_ctd.append(ctd_val)
            except:
                pass
    
    # Calculate weekend impact
    avg_weekend = round(statistics.mean(weekend_ctd), 2) if weekend_ctd else 0
    avg_weekday = round(statistics.mean(weekday_ctd), 2) if weekday_ctd else 0
    weekend_impact = round(avg_weekend - avg_weekday, 2) if avg_weekday and avg_weekend else 0
    
    # Find best and worst days
    day_avgs = {}
    for i, stats in day_stats.items():
        if stats["ctd_values"]:
            day_avgs[day_names[i]] = round(statistics.mean(stats["ctd_values"]), 2)
    
    best_day = min(day_avgs.items(), key=lambda x: x[1])[0] if day_avgs else "N/A"
    worst_day = max(day_avgs.items(), key=lambda x: x[1])[0] if day_avgs else "N/A"
    
    return {
        "total_shipments": total,
        "weekend_impact": weekend_impact,
        "avg_weekend_ctd": avg_weekend,
        "avg_weekday_ctd": avg_weekday,
        "best_day": best_day,
        "worst_day": worst_day,
        "by_day": day_avgs
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    
    observations = [
        f"Weekend avg CTD: {metrics['avg_weekend_ctd']} days, Weekday avg CTD: {metrics['avg_weekday_ctd']} days",
        f"Best order day: {metrics['best_day']}"
    ]
    
    return {
        "skill": "timing_patterns",
        "observations": observations,
        "summary": {
            "weekend_impact": metrics["weekend_impact"],
            "best_day": metrics["best_day"],
            "worst_day": metrics["worst_day"]
        },
        "continued_analysis": f"Timing analysis (deterministic fallback): weekend impact {metrics['weekend_impact']} days.",
        "enhanced_next_steps": "Monitor order timing patterns.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the timing patterns skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "timing_patterns", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="timing_patterns", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

