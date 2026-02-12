"""
ShipmentDecoderAgent - Phase 2 signal decoding for the shipments platform.

Loads signals from upstream ShipmentSignalsAgent or S3 fallback, runs Phase 2 skills
(delay predictor, signal decoder), and saves decoded results for the actions agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from packages.agents.base import BaseAgent
from packages.shared.exceptions import AgentError
from packages.shared.models import AgentManifest, AgentRequest, S3Source

from packages.agents.shipments.skills.runner import run_skills_phased


def _extract_records(data: Optional[Dict[str, Any]]) -> list:
    """Extract records array from S3 JSON (handles data/records keys)."""
    if not data:
        return []
    if isinstance(data, list):
        return data
    records = data.get("records") or data.get("data") or []
    return records if isinstance(records, list) else []


class ShipmentDecoderAgent(BaseAgent):
    """
    Agent that runs Phase 2 skills to decode shipment signals.

    Depends on ShipmentSignalsAgent. Loads signals from upstream_data or S3,
    runs delay predictor and signal decoder, persists for actions agent.
    """

    agent_name: str = "shipment_decoder"

    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="Shipment Decoder Agent",
            version="1.0.0",
            description="Runs Phase 2 skills: delay prediction and signal decoding",
            agent_name=self.agent_name,
            s3_sources=[
                S3Source(folder="shipment_agency_revised/signals", description="Signals output from upstream agent"),
                S3Source(folder="shipment_inspector_query", description="Shipment inspector data for context"),
            ],
            output_types=["json", "markdown"],
            output_path_template="shipment_agency_revised/decoded_signals/{run_id}.json",
            depends_on=["shipment_signals"],
        )

    async def _execute(self, request: AgentRequest) -> Dict[str, Any]:
        customer_id = request.customer_id
        run_id = request.run_id

        # 1. Load signals from upstream_data or S3 fallback
        if request.upstream_data:
            self.logger.info("Using upstream_data for signals")
            signals_data = request.upstream_data
            skill_results = signals_data.get("skill_results", signals_data.get("structured_output", {}).get("skill_results", {}))
        else:
            self.logger.info("Loading signals from S3 fallback")
            key = self.s3.find_latest_customer_file(
                customer_id,
                "shipment_agency_revised/signals",
                base_path=self.settings.s3.base_path,
                suffix=".json",
            )
            if not key:
                raise AgentError(
                    f"No signals found for customer {customer_id}. Run ShipmentSignalsAgent first.",
                    agent_name=self.agent_name,
                )
            signals_data = self.s3.download_json(key)
            skill_results = signals_data.get("skill_results", {})

        # Load shipment inspector for Phase 2 skills that need shipment records
        shipment_inspector = self.load_customer_json(customer_id, "shipment_inspector_query")
        main_shipment = self.load_customer_json(customer_id, "main_shipment_query")
        records = _extract_records(shipment_inspector) or _extract_records(main_shipment)

        state: Dict[str, Any] = {
            "customer_id": customer_id,
            "run_id": run_id,
            "skill_results": skill_results,
            "shipment_data": {"records": records},
            "shipment_inspector": {"data": records} if records else {},
        }

        # Inject Phase 1 results into state for Phase 2 skills
        for k, v in skill_results.items():
            state[k] = v

        # 2. Run Phase 2 skills
        self.logger.info("Running Phase 2 skills")
        result = run_skills_phased(state, phase_filter=[2])
        decoded_results = result.get("skill_results", {})
        errors = result.get("errors", [])

        if errors:
            self.logger.warning(f"Phase 2 completed with {len(errors)} skill errors: {errors[:3]}...")

        decoded_markdown = self._build_decoded_markdown(decoded_results)

        output_payload: Dict[str, Any] = {
            "run_id": run_id,
            "customer_id": customer_id,
            "decoded_results": decoded_results,
            "decoded_markdown": decoded_markdown,
            "errors": errors,
            "phase": 2,
            "skill_results": {**skill_results, **decoded_results},
        }

        # 3. Save to S3 under shipment_agency_revised/decoded_signals/
        base_path = self.settings.s3.base_path
        output_folder = "shipment_agency_revised/decoded_signals"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.json"
        md_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.md"

        try:
            self.s3.upload_json(output_payload, json_key)
            self.s3.upload_text(decoded_markdown, md_key)
            self.logger.info(f"Saved decoded signals to s3://{self.s3.bucket}/{json_key}")
        except Exception as e:
            self.logger.error(f"Failed to save decoded signals to S3: {e}")
            raise AgentError(f"S3 upload failed: {e}", agent_name=self.agent_name) from e

        structured_output = {
            "decoded_results": decoded_results,
            "decoded_markdown": decoded_markdown,
            "skill_results": {**skill_results, **decoded_results},
            "run_id": run_id,
            "s3_paths": {"json": json_key, "markdown": md_key},
        }

        return {
            "structured_output": structured_output,
            "decoded_results": decoded_results,
            "decoded_markdown": decoded_markdown,
            "s3_outputs": [json_key, md_key],
        }

    def _build_decoded_markdown(self, decoded_results: Dict[str, Any]) -> str:
        """Build markdown summary from Phase 2 skill results."""
        sections = ["# Decoded Shipment Signals (Phase 2)", ""]
        for key, value in decoded_results.items():
            if not value or value.get("error"):
                continue
            skill_name = value.get("skill", key)
            sections.append(f"## {skill_name}")
            if "summary" in value:
                sections.append(str(value["summary"]))
            if "observations" in value:
                for obs in value["observations"]:
                    sections.append(f"- {obs}")
            if "predictions" in value:
                for pred in value["predictions"][:10]:
                    sections.append(f"- {pred}")
            if "root_causes" in value:
                for rc in value["root_causes"][:10]:
                    sections.append(f"- {rc}")
            sections.append("")
        return "\n".join(sections) if sections else "# No decoded results"
