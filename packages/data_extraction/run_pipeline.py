#!/usr/bin/env python3
"""
Data Extraction Pipeline Runner for Shipments Agency Platform.

Executes the 7 Snowflake queries for a given customer_id and uploads
structured JSON results to S3.

Usage:
    python -m packages.data_extraction.run_pipeline <customer_id>
    python -m packages.data_extraction.run_pipeline 12345 --parallel 5
"""

from __future__ import annotations

import argparse
import sys
import time

from packages.shared.logging import get_logger, setup_logging

from .runner.data_pipeline import CATDataPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run shipments data extraction pipeline for a customer",
    )
    parser.add_argument("customer_id", type=str, help="Customer ID to process")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--parallel", type=int, help="Max parallel queries")
    parser.add_argument("--retries", type=int, help="Max retries per query")
    parser.add_argument("--list-queries", action="store_true", help="List available queries and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()
    setup_logging("DEBUG" if args.verbose else "INFO")
    logger = get_logger(__name__)

    try:
        with CATDataPipeline(
            config_path=args.config,
            max_parallel_queries=args.parallel,
            max_retries=args.retries,
        ) as pipeline:
            if args.list_queries:
                for info in pipeline.registry.get_all_queries().values():
                    has_cid = "customer_id" in (info.parameters or [])
                    marker = "Y" if has_cid else "-"
                    print(f"  [{marker}] {info.name}: {info.description or '(no description)'}")
                return

            logger.info(f"Starting extraction for customer_id={args.customer_id}")
            t0 = time.time()

            summary = pipeline.run_all_queries(args.customer_id)

            elapsed = time.time() - t0
            es = summary["execution_summary"]
            print("\nPipeline Summary")
            print(f"  Customer: {summary['customer_id']}")
            print(f"  Queries:  {es['successful_queries']}/{es['total_queries']} succeeded")
            print(f"  Time:     {elapsed:.1f}s")
            print(f"  Status:   {'OK' if summary['success'] else 'ERRORS'}")

            sys.exit(0 if summary["success"] else 1)

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except Exception as exc:
        logger.error(f"Pipeline failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
