"""
Package Analysis Skill - Analyzes package weight and dimensions.
"""

import json
from typing import Dict, Any
import statistics


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the package analysis skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "package_analysis", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    # Analyze package characteristics
    weights = []
    heavy_packages = 0
    multi_package = 0
    
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
    
    total = len(records)
    avg_weight = round(statistics.mean(weights), 2) if weights else 0
    max_weight = max(weights) if weights else 0
    min_weight = min(weights) if weights else 0
    
    heavy_pct = round((heavy_packages / total) * 100, 1) if total > 0 else 0
    multi_pkg_pct = round((multi_package / total) * 100, 1) if total > 0 else 0
    
    observations = [
        f"Average package weight: {avg_weight} lbs",
        f"Weight range: {min_weight} - {max_weight} lbs",
        f"Heavy packages (>30 lbs): {heavy_pct}%",
        f"Multi-package orders: {multi_pkg_pct}%"
    ]
    
    result = {
        "skill": "package_analysis",
        "observations": observations,
        "summary": {
            "avg_weight": avg_weight,
            "heavy_package_pct": heavy_pct,
            "multi_package_pct": multi_pkg_pct
        },
        "continued_analysis": f"Package analysis shows average weight of {avg_weight} lbs with {heavy_pct}% heavy packages.",
        "enhanced_next_steps": "Monitor heavy package handling for potential carrier surcharges.",
        "grounded_metrics": {
            "total_shipments": total,
            "avg_weight": avg_weight,
            "max_weight": max_weight,
            "min_weight": min_weight,
            "heavy_packages": heavy_packages,
            "heavy_package_pct": heavy_pct,
            "multi_package": multi_package,
            "multi_package_pct": multi_pkg_pct
        }
    }
    
    return result
