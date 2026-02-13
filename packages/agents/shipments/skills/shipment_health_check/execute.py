"""
Shipment Health Check Skill - BASE skill for shipments analysis.

Computes customer delivery performance vs ZIP benchmark.
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
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
    """
    Execute the shipment health check skill.
    
    This is a BASE skill that runs on raw data without LLM calls.
    All metrics are pre-calculated in Python to prevent hallucination.
    """
    customer_id = state.get("customer_id", "unknown")
    
    # Get shipment data from state
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {
            "error": "No shipment data available",
            "grounded_metrics": {
                "total_shipments": 0,
                "health_status": "UNKNOWN"
            }
        }
    
    # Calculate customer performance metrics
    ctd_values = []
    ctd_sources = []  # Track whether each CTD is "actual" or "estimated"
    exception_count = 0
    dates = []

    for record in records:
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        ctd_source = "actual"

        if ctd is None:
            # Estimated CTD fallback: compute from available dates
            #   delivery proxy: BULK_TRACK_DELIVERY_DTTM -> SHIPMENT_ESTIMATED_DELIVERY_DATE
            #                   -> WIZMO_CURRENT_ARRIVAL_DATE -> LAST_EXPECTED_DELIVERY_DATE
            #   order date: ORDER_PLACED_DTTM
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

        # S3 uses BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION (not EXCEPTION_FLAG)
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
    
    # Delivered classification with fallback:
    #   Primary: BULK_TRACK_DELIVERY_DTTM is not None
    #   Fallback: SHIPMENT_STATUS or WIZMO_CURRENT_PKG_STATUS == "DELIVERED"
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

    total_shipments = len(records)
    avg_ctd = round(statistics.mean(ctd_values), 2) if ctd_values else 0

    # Compute CTD threshold (mean + 1 std dev) for delay detection
    if len(ctd_values) > 1:
        ctd_std = statistics.stdev(ctd_values)
        ctd_threshold = round(avg_ctd + ctd_std, 2) if ctd_std else avg_ctd
    else:
        ctd_threshold = avg_ctd if avg_ctd else 3.0

    # Delayed = CTD > threshold (pure CTD-based detection)
    delayed_count = sum(1 for v in ctd_values if v > ctd_threshold)
    estimated_ctd_count = ctd_sources.count("estimated")
    median_ctd = round(statistics.median(ctd_values), 1) if ctd_values else 0
    min_ctd = min(ctd_values) if ctd_values else 0
    max_ctd = max(ctd_values) if ctd_values else 0
    delay_rate = round((delayed_count / total_shipments) * 100, 1) if total_shipments > 0 else 0
    on_time_rate = round(100 - delay_rate, 1)
    exception_rate = round((exception_count / total_shipments) * 100, 1) if total_shipments > 0 else 0
    
    # Get ZIP performance data (check node uses shortened keys: customer_zip, benchmark_zip)
    zip_perf = shipment_data.get("customer_zip_performance") or shipment_data.get("customer_zip") or {}
    benchmark = shipment_data.get("benchmark_zip_performance") or shipment_data.get("benchmark_zip") or {}
    # Unwrap S3 dict if needed
    if isinstance(zip_perf, dict) and "data" in zip_perf:
        zp_list = zip_perf["data"]
        zip_perf = zp_list[0] if isinstance(zp_list, list) and zp_list else {}
    if isinstance(benchmark, dict) and "data" in benchmark:
        bm_list = benchmark["data"]
        benchmark = bm_list[0] if isinstance(bm_list, list) and bm_list else {}
    
    postcode = zip_perf.get("POSTCODE") or records[0].get("POSTCODE", "Unknown") if records else "Unknown"
    
    # Calculate comparison
    try:
        benchmark_avg_ctd = float(benchmark.get("AVG_CTD", 0) or 0)
    except (ValueError, TypeError):
        benchmark_avg_ctd = 0
    ctd_difference = round(avg_ctd - benchmark_avg_ctd, 2) if benchmark_avg_ctd else 0
    
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
    if benchmark_avg_ctd and avg_ctd > benchmark_avg_ctd + 1:
        red_flags.append(f"CTD {avg_ctd} days exceeds benchmark by {ctd_difference} days")
    if delay_rate > 15:
        red_flags.append(f"High delay rate: {delay_rate}%")
    if exception_rate > 5:
        red_flags.append(f"High exception rate: {exception_rate}%")
    
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
    
    # Build observations (key findings as bullet points)
    observations = [
        f"Total shipments in analysis period: {total_shipments} ({delivered_count} delivered, {undelivered_count} undelivered/in-transit)",
        f"Average CTD: {avg_ctd} days (median: {median_ctd} days), threshold: {ctd_threshold} days",
        f"On-time delivery rate: {on_time_rate}% (delayed = CTD > {ctd_threshold} days)",
        f"Delayed shipments: {delayed_count} ({delay_rate}%)",
    ]
    if estimated_ctd_count > 0:
        observations.append(
            f"Note: {estimated_ctd_count} shipment(s) used estimated CTD from expected delivery dates"
        )
    
    if benchmark_avg_ctd:
        observations.append(f"ZIP {postcode} benchmark CTD: {benchmark_avg_ctd} days")
        observations.append(f"Customer vs benchmark: {ctd_vs_benchmark} ({estimated_percentile}th percentile)")
    
    if exception_count > 0:
        observations.append(f"Exception rate: {exception_rate}%")
    
    for flag in red_flags:
        observations.append(f"⚠️ RED FLAG: {flag}")
    
    # Build synthesis (detailed paragraph with specific data points)
    date_range_str = f"{min(dates)} to {max(dates)}" if dates else "date range unknown"
    
    synthesis = (
        f"Analyzed {total_shipments} shipments for customer {customer_id} from {date_range_str}. "
        f"Customer's average Click-to-Deliver time is {avg_ctd} days (median {median_ctd}), "
        f"compared to the ZIP {postcode} benchmark of {benchmark_avg_ctd} days. "
        f"This places the customer at the {estimated_percentile}th percentile ({ctd_vs_benchmark}). "
        f"On-time rate is {on_time_rate}% with {delayed_count} delayed shipments and {exception_count} exceptions. "
    )
    
    if health_status == "HEALTHY":
        synthesis += "Overall shipment health is HEALTHY with no significant concerns."
    elif health_status == "ATTENTION":
        synthesis += f"Health status requires ATTENTION due to: {red_flags[0] if red_flags else 'minor concerns'}."
    else:
        synthesis += f"CRITICAL health status identified with {len(red_flags)} red flags requiring immediate review."
    
    # Build summary for quick reference
    summary = {
        "health_status": health_status,
        "total_shipments": total_shipments,
        "avg_ctd": avg_ctd,
        "benchmark_ctd": benchmark_avg_ctd,
        "on_time_rate": on_time_rate,
        "percentile": estimated_percentile,
        "red_flag_count": len(red_flags)
    }
    
    # Build result
    result = {
        "skill": "shipment_health_check",
        "skill_type": "BASE_ANALYSIS",
        "observations": observations,
        "synthesis": synthesis,
        "summary": summary,
        "grounded_metrics": {
            "customer_id": customer_id,
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "customer_performance": {
                "total_shipments": total_shipments,
                "avg_ctd": avg_ctd,
                "median_ctd": median_ctd,
                "min_ctd": min_ctd,
                "max_ctd": max_ctd,
                "delayed_shipments": delayed_count,
                "delay_rate_pct": delay_rate,
                "on_time_rate_pct": on_time_rate,
                "exception_count": exception_count,
                "exception_rate_pct": exception_rate,
                "date_range": {
                    "earliest": min(dates) if dates else None,
                    "latest": max(dates) if dates else None
                }
            },
            "zip_performance": {
                "postcode": postcode,
                "total_shipments": zip_perf.get("TOTAL_SHIPMENTS", total_shipments),
                "avg_ctd": zip_perf.get("AVG_CTD", avg_ctd),
                "delay_rate_pct": zip_perf.get("DELAY_RATE", delay_rate)
            },
            "zip_benchmark": {
                "postcode": postcode,
                "benchmark_avg_ctd": benchmark_avg_ctd,
                "benchmark_median_ctd": benchmark.get("MEDIAN_CTD", 0),
                "benchmark_min_ctd": benchmark.get("MIN_CTD", 0),
                "benchmark_max_ctd": benchmark.get("MAX_CTD", 0),
                "benchmark_shipment_count": benchmark.get("TOTAL_SHIPMENTS", 0)
            },
            "comparison": {
                "customer_avg_ctd": avg_ctd,
                "benchmark_avg_ctd": benchmark_avg_ctd,
                "ctd_difference_days": ctd_difference,
                "ctd_vs_benchmark": ctd_vs_benchmark,
                "estimated_percentile": estimated_percentile
            },
            "health_status": health_status,
            "red_flags": red_flags,
            "delivered_count": delivered_count,
            "undelivered_count": undelivered_count,
            "ctd_threshold": ctd_threshold,
            "estimated_ctd_count": estimated_ctd_count,
            "delay_definition": f"CTD > {ctd_threshold} days (mean + 1 std dev)"
        },
        "continued_analysis": synthesis,
        "enhanced_next_steps": [
            "Review carrier analysis for carrier-specific patterns",
            "Check exception analysis for recurring issues",
            "Analyze timing patterns for optimal shipping days"
        ] if health_status != "HEALTHY" else ["Monitor for changes in delivery patterns"],
        "health_status": health_status,
        "primary_finding": primary_finding
    }
    
    return result
