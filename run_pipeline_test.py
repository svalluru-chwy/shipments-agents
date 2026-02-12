"""
Standalone end-to-end pipeline test for Shipments Agency Platform.

Runs all 3 agents (signals -> decoder -> actions) for a single customer
WITHOUT the FastAPI gateway, uvicorn, or HTTP server. This is a direct Python
invocation that replicates the PipelineOrchestrator's upstream-data-passing logic.

Usage:
    cd shipments-agents
    source .venv/bin/activate
    export AWS_PROFILE=PowerUserAccess-977247693856
    python run_pipeline_test.py [--customer-id 6180005]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from packages.shared.config import get_settings
from packages.shared.logging import get_logger, setup_logging
from packages.shared.models import AgentRequest, AgentResponse, RunStatus
from packages.shared.s3 import S3Client

# ---------------------------------------------------------------------------
# Pipeline order -- mirrors packages/gateway/orchestrator/pipeline.py
# ---------------------------------------------------------------------------

PIPELINE_ORDER: List[Tuple[str, Dict[str, str]]] = [
    ("shipment_signals", {}),
    (
        "shipment_decoder",
        {
            "skill_results": "skill_results",
            "signals_markdown": "signals_markdown",
            "shipment_data": "shipment_data",
        },
    ),
    (
        "shipment_actions",
        {
            "skill_results": "skill_results",
            "decoded_markdown": "decoded_markdown",
            "shipment_data": "shipment_data",
        },
    ),
]


def _snippet(text: str, max_len: int = 300) -> str:
    if not text:
        return "(empty)"
    text = str(text).strip()
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _save_agent_output(out_dir: str, agent_name: str, response: AgentResponse) -> None:
    if response.result:
        path = os.path.join(out_dir, f"{agent_name}_result.json")
        with open(path, "w") as fh:
            json.dump(response.result, fh, indent=2, default=str)

    if response.structured_output:
        path = os.path.join(out_dir, f"{agent_name}_structured.json")
        with open(path, "w") as fh:
            json.dump(response.structured_output, fh, indent=2, default=str)


def _print_separator(label: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {label}")
    print(f"{'=' * width}")


def _print_result(agent_name: str, response: AgentResponse, elapsed: float) -> None:
    status_icon = "PASS" if response.status == RunStatus.COMPLETED else "FAIL"
    print(f"\n  [{status_icon}] {agent_name}")
    print(f"  Status   : {response.status.value}")
    print(f"  Duration : {elapsed:.1f}s")

    if response.error:
        print(f"  Error    : {response.error}")

    if response.result:
        s3_paths = response.result.get("s3_paths", {})
        if s3_paths:
            print(f"  S3 Paths :")
            for k, v in s3_paths.items():
                print(f"    {k}: {v}")

    if response.structured_output:
        print(f"  Upstream keys: {list(response.structured_output.keys())}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_pipeline(customer_id: str) -> bool:
    setup_logging()
    logger = get_logger("pipeline_test")
    settings = get_settings()

    _print_separator(f"Standalone Pipeline Test -- Customer {customer_id}")
    print(f"  AWS_PROFILE : {os.getenv('AWS_PROFILE', '(not set)')}")
    print(f"  OPENAI_API_KEY : {'set' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
    print(f"  S3 Bucket  : {settings.s3.bucket}")
    print(f"  S3 Base    : {settings.s3.base_path}")

    # ---- Shared resources ------------------------------------------------
    print("\n  Initializing shared resources...")

    s3 = S3Client(bucket=settings.s3.bucket, region=settings.s3.region)
    print("    S3Client       : OK")

    # ---- Step 0: Data Extraction -----------------------------------------
    _print_separator(f"Step 0: Data Extraction -- Customer {customer_id}")
    try:
        from packages.data_extraction.runner.data_pipeline import CATDataPipeline

        with CATDataPipeline(s3_client=s3) as pipeline:
            extraction_summary = pipeline.run_all_queries(customer_id)

        es = extraction_summary["execution_summary"]
        print(f"  Queries: {es['successful_queries']}/{es['total_queries']} succeeded")
        print(f"  Time:    {es['execution_time_seconds']:.1f}s")

        if not extraction_summary["success"]:
            failed_queries = [r["query_name"] for r in extraction_summary.get("query_results", []) if not r.get("success")]
            print(f"  WARNING: Failed queries: {failed_queries}")
            print(f"  Continuing with available data...")
    except Exception as exc:
        print(f"  Data extraction skipped/failed: {exc}")
        print(f"  Proceeding with existing S3 data...")

    # ---- Instantiate agents -----------------------------------------------
    from packages.agents.shipments import ShipmentSignalsAgent, ShipmentDecoderAgent, ShipmentActionsAgent

    agents = {
        "shipment_signals": ShipmentSignalsAgent(s3_client=s3, settings=settings),
        "shipment_decoder": ShipmentDecoderAgent(s3_client=s3, settings=settings),
        "shipment_actions": ShipmentActionsAgent(s3_client=s3, settings=settings),
    }

    print(f"\n  Agents instantiated: {list(agents.keys())}")

    # ---- Output directory ---------------------------------------------------
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("output_local", f"{customer_id}_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n  Local output dir: {out_dir}")

    # ---- Run pipeline -----------------------------------------------------
    accumulated_upstream: Dict[str, Any] = {}
    results: Dict[str, Tuple[AgentResponse, float]] = {}
    pipeline_start = time.time()

    for agent_name, upstream_mapping in PIPELINE_ORDER:
        agent = agents.get(agent_name)
        if agent is None:
            logger.warning(f"Agent '{agent_name}' not found, skipping")
            continue

        upstream_data: Dict[str, Any] = {}
        for target_key, source_key in upstream_mapping.items():
            if source_key in accumulated_upstream:
                upstream_data[target_key] = accumulated_upstream[source_key]

        request = AgentRequest(
            customer_id=customer_id,
            upstream_data=upstream_data if upstream_data else None,
        )

        _print_separator(f"Running: {agent_name}")
        if upstream_data:
            print(f"  Upstream keys received: {list(upstream_data.keys())}")
        else:
            print("  Upstream keys received: (none -- first agent)")

        t0 = time.time()
        response = await agent.run(request)
        elapsed = time.time() - t0

        results[agent_name] = (response, elapsed)
        _print_result(agent_name, response, elapsed)
        _save_agent_output(out_dir, agent_name, response)

        if response.structured_output:
            accumulated_upstream.update(response.structured_output)

        if response.status == RunStatus.FAILED:
            logger.error(f"Agent '{agent_name}' failed: {response.error}")
            print(f"\n  >> Agent failed but continuing pipeline (fail-forward) <<")

    # ---- Summary ----------------------------------------------------------
    total_elapsed = time.time() - pipeline_start

    _print_separator("Pipeline Summary")
    all_passed = True
    for agent_name, (resp, elapsed) in results.items():
        icon = "PASS" if resp.status == RunStatus.COMPLETED else "FAIL"
        print(f"  [{icon}] {agent_name:25s} -- {elapsed:6.1f}s")
        if resp.status != RunStatus.COMPLETED:
            all_passed = False

    print(f"\n  Total time: {total_elapsed:.1f}s")
    if all_passed:
        print("  Result: ALL 3 AGENTS PASSED")
    else:
        failed = [name for name, (resp, _) in results.items() if resp.status != RunStatus.COMPLETED]
        print(f"  Result: FAILED agents: {failed}")

    # ---- Save pipeline summary locally ------------------------------------
    summary = {
        "customer_id": customer_id,
        "timestamp": ts,
        "total_seconds": round(total_elapsed, 1),
        "all_passed": all_passed,
        "agents": {
            name: {
                "status": resp.status.value,
                "duration_seconds": round(el, 1),
                "error": resp.error,
                "s3_paths": resp.result.get("s3_paths", {}) if resp.result else {},
            }
            for name, (resp, el) in results.items()
        },
    }
    summary_path = os.path.join(out_dir, "pipeline_summary.json")
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    print(f"\n  Local outputs saved to: {out_dir}/")

    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone shipments pipeline test")
    parser.add_argument("--customer-id", default="6180005", help="Customer ID to test")
    args = parser.parse_args()

    success = asyncio.run(run_pipeline(args.customer_id))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
