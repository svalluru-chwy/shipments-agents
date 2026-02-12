"""
Shipment Consolidator Skill Execution.

Generates executive briefing from all shipment analysis.
"""

import os
import json
from typing import Dict, Any
from openai import OpenAI
from packages.agents.shipments.skills.loader import load_skill_instructions, load_reference_docs


def build_prompt(state: Dict[str, Any], peer_level: str) -> str:
    """Build the prompt for consolidation."""
    
    instructions = load_skill_instructions("shipment_consolidator")
    references = load_reference_docs("shipment_consolidator")
    
    customer_profile = state.get("customer_profile", {})
    shipment_data = state.get("shipment_data", {})
    
    records = shipment_data.get("records", [])
    issues = shipment_data.get("issues", {})
    investigation_reasons = shipment_data.get("investigation_reasons", [])
    
    # Collect all shipment skill results from state
    shipment_skills = [
        'shipment_health_check', 'delivery_performance', 'carrier_analysis',
        'exception_analysis', 'geographic_patterns', 'routing_efficiency',
        'timing_patterns', 'package_analysis', 'order_behavior', 'current_order'
    ]
    
    context_parts = [
        f"Customer ID: {customer_profile.customer_id if hasattr(customer_profile, 'customer_id') else 'Unknown'}",
        f"Engagement: {customer_profile.engagement_class if hasattr(customer_profile, 'engagement_class') else 'Unknown'}",
        f"LTV: ${customer_profile.ltv if hasattr(customer_profile, 'ltv') else 0:,.2f}",
        "",
        "## Shipment Summary",
        f"Total Shipments: {len(records)}",
        f"Investigation Reasons: {', '.join(investigation_reasons) if investigation_reasons else 'None'}",
        "",
        "## Issues Found"
    ]
    
    if issues:
        for issue_type, issue_list in issues.items():
            context_parts.append(f"- {issue_type}: {len(issue_list)} items")
    
    # Add individual skill results
    context_parts.append("")
    context_parts.append("## Individual Skill Results")
    context_parts.append("")
    
    for skill_name in shipment_skills:
        skill_key = f"{skill_name}_result"
        skill_result = state.get(skill_key, {})
        if skill_result and isinstance(skill_result, dict):
            context_parts.append(f"### {skill_name}")
            context_parts.append(f"```json")
            context_parts.append(json.dumps(skill_result, indent=2))
            context_parts.append(f"```")
            context_parts.append("")
    
    prompt = f"""
{instructions}

---

## Reference Documentation

{references}

---

## Analysis Data

{chr(10).join(context_parts)}

---

CRITICAL: Only reference order IDs, tracking numbers, FC names, and metrics
that appear verbatim in the skill results above. Do not invent or extrapolate
data points. If a skill reports NO_DATA, reflect that status as-is.

Please generate the executive briefing.
Return ONLY valid JSON matching the output format in the instructions.
"""
    
    return prompt


def execute(state: Dict[str, Any], target_key: str = "shipments_result", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the consolidator skill."""
    
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {
            "skill": "shipment_consolidator",
            "error": "No shipment data available",
            "executive_briefing": {}
        }
    
    prompt = build_prompt(state, peer_level)
    
    client = OpenAI(timeout=600.0)
    model = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")
    
    try:
        response = client.responses.create(
            model=model,
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": "You are a Shipment Intelligence Analyst. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            text={"format": {"type": "json_object"}}
        )
        
        result = json.loads(response.output_text)
        result["skill"] = "shipment_consolidator"
        return result
        
    except Exception as e:
        return {
            "skill": "shipment_consolidator",
            "error": str(e),
            "executive_briefing": {}
        }
