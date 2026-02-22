"""
Shipment Health Check Skill - LLM-powered with deterministic fallback.

Analyzes customer delivery performance vs ZIP benchmark using AI for nuanced insights.
Falls back to deterministic calculation if LLM fails.
"""

import json
import statistics
from typing import Dict, Any, List, Optional
from datetime import datetime

from packages.shared.logging import get_logger
from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor

logger = get_logger(__name__)


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


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute baseline metrics from shipment records (deterministic).
    
    This provides the LLM with pre-calculated metrics to prevent hallucination.
    Also used as fallback if LLM fails.
    """
    if not records:
        return {
            "total_shipments": 0,
            "avg_ctd": 0,
            "median_ctd": 0,
            "ctd_threshold": 3.0,
            "delayed_count": 0,
            "delay_rate": 0,
            "on_time_rate": 100,
            "exception_count": 0,
            "delivered_count": 0,
            "undelivered_count": 0
        }
    
    # Calculate CTD values
    ctd_values = []
    ctd_sources = []
    exception_count = 0
    dates = []
    
    for record in records:
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        ctd_source = "actual"
        
        # Estimated CTD fallback
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
                ctd_source = "estimated"
        
        if ctd is not None:
            try:
                ctd_values.append(float(ctd))
                ctd_sources.append(ctd_source)
            except (ValueError, TypeError):
                pass
        
        # Exception detection
        exc_desc = str(record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION", "") or "")
        if exc_desc and exc_desc.lower() not in ("no exception", "", "none"):
            exception_count += 1
        
        # Track dates
        for date_field in ["BULK_TRACK_DELIVERY_DTTM", "ACTUAL_SHIP_DATE"]:
            date_val = record.get(date_field)
            if date_val:
                try:
                    if isinstance(date_val, str):
                        dates.append(date_val[:10])
                except:
                    pass
    
    # Delivered vs undelivered classification
    delivered_count = 0
    undelivered_count = 0
    for record in records:
        if record.get("BULK_TRACK_DELIVERY_DTTM") is not None:
            delivered_count += 1
        elif (record.get("SHIPMENT_STATUS") or "").upper() == "DELIVERED" or \
             (record.get("WIZMO_CURRENT_PKG_STATUS") or "").upper() == "DELIVERED":
            delivered_count += 1
        else:
            undelivered_count += 1
    
    # Calculate metrics
    total_shipments = len(records)
    avg_ctd = round(statistics.mean(ctd_values), 2) if ctd_values else 0
    median_ctd = round(statistics.median(ctd_values), 1) if ctd_values else 0
    min_ctd = min(ctd_values) if ctd_values else 0
    max_ctd = max(ctd_values) if ctd_values else 0
    
    # CTD threshold (mean + 1 std dev)
    if len(ctd_values) > 1:
        ctd_std = statistics.stdev(ctd_values)
        ctd_threshold = round(avg_ctd + ctd_std, 2) if ctd_std else avg_ctd
    else:
        ctd_threshold = avg_ctd if avg_ctd else 3.0
    
    # Delayed count
    delayed_count = sum(1 for v in ctd_values if v > ctd_threshold)
    delay_rate = round((delayed_count / total_shipments) * 100, 1) if total_shipments > 0 else 0
    on_time_rate = round(100 - delay_rate, 1)
    exception_rate = round((exception_count / total_shipments) * 100, 1) if total_shipments > 0 else 0
    estimated_ctd_count = ctd_sources.count("estimated")
    
    return {
        "total_shipments": total_shipments,
        "avg_ctd": avg_ctd,
        "median_ctd": median_ctd,
        "min_ctd": min_ctd,
        "max_ctd": max_ctd,
        "ctd_threshold": ctd_threshold,
        "delayed_count": delayed_count,
        "delay_rate": delay_rate,
        "on_time_rate": on_time_rate,
        "exception_count": exception_count,
        "exception_rate": exception_rate,
        "delivered_count": delivered_count,
        "undelivered_count": undelivered_count,
        "estimated_ctd_count": estimated_ctd_count,
        "date_range": {
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None
        }
    }


def _deterministic_fallback(
    records: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Deterministic fallback if LLM fails.
    
    Returns basic metrics without AI-powered insights.
    """
    customer_id = context.get("customer_id", "unknown")
    zip_benchmark = context.get("zip_benchmark", {})
    
    # Unwrap S3 dict if needed
    if isinstance(zip_benchmark, dict) and "data" in zip_benchmark:
        bm_list = zip_benchmark["data"]
        zip_benchmark = bm_list[0] if isinstance(bm_list, list) and bm_list else {}
    
    # Get postcode
    postcode = records[0].get("POSTCODE", "Unknown") if records else "Unknown"
    
    # Calculate comparison
    try:
        benchmark_avg_ctd = float(zip_benchmark.get("AVG_CTD", 0) or 0)
    except (ValueError, TypeError):
        benchmark_avg_ctd = 0
    
    ctd_difference = round(baseline["avg_ctd"] - benchmark_avg_ctd, 2) if benchmark_avg_ctd else 0
    
    # Determine comparison status
    if benchmark_avg_ctd:
        if ctd_difference <= -0.5:
            ctd_vs_benchmark = "ABOVE_AVERAGE"
            estimated_percentile = max(10, 50 - int(abs(ctd_difference) * 20))
        elif ctd_difference <= 0.5:
            ctd_vs_benchmark = "AVERAGE"
            estimated_percentile = 50
        else:
            ctd_vs_benchmark = "BELOW_AVERAGE"
            estimated_percentile = min(90, 50 + int(ctd_difference * 20))
    else:
        ctd_vs_benchmark = "NO_BENCHMARK"
        estimated_percentile = 50
    
    # Identify red flags
    red_flags = []
    if benchmark_avg_ctd and baseline["avg_ctd"] > benchmark_avg_ctd + 1:
        red_flags.append(f"CTD {baseline['avg_ctd']} days exceeds benchmark by {ctd_difference} days")
    if baseline["delay_rate"] > 15:
        red_flags.append(f"High delay rate: {baseline['delay_rate']}%")
    if baseline["exception_rate"] > 5:
        red_flags.append(f"High exception rate: {baseline['exception_rate']}%")
    
    # Determine health status
    if len(red_flags) == 0:
        health_status = "HEALTHY"
        primary_finding = "Customer delivery performance is healthy vs ZIP benchmark"
    elif len(red_flags) <= 2:
        health_status = "ATTENTION"
        primary_finding = f"Minor delivery concerns: {red_flags[0]}"
    else:
        health_status = "CRITICAL"
        primary_finding = f"Multiple delivery issues identified: {len(red_flags)} red flags"
    
    return {
        "skill": "shipment_health_check",
        "grounded_metrics": {
            "customer_id": customer_id,
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "customer_performance": {
                "total_shipments": baseline["total_shipments"],
                "avg_ctd": baseline["avg_ctd"],
                "median_ctd": baseline["median_ctd"],
                "min_ctd": baseline["min_ctd"],
                "max_ctd": baseline["max_ctd"],
                "delayed_shipments": baseline["delayed_count"],
                "delay_rate_pct": baseline["delay_rate"],
                "on_time_rate_pct": baseline["on_time_rate"],
                "exception_count": baseline["exception_count"],
                "exception_rate_pct": baseline["exception_rate"],
                "delivered_count": baseline["delivered_count"],
                "undelivered_count": baseline["undelivered_count"],
                "date_range": baseline["date_range"]
            },
            "zip_performance": {
                "postcode": postcode,
                "total_shipments": baseline["total_shipments"],
                "avg_ctd": baseline["avg_ctd"],
                "delay_rate_pct": baseline["delay_rate"]
            },
            "zip_benchmark": {
                "postcode": postcode,
                "benchmark_avg_ctd": benchmark_avg_ctd,
                "benchmark_median_ctd": zip_benchmark.get("MEDIAN_CTD", 0),
                "benchmark_min_ctd": zip_benchmark.get("MIN_CTD", 0),
                "benchmark_max_ctd": zip_benchmark.get("MAX_CTD", 0),
                "benchmark_shipment_count": zip_benchmark.get("TOTAL_SHIPMENTS", 0)
            },
            "comparison": {
                "customer_avg_ctd": baseline["avg_ctd"],
                "benchmark_avg_ctd": benchmark_avg_ctd,
                "ctd_difference_days": ctd_difference,
                "ctd_vs_benchmark": ctd_vs_benchmark,
                "estimated_percentile": estimated_percentile
            },
            "health_status": health_status,
            "red_flags": red_flags,
            "ctd_threshold": baseline["ctd_threshold"],
            "delay_definition": f"CTD > {baseline['ctd_threshold']} days (mean + 1 std dev)"
        },
        "continued_analysis": f"Deterministic analysis for customer {customer_id}: {baseline['total_shipments']} shipments, avg CTD {baseline['avg_ctd']} days, {baseline['on_time_rate']}% on-time rate. {health_status} status.",
        "enhanced_next_steps": ["LLM analysis unavailable - showing basic metrics only"],
        "health_status": health_status,
        "primary_finding": primary_finding,
        "llm_fallback": True
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """
    Execute the shipment health check skill with LLM analysis.
    
    Falls back to deterministic calculation if LLM fails.
    """
    customer_id = state.get("customer_id", "unknown")
    
    # Get shipment data from state
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {
            "skill": "shipment_health_check",
            "error": "No shipment data available",
            "grounded_metrics": {
                "total_shipments": 0,
                "health_status": "UNKNOWN"
            }
        }
    
    # Step 1: Compute baseline metrics (deterministic)
    logger.info(f"Computing baseline metrics for {customer_id}, {len(records)} records")
    baseline_metrics = _compute_baseline_metrics(records)
    
    # Step 2: Prepare context for LLM
    zip_perf = shipment_data.get("customer_zip_performance") or shipment_data.get("customer_zip") or {}
    zip_benchmark = shipment_data.get("benchmark_zip_performance") or shipment_data.get("benchmark_zip") or {}
    
    context = {
        "customer_id": customer_id,
        "zip_benchmark": zip_benchmark
    }
    
    # Step 3: Execute with LLM
    executor = LLMSkillExecutor(
        skill_name="shipment_health_check",
        reasoning_effort="medium"
    )
    
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50  # Limit for cost control
    )
    
    return result
