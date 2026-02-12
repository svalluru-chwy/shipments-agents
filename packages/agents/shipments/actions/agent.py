"""
ShipmentActionsAgent - Phase 3-4 action planning and consolidation for the shipments platform.

Loads decoded signals from upstream ShipmentDecoderAgent or S3 fallback, runs Phase 3
(intervention, prioritizer) and Phase 4 (consolidator) skills, and saves consolidated
results to S3.
"""

from __future__ import annotations

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


class ShipmentActionsAgent(BaseAgent):
    """
    Agent that runs Phase 3-4 skills for action planning and consolidation.

    Depends on ShipmentDecoderAgent. Loads decoded output from upstream or S3,
    runs intervention, prioritizer, and consolidator skills.
    """

    agent_name: str = "shipment_actions"

    def manifest(self) -> AgentManifest:
        return AgentManifest(
            name="Shipment Actions Agent",
            version="1.0.0",
            description="Runs Phase 3-4 skills: intervention, prioritizer, and consolidator",
            agent_name=self.agent_name,
            s3_sources=[
                S3Source(
                    folder="shipment_agency_revised/decoded_signals",
                    description="Decoded signals output from upstream agent",
                ),
                S3Source(folder="customer_information_query", description="Customer profile and information"),
            ],
            output_types=["json", "markdown"],
            output_path_template="shipment_agency_revised/consolidated/{run_id}.json",
            depends_on=["shipment_decoder"],
        )

    async def _execute(self, request: AgentRequest) -> Dict[str, Any]:
        customer_id = request.customer_id
        run_id = request.run_id

        # 1. Load decoded signals from upstream_data or S3 fallback
        if request.upstream_data:
            self.logger.info("Using upstream_data for decoded signals")
            decoded_data = request.upstream_data
            all_skill_results = decoded_data.get(
                "skill_results",
                decoded_data.get("structured_output", {}).get("skill_results", {}),
            )
        else:
            self.logger.info("Loading decoded signals from S3 fallback")
            key = self.s3.find_latest_customer_file(
                customer_id,
                "shipment_agency_revised/decoded_signals",
                base_path=self.settings.s3.base_path,
                suffix=".json",
            )
            if not key:
                raise AgentError(
                    f"No decoded signals found for customer {customer_id}. Run ShipmentDecoderAgent first.",
                    agent_name=self.agent_name,
                )
            decoded_data = self.s3.download_json(key)
            all_skill_results = decoded_data.get("skill_results", {})

        # Load customer information and shipment data for Phase 3-4 skills
        customer_info = self.load_customer_json(customer_id, "customer_information_query")
        main_shipment = self.load_customer_json(customer_id, "main_shipment_query")
        records = _extract_records(main_shipment)

        # Build shipment_data with issues/investigation_reasons from decoder
        shipment_data: Dict[str, Any] = {"records": records}
        decoder_results = decoded_data.get("decoded_results", all_skill_results)
        intervention_result = decoder_results.get("shipment_intervention_result") or all_skill_results.get(
            "shipment_intervention_result", {}
        )
        decoder_result = decoder_results.get("shipment_signal_decoder_result") or all_skill_results.get(
            "shipment_signal_decoder_result", {}
        )
        shipment_data["issues"] = intervention_result.get("issues", {})
        shipment_data["investigation_reasons"] = decoder_result.get("investigation_reasons", [])

        state: Dict[str, Any] = {
            "customer_id": customer_id,
            "run_id": run_id,
            "shipment_data": shipment_data,
            "customer_profile": customer_info or {},
            "skill_results": all_skill_results,
        }

        # Inject all prior results into state for Phase 3-4 skills
        for k, v in all_skill_results.items():
            state[k] = v

        # 2. Run Phase 3 skills
        self.logger.info("Running Phase 3 skills")
        phase3_result = run_skills_phased(state, phase_filter=[3])
        phase3_results = phase3_result.get("skill_results", {})
        all_skill_results = {**all_skill_results, **phase3_results}
        state["skill_results"] = all_skill_results
        for k, v in phase3_results.items():
            state[k] = v

        errors = list(phase3_result.get("errors", []))

        # 3. Run Phase 4 skills
        self.logger.info("Running Phase 4 skills")
        phase4_result = run_skills_phased(state, phase_filter=[4])
        phase4_results = phase4_result.get("skill_results", {})
        all_skill_results = {**all_skill_results, **phase4_results}
        errors.extend(phase4_result.get("errors", []))

        if errors:
            self.logger.warning(f"Phase 3-4 completed with {len(errors)} skill errors: {errors[:3]}...")

        consolidated_markdown = self._build_consolidated_markdown(all_skill_results)

        output_payload: Dict[str, Any] = {
            "run_id": run_id,
            "customer_id": customer_id,
            "consolidated_results": all_skill_results,
            "consolidated_markdown": consolidated_markdown,
            "errors": errors,
            "phases": [3, 4],
        }

        # 4. Save to S3 under shipment_agency_revised/consolidated/
        base_path = self.settings.s3.base_path
        output_folder = "shipment_agency_revised/consolidated"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.json"
        md_key = f"{base_path}/{customer_id}/{output_folder}/{run_id}_{timestamp}.md"

        try:
            self.s3.upload_json(output_payload, json_key)
            self.s3.upload_text(consolidated_markdown, md_key)
            self.logger.info(f"Saved consolidated results to s3://{self.s3.bucket}/{json_key}")
        except Exception as e:
            self.logger.error(f"Failed to save consolidated results to S3: {e}")
            raise AgentError(f"S3 upload failed: {e}", agent_name=self.agent_name) from e

        structured_output = {
            "consolidated_results": all_skill_results,
            "consolidated_markdown": consolidated_markdown,
            "skill_results": all_skill_results,
            "run_id": run_id,
            "s3_paths": {"json": json_key, "markdown": md_key},
        }

        return {
            "structured_output": structured_output,
            "consolidated_results": all_skill_results,
            "consolidated_markdown": consolidated_markdown,
            "s3_outputs": [json_key, md_key],
        }

    def _build_consolidated_markdown(self, skill_results: Dict[str, Any]) -> str:
        """Build executive briefing markdown from consolidated skill results."""
        sections: List[str] = ["# Consolidated Shipment Actions", ""]

        consolidator = skill_results.get("shipment_consolidator_result", {})
        if consolidator and not consolidator.get("error"):
            exec_briefing = consolidator.get("executive_briefing", {})
            if exec_briefing:
                sections.append("## Executive Briefing")
                if isinstance(exec_briefing, dict):
                    for k, v in exec_briefing.items():
                        sections.append(f"### {k}")
                        sections.append(str(v))
                else:
                    sections.append(str(exec_briefing))
                sections.append("")

        prioritizer = skill_results.get("shipment_action_prioritizer_result", {})
        if prioritizer and not prioritizer.get("error"):
            sections.append("## Prioritized Actions")
            actions = prioritizer.get("prioritized_actions", [])
            for i, act in enumerate(actions[:10], 1):
                sections.append(f"{i}. {act}")
            sections.append("")

        return "\n".join(sections) if sections else "# No consolidated output"
