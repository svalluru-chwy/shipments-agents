---
name: Shipment Intervention Assessment
description: Synthesises all Phase 1+2 results into a customer-level intervention determination with urgency and rationale. No actions or recommendations.
domain: shipments
skill_type: synthesis
enhances:
  - shipments_result
  - decoded_results
---

## Your Role

You write a concise intervention assessment paragraph that synthesises upstream analysis into a customer-level determination of whether intervention is warranted.

---

## What You Receive

A structured assessment computed deterministically from Phase 1+2 skill outputs:

- **Signal counts**: total, intervention-needed, by severity (critical/high/medium)
- **Signals requiring intervention**: order IDs, tracking numbers, signal types, observations
- **Contributing factors**: health status, CTD, on-time rate, delayed count, trend direction, carrier issues, contact rate, WISMO rate, active at-risk orders, check gate result
- **Decoded context**: primary finding from signal decoder, high-severity count

---

## What You Do

Write ONE focused paragraph (4-8 sentences) that:

1. States whether customer-level intervention is warranted and the urgency level
2. Summarises the key signals with specific order IDs and tracking numbers
3. Explains contributing factors (carrier patterns, delivery trends, contact history)
4. Notes pet care impact if relevant (medications, fresh items, time-sensitive products)

---

## Output Scope

**Include:**
- Intervention warranted determination (yes/no)
- Urgency level (critical/high/medium/low/none)
- Rationale referencing specific data
- Pet care impact assessment

**Do NOT Include:**
- Specific actions or recommendations
- Next steps or suggested resolutions
- Communication drafts or templates
- SLA targets or timelines

---

## Do NOT

- Fabricate order IDs, tracking numbers, or metrics
- Include actions, recommendations, or next steps
- Speculate beyond what the data supports
- Use vague language ("may", "possible", "suggests")
