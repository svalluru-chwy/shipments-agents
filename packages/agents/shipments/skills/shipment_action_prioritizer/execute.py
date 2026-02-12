"""
Shipment Action Prioritizer Skill Execution.

Prioritizes shipment interventions by impact, urgency, and ROI.
"""

import os
import json
from typing import Dict, Any

from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_instructions, load_reference_docs


def build_prompt(state: Dict[str, Any], target_key: str, peer_level: str) -> str:
    """Build the prompt for action prioritization."""
    
    # Load skill instructions
    instructions = load_skill_instructions("shipment_action_prioritizer")
    references = load_reference_docs("shipment_action_prioritizer")
    
    # Get customer profile
    customer_profile = state.get("customer_profile")
    customer_id = state.get("customer_id", "unknown")
    
    # Get shipment analysis results
    shipments_result = state.get("shipments_result")
    shipment_data = state.get("shipment_data", {})
    
    # Extract intervention data from phased execution (top-level keys or skill_results)
    interventions = []
    signals = []
    
    # Get interventions from shipment_intervention_result
    intervention_result = state.get("shipment_intervention_result") or state.get("skill_results", {}).get("shipment_intervention_result", {})
    if isinstance(intervention_result, dict):
        interventions = intervention_result.get("recommended_interventions", [])
    
    # Get decoded signals from shipment_signal_decoder_result
    decoder_result = state.get("shipment_signal_decoder_result") or state.get("skill_results", {}).get("shipment_signal_decoder_result", {})
    if isinstance(decoder_result, dict):
        signals = decoder_result.get("decoded_signals", [])
    
    # Build prompt
    prompt = f"""
{instructions}

---

{references}

---

## Customer Context

**Customer ID**: {customer_id}
**Customer Class**: {customer_profile.customer_class if customer_profile else 'Unknown'}
**LTV**: ${customer_profile.ltv if customer_profile else 0:.2f}
**Churn Risk**: {customer_profile.churn_risk if customer_profile else 0:.1%}
**Engagement**: {customer_profile.engagement_class if customer_profile else 'Unknown'}

## Shipment Issues Identified

{json.dumps(shipment_data.get('issues', {}), indent=2, default=str)}

## Investigation Reasons

{json.dumps(shipment_data.get('investigation_reasons', []), indent=2, default=str)}

## Interventions to Prioritize

{json.dumps(interventions[:20], indent=2, default=str)}

## Decoded Signals

{json.dumps(signals[:10], indent=2, default=str)}

## Task

Analyze the above data and create a prioritized action plan for this customer's shipment issues.
Use the priority scoring matrix to rank each action.
Return your response as a valid JSON object following the output format specified above.
"""
    
    return prompt


def execute(state: Dict[str, Any], target_key: str = "shipments_result", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """
    Execute the shipment action prioritizer skill.
    
    Args:
        state: Current agent state
        target_key: The result key to enhance
        peer_level: Peer comparison level
        
    Returns:
        Prioritization result dict
    """
    prompt = build_prompt(state, target_key, peer_level)
    
    client = OpenAI(timeout=600.0)
    model = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")
    
    try:
        response = client.responses.create(
            model=model,
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": "You are a shipment action prioritization specialist. Respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            text={"format": {"type": "json_object"}}
        )
        
        content = response.output_text.strip()
        
        # Parse JSON from response
        if content.startswith("```"):
            lines = content.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                elif line.startswith("```"):
                    in_json = False
                    continue
                if in_json:
                    json_lines.append(line)
            content = "\n".join(json_lines)
        
        result = json.loads(content)
        result["skill"] = "shipment_action_prioritizer"
        return result
        
    except json.JSONDecodeError as e:
        return {
            "skill": "shipment_action_prioritizer",
            "error": f"Failed to parse JSON: {e}",
            "prioritized_actions": []
        }
    except Exception as e:
        return {
            "skill": "shipment_action_prioritizer",
            "error": str(e),
            "prioritized_actions": []
        }
