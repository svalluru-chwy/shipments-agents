"""
Package Analysis Skill - Analyzes package weight and dimensions.
"""

from typing import Dict, Any, List
import statistics

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline package metrics (deterministic)."""
    weights = []
    heavy_packages = 0
    multi_package = 0
    total = len(records)
    
    for record in records:
        # Weight fallback chain:
        #   BULK_TRACK_LB_PACKAGE_WEIGHT -> SHIPMENT_PLANNED_WEIGHT -> WAREHOUSE_SCALE_WEIGHT
        weight = (
            record.get("BULK_TRACK_LB_PACKAGE_WEIGHT")
            or record.get("SHIPMENT_PLANNED_WEIGHT")
            or record.get("WAREHOUSE_SCALE_WEIGHT")
        )
        # S3 field is ORDERS_ORDER_PACKAGE_COUNT, not PACKAGE_COUNT
        pkg_count = record.get("ORDERS_ORDER_PACKAGE_COUNT", 1)
        
        if weight:
            try:
                w = float(weight)
                weights.append(w)
                if w > 30:
                    heavy_packages += 1
            except:
                pass
        
        if pkg_count and int(pkg_count) > 1:
            multi_package += 1
    
    avg_weight = round(statistics.mean(weights), 2) if weights else 0
    max_weight = max(weights) if weights else 0
    min_weight = min(weights) if weights else 0
    heavy_pct = round((heavy_packages / total) * 100, 1) if total > 0 else 0
    multi_pkg_pct = round((multi_package / total) * 100, 1) if total > 0 else 0
    
    return {
        "total_shipments": total,
        "avg_weight": avg_weight,
        "max_weight": max_weight,
        "min_weight": min_weight,
        "heavy_packages": heavy_packages,
        "heavy_package_pct": heavy_pct,
        "multi_package": multi_package,
        "multi_package_pct": multi_pkg_pct
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    
    observations = [
        f"Average package weight: {metrics['avg_weight']} lbs",
        f"Weight range: {metrics['min_weight']} - {metrics['max_weight']} lbs",
        f"Heavy packages (>30 lbs): {metrics['heavy_package_pct']}%",
        f"Multi-package orders: {metrics['multi_package_pct']}%"
    ]
    
    return {
        "skill": "package_analysis",
        "observations": observations,
        "summary": {
            "avg_weight": metrics["avg_weight"],
            "heavy_package_pct": metrics["heavy_package_pct"],
            "multi_package_pct": metrics["multi_package_pct"]
        },
        "continued_analysis": f"Package analysis (deterministic fallback): average weight {metrics['avg_weight']} lbs.",
        "enhanced_next_steps": "Monitor heavy package handling.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the package analysis skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "package_analysis", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="package_analysis", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

