"""
Shipment Intervention Assessment Skill - Execute Module

Synthesises all Phase 1 + Phase 2 results into a customer-level
intervention determination: is intervention warranted, at what urgency,
and why?

Architecture:
  1. Deterministic Python aggregation of upstream skill outputs.
  2. Lightweight LLM call to write the synthesis paragraph.
  3. NO specific actions, recommendations, or next steps.
"""

import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")


# ---------------------------------------------------------------------------
# Deterministic aggregation
# ---------------------------------------------------------------------------

def _gather_signals(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract signals from signal_generator result."""
    gen = (
        state.get("shipment_signal_generator_result")
        or (state.get("skill_results") or {}).get("shipment_signal_generator_result")
        or {}
    )
    return gen.get("signals", []) if isinstance(gen, dict) else []


def _gather_decoded(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract signal_decoder result."""
    return (
        state.get("shipment_signal_decoder_result")
        or (state.get("skill_results") or {}).get("shipment_signal_decoder_result")
        or {}
    )


def _gather_delay_predictor(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract delay_predictor result."""
    return (
        state.get("shipment_delay_predictor_result")
        or (state.get("skill_results") or {}).get("shipment_delay_predictor_result")
        or {}
    )


def _gather_phase1_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pull key metrics from Phase 1 deterministic skills."""
    skills = state.get("skill_results") or {}

    def _get(key: str) -> Dict[str, Any]:
        val = state.get(key) or skills.get(key) or {}
        return val if isinstance(val, dict) else {}

    health = _get("shipment_health_check_result")
    delivery = _get("delivery_performance_result")
    carrier = _get("carrier_analysis_result")
    contact = _get("contact_correlation_result")
    current = _get("current_order_result")
    check_gate = state.get("check_gate") or state.get("shipment_data", {}).get("check_gate", {})

    return {
        "health_status": (health.get("summary") or {}).get("health_status"),
        "avg_ctd": (health.get("summary") or {}).get("avg_ctd"),
        "on_time_rate": (health.get("summary") or {}).get("on_time_rate"),
        "delayed_count": (health.get("grounded_metrics") or {}).get("customer_performance", {}).get("delayed_shipments"),
        "total_shipments": (health.get("summary") or {}).get("total_shipments"),
        "trend_direction": (delivery.get("summary") or {}).get("trend_direction"),
        "primary_carrier": (carrier.get("summary") or {}).get("primary_carrier"),
        "carrier_with_issues": (carrier.get("summary") or {}).get("carrier_with_issues"),
        "contact_rate": (contact.get("summary") or {}).get("contact_rate"),
        "wismo_rate": (contact.get("summary") or {}).get("wismo_rate"),
        "active_orders": (current.get("grounded_metrics") or {}).get("total_active_orders", 0),
        "at_risk_orders": (current.get("grounded_metrics") or {}).get("at_risk_orders", 0),
        "check_gate_is_red": check_gate.get("is_red", False) if isinstance(check_gate, dict) else False,
        "check_gate_severity": check_gate.get("severity") if isinstance(check_gate, dict) else None,
    }


def _compute_assessment(
    signals: List[Dict[str, Any]],
    decoded: Dict[str, Any],
    delay_pred: Dict[str, Any],
    phase1: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic intervention assessment from aggregated results.

    Returns:
        Dict with intervention_warranted, urgency, rationale bullets,
        and structured signal summaries.
    """
    # Count signals by intervention_needed and severity
    intervention_signals = [s for s in signals if s.get("intervention_needed")]
    critical_signals = [s for s in intervention_signals if s.get("severity") in ("critical",)]
    high_signals = [s for s in intervention_signals if s.get("severity") in ("high",)]
    medium_signals = [s for s in intervention_signals if s.get("severity") in ("medium",)]

    # Delay predictor at-risk count
    at_risk_active = phase1.get("at_risk_orders", 0)
    has_active_risk = at_risk_active > 0

    # Determine urgency
    if critical_signals or has_active_risk:
        urgency = "critical"
    elif len(high_signals) >= 3:
        urgency = "critical"
    elif high_signals:
        urgency = "high"
    elif medium_signals:
        urgency = "medium"
    elif intervention_signals:
        urgency = "low"
    else:
        urgency = "none"

    intervention_warranted = urgency not in ("none",)

    # Build rationale bullets
    rationale: List[str] = []
    if not intervention_signals:
        rationale.append("No signals flagged as requiring intervention.")
    else:
        rationale.append(
            f"{len(intervention_signals)} of {len(signals)} signals flagged as intervention-needed "
            f"({len(critical_signals)} critical, {len(high_signals)} high, {len(medium_signals)} medium)."
        )

    if has_active_risk:
        rationale.append(f"{at_risk_active} active shipment(s) at risk of delay.")

    if phase1.get("check_gate_is_red"):
        rationale.append(f"Check gate flagged RED (severity: {phase1.get('check_gate_severity')}).")

    if phase1.get("trend_direction") == "DECLINING":
        rationale.append("Delivery performance trend is DECLINING.")

    contact_rate = phase1.get("contact_rate")
    if contact_rate is not None and contact_rate > 30:
        rationale.append(f"Elevated contact rate ({contact_rate}%) suggests customer friction.")

    wismo_rate = phase1.get("wismo_rate")
    if wismo_rate is not None and wismo_rate > 0:
        rationale.append(f"WISMO inquiries detected ({wismo_rate}%) -- customer tracking concerns.")

    # Build signal summaries for output
    signal_summaries = []
    for s in intervention_signals:
        signal_summaries.append({
            "signal_id": s.get("signal_id"),
            "orders_order_id": s.get("orders_order_id"),
            "shipment_tracking_number": s.get("shipment_tracking_number"),
            "signal_type": s.get("signal_type"),
            "severity": s.get("severity"),
            "observation": s.get("observation"),
            "intervention_needed": True,
        })

    # Decoded signals summary
    decoded_summary = (decoded.get("summary") or {}).get("primary_finding")
    decoded_high_count = (decoded.get("summary") or {}).get("high_severity_signals", 0)

    return {
        "intervention_warranted": intervention_warranted,
        "urgency": urgency,
        "rationale": rationale,
        "signals_assessed": {
            "total": len(signals),
            "intervention_needed": len(intervention_signals),
            "critical": len(critical_signals),
            "high": len(high_signals),
            "medium": len(medium_signals),
        },
        "signals_requiring_intervention": signal_summaries,
        "contributing_factors": {
            "health_status": phase1.get("health_status"),
            "avg_ctd": phase1.get("avg_ctd"),
            "on_time_rate": phase1.get("on_time_rate"),
            "delayed_count": phase1.get("delayed_count"),
            "total_shipments": phase1.get("total_shipments"),
            "trend_direction": phase1.get("trend_direction"),
            "carrier_with_issues": phase1.get("carrier_with_issues"),
            "contact_rate": contact_rate,
            "wismo_rate": wismo_rate,
            "active_at_risk": at_risk_active,
            "check_gate_red": phase1.get("check_gate_is_red"),
        },
        "decoded_context": {
            "primary_finding": decoded_summary,
            "high_severity_count": decoded_high_count,
        },
    }


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """You are a shipment analyst writing a concise intervention assessment paragraph.

You will receive a structured assessment with:
- Whether intervention is warranted and at what urgency
- Signal counts and details
- Contributing factors from delivery performance, carrier analysis, contact history

Write ONE focused paragraph (4-8 sentences) that:
1. States whether customer-level intervention is warranted and the urgency level.
2. Summarises the key signals (reference specific order IDs and tracking numbers).
3. Explains the contributing factors (carrier patterns, delivery trends, contact history).
4. Notes the pet care impact if relevant (medications, fresh items).
5. Does NOT include specific actions, recommendations, or next steps.

Output ONLY the paragraph text. No JSON, no markdown, no headers."""


def _write_synthesis(assessment: Dict[str, Any], customer_id: str) -> str:
    """Call LLM to write the synthesis paragraph from the deterministic assessment."""
    prompt = f"""Customer {customer_id} -- Intervention Assessment Data:

{json.dumps(assessment, indent=2, default=str)}

Write one synthesis paragraph focused on whether intervention is warranted and why.
Reference specific order IDs and metrics. Do NOT include actions or recommendations."""

    try:
        client = OpenAI(timeout=120.0)
        response = client.responses.create(
            model=OPENAI_MODEL,
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.output_text.strip()
    except Exception as e:
        # Fallback: deterministic summary
        warranted = assessment["intervention_warranted"]
        urgency = assessment["urgency"]
        count = assessment["signals_assessed"]["intervention_needed"]
        total = assessment["signals_assessed"]["total"]
        return (
            f"Intervention {'is' if warranted else 'is not'} warranted "
            f"(urgency: {urgency}). "
            f"{count} of {total} signals flagged for intervention. "
            + " ".join(assessment["rationale"])
        )


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(state: Dict[str, Any], target_result_key: str = "", peer_level: str = "SEGMENT") -> Optional[Dict[str, Any]]:
    """
    Execute intervention assessment by aggregating Phase 1+2 results.

    Flow:
      1. Gather signals, decoded results, delay predictions, Phase 1 metrics.
      2. Compute deterministic assessment (warranted, urgency, rationale).
      3. LLM writes synthesis paragraph.
      4. Return structured result.
    """
    customer_id = state.get("customer_id", "unknown")
    prompt_logger = state.get("prompt_logger")

    # ── Gather upstream results ──
    signals = _gather_signals(state)
    decoded = _gather_decoded(state)
    delay_pred = _gather_delay_predictor(state)
    phase1 = _gather_phase1_metrics(state)

    # ── Deterministic assessment ──
    assessment = _compute_assessment(signals, decoded, delay_pred, phase1)

    # ── LLM synthesis paragraph ──
    synthesis = _write_synthesis(assessment, customer_id)

    if prompt_logger:
        prompt_logger.log_prompt(
            category="skills",
            metric_name="Shipment Intervention Assessment",
            peer_level=peer_level,
            prompt=json.dumps(assessment, indent=2, default=str),
            response=synthesis,
        )

    # ── Build result ──
    observations = [
        f"Intervention {'warranted' if assessment['intervention_warranted'] else 'not warranted'} "
        f"(urgency: {assessment['urgency']}).",
    ]
    observations.extend(assessment["rationale"])

    return {
        "skill": "shipment_intervention",
        "observations": observations,
        "summary": {
            "overall_health": assessment["urgency"].upper() if assessment["intervention_warranted"] else "HEALTHY",
            "primary_finding": assessment["rationale"][0] if assessment["rationale"] else "No issues found.",
            "intervention_warranted": assessment["intervention_warranted"],
            "urgency": assessment["urgency"],
        },
        "grounded_metrics": {
            "intervention_warranted": assessment["intervention_warranted"],
            "urgency": assessment["urgency"],
            "signals_assessed": assessment["signals_assessed"],
            "signals_requiring_intervention": assessment["signals_requiring_intervention"],
            "contributing_factors": assessment["contributing_factors"],
            "decoded_context": assessment["decoded_context"],
        },
        "continued_analysis": synthesis,
    }
