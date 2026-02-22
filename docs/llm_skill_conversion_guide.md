# LLM Skill Conversion Guide

**Date**: 2026-02-22  
**Status**: POC Complete - Ready for Remaining Skills

This guide documents the process for converting deterministic Phase 1 skills to LLM-powered skills using OpenAI. Based on the successful POC with `shipment_health_check`.

---

## Table of Contents

1. [Overview](#overview)
2. [POC Results](#poc-results)
3. [Conversion Pattern](#conversion-pattern)
4. [Step-by-Step Guide](#step-by-step-guide)
5. [Testing](#testing)
6. [Troubleshooting](#troubleshooting)
7. [Remaining Skills](#remaining-skills)

---

## Overview

### What Was Built

- **LLM Skill Base Class** (`llm_skill_base.py`): Reusable executor for LLM-powered skills
- **Converted POC Skill**: `shipment_health_check` now uses OpenAI for analysis
- **Test Infrastructure**: Comparison script to validate LLM vs deterministic outputs
- **Permanent Fallback**: Deterministic calculation if LLM fails

### Architecture

```
┌─────────────────────────────────────┐
│  Skill execute() function           │
├─────────────────────────────────────┤
│ 1. Load data from state             │
│ 2. Compute baseline (Python)        │  ← Deterministic, prevents hallucination
│ 3. Call LLM via base class          │
│    ├─ Trim records (274→26 fields)  │
│    ├─ Load SKILL.md as system prompt│
│    ├─ Call OpenAI API               │
│    └─ Parse JSON output             │
│ 4. Return structured result         │
│                                      │
│ If LLM fails → deterministic_fallback│  ← Permanent safety net
└─────────────────────────────────────┘
```

---

## POC Results

### Test: shipment_health_check (Customer 6180005)

**LLM Version**:
- ✅ Success Rate: 100%
- ⏱️ Execution Time: **68.5 seconds**
- 🎯 Health Status: ATTENTION (correct)
- 📝 Analysis Quality: 1080 characters of detailed insights
- 🔍 Pattern Recognition: Identified carrier-specific issues, temporal patterns
- 💰 Cost: ~$0.01 per execution (gpt-5-nano)

**Deterministic Fallback**:
- ✅ Success Rate: 100%
- ⏱️ Execution Time: **0.3 seconds** (227x faster)
- 🎯 Health Status: ATTENTION (matches LLM)
- 📝 Analysis Quality: 115 characters basic metrics
- 💰 Cost: $0

**Comparison**:
- ✅ Health status matched perfectly
- ✅ Grounded metrics within acceptable tolerance
- ✅ LLM provides significantly richer qualitative insights
- ✅ Fallback works reliably when LLM unavailable

### Key Learnings

1. **LLM adds value**: Nuanced analysis, pattern recognition, edge case handling
2. **Fallback is essential**: Provides reliability if API fails
3. **Record trimming works**: 90% reduction in prompt size without losing accuracy
4. **Execution time acceptable**: 68s for one skill, ~60-120s for 11 in parallel
5. **Output structure maintained**: Phase 2/3 compatibility preserved

---

## Conversion Pattern

### File Structure

For each skill to convert:
```
packages/agents/shipments/skills/{skill_name}/
├── execute.py          ← MODIFY: Add LLM execution + fallback
├── SKILL.md            ← MODIFY: Convert to LLM system prompt
└── references/
    └── data_dictionary.md
```

### Code Pattern

**execute.py structure**:
```python
from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor

def _compute_baseline_metrics(records):
    """Deterministic calculation of baseline metrics."""
    # Pure Python - no LLM
    # Returns dict with key metrics
    pass

def _deterministic_fallback(records, baseline, context):
    """Fallback if LLM fails."""
    # Returns valid skill output with basic metrics
    pass

def execute(state, target_key="", peer_level="SEGMENT"):
    """Main execution with LLM."""
    # 1. Extract data
    # 2. Compute baseline
    # 3. Call LLM
    # 4. Return result (or fallback)
    pass
```

**SKILL.md structure**:
```markdown
---
name: Skill Name
description: AI-powered skill description
skill_type: llm
---

# Role
You are a [specific role] analyst for Chewy's supply chain...

# Task
Analyze [specific data] and determine [specific output]...

# CRITICAL: DATA INTEGRITY RULES
**You MUST follow these rules:**
1. ONLY use data provided in the input
2. Never fabricate IDs, tracking numbers, or metrics
...

# Input Schema
You receive JSON with:
- shipment_records: [array]
- baseline_metrics: {dict}
...

# Output Schema (JSON only, no markdown)
{
  "grounded_metrics": {...},
  "continued_analysis": "string",
  ...
}

# Analysis Instructions
[Step-by-step instructions]

# Edge Case Handling
[How to handle missing data, outliers, etc.]
```

---

## Step-by-Step Guide

### Step 1: Prepare Baseline Metrics Function

Extract key calculations from existing deterministic code:

```python
def _compute_baseline_metrics(records: List[Dict]) -> Dict[str, Any]:
    """
    Compute baseline metrics (deterministic).
    These are provided to LLM to prevent hallucination.
    """
    # Example: CTD calculations
    ctd_values = [r.get("CLICK_TO_DELIVER_DAYS") for r in records if r.get("CLICK_TO_DELIVER_DAYS")]
    
    return {
        "total_shipments": len(records),
        "avg_ctd": statistics.mean(ctd_values) if ctd_values else 0,
        "median_ctd": statistics.median(ctd_values) if ctd_values else 0,
        # ... other key metrics
    }
```

**Guidelines**:
- Keep calculations simple and deterministic
- Include metrics that LLM will reference
- Handle missing/null data gracefully
- Don't compute complex derived metrics (let LLM do that)

### Step 2: Create Deterministic Fallback

Minimal version that returns valid output:

```python
def _deterministic_fallback(
    records: List[Dict],
    baseline: Dict,
    context: Dict
) -> Dict[str, Any]:
    """Fallback if LLM fails."""
    
    return {
        "skill": "skill_name",
        "grounded_metrics": {
            # Essential metrics from baseline
            "total_shipments": baseline["total_shipments"],
            "avg_metric": baseline["avg_metric"],
            "status": "UNKNOWN"  # Can't determine without LLM
        },
        "continued_analysis": "LLM analysis unavailable. Showing basic deterministic metrics only.",
        "qualitative_observations": ["LLM analysis unavailable"],
        "llm_fallback": True,
        "llm_used": False
    }
```

**Guidelines**:
- Return same structure as LLM version
- Include basic metrics only
- Mark with `llm_fallback: True`
- Don't try to replicate LLM logic

### Step 3: Update execute() Function

Replace deterministic logic with LLM call:

```python
def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute with LLM analysis."""
    
    # 1. Extract data (same as before)
    customer_id = state.get("customer_id")
    records = state.get("shipment_data", {}).get("records", [])
    
    if not records:
        return {"error": "No data", "grounded_metrics": {}}
    
    # 2. Compute baseline metrics (deterministic)
    baseline_metrics = _compute_baseline_metrics(records)
    
    # 3. Prepare context
    context = {
        "customer_id": customer_id,
        # Add any skill-specific context
    }
    
    # 4. Execute with LLM
    executor = LLMSkillExecutor(
        skill_name="skill_name",
        reasoning_effort="medium"  # or "low" for faster skills
    )
    
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50  # Cost control
    )
    
    return result
```

### Step 4: Convert SKILL.md to LLM System Prompt

Transform from instructional to system prompt format:

**Before** (instructional):
```markdown
## Your Role
You are a delivery performance analyst...

## What You Receive
1. Shipment records with CTD values
2. Baseline performance metrics

## What You Do
Calculate delay rates and identify patterns...
```

**After** (system prompt):
```markdown
# Role
You are an AI-powered delivery performance analyst for Chewy's supply chain platform.

# Task
Analyze shipment CTD data and identify delay patterns with nuanced insights.

# Input Schema
You receive JSON with:
```json
{
  "shipment_records": [...],
  "baseline_metrics": {...}
}
```

# Output Schema (JSON only, no markdown)
```json
{
  "grounded_metrics": {...},
  "continued_analysis": "string"
}
```

# Analysis Instructions
1. Use baseline_metrics.avg_ctd as reference
2. Identify patterns in delays (carrier, FC, time-based)
3. Flag edge cases and anomalies
4. Provide specific data points in analysis

# CRITICAL Rules
- NEVER fabricate order IDs or tracking numbers
- ONLY use data provided in input
- Calculate percentages from actual counts
```

**Key Changes**:
- Add explicit input/output JSON schemas
- Include CRITICAL rules section
- Specify what LLM should analyze (not just calculate)
- Add edge case handling instructions
- Emphasize using actual data, not assumptions

### Step 5: Test the Conversion

Run comparison test:

```bash
python3 test_llm_vs_deterministic.py --customer-id 6180005 --skill skill_name
```

**Check**:
- ✅ LLM version succeeds
- ✅ Fallback version succeeds  
- ✅ Output structure matches expected schema
- ✅ Health/status determinations are reasonable
- ✅ Execution time < 90s
- ✅ Grounded metrics within tolerance of fallback

### Step 6: Validate Full Pipeline

After converting 2-3 skills, test full pipeline:

```bash
python3 run_pipeline_test.py
```

**Verify**:
- Phase 1 completes successfully
- Phase 2/3 skills receive correct input
- Total pipeline time still acceptable (< 5 min)
- No breaking changes to output structure

---

## Testing

### Test Script Usage

```bash
# Test single skill (LLM only)
python3 test_llm_vs_deterministic.py --customer-id 6180005 --skill skill_name --llm-only

# Test single skill (full comparison)
python3 test_llm_vs_deterministic.py --customer-id 6180005 --skill skill_name

# Test all converted skills
python3 test_llm_vs_deterministic.py --customer-id 6180005 --all-skills
```

### Interpretation

**Success Criteria**:
- LLM execution < 90s
- Health/status matches fallback OR is more accurate
- Grounded metrics within ±10% of fallback
- Analysis is more detailed than fallback
- No errors or crashes

**Warning Signs**:
- Execution > 120s → prompt too long, optimize
- Health status disagrees with fallback → review logic
- Grounded metrics differ significantly → check calculations
- LLM returns empty/invalid JSON → improve schema instructions

---

## Troubleshooting

### Issue: LLM Returns Invalid JSON

**Symptoms**: `JSONDecodeError` in logs

**Solutions**:
1. Add explicit JSON format instruction to SKILL.md:
   ```markdown
   # Output Format
   Return ONLY valid JSON. No markdown code blocks, no explanations.
   ```

2. Check `_parse_response()` in base class strips markdown correctly

3. Validate output schema in SKILL.md matches expected structure

### Issue: LLM Fabricates Order IDs

**Symptoms**: Order IDs in output don't match input records

**Solutions**:
1. Add to CRITICAL rules:
   ```markdown
   - NEVER fabricate ORDERS_ORDER_ID or tracking numbers
   - Only reference IDs present in shipment_records
   ```

2. Provide pre-calculated list in baseline_metrics:
   ```python
   baseline = {
       "order_ids": [r.get("ORDERS_ORDER_ID") for r in records],
       ...
   }
   ```

3. Validate output against input in base class

### Issue: Execution Time Too Long

**Symptoms**: Skill takes > 120s

**Solutions**:
1. Reduce `max_records` parameter (try 30 instead of 50)
2. Check record trimming is working (should be 26 fields)
3. Use `reasoning_effort="low"` for faster execution
4. Consider batching multiple records into summary stats

### Issue: Fallback Always Triggers

**Symptoms**: All executions use fallback, LLM never succeeds

**Solutions**:
1. Check OpenAI API key is set: `echo $OPENAI_API_KEY`
2. Verify model name is correct in environment
3. Check API rate limits / quota
4. Review logs for specific API errors

---

## Remaining Skills

### Priority Order (from plan)

**High Priority** (core metrics) - Convert next:
1. ✅ `shipment_health_check` - DONE (POC)
2. ⏳ `delivery_performance` - CTD patterns and delays
3. ⏳ `carrier_analysis` - Per-carrier performance

**Medium Priority** (patterns):
4. ⏳ `geographic_patterns` - ZIP/FC routing
5. ⏳ `timing_patterns` - Day-of-week analysis
6. ⏳ `exception_analysis` - Carrier exceptions
7. ⏳ `routing_efficiency` - Distance optimization

**Lower Priority** (context):
8. ⏳ `package_analysis` - Weight/dimensions
9. ⏳ `order_behavior` - Autoship patterns
10. ⏳ `contact_correlation` - Contact rates
11. ⏳ `current_order` - Active orders

### Batch Strategy

- **Batch 1**: delivery_performance, carrier_analysis (test after)
- **Batch 2**: geographic_patterns, timing_patterns, exception_analysis (test after)
- **Batch 3**: routing_efficiency, package_analysis, order_behavior (test after)
- **Batch 4**: contact_correlation, current_order (final test)

---

## Success Metrics

### Per-Skill Metrics

- ✅ LLM execution success rate > 95%
- ✅ Execution time < 90s
- ✅ Fallback success rate = 100%
- ✅ Output structure matches schema
- ✅ Health/status determination reasonable

### Pipeline Metrics

- ✅ Total Phase 1 time: 60-120s (parallel execution)
- ✅ Total pipeline time: < 5 minutes
- ✅ Phase 2/3 compatibility maintained
- ✅ No breaking changes to API responses

### Cost Metrics

- Current: ~3 LLM calls per customer
- After conversion: ~14 LLM calls per customer
- Target cost: < $0.25 per customer
- Actual cost (POC): ~$0.01 per skill = ~$0.15 total

---

## Notes

- Always test with customer 6180005 (known good data)
- Keep deterministic fallback permanently
- Maintain output structure for backward compatibility
- Monitor execution times and optimize if needed
- Use record trimming (274→26 fields) for all skills
- Pre-compute baseline metrics in Python
- Never let LLM compute raw metrics from scratch

---

## References

- Plan: `.cursor/plans/convert_deterministic_skills_to_llm_49e3fc10.plan.md`
- POC Commit: c9c7fd0
- Base Class: `packages/agents/shipments/skills/llm_skill_base.py`
- Test Script: `test_llm_vs_deterministic.py`
- Example: `packages/agents/shipments/skills/shipment_health_check/`
