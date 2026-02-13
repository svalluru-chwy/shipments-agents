"""
Carrier Analysis Skill - Analyzes carrier performance patterns.
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime
import statistics


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


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the carrier analysis skill."""
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
    
    # Analyze by carrier
    carrier_stats = {}
    total = len(records)
    
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
    primary_carrier = max(carriers.items(), key=lambda x: x[1]["count"])[0]
    
    # Identify best performer (lowest avg CTD with >1 shipment)
    valid_carriers = {k: v for k, v in carriers.items() if v["count"] > 1 and v["avg_ctd"] > 0}
    best_performer = min(valid_carriers.items(), key=lambda x: x[1]["avg_ctd"])[0] if valid_carriers else primary_carrier
    
    # Identify carrier with issues (highest delayed_pct)
    carriers_with_delays = {k: v for k, v in carriers.items() if v["delayed_pct"] > 15}
    carrier_with_issues = max(carriers_with_delays.items(), key=lambda x: x[1]["delayed_pct"])[0] if carriers_with_delays else None
    
    # Build observations
    observations = []
    for carrier, stats in sorted(carriers.items(), key=lambda x: -x[1]["count"]):
        observations.append(
            f"{carrier} handled {stats['percentage']}% of shipments with an average CTD of {stats['avg_ctd']} days."
        )
        if stats["delayed_count"] > 0:
            observations.append(
                f"{carrier} had {stats['delayed_count']} delayed shipment(s), resulting in a {stats['delayed_pct']}% delayed rate."
            )
        observations.append(
            f"{carrier} {'reported no exceptions' if stats['exception_count'] == 0 else f'had {stats['exception_count']} exception(s)'}, resulting in an exception rate of {stats['exception_rate']}%."
        )
        observations.append(
            f"{carrier} achieved a {stats['on_time_pct']}% on-time delivery rate."
        )
    
    result = {
        "skill": "carrier_analysis",
        "observations": observations,
        "summary": {
            "primary_carrier": primary_carrier,
            "best_performer": best_performer,
            "carrier_with_issues": carrier_with_issues,
            "key_finding": f"{primary_carrier} is the primary carrier, handling {carriers[primary_carrier]['percentage']}% of shipments with {'the lowest' if primary_carrier == best_performer else 'an'} average CTD of {carriers[primary_carrier]['avg_ctd']} days."
        },
        "continued_analysis": f"The analysis of carrier performance reveals that {primary_carrier} is the primary carrier, managing {carriers[primary_carrier]['percentage']}% of the total shipments with an average CTD of {carriers[primary_carrier]['avg_ctd']} days. " + (f"Despite having {carriers[primary_carrier]['delayed_count']} delayed shipment(s), it maintained an on-time delivery rate of {carriers[primary_carrier]['on_time_pct']}%." if carriers[primary_carrier]['delayed_count'] > 0 else f"It maintained a perfect on-time delivery rate."),
        "enhanced_next_steps": f"Continue monitoring {primary_carrier} performance. " + (f"Consider addressing issues with {carrier_with_issues} which has a {carriers[carrier_with_issues]['delayed_pct']}% delay rate." if carrier_with_issues else "All carriers are performing within acceptable thresholds."),
        "grounded_metrics": {
            "total_shipments": total,
            "carriers": carriers
        }
    }
    
    return result
