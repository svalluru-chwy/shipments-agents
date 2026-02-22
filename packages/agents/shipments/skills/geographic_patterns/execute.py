"""
Geographic Patterns Skill - Analyzes shipping patterns by ZIP code and fulfillment center.
"""

from typing import Dict, Any, List
import statistics

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline geographic metrics (deterministic)."""
    zip_stats = {}
    fc_stats = {}
    routes = {}
    total = len(records)
    
    for record in records:
        postcode = record.get("POSTCODE", "Unknown")
        fc = record.get("FFMCENTER_NAME", "Unknown")
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        
        # ZIP stats
        if postcode not in zip_stats:
            zip_stats[postcode] = {"count": 0, "ctd_values": []}
        zip_stats[postcode]["count"] += 1
        if ctd: zip_stats[postcode]["ctd_values"].append(float(ctd))
        
        # FC stats
        if fc not in fc_stats:
            fc_stats[fc] = {"count": 0, "ctd_values": []}
        fc_stats[fc]["count"] += 1
        if ctd: fc_stats[fc]["ctd_values"].append(float(ctd))
        
        # Route patterns
        route = f"{fc}->{postcode}"
        if route not in routes:
            routes[route] = {"count": 0, "ctd_values": []}
        routes[route]["count"] += 1
        if ctd: routes[route]["ctd_values"].append(float(ctd))
    
    primary_zip = max(zip_stats.items(), key=lambda x: x[1]["count"])[0] if zip_stats else "Unknown"
    primary_fc = max(fc_stats.items(), key=lambda x: x[1]["count"])[0] if fc_stats else "Unknown"
    
    # Calculate FC summary
    fc_summary = {}
    for fc, stats in fc_stats.items():
        fc_summary[fc] = {
            "count": stats["count"],
            "percentage": round((stats["count"] / total) * 100, 1),
            "avg_ctd": round(statistics.mean(stats["ctd_values"]), 2) if stats["ctd_values"] else 0
        }
    
    # Determine routing efficiency
    best_fc = min(fc_summary.items(), key=lambda x: x[1]["avg_ctd"]) if fc_summary else (primary_fc, fc_summary.get(primary_fc, {}))
    if best_fc[0] == primary_fc:
        routing_efficiency = "GOOD"
    else:
        routing_efficiency = "SUBOPTIMAL"
    
    return {
        "total_shipments": total,
        "primary_zip": primary_zip,
        "primary_fc": primary_fc,
        "by_fc": fc_summary,
        "routing_efficiency": routing_efficiency
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    primary_fc = metrics["primary_fc"]
    routing_efficiency = metrics["routing_efficiency"]
    
    observations = [
        f"Primary delivery ZIP: {metrics['primary_zip']}",
        f"Primary fulfillment center: {primary_fc}",
        f"Routing efficiency: {routing_efficiency}"
    ]
    
    return {
        "skill": "geographic_patterns",
        "observations": observations,
        "summary": {
            "primary_zip": metrics["primary_zip"],
            "primary_fc": primary_fc,
            "routing_efficiency": routing_efficiency,
            "key_finding": f"Orders routed through {primary_fc}"
        },
        "continued_analysis": f"Geographic analysis (deterministic fallback): primary FC is {primary_fc}.",
        "enhanced_next_steps": "Monitor routing patterns.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the geographic patterns skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "geographic_patterns", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="geographic_patterns", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

