"""
Shipment Signal Generator Skill - Execution Logic

Analyzes shipment data to generate signals/observations for proactive care.

Architecture:
  1. Python pre-filter deterministically flags anomalous records.
  2. Only flagged (trimmed) records + a normal-shipment summary are sent to the LLM.
  3. LLM generates contextualised signals with analysis and intervention-needed flags.

This avoids prompt bloat (274 -> 26 fields, 50 -> ~3-8 records) and eliminates
the non-deterministic "0 signals vs 30 signals" variance.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from dateutil import parser as dateutil_parser
from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_instructions, load_reference_docs
from packages.agents.shipments.skills.record_trimmer import trim_record, trim_records

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")

RECENCY_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_datetime(value: Any) -> datetime | None:
    """Safely parse a datetime string into a timezone-aware datetime."""
    if value is None:
        return None
    try:
        dt = dateutil_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Anomaly detection (deterministic, runs in Python)
# ---------------------------------------------------------------------------

def _flag_anomalies(
    records: List[Dict[str, Any]],
    baseline: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Split records into (anomalous, normal) lists.

    A record is flagged as anomalous if ANY of these conditions hold:
      - CTD exceeds the baseline threshold (ctd_avg + 1 std dev)
      - SHIPMENT_WAS_DELAYED is truthy
      - Active / in-transit (no delivery date and status != DELIVERED)
      - Carrier exception present
      - Fresh/Rx items with CTD above threshold

    NOTE: ONTIME_DELIVERY_FLAG is intentionally NOT used (unreliable).

    Each anomalous record gets:
      - ``_flags``: list of reasons it was flagged
      - ``_recency``: "active" | "recent" | "historical"
      - ``_days_since_event``: int days since delivery (0 for active)
    """
    ctd_threshold = baseline.get("ctd_threshold", 5.0)
    now = datetime.now(timezone.utc)

    anomalous: List[Dict[str, Any]] = []
    normal: List[Dict[str, Any]] = []

    for record in records:
        flags: List[str] = []

        # --- CTD exceeds threshold ---
        ctd = record.get("CLICK_TO_DELIVER_DAYS")
        if ctd is not None:
            try:
                if float(ctd) > ctd_threshold:
                    flags.append(f"CTD {ctd} exceeds threshold {ctd_threshold}")
            except (ValueError, TypeError):
                pass

        # --- Explicitly flagged as delayed ---
        if record.get("SHIPMENT_WAS_DELAYED"):
            flags.append("SHIPMENT_WAS_DELAYED=True")

        # --- Active / in-transit (not yet delivered) ---
        delivery_dttm = record.get("BULK_TRACK_DELIVERY_DTTM")
        shipment_status = (record.get("SHIPMENT_STATUS") or "").upper()
        tracking_status = (record.get("BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION") or "").upper()
        is_delivered = (
            delivery_dttm is not None
            or shipment_status == "DELIVERED"
            or tracking_status == "DELIVERED"
        )
        if not is_delivered:
            flags.append("Active/in-transit (not yet delivered)")

        # --- Carrier exception ---
        exception = record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION")
        if exception and str(exception).strip():
            exc_upper = str(exception).strip().upper()
            if exc_upper not in ("NO EXCEPTION", "NONE", "N/A", "NA", "NULL", ""):
                flags.append(f"Exception: {exception}")

        # --- Fresh/perishable with elevated CTD ---
        is_fresh = record.get("SHIPMENT_CONTAINS_FRESH")
        if is_fresh and ctd is not None:
            try:
                if float(ctd) > max(ctd_threshold * 0.75, 3.0):
                    flags.append(f"Fresh item with CTD {ctd}")
            except (ValueError, TypeError):
                pass

        if flags:
            trimmed = trim_record(record)
            trimmed["_flags"] = flags

            # --- Recency classification ---
            if not is_delivered:
                trimmed["_recency"] = "active"
                trimmed["_days_since_event"] = 0
            else:
                delivery_dt = _parse_datetime(delivery_dttm)
                if delivery_dt:
                    days_since = (now - delivery_dt).days
                    trimmed["_days_since_event"] = max(days_since, 0)
                    trimmed["_recency"] = (
                        "recent" if days_since <= RECENCY_WINDOW_DAYS else "historical"
                    )
                else:
                    order_dt = _parse_datetime(record.get("ORDER_PLACED_DTTM"))
                    if order_dt:
                        days_since = (now - order_dt).days
                        trimmed["_days_since_event"] = max(days_since, 0)
                        trimmed["_recency"] = (
                            "recent" if days_since <= RECENCY_WINDOW_DAYS else "historical"
                        )
                    else:
                        trimmed["_recency"] = "unknown"
                        trimmed["_days_since_event"] = -1

            anomalous.append(trimmed)
        else:
            normal.append(record)

    return anomalous, normal


def _build_normal_summary(normal_records: List[Dict[str, Any]], baseline: Dict[str, Any]) -> str:
    """Build a compact summary string for the normal (non-flagged) shipments."""
    count = len(normal_records)
    if count == 0:
        return "No normal shipments (all flagged for analysis)."

    ctd_values = []
    carriers: Dict[str, int] = {}
    for r in normal_records:
        ctd = r.get("CLICK_TO_DELIVER_DAYS")
        if ctd is not None:
            try:
                ctd_values.append(float(ctd))
            except (ValueError, TypeError):
                pass
        carrier = r.get("WAREHOUSE_CARRIER") or "Unknown"
        carriers[carrier] = carriers.get(carrier, 0) + 1

    avg_ctd = round(sum(ctd_values) / len(ctd_values), 1) if ctd_values else "N/A"
    carrier_str = ", ".join(f"{c} ({n})" for c, n in sorted(carriers.items(), key=lambda x: -x[1]))

    return (
        f"{count} shipments delivered normally. "
        f"Average CTD: {avg_ctd} days. "
        f"Carriers: {carrier_str}."
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(
    state: Dict[str, Any],
    anomalous_records: List[Dict[str, Any]],
    normal_summary: str,
    baseline_stats: Dict[str, Any],
) -> str:
    """
    Build the signal generation prompt using only flagged records.
    """
    skill_md = load_skill_instructions("shipment_signal_generator")
    data_dict = load_reference_docs("shipment_signal_generator")

    customer_id = state.get("customer_id", "unknown")
    customer_profile = state.get("customer_profile")

    baseline_context = f"""
## CUSTOMER BASELINE REFERENCE
- CTD Average: {baseline_stats.get('ctd_avg', 'N/A')} days
- CTD Threshold (avg + 1 std): {baseline_stats.get('ctd_threshold', 'N/A')} days
- Primary Carrier: {baseline_stats.get('primary_carrier', 'Unknown')}
- Total Orders: {baseline_stats.get('total_records', 0)}
"""

    customer_context = f"""
## CUSTOMER CONTEXT
- Customer ID: {customer_id}
- Customer Class: {customer_profile.customer_class if customer_profile else 'Unknown'}
- LTV: ${customer_profile.ltv if customer_profile else 0:.2f}
- Churn Risk: {customer_profile.churn_risk if customer_profile else 'Unknown'}
"""

    data_section = f"""
## FLAGGED SHIPMENTS TO ANALYZE
Records flagged by automated anomaly detection: {len(anomalous_records)}

Each record includes:
- "_flags": reasons it was flagged
- "_recency": "active", "recent" (<=14 days), or "historical" (>14 days)
- "_days_since_event": days since delivery (0 for active)

```json
{json.dumps(anomalous_records, indent=2, default=str)}
```

## NORMAL SHIPMENTS SUMMARY
{normal_summary}
"""

    prompt = f"""{skill_md}

---

{data_dict}

---

{baseline_context}

{customer_context}

{data_section}

---

## MANDATE
- Generate ONE signal per flagged shipment above.
- Each signal must include the specific ORDERS_ORDER_ID, SHIPMENT_TRACKING_NUMBER, dates, and metrics from the data.
- Include a baseline summary for the normal shipments.
- If no records were flagged, return an empty signals array with only the baseline summary.
- Do NOT fabricate order IDs, tracking numbers, or dates.
- Output ONLY valid JSON.
"""
    return prompt


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a shipment anomaly detection expert analyzing pre-flagged shipment records.

CONTEXT:
Records have already been filtered by an automated anomaly detector. Each record
includes:
- "_flags": list of reasons the record was flagged
- "_recency": "active" (not yet delivered), "recent" (delivered within 14 days),
  or "historical" (delivered more than 14 days ago)
- "_days_since_event": integer days since the event

YOUR TASK:
For each flagged record, generate a signal containing:
1. **Signal/Observation**: What was detected -- reference specific IDs, dates, metrics.
2. **Analysis**: Root cause hypothesis, severity assessment, pet care impact.
3. **Intervention Needed**: Determined by recency:
   - "active" or "recent" events -> intervention_needed: true
   - "historical" events -> intervention_needed: false (pattern context only)
4. **Recency**: Copy the _recency and _days_since_event values from the record.

DO NOT include:
- Specific actions or recommendations
- Next steps or suggested resolutions
- "Normal Processing" signals (normal shipments are summarized separately)

OUTPUT FORMAT:
Return valid JSON with this structure:
{
  "signals": [...],
  "baseline_summary": "...",
  "total_flagged": N,
  "total_normal": N
}

Each signal in the array:
{
  "signal_id": 1,
  "signal_type": "Excessive Delay | Active At-Risk | Carrier Exception | Fresh Item Concern | ...",
  "orders_order_id": "actual ID from data",
  "shipment_tracking_number": "actual tracking from data",
  "observation": "What was detected with specific metrics",
  "analysis": "Root cause, severity, pet care impact",
  "intervention_needed": true/false,
  "recency": "active | recent | historical",
  "days_since_event": N,
  "severity": "critical | high | medium | low",
  "flags": ["from _flags field"]
}

CRITICAL RULES:
1. Use ONLY data from the provided records. Do not fabricate IDs or metrics.
2. Reference ORDERS_ORDER_ID (not ORDER_ID) as the order identifier.
3. Every flagged record MUST get exactly one signal.
4. intervention_needed MUST be true for active/recent, false for historical.
5. Output ONLY valid JSON -- no markdown, no code blocks, no extra text."""


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """
    Execute the shipment signal generator skill.

    Flow:
      1. Pre-filter records into anomalous vs normal (deterministic Python).
      2. Trim anomalous records to ~26 fields.
      3. Send only flagged records + normal summary to the LLM.
      4. Parse and return structured signal output.
    """
    customer_id = state.get("customer_id", "unknown")
    prompt_logger = state.get("prompt_logger")

    # ── Get shipment data ──
    shipment_records: List[Dict[str, Any]] = []
    baseline_stats: Dict[str, Any] = {}

    if state.get("shipment_data"):
        data = state["shipment_data"]
        shipment_records = data.get("records", [])
        baseline_stats = data.get("baseline", {})

    # Fallback: active shipments from result object
    shipments_result = state.get("shipments_result")
    if not shipment_records and shipments_result and hasattr(shipments_result, "active_shipments"):
        for shipment in shipments_result.active_shipments:
            record = {
                "ORDERS_ORDER_ID": shipment.order_id,
                "SHIPMENT_TRACKING_NUMBER": shipment.shipment_id,
                "WAREHOUSE_CARRIER": shipment.carrier,
                "ACTUAL_SHIP_DATE": str(shipment.ship_date),
                "BULK_TRACK_DELIVERY_DTTM": str(shipment.expected_delivery),
                "SHIPMENT_STATUS": shipment.status,
            }
            shipment_records.append(record)

    if not shipment_records:
        return {
            "skill": "shipment_signal_generator",
            "error": "No shipment records available for analysis",
            "signals": [],
        }

    # ── Step 1: Pre-filter anomalies (deterministic) ──
    anomalous, normal = _flag_anomalies(shipment_records, baseline_stats)
    normal_summary = _build_normal_summary(normal, baseline_stats)

    # If nothing is flagged, return clean result without calling LLM
    if not anomalous:
        return {
            "skill": "shipment_signal_generator",
            "customer_id": customer_id,
            "total_signals": 0,
            "total_flagged": 0,
            "total_normal": len(normal),
            "signals": [],
            "baseline_summary": normal_summary,
            "continued_analysis": (
                f"Automated anomaly detection scanned {len(shipment_records)} shipments. "
                f"No anomalies detected. {normal_summary}"
            ),
        }

    # ── Step 2: Build prompt with only flagged (trimmed) records ──
    prompt = build_prompt(state, anomalous, normal_summary, baseline_stats)

    # ── Step 3: Call LLM ──
    client = OpenAI(timeout=600.0)

    response = client.responses.create(
        model=OPENAI_MODEL,
        reasoning={"effort": "medium"},
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        text={"format": {"type": "json_object"}},
    )

    content = response.output_text.strip()

    # Log prompt + response
    if prompt_logger:
        prompt_logger.log_prompt(
            category="skills",
            metric_name="Shipment Signal Generator",
            peer_level=peer_level,
            prompt=prompt,
            response=content,
        )

    # ── Step 4: Parse response ──
    try:
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        result = json.loads(content)
        result["skill"] = "shipment_signal_generator"
        result["customer_id"] = customer_id
        # Ensure counts are present
        result.setdefault("total_flagged", len(anomalous))
        result.setdefault("total_normal", len(normal))
        result.setdefault("total_signals", len(result.get("signals", [])))
        return result

    except json.JSONDecodeError as e:
        return {
            "skill": "shipment_signal_generator",
            "error": f"Failed to parse LLM response: {str(e)}",
            "raw_response": content[:500],
        }
