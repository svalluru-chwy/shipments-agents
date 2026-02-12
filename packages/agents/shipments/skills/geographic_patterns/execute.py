"""
Geographic Patterns Skill - Analyzes shipping patterns by ZIP code and fulfillment center.
"""

import json
from typing import Dict, Any
import statistics


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the geographic patterns skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "geographic_patterns", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    # Analyze by ZIP and FC
    zip_stats = {}
    fc_stats = {}
    routes = {}
    
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
    
    total = len(records)
    primary_zip = max(zip_stats.items(), key=lambda x: x[1]["count"])[0]
    primary_fc = max(fc_stats.items(), key=lambda x: x[1]["count"])[0]
    
    # Calculate FC summary
    fc_summary = {}
    for fc, stats in fc_stats.items():
        fc_summary[fc] = {
            "count": stats["count"],
            "percentage": round((stats["count"] / total) * 100, 1),
            "avg_ctd": round(statistics.mean(stats["ctd_values"]), 2) if stats["ctd_values"] else 0
        }
    
    # Determine routing efficiency
    best_fc = min(fc_summary.items(), key=lambda x: x[1]["avg_ctd"])
    if best_fc[0] == primary_fc:
        routing_efficiency = "GOOD"
    else:
        routing_efficiency = "SUBOPTIMAL"
    
    observations = [
        f"Primary delivery ZIP: {primary_zip}",
        f"Primary fulfillment center: {primary_fc}",
        f"{primary_fc} handles {fc_summary[primary_fc]['percentage']}% of orders with avg CTD {fc_summary[primary_fc]['avg_ctd']} days.",
        f"Routing efficiency: {routing_efficiency}"
    ]
    
    result = {
        "skill": "geographic_patterns",
        "observations": observations,
        "summary": {
            "primary_zip": primary_zip,
            "primary_fc": primary_fc,
            "routing_efficiency": routing_efficiency,
            "key_finding": f"Orders are primarily routed through {primary_fc}, {'the nearest fulfillment center' if routing_efficiency == 'GOOD' else 'which may not be optimal'}."
        },
        "continued_analysis": f"Geographic analysis shows {primary_fc} as the primary FC for ZIP {primary_zip}.",
        "enhanced_next_steps": "Continue monitoring routing patterns for efficiency.",
        "grounded_metrics": {
            "total_shipments": total,
            "primary_zip": primary_zip,
            "primary_fc": primary_fc,
            "by_fc": fc_summary,
            "routing_efficiency": routing_efficiency
        }
    }
    
    return result
