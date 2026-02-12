"""
Shipment Intervention Recommender Skill - Execute Module

Recommends optimal interventions based on delay predictions and customer value.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_reference, load_shared_context, load_skill


def _build_prompt(
    delay_prediction: Dict[str, Any],
    customer_profile: Dict[str, Any],
    shipment: Dict[str, Any],
    context: str,
    skill_md: str,
    data_dictionary: str
) -> str:
    """Build the prompt for intervention recommendation."""
    
    delay_json = json.dumps(delay_prediction, indent=2, default=str)
    customer_json = json.dumps(customer_profile, indent=2, default=str)
    shipment_json = json.dumps(shipment, indent=2, default=str)
    
    return f"""{context}

---

{skill_md}

---

## Data Dictionary

{data_dictionary}

---

## Delay Prediction (JSON)

```json
{delay_json}
```

---

## Customer Profile (JSON)

```json
{customer_json}
```

---

## Shipment Details (JSON)

```json
{shipment_json}
```

---

Output ONLY valid JSON. No markdown, no code blocks, no additional text.
"""


def execute(state: Dict[str, Any], target_result_key: str, peer_level: str = "SEGMENT") -> Optional[Dict[str, Any]]:
    """
    Execute intervention recommendation for shipment delays.
    
    Args:
        state: Current agent state
        target_result_key: Key of result to enhance
        peer_level: Peer level context
        
    Returns:
        Dict with skill enhancement or None if failed
    """
    customer_id = state.get("customer_id")
    prompt_logger = state.get("prompt_logger")
    
    # Get delay predictions from phased execution (top-level key or skill_results)
    delay_prediction = state.get("shipment_delay_predictor_result")

    if not delay_prediction:
        skill_results = state.get("skill_results", {})
        delay_prediction = skill_results.get("shipment_delay_predictor_result")

    if not delay_prediction:
        # Fallback: try legacy shipments_result
        shipments_result = state.get("shipments_result")
        if shipments_result and hasattr(shipments_result, 'delay_predictions'):
            predictions = shipments_result.delay_predictions
            if predictions:
                delay_prediction = predictions[0].model_dump() if hasattr(predictions[0], 'model_dump') else dict(predictions[0])
    
    if not delay_prediction:
        print(f"  ⚠ No delay prediction found to base intervention on")
        return None
    
    # Get customer profile
    customer_profile = state.get("customer_profile")
    if customer_profile and hasattr(customer_profile, 'model_dump'):
        customer_profile = customer_profile.model_dump()
    elif not customer_profile:
        customer_profile = {"customer_id": customer_id, "customer_class": "Standard"}
    
    # Get shipment details
    shipments_result = state.get("shipments_result")
    shipment = {}
    if shipments_result:
        active_shipments = getattr(shipments_result, 'active_shipments', []) or []
        if active_shipments:
            first = active_shipments[0]
            shipment = first.model_dump() if hasattr(first, 'model_dump') else dict(first)
    
    # Load skill resources
    context = load_shared_context() or "You are recommending interventions for delayed shipments."
    skill_md = load_skill("shipment_intervention") or "Recommend optimal interventions."
    data_dictionary = load_skill_reference("shipment_intervention", "data_dictionary.md") or ""
    
    # Build prompt
    prompt = _build_prompt(
        delay_prediction=delay_prediction,
        customer_profile=customer_profile,
        shipment=shipment,
        context=context,
        skill_md=skill_md,
        data_dictionary=data_dictionary
    )
    
    # Call LLM using Responses API
    try:
        client = OpenAI(timeout=600.0)
        model = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")
        
        system_prompt = "You are an expert in customer service operations and intervention strategies."
        
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
        
        if prompt_logger:
            prompt_logger.log_prompt(
                category="skills",
                metric_name="Shipment Intervention",
                peer_level=peer_level,
                prompt=prompt,
                response=response_text
            )
        
        # Parse response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.split("```")[0].strip()
        
        response_text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', response_text)
        result = json.loads(response_text)
        
        if "skill" not in result:
            result["skill"] = "shipment_intervention"
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"  ✗ Intervention JSON parsing failed: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Intervention analysis failed: {e}")
        return None
