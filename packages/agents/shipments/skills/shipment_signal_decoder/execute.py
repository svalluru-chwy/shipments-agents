"""
Shipment Signal Decoder Skill - Execution Logic

Decodes signals to determine root causes and business impact.
Based on the original shipments_signal_decoder_agent_fixed.py.
"""

import json
import os
from typing import Dict, Any, List

from openai import OpenAI

from packages.agents.shipments.skills.loader import load_skill_instructions, load_reference_docs
from packages.agents.shipments.skills.record_trimmer import trim_records

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano-2025-08-07")


def build_prompt(
    state: Dict[str, Any],
    signals: List[Dict],
    shipment_records: List[Dict]
) -> str:
    """
    Build the signal decoding prompt.
    
    Args:
        state: Current agent state
        signals: Generated signals to decode
        shipment_records: Raw shipment records for evidence
        
    Returns:
        Complete prompt string
    """
    # Load skill instructions
    skill_md = load_skill_instructions("shipment_signal_decoder")
    
    # Load data dictionary
    data_dict = load_reference_docs("shipment_signal_decoder")
    
    # Get customer context
    customer_id = state.get("customer_id", "unknown")
    customer_profile = state.get("customer_profile")
    
    # Build customer context
    customer_context = f"""
## CUSTOMER CONTEXT
- Customer ID: {customer_id}
- Customer Class: {customer_profile.customer_class if customer_profile else 'Unknown'}
- LTV: ${customer_profile.ltv if customer_profile else 0:.2f}
- Churn Risk: {customer_profile.churn_risk if customer_profile else 'Unknown'}
"""
    
    # Build signals section
    signals_section = f"""
## SIGNALS TO DECODE
Total Signals: {len(signals)}

```json
{json.dumps(signals, indent=2, default=str)}
```
"""
    
    # Build raw data section (sample for context, trimmed to relevant fields)
    sample_records = shipment_records[:10] if shipment_records else []
    trimmed_samples = trim_records(sample_records)
    data_section = f"""
## SHIPMENT DATA (Sample, trimmed to relevant fields)
Available for evidence gathering:

```json
{json.dumps(trimmed_samples, indent=2, default=str)}
```
"""
    
    # Combine all sections
    prompt = f"""{skill_md}

---

{data_dict}

---

{customer_context}

{signals_section}

{data_section}

---

## MANDATE
For each signal:
1. Determine root cause at all 3 levels
2. Quantify business impact with specific metrics
3. Assess customer experience and pet care impact
4. Cite specific evidence from the data
5. Write a synthesis paragraph

Output ONLY valid JSON. No markdown, no code blocks, no additional text.
"""
    
    return prompt


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """
    Execute the shipment signal decoder skill.
    
    Args:
        state: Current agent state with signals
        target_key: State key being enhanced (e.g., "shipments_result")
        peer_level: Peer comparison level
        
    Returns:
        Decoded signal results
    """
    customer_id = state.get("customer_id", "unknown")
    prompt_logger = state.get("prompt_logger")
    
    # Get signals from phased execution (skill_results or top-level key)
    signals = []
    shipment_records = []
    
    # With phased execution, signal_generator_result is a top-level key
    generator_result = state.get("shipment_signal_generator_result", {})
    if isinstance(generator_result, dict):
        signals = generator_result.get("signals", [])

    # Fallback: check skill_results
    if not signals:
        skill_results = state.get("skill_results", {})
        gen_result = skill_results.get("shipment_signal_generator_result", {})
        if isinstance(gen_result, dict):
            signals = gen_result.get("signals", [])
    
    # Get shipment records
    if state.get("shipment_data"):
        shipment_records = state["shipment_data"].get("records", [])
    
    if not signals:
        return {
            "skill": "shipment_signal_decoder",
            "error": "No signals available to decode",
            "decoded_signals": []
        }
    
    # Build prompt
    prompt = build_prompt(state, signals, shipment_records)
    
    # Call LLM using Responses API
    client = OpenAI(timeout=600.0)
    
    system_prompt = """You are a Signal Decoder Agent performing root cause analysis.

CRITICAL ANTI-HALLUCINATION REQUIREMENTS:
- Use ONLY data explicitly present in the input
- Do NOT fabricate carrier names, dates, or metrics
- Reference specific field names when making claims
- If information is missing, state "not available in data"

ANALYSIS REQUIREMENTS:
- Provide root cause at all 3 levels (direct, systemic, external)
- Quantify business impact with specific numbers
- Assess customer and pet care impact
- Cite evidence from the data
- Output ONLY valid JSON"""
    
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
            metric_name="Shipment Signal Decoder",
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
        result["skill"] = "shipment_signal_decoder"
        return result
        
    except json.JSONDecodeError as e:
        return {
            "skill": "shipment_signal_decoder",
            "error": f"Failed to parse LLM response: {str(e)}",
            "raw_response": content[:500]
        }
