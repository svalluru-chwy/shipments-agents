"""
Routing Efficiency Skill - Analyzes arc distance and FC distance optimization.
"""

from typing import Dict, Any, List
import statistics

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline routing metrics (deterministic)."""
    total = len(records)
    
    # Analyze routing metrics
    arc_distances = []
    best_fc_distances = []
    fc_distances = {}
    arc_ranges = {}
    
    for record in records:
        # Use ARC_DISTANCE and BEST_FC_ARC_DISTANCE from shipment_inspector
        arc = record.get("ARC_DISTANCE")
        best_fc_arc = record.get("BEST_FC_ARC_DISTANCE")
        fc = record.get("FFMCENTER_NAME", "Unknown")
        arc_range = record.get("ARC_RANGE", "Unknown")
        
        if arc: 
            arc_distances.append(float(arc))
            
            # Track by FC
            if fc not in fc_distances:
                fc_distances[fc] = []
            fc_distances[fc].append(float(arc))
            
        if best_fc_arc: 
            best_fc_distances.append(float(best_fc_arc))
            
        # Track arc ranges
        if arc_range not in arc_ranges:
            arc_ranges[arc_range] = 0
        arc_ranges[arc_range] += 1
    
    total = len(records)
    avg_arc = round(statistics.mean(arc_distances), 2) if arc_distances else 0
    avg_best_fc = round(statistics.mean(best_fc_distances), 2) if best_fc_distances else 0
    
    # Calculate efficiency: how close is actual routing to optimal?
    if avg_best_fc > 0 and avg_arc > 0:
        routing_efficiency_pct = round((avg_best_fc / avg_arc) * 100, 1)
        avg_excess_miles = round(avg_arc - avg_best_fc, 2)
    else:
        # No data available
        routing_efficiency_pct = 0
        avg_excess_miles = 0
    
    # Determine status based on efficiency
    if routing_efficiency_pct == 0:
        routing_status = "NO_DATA"
    elif routing_efficiency_pct >= 95:
        routing_status = "OPTIMAL"
    elif routing_efficiency_pct >= 85:
        routing_status = "ACCEPTABLE"
    else:
        routing_status = "SUBOPTIMAL"
    
    # Primary FC
    primary_fc = max(fc_distances.items(), key=lambda x: len(x[1]))[0] if fc_distances else "Unknown"
    
    return {
        "total_shipments": total,
        "avg_arc_distance": avg_arc,
        "avg_optimal_distance": avg_best_fc,
        "routing_efficiency_pct": routing_efficiency_pct,
        "avg_excess_miles": avg_excess_miles,
        "primary_fc": primary_fc,
        "routing_status": routing_status,
        "arc_range_distribution": arc_ranges
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    
    observations = [f"Analyzed {metrics['total_shipments']} shipments for routing efficiency"]
    if metrics["routing_efficiency_pct"] > 0:
        observations.append(f"Routing efficiency: {metrics['routing_efficiency_pct']}%")
    
    return {
        "skill": "routing_efficiency",
        "observations": observations,
        "summary": {
            "routing_efficiency_pct": metrics["routing_efficiency_pct"],
            "routing_status": metrics["routing_status"]
        },
        "continued_analysis": f"Routing analysis (deterministic fallback): {metrics['routing_status'].lower()}.",
        "enhanced_next_steps": "Monitor routing efficiency.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the routing efficiency skill with LLM analysis."""
    shipment_inspector = state.get("shipment_inspector", {})
    records = shipment_inspector.get("data", []) if isinstance(shipment_inspector, dict) else []
    
    if not records:
        shipment_data = state.get("shipment_data", {})
        records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "routing_efficiency", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="routing_efficiency", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result
