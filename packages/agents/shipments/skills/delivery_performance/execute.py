"""
Delivery Performance Skill - Analyzes CTD patterns and identifies delayed shipments.
"""

import json
import os
from typing import Dict, Any, List
from datetime import datetime
import statistics

from openai import OpenAI
from packages.agents.shipments.skills.loader import load_skill_instructions

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the delivery performance skill."""
    customer_id = state.get("customer_id", "unknown")
    prompt_logger = state.get("prompt_logger")
    
    # Get shipment data
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    baseline = shipment_data.get("baseline", {})
    
    if not records:
        return {
            "skill": "delivery_performance",
            "error": "No shipment data available",
            "grounded_metrics": {"total_shipments": 0}
        }
    
    # Pre-calculate grounded metrics (no LLM needed for these)
    ctd_values = []
    delayed_shipments = []
    carrier_stats = {}
    fc_stats = {}
    
    ctd_threshold = baseline.get("ctd_threshold", 3.0)
    
    for record in records:
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        if ctd is not None:
            try:
                ctd_val = float(ctd)
                ctd_values.append(ctd_val)
                
                # Track delayed (S3 uses boolean true/null, not "Y" string)
                if ctd_val > ctd_threshold or record.get("SHIPMENT_WAS_DELAYED") is True:
                    delayed_shipments.append({
                        "order_id": record.get("ORDER_ID"),
                        "tracking_number": record.get("SHIPMENT_TRACKING_NUMBER"),
                        "ctd_days": ctd_val,
                        "carrier": record.get("WAREHOUSE_CARRIER"),
                        "fc": record.get("FFMCENTER_NAME"),
                        "reason": "Exceeded threshold" if ctd_val > ctd_threshold else "Marked delayed"
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
    
    total = len(records)
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
    
    # Build grounded metrics
    grounded_metrics = {
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
        "delay_definition": f"CTD > {ctd_threshold} days OR SHIPMENT_WAS_DELAYED=true"
    }
    
    # Determine health status
    if delayed_pct <= 5:
        health = "HEALTHY"
    elif delayed_pct <= 15:
        health = "ATTENTION"
    else:
        health = "CRITICAL"
    
    # Build observations
    observations = [
        f"Total shipments processed: {total}, all delivered.",
        f"Average Click-to-Deliver (CTD) time is {avg_ctd} days, with a maximum of {max_ctd} days.",
        f"{delayed_pct}% of shipments ({delayed_count} out of {total}) exceeded the {ctd_threshold}-day CTD threshold."
    ]
    
    # Add delayed shipment details
    for ds in delayed_shipments[:3]:  # Limit to first 3
        observations.append(
            f"The delayed shipment (Order ID: {ds['order_id']}, Tracking Number: {ds['tracking_number']}) had a CTD of {ds['ctd_days']} days."
        )
    
    # Add carrier info
    if carrier_summary:
        primary_carrier = max(carrier_summary.items(), key=lambda x: x[1]["count"])
        observations.append(
            f"{primary_carrier[0]} accounted for {primary_carrier[1]['percentage']}% of shipments, averaging a CTD of {primary_carrier[1]['avg_ctd']} days."
        )
    
    # Add FC info
    if fc_summary:
        best_fc = min(fc_summary.items(), key=lambda x: x[1]["avg_ctd"])
        observations.append(
            f"{best_fc[0]} fulfillment center had the best performance with an average CTD of {best_fc[1]['avg_ctd']} days."
        )
    
    # Add trend
    if trend_direction != "INSUFFICIENT_DATA":
        observations.append(
            f"The trend analysis indicates {'an improving' if trend_direction == 'IMPROVING' else 'a stable' if trend_direction == 'STABLE' else 'a declining'} CTD performance, with a change of {trend_change} days from the first half to the second half of the period."
        )
    
    # Build result
    result = {
        "skill": "delivery_performance",
        "observations": observations,
        "summary": {
            "overall_health": health,
            "primary_finding": f"CTD averaging {avg_ctd} days {'is stable' if health == 'HEALTHY' else 'has ' + str(delayed_pct) + '% of shipments exceeding the ' + str(ctd_threshold) + '-day threshold.'}",
            "trend_direction": trend_direction
        },
        "continued_analysis": f"The delivery performance analysis shows that while the average Click-to-Deliver (CTD) time is {avg_ctd} days, there {'are no major concerns' if delayed_count == 0 else f'is a notable concern with {delayed_pct}% of shipments exceeding the {ctd_threshold}-day threshold'}. {'No shipments were delayed.' if delayed_count == 0 else f'The delayed shipments include Order IDs: {', '.join([str(d['order_id']) for d in delayed_shipments[:3] if d.get('order_id')])}.'} The overall trend is {trend_direction.lower()}, with a change of {trend_change} days in CTD from the first half to the second half of the analysis period.",
        "enhanced_next_steps": f"{'Continue monitoring shipment performance.' if health == 'HEALTHY' else 'Monitor the performance of delayed shipments closely. ' + ('Focus on ' + primary_carrier[0] + ' carrier performance.' if carrier_summary else '')}",
        "flagged_shipments": delayed_shipments,
        "grounded_metrics": grounded_metrics
    }
    
    return result
