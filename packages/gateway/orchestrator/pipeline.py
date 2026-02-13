"""
Pipeline Orchestrator for Shipments Gateway.

Runs agents in sequence, passing upstream outputs as upstream_data to each agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from packages.shared.logging import get_logger
from packages.shared.models import AgentRequest, AgentResponse

from packages.gateway.registry import AgentRegistry

logger = get_logger(__name__)

# Pipeline order: (agent_name, {upstream_output_key: downstream_input_key})
# Empty dict for first agent; later agents receive merged upstream_data.
#
# Phase 3-4 (actions/prioritization/consolidation) are NOT included.
# The pipeline runs: signals (check gate + Phase 1) -> decoder (Phase 2).
PIPELINE_ORDER: List[Tuple[str, Dict[str, str]]] = [
    ("shipment_signals", {}),
    (
        "shipment_decoder",
        {
            "skill_results": "skill_results",
            "signals_markdown": "signals_markdown",
            "shipment_data": "shipment_data",
            "check_gate": "check_gate",
        },
    ),
]


class PipelineOrchestrator:
    """
    Orchestrates the shipment agent pipeline.

    Runs agents in PIPELINE_ORDER, passing upstream results as upstream_data
    to each downstream agent. Mapping defines which output keys feed which
    input keys for the next agent.
    """

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    async def run(
        self,
        customer_id: str,
        run_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run the full pipeline for a customer.

        Args:
            customer_id: Customer to process.
            run_id: Optional run identifier (defaults to uuid).
            options: Optional request options passed to each agent.

        Returns:
            Dict with results per agent, final status, and any errors.
        """
        import uuid

        run_id = run_id or str(uuid.uuid4())
        options = options or {}

        results: Dict[str, Any] = {}
        upstream_data: Dict[str, Any] = {}
        errors: List[str] = []

        for agent_name, mapping in PIPELINE_ORDER:
            agent = self.registry.get(agent_name)
            if not agent:
                errors.append(f"Agent {agent_name} not found in registry")
                logger.error(f"Agent {agent_name} not registered")
                continue

            # Build upstream_data from prior agent outputs using mapping
            request_upstream: Dict[str, Any] = {}
            if mapping:
                for out_key, in_key in mapping.items():
                    val = upstream_data.get(out_key)
                    if val is not None:
                        request_upstream[in_key] = val

            request = AgentRequest(
                customer_id=customer_id,
                run_id=run_id,
                options=options,
                upstream_data=request_upstream if request_upstream else None,
            )

            try:
                response: AgentResponse = await agent.run(request)
                results[agent_name] = {
                    "status": response.status.value,
                    "result": response.result,
                    "metadata": response.metadata.model_dump() if response.metadata else None,
                    "error": response.error,
                }

                if response.status.value == "failed":
                    if response.error:
                        errors.append(f"{agent_name}: {response.error}")
                    continue

                # Merge this agent's result into upstream_data for next agent
                result = response.result or {}
                structured = response.structured_output or result

                # Map result keys into upstream_data for downstream consumption
                for key in ("skill_results", "signals_markdown", "decoded_markdown", "shipment_data"):
                    if key in result and result[key] is not None:
                        upstream_data[key] = result[key]

                # Also pass full structured_output for flexible key access
                for k, v in structured.items():
                    if k not in upstream_data and v is not None:
                        upstream_data[k] = v

            except Exception as e:
                logger.exception(f"Pipeline agent {agent_name} failed")
                errors.append(f"{agent_name}: {str(e)}")
                results[agent_name] = {
                    "status": "failed",
                    "error": str(e),
                }

        return {
            "run_id": run_id,
            "customer_id": customer_id,
            "results": results,
            "errors": errors,
            "success": len(errors) == 0,
        }

    async def run_batch(
        self,
        customer_ids: List[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run the pipeline for multiple customers.

        Returns a dict with per-customer results and a summary.
        """
        batch_results: Dict[str, Dict[str, Any]] = {}
        all_errors: List[str] = []

        for customer_id in customer_ids:
            result = await self.run(customer_id, options=options)
            batch_results[customer_id] = result
            all_errors.extend([f"{customer_id}: {e}" for e in result.get("errors", [])])

        return {
            "customer_count": len(customer_ids),
            "results": batch_results,
            "errors": all_errors,
            "success": len(all_errors) == 0,
        }
