"""
Timing Patterns Skill - Analyzes weekend/weekday and day-of-week patterns.
"""

import json
from typing import Dict, Any
from datetime import datetime
import statistics


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the timing patterns skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "timing_patterns", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    # Analyze by day of week
    day_stats = {i: {"count": 0, "ctd_values": []} for i in range(7)}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekend_ctd = []
    weekday_ctd = []
    
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
    
    total = len(records)
    
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
    
    observations = [
        f"Weekend orders have {'a delay of ' + str(weekend_impact) + ' days compared to weekdays' if weekend_impact > 0 else 'no significant delay'}.",
        f"Best order day: {best_day} (avg CTD: {day_avgs.get(best_day, 'N/A')} days)",
        f"Worst order day: {worst_day} (avg CTD: {day_avgs.get(worst_day, 'N/A')} days)",
        f"Weekend avg CTD: {avg_weekend} days, Weekday avg CTD: {avg_weekday} days"
    ]
    
    result = {
        "skill": "timing_patterns",
        "observations": observations,
        "summary": {
            "weekend_impact": weekend_impact,
            "best_day": best_day,
            "worst_day": worst_day,
            "key_pattern": f"Weekend orders have {'a slight delay' if weekend_impact > 0 else 'no significant impact'} compared to weekdays."
        },
        "continued_analysis": f"Timing analysis shows {best_day} as the optimal order day with lowest CTD.",
        "enhanced_next_steps": "Consider order timing recommendations for time-sensitive items.",
        "grounded_metrics": {
            "total_shipments": total,
            "weekend_impact": weekend_impact,
            "avg_weekend_ctd": avg_weekend,
            "avg_weekday_ctd": avg_weekday,
            "best_day": best_day,
            "worst_day": worst_day,
            "by_day": day_avgs
        }
    }
    
    return result
