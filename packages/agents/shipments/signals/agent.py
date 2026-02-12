"""
ShipmentSignalsAgent - Phase 1 signals generation for the shipments platform.

Loads shipment data from S3, runs Phase 1 skills (signal generation, health check,
delivery performance, etc.), and saves results to S3 for downstream agents.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.agents.base import BaseAgent
from packages.shared.exceptions import AgentError
from packages.shared.models import AgentManifest, AgentRequest, S3Source

from packages.agents.shipments.skills.runner import run_skills_phased


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


class ShipmentSignalsAgent(BaseAgent):
    """
    Agent that runs Phase 1 skills to generate shipment signals.

    Loads data from S3, executes signal generation and analysis skills,
    and persists output for the decoder agent.
    """

    agent_name: str = "shipment_signals"

    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="Shipment Signals Agent",
            version="1.0.0",
            description="Runs Phase 1 skills: signal generation, health check, delivery performance, and analysis",
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

    async def _execute(self, request: AgentRequest) -> Dict[str, Any]:
        customer_id = request.customer_id
        run_id = request.run_id

        self.logger.info(f"Loading shipment data for customer {customer_id}")

        # 1. Load all S3 sources
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

        # Build state dict matching what Phase 1 skills expect
        shipment_data: Dict[str, Any] = {
            "records": records,
            "baseline": baseline,
        }

        if customer_zip:
            zp_data = customer_zip.get("data")
            shipment_data["customer_zip_performance"] = zp_data[0] if isinstance(zp_data, list) and zp_data else customer_zip
        if benchmark_zip:
            bm_data = benchmark_zip.get("data")
            shipment_data["benchmark_zip_performance"] = bm_data[0] if isinstance(bm_data, list) and bm_data else benchmark_zip

        inspector_records = _extract_records(shipment_inspector) if shipment_inspector else records

        state: Dict[str, Any] = {
            "customer_id": customer_id,
            "run_id": run_id,
            "shipment_data": shipment_data,
            "shipment_inspector": {"data": inspector_records} if inspector_records else {},
            "customer_contacts": customer_contacts or {},
        }

        # 2. Run Phase 1 skills
        self.logger.info("Running Phase 1 skills")
        result = run_skills_phased(state, phase_filter=[1])
        skill_results = result.get("skill_results", {})
        errors = result.get("errors", [])

        if errors:
            self.logger.warning(f"Phase 1 completed with {len(errors)} skill errors: {errors[:3]}...")

        # Build signals markdown from skill outputs
        signals_markdown = self._build_signals_markdown(skill_results)

        output_payload: Dict[str, Any] = {
            "run_id": run_id,
            "customer_id": customer_id,
            "skill_results": skill_results,
            "signals_markdown": signals_markdown,
            "errors": errors,
            "phase": 1,
        }

        # 3. Save to S3 under shipment_agency_revised/signals/
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
            "run_id": run_id,
            "s3_paths": {"json": json_key, "markdown": md_key},
            "shipment_data": shipment_data,
        }

        return {
            "structured_output": structured_output,
            "skill_results": skill_results,
            "signals_markdown": signals_markdown,
            "shipment_data": shipment_data,
            "s3_outputs": [json_key, md_key],
        }

    def _build_signals_markdown(self, skill_results: Dict[str, Any]) -> str:
        """Build a markdown summary from Phase 1 skill results."""
        sections: List[str] = ["# Shipment Signals (Phase 1)", ""]
        for key, value in skill_results.items():
            if not value or value.get("error"):
                continue
            skill_name = value.get("skill", key)
            sections.append(f"## {skill_name}")
            if "summary" in value:
                sections.append(str(value["summary"]))
            if "observations" in value:
                for obs in value["observations"]:
                    sections.append(f"- {obs}")
            if "signals" in value:
                for sig in value["signals"][:10]:
                    sections.append(f"- {sig}")
            sections.append("")
        return "\n".join(sections) if sections else "# No signals generated"
