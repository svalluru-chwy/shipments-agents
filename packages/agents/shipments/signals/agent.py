"""
ShipmentSignalsAgent - Phase 1 signals generation for the shipments platform.

Flow:
  1. Load shipment data from S3
  2. Run Check Gate (LLM RED-flag decision) -- determines if analysis is warranted
  3. Run Phase 1 skills (12 skills in parallel) including contact_correlation
  4. Save results to S3 and locally for downstream decoder agent
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from packages.agents.base import BaseAgent
from packages.shared.exceptions import AgentError
from packages.shared.models import AgentManifest, AgentRequest, S3Source

from packages.agents.shipments.skills.runner import run_skills_phased


# ---------------------------------------------------------------------------
# Check Gate: LLM system prompt from cat-agents check_node_llm.py
# ---------------------------------------------------------------------------

CHECK_GATE_SYSTEM_PROMPT = """# Role

You are a Shipment Performance Analyst for Chewy's Customer Action Team (CAT). Your job is to analyze a customer's shipment history and determine if it warrants detailed investigation.

# Your Task

Analyze the provided shipment data and decide:
1. Is there a RED flag? (warrants detailed analysis)
2. What specific issues exist?
3. What is the severity level?
4. What should we investigate?

# Decision Criteria for RED Flag

Flag as RED if **any** of the following apply:

## High Priority (Immediate RED)
- **Critical Item Delays**: Rx/medication shipments delayed >2 days
- **Active At-Risk**: Packages in transit >7 days without delivery
- **High Exception Rate**: >10% of shipments have carrier exceptions
- **Multiple Recent Delays**: 3+ delays in last 30 days

## Medium Priority (RED for High-Value Customers)
- **Performance Degradation**: Customer CTD significantly worse than ZIP benchmark
- **Increasing Delay Trend**: Delays increasing over time
- **Cluster of Issues**: Multiple delayed shipments to same address
- **High-Value Customer Impact**: LTV >$1000 with any delay pattern

## Context Factors (Influence Decision)
- **Customer Tier**: Loyal/Engaged customers get lower threshold for RED
- **LTV**: Higher LTV = more sensitivity to issues
- **Recency**: Recent issues matter more than historical
- **Product Mix**: Essential items (food, meds) get higher priority

# What NOT to Flag as RED
- One-time delays >60 days ago (historical)
- Weather-related delays that are now resolved
- Customer-caused delays (incorrect address, refused delivery)
- Normal variation within ZIP benchmark range
- Low-value one-time buyers with single historical delay

# Analysis Approach

1. **Calculate Key Metrics**:
   - Total shipments (last 60 days)
   - Average CTD vs ZIP benchmark
   - Delay rate, exception rate
   - Active shipments at risk

2. **Assess Severity**:
   - CRITICAL: Immediate customer impact (Rx delays, active at-risk)
   - HIGH: Pattern of issues, high-value customer affected
   - MEDIUM: Performance below benchmark, needs monitoring
   - LOW: Minor issues, no immediate action needed

3. **Consider Context**:
   - Customer value (LTV, tier)
   - Product criticality (Rx, food vs toys)
   - Recency and trends
   - Historical relationship

4. **Make Decision**:
   - RED if CRITICAL or HIGH severity
   - RED if MEDIUM severity + high customer value
   - GREEN otherwise

# Output Format

Return valid JSON (no markdown formatting):

{
  "is_red": true,
  "peer_level": "SEGMENT",
  "severity": "HIGH",
  "issues_summary": "4 delayed shipments in last 30 days, customer CTD 45% above ZIP benchmark",
  "investigation_reasons": [
    "4 shipments delayed beyond threshold",
    "Customer CTD (2.8 days) is 45% above ZIP benchmark (1.9 days)",
    "High-value customer (LTV $2,341) experiencing consistent delays"
  ],
  "key_metrics": {
    "total_shipments_60d": 12,
    "delayed_count": 4,
    "delay_rate_pct": 33.3,
    "avg_ctd_days": 2.8,
    "zip_benchmark_ctd": 1.9,
    "pct_above_benchmark": 47.4,
    "active_at_risk": 1,
    "exceptions_count": 2
  },
  "critical_issues": [],
  "recommended_peer_level": "SEGMENT",
  "confidence": "HIGH",
  "reasoning": "Multiple delayed shipments combined with performance significantly below ZIP benchmark indicates systematic delivery issues."
}

# Critical Rules

1. **Only use data provided** - do not infer or fabricate tracking numbers, dates, or metrics
2. **Be conservative with RED flags** - false positives waste resources
3. **Consider customer value** - higher LTV = lower threshold for RED
4. **Focus on recent issues** - last 30 days matters most
5. **Distinguish patterns from noise** - one-off events don't warrant RED unless critical
6. **Return valid JSON only** - no markdown code blocks, no explanatory text outside JSON
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_records(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract records array from S3 JSON (handles data/records keys)."""
    if not data:
        return []
    if isinstance(data, list):
        return data
    records = data.get("records") or data.get("data") or []
    return records if isinstance(records, list) else []


def _build_baseline(records: List[Dict[str, Any]], summary_stats: Optional[Dict] = None) -> Dict[str, Any]:
    """Compute baseline stats (ctd_avg, ctd_threshold, primary_carrier) for skills."""
    baseline: Dict[str, Any] = {}
    if summary_stats:
        baseline.update(summary_stats)

    ctd_values = []
    carrier_counts: Dict[str, int] = {}
    for r in records:
        ctd = r.get("CLICK_TO_DELIVER_DAYS")
        if ctd is not None:
            try:
                ctd_values.append(float(ctd))
            except (ValueError, TypeError):
                pass
        carrier = r.get("WAREHOUSE_CARRIER") or "Unknown"
        carrier_counts[carrier] = carrier_counts.get(carrier, 0) + 1

    if ctd_values:
        baseline.setdefault("ctd_avg", round(statistics.mean(ctd_values), 2))
        std = statistics.stdev(ctd_values) if len(ctd_values) > 1 else 0
        baseline.setdefault(
            "ctd_threshold",
            round(baseline.get("ctd_avg", 0) + std, 2) if std else baseline.get("ctd_avg", 3.0),
        )
    else:
        baseline.setdefault("ctd_avg", 0)
        baseline.setdefault("ctd_threshold", 3.0)

    if carrier_counts:
        baseline.setdefault("primary_carrier", max(carrier_counts, key=carrier_counts.get))
    baseline.setdefault("total_records", len(records))

    return baseline


def _filter_recent_records(records: List[Dict[str, Any]], days: int = 60) -> List[Dict[str, Any]]:
    """Filter shipment records to the last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    recent: List[Dict[str, Any]] = []

    for record in records:
        order_date = record.get("ORDER_PLACED_DTTM") or record.get("ACTUAL_SHIP_DATE")
        if order_date:
            try:
                if isinstance(order_date, str):
                    parsed = datetime.fromisoformat(order_date.replace("Z", "+00:00"))
                else:
                    parsed = order_date
                if parsed.replace(tzinfo=None) >= cutoff:
                    recent.append(record)
            except Exception:
                recent.append(record)
        else:
            recent.append(record)
    return recent


def _build_check_gate_context(
    customer_id: str,
    records: List[Dict[str, Any]],
    recent_records: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    benchmark_zip: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the data context dict that the check gate LLM expects."""
    # Extract benchmark CTD
    benchmark_ctd = None
    if benchmark_zip:
        zip_data = benchmark_zip.get("data", [benchmark_zip]) if isinstance(benchmark_zip, dict) else benchmark_zip
        if zip_data and len(zip_data) > 0:
            zip_record = zip_data[0] if isinstance(zip_data, list) else zip_data
            benchmark_ctd = zip_record.get("AVG_CTD") or zip_record.get("BENCHMARK_CTD")

    customer_context = {
        "customer_id": customer_id,
        "customer_tier": "Unknown",
        "ltv": 0,
        "engagement_class": "Unknown",
    }

    shipment_summary = []
    for record in recent_records[:50]:
        summary = {
            "order_id": record.get("ORDER_ID"),
            "tracking": record.get("SHIPMENT_TRACKING_NUMBER"),
            "order_date": str(record.get("ORDER_PLACED_DTTM", ""))[:10],
            "ship_date": str(record.get("SHIPMENT_SHIPPED_DTTM", ""))[:10],
            "delivery_date": str(record.get("BULK_TRACK_DELIVERY_DTTM", ""))[:10] if record.get("BULK_TRACK_DELIVERY_DTTM") else None,
            "status": record.get("BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION") or record.get("STATUS"),
            "carrier": record.get("WAREHOUSE_CARRIER"),
            "ctd_days": record.get("CLICK_TO_DELIVER_DAYS") or record.get("CTD"),
            "delayed_flag": record.get("SHIPMENT_WAS_DELAYED") or record.get("WIZMO_SHIPMENT_WAS_DELAYED"),
            "exception": record.get("EXCEPTION_CODE") or record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION"),
            "product_category": record.get("MC2") or record.get("CATEGORY"),
            "zip": record.get("POSTCODE"),
        }
        shipment_summary.append(summary)

    return {
        "customer": customer_context,
        "shipments": {
            "total_records": len(records),
            "recent_60d_count": len(recent_records),
            "baseline_metrics": {
                "avg_ctd": baseline.get("ctd_avg"),
                "median_ctd": baseline.get("ctd_median"),
                "ctd_threshold": baseline.get("ctd_threshold"),
                "on_time_rate": baseline.get("on_time_rate"),
            },
            "zip_benchmark_ctd": benchmark_ctd,
            "shipment_details": shipment_summary,
        },
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ShipmentSignalsAgent(BaseAgent):
    """
    Agent that runs the check gate + Phase 1 skills to generate shipment signals.

    Flow:
      1. Load S3 data (main shipment, contacts, ZIP perf, inspector, summary stats)
      2. Run Check Gate LLM to determine if RED-flag analysis is warranted
      3. Run Phase 1 skills (12 skills in parallel)
      4. Save results to S3 and return structured output for decoder
    """

    agent_name: str = "shipment_signals"

    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="Shipment Signals Agent",
            version="1.0.0",
            description="Check gate + Phase 1 skills: signal generation, health check, delivery performance, contact correlation, and analysis",
            agent_name=self.agent_name,
            s3_sources=[
                S3Source(folder="main_shipment_query", description="Main shipment query data"),
                S3Source(folder="customer_contacts_query", description="Customer contacts data"),
                S3Source(folder="customer_zip_performance", description="Customer ZIP performance metrics"),
                S3Source(folder="benchmark_zip_performance", description="Benchmark ZIP performance"),
                S3Source(folder="shipment_inspector_query", description="Shipment inspector with routing data"),
                S3Source(folder="order_shipment_summary_stats", description="Order/shipment summary statistics"),
            ],
            output_types=["json", "markdown"],
            output_path_template="shipment_agency_revised/signals/{run_id}.json",
            depends_on=[],
        )

    # ------------------------------------------------------------------
    # Check Gate
    # ------------------------------------------------------------------

    def _run_check_gate(
        self,
        customer_id: str,
        records: List[Dict[str, Any]],
        baseline: Dict[str, Any],
        benchmark_zip: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Run the LLM-powered check gate to decide if RED-flag analysis is warranted.

        Returns the parsed LLM response dict (is_red, severity, investigation_reasons, ...).
        Falls back to a deterministic heuristic if the LLM call fails.
        """
        recent_records = _filter_recent_records(records, days=60)
        self.logger.info(f"Check gate: {len(recent_records)} shipments in last 60 days (of {len(records)} total)")

        data_context = _build_check_gate_context(customer_id, records, recent_records, baseline, benchmark_zip)

        question = (
            "Analyze this customer's shipment data and determine if detailed investigation is warranted.\n\n"
            "Consider:\n"
            "1. Are there delayed shipments or exceptions?\n"
            "2. Is customer performance worse than ZIP benchmark?\n"
            "3. Are there active shipments at risk?\n"
            "4. Given the customer's tier and LTV, is this worth investigating?\n\n"
            "Return your analysis and RED flag decision in the specified JSON format."
        )

        # Build user prompt with sections (same pattern as cat-agents call_llm_with_context)
        section_parts = []
        for key, value in data_context.items():
            section_parts.append(f"\n## {key}\n\n{json.dumps(value, indent=2, default=str)}")
        user_prompt = "".join(section_parts) + f"\n\n## Question\n\n{question}\n"

        try:
            model = self.settings.agents.shipment_signals.check_gate_model
            self.logger.info(f"Calling check gate LLM ({model})...")

            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CHECK_GATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                timeout=120,
            )

            content = response.choices[0].message.content or "{}"
            result = json.loads(content)

            is_red = result.get("is_red", False)
            severity = result.get("severity", "LOW")
            self.logger.info(f"Check gate result: is_red={is_red}, severity={severity}")

            if is_red:
                self.logger.info(f"  RED flag: {result.get('issues_summary', 'Issues detected')}")
            else:
                self.logger.info("  GREEN: No significant shipment issues detected")

            return result

        except Exception as e:
            self.logger.warning(f"Check gate LLM failed ({e}), using deterministic fallback")
            # Fallback: flag RED if any recent delayed shipments exist
            is_red = any(r.get("SHIPMENT_WAS_DELAYED") for r in recent_records)
            return {
                "is_red": is_red,
                "severity": "MEDIUM" if is_red else "LOW",
                "issues_summary": "Fallback heuristic: delayed shipments detected" if is_red else "No issues",
                "investigation_reasons": ["LLM analysis failed, using fallback heuristic"],
                "key_metrics": {
                    "total_shipments_60d": len(recent_records),
                    "delayed_count": sum(1 for r in recent_records if r.get("SHIPMENT_WAS_DELAYED")),
                },
                "critical_issues": [],
                "confidence": "LOW",
                "reasoning": "Deterministic fallback used because LLM call failed.",
            }

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def _execute(self, request: AgentRequest) -> Dict[str, Any]:
        customer_id = request.customer_id
        run_id = request.run_id

        self.logger.info(f"Loading shipment data for customer {customer_id}")

        # ---- Step 1: Load all S3 sources ----
        main_shipment = self.load_customer_json(customer_id, "main_shipment_query")
        customer_contacts = self.load_customer_json(customer_id, "customer_contacts_query")
        customer_zip = self.load_customer_json(customer_id, "customer_zip_performance")
        benchmark_zip = self.load_customer_json(customer_id, "benchmark_zip_performance")
        shipment_inspector = self.load_customer_json(customer_id, "shipment_inspector_query")
        summary_stats = self.load_customer_json(customer_id, "order_shipment_summary_stats")

        records = _extract_records(main_shipment)
        if not records:
            raise AgentError(
                f"No shipment records found for customer {customer_id} in main_shipment_query",
                agent_name=self.agent_name,
            )

        baseline = _build_baseline(records, summary_stats)

        # ---- Step 2: Run Check Gate ----
        check_gate_result = self._run_check_gate(customer_id, records, baseline, benchmark_zip)

        # ---- Step 3: Build state for Phase 1 skills ----
        shipment_data: Dict[str, Any] = {
            "records": records,
            "baseline": baseline,
            "check_gate": check_gate_result,
        }

        if customer_zip:
            zp_data = customer_zip.get("data")
            shipment_data["customer_zip_performance"] = zp_data[0] if isinstance(zp_data, list) and zp_data else customer_zip
        if benchmark_zip:
            bm_data = benchmark_zip.get("data")
            shipment_data["benchmark_zip_performance"] = bm_data[0] if isinstance(bm_data, list) and bm_data else benchmark_zip

        inspector_records = _extract_records(shipment_inspector) if shipment_inspector else records

        # Extract contact records for the contact_correlation skill.
        # The skill reads from state["voc_data"]["contacts"], so we map
        # the customer_contacts_query data to that key.
        contact_records = _extract_records(customer_contacts)

        state: Dict[str, Any] = {
            "customer_id": customer_id,
            "run_id": run_id,
            "shipment_data": shipment_data,
            "shipment_inspector": {"data": inspector_records} if inspector_records else {},
            # contact_correlation reads from voc_data.contacts
            "voc_data": {"contacts": contact_records},
            # Also store raw contacts for other skills that may read it differently
            "customer_contacts": customer_contacts or {},
        }

        # ---- Step 4: Run Phase 1 skills ----
        self.logger.info("Running Phase 1 skills (12 skills)")
        result = run_skills_phased(state, phase_filter=[1])
        skill_results = result.get("skill_results", {})
        errors = result.get("errors", [])

        if errors:
            self.logger.warning(f"Phase 1 completed with {len(errors)} skill errors: {errors[:3]}...")

        # Build signals markdown from skill outputs
        signals_markdown = self._build_signals_markdown(skill_results, check_gate_result)

        output_payload: Dict[str, Any] = {
            "run_id": run_id,
            "customer_id": customer_id,
            "check_gate": check_gate_result,
            "skill_results": skill_results,
            "signals_markdown": signals_markdown,
            "errors": errors,
            "phase": 1,
        }

        # ---- Step 5: Save to S3 ----
        base_path = self.settings.s3.base_path
        output_folder = "shipment_agency_revised/signals"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.json"
        md_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.md"

        try:
            self.s3.upload_json(output_payload, json_key)
            self.s3.upload_text(signals_markdown, md_key)
            self.logger.info(f"Saved signals to s3://{self.s3.bucket}/{json_key}")
        except Exception as e:
            self.logger.error(f"Failed to save signals to S3: {e}")
            raise AgentError(f"S3 upload failed: {e}", agent_name=self.agent_name) from e

        structured_output = {
            "skill_results": skill_results,
            "signals_markdown": signals_markdown,
            "check_gate": check_gate_result,
            "run_id": run_id,
            "s3_paths": {"json": json_key, "markdown": md_key},
            "shipment_data": shipment_data,
        }

        return {
            "structured_output": structured_output,
            "skill_results": skill_results,
            "signals_markdown": signals_markdown,
            "check_gate": check_gate_result,
            "shipment_data": shipment_data,
            "s3_paths": {"json": json_key, "markdown": md_key},
        }

    # ------------------------------------------------------------------
    # Markdown builder
    # ------------------------------------------------------------------

    def _build_signals_markdown(self, skill_results: Dict[str, Any], check_gate: Dict[str, Any]) -> str:
        """Build a markdown summary from check gate + Phase 1 skill results."""
        sections: List[str] = ["# Shipment Signals Report", ""]

        # Check gate section
        sections.append("## Check Gate Analysis")
        is_red = check_gate.get("is_red", False)
        severity = check_gate.get("severity", "N/A")
        sections.append(f"- **RED Flag**: {'YES' if is_red else 'NO'}")
        sections.append(f"- **Severity**: {severity}")
        if check_gate.get("issues_summary"):
            sections.append(f"- **Summary**: {check_gate['issues_summary']}")
        reasons = check_gate.get("investigation_reasons", [])
        if reasons:
            sections.append("- **Investigation Reasons**:")
            for reason in reasons:
                sections.append(f"  - {reason}")
        key_metrics = check_gate.get("key_metrics", {})
        if key_metrics:
            sections.append("- **Key Metrics**:")
            for k, v in key_metrics.items():
                sections.append(f"  - {k}: {v}")
        sections.append("")

        # Phase 1 skill results
        sections.append("## Phase 1 Skill Results")
        sections.append("")
        for key, value in skill_results.items():
            if not value or value.get("error"):
                continue
            skill_name = value.get("skill", key)
            sections.append(f"### {skill_name}")
            if "summary" in value:
                sections.append(str(value["summary"]))
            if "observations" in value:
                for obs in value["observations"]:
                    sections.append(f"- {obs}")
            if "signals" in value:
                for sig in value["signals"][:10]:
                    sections.append(f"- {sig}")
            if "continued_analysis" in value:
                sections.append(f"\n{value['continued_analysis']}")
            sections.append("")

        return "\n".join(sections) if sections else "# No signals generated"
