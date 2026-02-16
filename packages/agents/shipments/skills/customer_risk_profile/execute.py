"""
Customer Risk Profile Skill - Deterministic cross-skill risk computation.

Runs after Phase 1 + Phase 2. Reads all upstream skill results and computes
four risk dimensions purely in Python (no LLM call):

  1. Temporal Recency  - classify signals by age
  2. Pattern Correlation - group signals by carrier + route
  3. Forward Risk      - estimate future delay exposure
  4. Relationship Signal - WISMO, contacts, product criticality

Output: structured risk profile with overall_risk_level.
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers to safely extract nested values from state
# ---------------------------------------------------------------------------

def _get_grounded(state: Dict[str, Any], result_key: str) -> Dict[str, Any]:
    """Return grounded_metrics from a skill result, or empty dict."""
    result = state.get(result_key)
    if isinstance(result, dict):
        return result.get("grounded_metrics") or result.get("summary") or {}
    return {}


def _get_signals(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the signals list from the signal generator result."""
    result = state.get("shipment_signal_generator_result")
    if isinstance(result, dict):
        return result.get("signals") or []
    return []


# ---------------------------------------------------------------------------
# Dimension 1: Temporal Recency
# ---------------------------------------------------------------------------

def _compute_temporal_recency(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify signals into recency buckets and summarise."""
    active: List[Dict[str, Any]] = []
    recent: List[Dict[str, Any]] = []
    historical: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []

    for sig in signals:
        recency = sig.get("recency", "unknown")
        detail = {
            "signal_id": sig.get("signal_id"),
            "orders_order_id": sig.get("orders_order_id"),
            "signal_type": sig.get("signal_type"),
            "severity": sig.get("severity"),
            "days_since_event": sig.get("days_since_event"),
        }
        if recency == "active":
            active.append(detail)
        elif recency == "recent":
            recent.append(detail)
        elif recency == "historical":
            historical.append(detail)
        else:
            unknown.append(detail)

    total = len(signals)
    parts: List[str] = []
    if active:
        parts.append(f"{len(active)} active (not yet delivered)")
    if recent:
        parts.append(f"{len(recent)} recent (within 14 days)")
    if historical:
        parts.append(f"{len(historical)} historical (>14 days)")

    if total == 0:
        finding = "No signals detected."
    elif not active and not recent:
        finding = (
            f"All {len(historical)} signal(s) are historical (>14 days old). "
            "No current deliveries at risk."
        )
    else:
        finding = f"Of {total} signals: {', '.join(parts)}."

    return {
        "active_signals": len(active),
        "recent_signals": len(recent),
        "historical_signals": len(historical),
        "total_signals": total,
        "active_details": active if active else None,
        "recent_details": recent if recent else None,
        "finding": finding,
    }


# ---------------------------------------------------------------------------
# Dimension 2: Pattern Correlation
# ---------------------------------------------------------------------------

def _build_record_lookups(
    state: Dict[str, Any],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Build lookups from order ID and tracking number to raw shipment records.

    Handles two data source conventions:
      - main_shipment_query: ORDERS_ORDER_ID, WAREHOUSE_CARRIER
      - shipment_inspector_query: ORDER_ID, CARRIER_CODE
    """
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])

    by_order: Dict[str, Dict[str, Any]] = {}
    by_tracking: Dict[str, Dict[str, Any]] = {}

    for r in records:
        oid = str(r.get("ORDERS_ORDER_ID") or r.get("ORDER_ID") or "")
        if oid:
            by_order[oid] = r

        tn = str(r.get("SHIPMENT_TRACKING_NUMBER") or "")
        if tn:
            by_tracking[tn] = r

    return by_order, by_tracking


def _get_carrier_fc(record: Dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract carrier and FC from a record, handling field name variants."""
    carrier = record.get("WAREHOUSE_CARRIER")
    if not carrier:
        carrier = record.get("CARRIER_CODE")
    fc = record.get("FFMCENTER_NAME")
    return carrier, fc


def _compute_pattern_correlation(
    signals: List[Dict[str, Any]],
    carrier_metrics: Dict[str, Any],
    by_order: Dict[str, Dict[str, Any]],
    by_tracking: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Group signals by carrier+FC and find the dominant pattern.

    Looks up carrier and fulfillment center from the raw shipment records
    (by order ID or tracking number) rather than parsing LLM free text.
    """
    carrier_groups: Dict[str, Dict[str, Any]] = {}

    for sig in signals:
        order_id = str(sig.get("orders_order_id") or "")
        tracking = str(sig.get("shipment_tracking_number") or "")
        record = by_order.get(order_id) or by_tracking.get(tracking) or {}
        carrier, fc = _get_carrier_fc(record)
        if not carrier:
            continue

        if carrier not in carrier_groups:
            carrier_groups[carrier] = {
                "carrier": carrier,
                "fcs": set(),
                "signal_count": 0,
                "signal_ids": [],
            }
        if fc:
            carrier_groups[carrier]["fcs"].add(fc)
        carrier_groups[carrier]["signal_count"] += 1
        carrier_groups[carrier]["signal_ids"].append(sig.get("signal_id"))

    group_list = []
    for g in sorted(carrier_groups.values(), key=lambda x: -x["signal_count"]):
        carrier_info = carrier_metrics.get(g["carrier"], {})
        group_list.append({
            "carrier": g["carrier"],
            "routes": sorted(g["fcs"]),
            "signal_count": g["signal_count"],
            "signal_ids": g["signal_ids"],
            "carrier_delay_rate_pct": carrier_info.get("delayed_pct"),
            "carrier_avg_ctd": carrier_info.get("avg_ctd"),
        })

    total = len(signals)
    dominant = group_list[0] if group_list else None

    if not dominant or total == 0:
        finding = "No carrier pattern identified."
    elif dominant["signal_count"] == total and total > 1:
        routes_str = ", ".join(dominant["routes"]) if dominant["routes"] else "unknown"
        finding = (
            f"All {total} delay signals involve {dominant['carrier']} "
            f"via {routes_str}."
        )
    elif dominant["signal_count"] > 1:
        pct = round(dominant["signal_count"] / total * 100, 0)
        routes_str = ", ".join(dominant["routes"]) if dominant["routes"] else "unknown"
        finding = (
            f"{dominant['signal_count']} of {total} delays "
            f"({pct:.0f}%) share {dominant['carrier']} via "
            f"{routes_str}."
        )
        delay_pct = dominant.get("carrier_delay_rate_pct")
        if delay_pct is not None:
            finding += f" Carrier delay rate: {delay_pct}%."
    else:
        finding = "No dominant carrier pattern across signals."

    return {
        "dominant_pattern": (
            f"{dominant['carrier']} via {', '.join(dominant['routes'])}"
            if dominant and dominant["signal_count"] > 1 and dominant["routes"]
            else None
        ),
        "carrier_route_groups": group_list,
        "finding": finding,
    }


# ---------------------------------------------------------------------------
# Dimension 3: Forward Risk
# ---------------------------------------------------------------------------

def _compute_forward_risk(
    order_metrics: Dict[str, Any],
    delivery_metrics: Dict[str, Any],
    carrier_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Estimate future delay exposure from autoship, carrier, and trend data."""
    autoship_rate = order_metrics.get("autoship_rate", 0.0)
    order_freq = order_metrics.get("order_frequency", 0.0)
    trend_dir = delivery_metrics.get("trend_direction", "STABLE")
    trend_change = delivery_metrics.get("trend_change", 0.0)

    # Find the primary carrier's delay rate
    carriers = carrier_metrics.get("carriers", {})
    primary_carrier: Optional[str] = None
    primary_share: float = 0.0
    primary_delay_rate: float = 0.0
    for name, info in carriers.items():
        if name in ("null", "None", None):
            continue
        share = info.get("percentage", 0.0)
        if share > primary_share:
            primary_share = share
            primary_carrier = name
            primary_delay_rate = info.get("delayed_pct", 0.0)

    # Estimated delayed orders per month
    if order_freq > 0 and primary_share > 0:
        carrier_fraction = primary_share / 100.0
        delay_fraction = primary_delay_rate / 100.0
        estimated_delays = round(order_freq * carrier_fraction * delay_fraction, 1)
    else:
        estimated_delays = 0.0

    # Risk level
    trend_upper = trend_dir.upper() if trend_dir else "STABLE"
    if estimated_delays >= 2.0 and trend_upper == "DECLINING":
        risk_level = "high"
    elif estimated_delays >= 1.0 or trend_upper == "DECLINING":
        risk_level = "elevated"
    elif estimated_delays > 0:
        risk_level = "moderate"
    else:
        risk_level = "low"

    parts: List[str] = []
    if order_freq > 0:
        parts.append(f"{order_freq} orders/month")
    if autoship_rate > 0:
        parts.append(f"{autoship_rate}% autoship")
    if primary_carrier:
        parts.append(
            f"{primary_carrier} ({primary_share}% share, "
            f"{primary_delay_rate}% delay rate)"
        )

    if estimated_delays > 0:
        finding = (
            f"At {', '.join(parts)}, expect ~{estimated_delays} "
            f"delayed order(s)/month if routing unchanged."
        )
        if trend_upper == "DECLINING":
            finding += f" Trend is declining (+{trend_change} days CTD shift)."
    elif not parts:
        finding = "Insufficient data to estimate forward risk."
    else:
        finding = f"Low forward risk. {', '.join(parts)}."

    return {
        "autoship_rate_pct": autoship_rate,
        "orders_per_month": order_freq,
        "trend_direction": trend_dir,
        "trend_change_days": trend_change,
        "primary_carrier": primary_carrier,
        "primary_carrier_share_pct": primary_share,
        "primary_carrier_delay_rate_pct": primary_delay_rate,
        "estimated_delays_per_month": estimated_delays,
        "risk_level": risk_level,
        "finding": finding,
    }


# ---------------------------------------------------------------------------
# Dimension 4: Relationship Signal
# ---------------------------------------------------------------------------

_RX_KEYWORDS = (
    "apoquel", "rx", "prescription", "medication", "tablet", "capsule",
    "ointment", "injection", "insulin", "vetmedin", "gabapentin",
    "prednisone", "carprofen", "meloxicam", "tramadol",
)


def _has_rx_products(signals: List[Dict[str, Any]]) -> bool:
    """Check if any signal involves Rx / prescription products."""
    for sig in signals:
        text = (
            (sig.get("observation") or "")
            + " "
            + (sig.get("analysis") or "")
        ).lower()
        if any(kw in text for kw in _RX_KEYWORDS):
            return True
    return False


def _compute_relationship_signal(
    contact_metrics: Dict[str, Any],
    current_order_metrics: Dict[str, Any],
    signals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Combine engagement and product context into a relationship signal."""
    contact_rate = contact_metrics.get("contact_rate", 0.0)
    wismo_rate = contact_metrics.get("wismo_rate", 0.0)
    at_risk = current_order_metrics.get("at_risk_orders", 0)
    has_rx = _has_rx_products(signals)

    total_signals = len(signals)
    recent_or_active = sum(
        1 for s in signals if s.get("recency") in ("recent", "active")
    )

    parts: List[str] = []
    if wismo_rate > 0:
        parts.append(f"WISMO rate is {wismo_rate}% (customer is already escalating)")
    elif total_signals > 0:
        parts.append(
            f"0% WISMO despite {total_signals} delay signal(s) "
            "(customer has not escalated yet)"
        )

    if contact_rate > 0:
        parts.append(f"Contact rate: {contact_rate}%")

    if has_rx:
        parts.append("Rx medication on record (elevated care sensitivity)")

    if at_risk > 0:
        parts.append(f"{at_risk} active order(s) currently at risk")

    finding = ". ".join(parts) + "." if parts else "No relationship signals."

    return {
        "contact_rate_pct": contact_rate,
        "wismo_rate_pct": wismo_rate,
        "has_rx_on_autoship": has_rx,
        "active_at_risk": at_risk,
        "recent_or_active_signals": recent_or_active,
        "finding": finding,
    }


# ---------------------------------------------------------------------------
# Overall risk level
# ---------------------------------------------------------------------------

def _compute_overall_risk(
    temporal: Dict[str, Any],
    pattern: Dict[str, Any],
    forward: Dict[str, Any],
    relationship: Dict[str, Any],
) -> str:
    """Determine the overall customer risk level from the four dimensions."""
    active = temporal.get("active_signals", 0)
    recent = temporal.get("recent_signals", 0)
    total = temporal.get("total_signals", 0)

    has_pattern = pattern.get("dominant_pattern") is not None
    forward_level = forward.get("risk_level", "low")
    trend = (forward.get("trend_direction") or "STABLE").upper()
    has_rx = relationship.get("has_rx_on_autoship", False)
    at_risk = relationship.get("active_at_risk", 0)

    # High: active shipments at risk, or recent signals with Rx impact
    if active > 0 or at_risk > 0:
        return "high"
    if recent > 0 and has_rx:
        return "high"

    # Elevated: carrier pattern + declining + high autoship, or forward = high
    if forward_level == "high":
        return "elevated"
    if has_pattern and trend == "DECLINING":
        return "elevated"
    if recent > 0:
        return "elevated"

    # Moderate: some signals but all historical
    if total > 0:
        return "moderate"

    return "low"


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(
    state: Dict[str, Any],
    target_key: str = "",
    peer_level: str = "SEGMENT",
) -> Dict[str, Any]:
    """
    Compute the customer risk profile deterministically from Phase 1+2 results.

    No LLM call. Returns structured risk dimensions and overall risk level.
    """
    customer_id = state.get("customer_id", "unknown")
    signals = _get_signals(state)

    carrier_metrics = _get_grounded(state, "carrier_analysis_result")
    delivery_metrics = _get_grounded(state, "delivery_performance_result")
    order_metrics = _get_grounded(state, "order_behavior_result")
    contact_metrics = _get_grounded(state, "contact_correlation_result")
    current_order_metrics = _get_grounded(state, "current_order_result")
    by_order, by_tracking = _build_record_lookups(state)

    temporal = _compute_temporal_recency(signals)
    pattern = _compute_pattern_correlation(
        signals, carrier_metrics.get("carriers", {}), by_order, by_tracking,
    )
    forward = _compute_forward_risk(order_metrics, delivery_metrics, carrier_metrics)
    relationship = _compute_relationship_signal(
        contact_metrics, current_order_metrics, signals,
    )

    overall = _compute_overall_risk(temporal, pattern, forward, relationship)

    return {
        "skill": "customer_risk_profile",
        "customer_id": customer_id,
        "overall_risk_level": overall,
        "risk_dimensions": {
            "temporal_recency": temporal,
            "pattern_correlation": pattern,
            "forward_risk": forward,
            "relationship_signal": relationship,
        },
        "grounded_metrics": {
            "signals_count": len(signals),
            "carrier_source": "carrier_analysis_result",
            "delivery_source": "delivery_performance_result",
            "order_source": "order_behavior_result",
            "contact_source": "contact_correlation_result",
            "current_order_source": "current_order_result",
        },
        "observations": [
            f"Overall risk level: {overall}",
            f"Temporal: {temporal['finding']}",
            f"Pattern: {pattern['finding']}",
            f"Forward: {forward['finding']}",
            f"Relationship: {relationship['finding']}",
        ],
        "summary": {
            "overall_risk_level": overall,
            "total_signals": len(signals),
            "recent_signals": temporal.get("recent_signals", 0),
            "active_signals": temporal.get("active_signals", 0),
            "dominant_pattern": pattern.get("dominant_pattern"),
            "forward_risk_level": forward.get("risk_level"),
        },
    }
