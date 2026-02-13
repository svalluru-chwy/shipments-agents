"""
Shipment Delay Predictor Skill - Execute Module

Predicts shipment delays based on tracking events, carrier performance,
and exception indicators.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_reference, load_shared_context, load_skill


def _build_prompt(
    shipment: Dict[str, Any],
    tracking_events: list,
    context: str,
    skill_md: str,
    data_dictionary: str
) -> str:
    """
    Build the prompt for delay prediction analysis.
    
    Args:
        shipment: Shipment data dictionary
        tracking_events: List of tracking events
        context: Shared workflow context from CONTEXT.md
        skill_md: Skill-specific instructions from SKILL.md
        data_dictionary: Data dictionary content
        
    Returns:
        Formatted prompt string
    """
    shipment_json = json.dumps(shipment, indent=2, default=str)
    tracking_json = json.dumps(tracking_events, indent=2, default=str)
    
    return f"""{context}

---

{skill_md}

---

## Data Dictionary

{data_dictionary}

---

## Shipment Data (JSON)

```json
{shipment_json}
```

---

## Tracking Events (JSON)

```json
{tracking_json}
```

---

## Current Date

{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

Output ONLY valid JSON. No markdown, no code blocks, no additional text.
"""


def _find_active_shipments(state: Dict[str, Any], target_result_key: str) -> list:
    """
    Locate active (undelivered / in-transit) shipments from the best available
    source in state.

    Lookup order:
      1. state[target_result_key].active_shipments  (original cat-agents path)
      2. state["current_order_result"]["grounded_metrics"]["active_order_details"]
         (Phase 1 result injected by the runner between phases)
      3. state["shipment_data"]["records"] filtered for undelivered records

    Returns a list of dicts, each representing one active shipment.
    """
    # --- Source 1: original shipments_result key ---
    shipments_result = state.get(target_result_key)
    if shipments_result:
        if hasattr(shipments_result, "active_shipments") and shipments_result.active_shipments:
            return list(shipments_result.active_shipments)
        if isinstance(shipments_result, dict) and shipments_result.get("active_shipments"):
            return list(shipments_result["active_shipments"])

    # --- Source 2: Phase 1 current_order skill result ---
    current_order = state.get("current_order_result")
    if isinstance(current_order, dict):
        metrics = current_order.get("grounded_metrics", {})
        details = metrics.get("active_order_details") or []
        if details:
            return list(details)

    # --- Source 3: raw shipment records, filtered for in-transit ---
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    active = []
    for r in records:
        # Delivered check with fallback chain:
        #   Primary: BULK_TRACK_DELIVERY_DTTM is not None
        #   Fallback: SHIPMENT_STATUS or WIZMO_CURRENT_PKG_STATUS == "DELIVERED"
        delivery_date = r.get("BULK_TRACK_DELIVERY_DTTM")
        is_delivered = delivery_date is not None
        if not is_delivered:
            shipment_status = (r.get("SHIPMENT_STATUS") or "").upper()
            wizmo_status = (r.get("WIZMO_CURRENT_PKG_STATUS") or "").upper()
            if shipment_status == "DELIVERED" or wizmo_status == "DELIVERED":
                is_delivered = True

        # Status fallback chain for filtering
        status = (
            r.get("BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION")
            or r.get("SHIPMENT_STATUS")
            or r.get("WIZMO_CURRENT_PKG_STATUS")
            or ""
        ).upper()

        if not is_delivered and status not in ("DELIVERED", "COMPLETE"):
            active.append(r)
    return active


def execute(state: Dict[str, Any], target_result_key: str, peer_level: str = "SEGMENT") -> Optional[Dict[str, Any]]:
    """
    Execute delay prediction for shipments in the target result.
    
    Args:
        state: Current agent state
        target_result_key: Key of result to enhance (e.g., "shipments_result")
        peer_level: Which peer level context to use
        
    Returns:
        Dict with skill enhancement or None if failed
    """
    customer_id = state.get("customer_id")
    prompt_logger = state.get("prompt_logger")
    
    # Resolve active shipments from multiple possible state locations
    active_shipments = _find_active_shipments(state, target_result_key)
    
    if not active_shipments:
        # All shipments delivered -- return a clean result instead of None
        return {
            "skill": "shipment_delay_predictor",
            "status": "no_active_shipments",
            "observations": [
                "No active or in-transit shipments found to predict delays for.",
                "All shipments appear to have been delivered.",
            ],
            "delay_predictions": [],
            "grounded_metrics": {
                "active_shipments_count": 0,
                "predictions_made": 0,
            },
        }
    
    # Load shared context
    context = load_shared_context()
    if not context:
        context = "You are analyzing shipment data to predict delays."
    
    # Load skill instructions
    skill_md = load_skill("shipment_delay_predictor")
    if not skill_md:
        print(f"  ⚠ Could not load SKILL.md for shipment_delay_predictor")
        skill_md = "Analyze tracking data to predict shipment delays."
    
    # Load data dictionary
    data_dictionary = load_skill_reference("shipment_delay_predictor", "data_dictionary.md")
    if not data_dictionary:
        data_dictionary = "Standard shipment tracking data fields."
    
    # Process first shipment (or aggregate all)
    # For now, analyze the first at-risk shipment
    shipment = active_shipments[0] if active_shipments else None
    if not shipment:
        return None
    
    # Convert to dict if needed
    if hasattr(shipment, 'model_dump'):
        shipment_dict = shipment.model_dump()
    else:
        shipment_dict = dict(shipment)
    
    tracking_events = shipment_dict.get('tracking_events', [])
    
    # Build prompt
    prompt = _build_prompt(
        shipment=shipment_dict,
        tracking_events=tracking_events,
        context=context,
        skill_md=skill_md,
        data_dictionary=data_dictionary
    )
    
    # Call LLM using Responses API
    try:
        client = OpenAI(timeout=600.0)
        model = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")
        
        system_prompt = "You are an expert logistics analyst specializing in shipment delay prediction."
        
        response = client.responses.create(
            model=model,
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            text={"format": {"type": "json_object"}}
        )
        
        response_text = response.output_text.strip()
        
        # Log prompt and response
        if prompt_logger:
            prompt_logger.log_prompt(
                category="skills",
                metric_name="Shipment Delay Predictor",
                peer_level=peer_level,
                prompt=prompt,
                response=response_text
            )
        
        # Parse JSON response
        if response_text.startswith("```json"):
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif response_text.startswith("```"):
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        # Fix common invalid escape sequences
        response_text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', response_text)
        
        result = json.loads(response_text)
        
        # Ensure correct format
        if "skill" not in result:
            result["skill"] = "shipment_delay_predictor"
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"  ✗ Delay predictor JSON parsing failed: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Delay predictor analysis failed: {e}")
        return None
