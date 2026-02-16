---
name: Customer Risk Profile
description: Deterministic cross-skill computation that produces a customer-level risk profile from Phase 1+2 results. No LLM call.
domain: shipments
skill_type: synthesis
enhances:
  - shipment_signal_generator_result
  - carrier_analysis_result
  - delivery_performance_result
  - order_behavior_result
  - contact_correlation_result
  - current_order_result
---

## Your Role

You are a deterministic post-processing step that runs after all Phase 1 and Phase 2 skills. You cross-reference their outputs to produce a structured customer risk profile with four dimensions.

This skill makes zero LLM calls. All computation is pure Python.

---

## What You Receive

All Phase 1 and Phase 2 skill results via the shared state dict, including:

- `shipment_signal_generator_result` -- signals with `recency`, `days_since_event`
- `carrier_analysis_result` -- carrier delay rates and performance
- `delivery_performance_result` -- trend direction, CTD stats
- `order_behavior_result` -- autoship rate, order frequency
- `contact_correlation_result` -- contact rate, WISMO rate
- `current_order_result` -- active/at-risk orders

---

## What You Compute

### 1. Temporal Recency

Classify signals into recent (<=14 days), historical (>14 days), and active buckets. Count each. List details for recent/active signals.

### 2. Pattern Correlation

Group flagged signals by carrier + fulfillment center route. Identify the dominant pattern. Cross-reference with carrier delay rates.

### 3. Forward Risk

Estimate future delay exposure: autoship_rate x primary_carrier_share x carrier_delay_rate. Factor in trend direction.

### 4. Relationship Signal

Combine WISMO rate, contact rate, product criticality (Rx/fresh on autoship), and active-at-risk count.

### Overall Risk Level

- "high": any active signals, or recent + high severity
- "elevated": carrier pattern + declining trend + high autoship
- "moderate": some signals but mostly historical, stable trend
- "low": all historical, improving/stable trend

---

## Output Scope

**Include:**
- Four risk dimensions with grounded metrics
- Overall risk level determination
- Per-dimension findings (one-sentence summaries)

**Do NOT Include:**
- Actions or recommendations
- LLM-generated text
- Speculative predictions
