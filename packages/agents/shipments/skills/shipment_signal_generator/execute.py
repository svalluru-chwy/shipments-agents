"""
Shipment Signal Generator Skill - Execution Logic

Analyzes shipment data to generate per-order signals for proactive intervention.
Based on the original shipments_signals_agent.py.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_instructions, load_reference_docs

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")


def build_prompt(
    state: Dict[str, Any],
    shipment_records: List[Dict],
    baseline_stats: Dict[str, Any]
) -> str:
    """
    Build the signal generation prompt.
    
    Args:
        state: Current agent state
        shipment_records: List of shipment records to analyze
        baseline_stats: Pre-computed baseline statistics
        
    Returns:
        Complete prompt string
    """
    # Load skill instructions
    skill_md = load_skill_instructions("shipment_signal_generator")
    
    # Load data dictionary
    data_dict = load_reference_docs("shipment_signal_generator")
    
    # Get customer context
    customer_id = state.get("customer_id", "unknown")
    customer_profile = state.get("customer_profile")
    
    # Build baseline context
    baseline_context = f"""
## CUSTOMER BASELINE REFERENCE
Use these when making comparative statements:
- CTD Average: {baseline_stats.get('ctd_avg', 'N/A')} days
- CTD Threshold (avg + 1 std): {baseline_stats.get('ctd_threshold', 'N/A')} days
- Primary Carrier: {baseline_stats.get('primary_carrier', 'Unknown')}
- Total Orders: {baseline_stats.get('total_records', 0)}
"""
    
    # Build customer context
    customer_context = f"""
## CUSTOMER CONTEXT
- Customer ID: {customer_id}
- Customer Class: {customer_profile.customer_class if customer_profile else 'Unknown'}
- LTV: ${customer_profile.ltv if customer_profile else 0:.2f}
- Churn Risk: {customer_profile.churn_risk if customer_profile else 'Unknown'}
"""
    
    # Build data section
    # Limit records if too many
    records_to_analyze = shipment_records[:50]  # Process up to 50 at a time
    
    data_section = f"""
## SHIPMENT DATA TO ANALYZE
Total Records: {len(records_to_analyze)}

```json
{json.dumps(records_to_analyze, indent=2, default=str)}
```
"""
    
    # Combine all sections
    prompt = f"""{skill_md}

---

{data_dict}

---

{baseline_context}

{customer_context}

{data_section}

---

## MANDATE
- Generate a signal for EVERY order_id/shipment_tracking_number in the data
- Include specific Order IDs, Tracking Numbers, Dates, Postcodes
- Do not skip any records
- Output ONLY valid JSON

Output ONLY valid JSON. No markdown, no code blocks, no additional text.
"""
    
    return prompt


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """
    Execute the shipment signal generator skill.
    
    Args:
        state: Current agent state with shipment data
        target_key: State key being enhanced (e.g., "shipments_result")
        peer_level: Peer comparison level (SEGMENT, COHORT, BOTH)
        
    Returns:
        Signal generation results
    """
    customer_id = state.get("customer_id", "unknown")
    prompt_logger = state.get("prompt_logger")
    
    # Get shipment data from state
    shipments_result = state.get("shipments_result")
    
    # Try to get records from different sources
    shipment_records = []
    baseline_stats = {}
    
    # From S3 loaded data
    if state.get("shipment_data"):
        data = state.get("shipment_data")
        shipment_records = data.get("records", [])
        baseline_stats = data.get("baseline", {})
    
    # Fallback: Generate from active shipments in result
    elif shipments_result and hasattr(shipments_result, 'active_shipments'):
        # Convert ShipmentInfo to dicts
        for shipment in shipments_result.active_shipments:
            record = {
                "ORDER_ID": shipment.order_id,
                "SHIPMENT_TRACKING_NUMBER": shipment.shipment_id,
                "WAREHOUSE_CARRIER": shipment.carrier,
                "ACTUAL_SHIP_DATE": str(shipment.ship_date),
                "BULK_TRACK_DELIVERY_DTTM": str(shipment.expected_delivery),
                "STATUS": shipment.status,
            }
            shipment_records.append(record)
    
    if not shipment_records:
        return {
            "skill": "shipment_signal_generator",
            "error": "No shipment records available for analysis",
            "signals": []
        }
    
    # Build prompt
    prompt = build_prompt(state, shipment_records, baseline_stats)
    
    # Call LLM using Responses API
    client = OpenAI(timeout=600.0)
    
    system_prompt = """You are a shipment anomaly detection expert analyzing individual shipment records.

CRITICAL INSTRUCTIONS:
1. Generate INDIVIDUAL ORDER-LEVEL signals with specific Order IDs, Tracking numbers, Dates
2. NEVER generate summary or aggregate signals
3. Each signal MUST reference specific order details
4. Generate signals until you naturally run out of patterns
5. Output ONLY valid JSON"""
    
    response = client.responses.create(
        model=OPENAI_MODEL,
        reasoning={"effort": "medium"},
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        text={"format": {"type": "json_object"}}
    )
    
    content = response.output_text.strip()
    
    # Log prompt and response if logger available
    if prompt_logger:
        prompt_logger.log_prompt(
            category="skills",
            metric_name="Shipment Signal Generator",
            peer_level=peer_level,
            prompt=prompt,
            response=content
        )
    
    # Parse JSON response
    try:
        # Clean up response if needed
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content)
        result["skill"] = "shipment_signal_generator"
        return result
        
    except json.JSONDecodeError as e:
        return {
            "skill": "shipment_signal_generator",
            "error": f"Failed to parse LLM response: {str(e)}",
            "raw_response": content[:500]
        }
