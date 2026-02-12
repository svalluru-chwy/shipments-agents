"""
CAT Data Pipeline -- orchestrator for running queries and saving results.

Adapted for the Shipments Agency Platform.
Executes 7 shipment-related Snowflake queries and uploads results to S3.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.shared.config import get_settings
from packages.shared.logging import get_logger
from packages.shared.s3 import S3Client

from .query_registry import QueryInfo, QueryRegistry
from .sql_runner import SQLRunner


class CATDataPipeline:
    """
    Orchestrates Snowflake query execution for a given customer_id and
    saves structured JSON results to S3 (or local disk).
    """

    def __init__(
        self,
        queries_dir: Optional[str] = None,
        config_path: Optional[str] = None,
        max_parallel_queries: Optional[int] = None,
        max_retries: Optional[int] = None,
        s3_client: Optional[S3Client] = None,
    ):
        self.logger = get_logger(__name__)
        settings = get_settings(config_path)

        if queries_dir is None:
            queries_dir = str(Path(__file__).resolve().parents[1] / "queries")
        self.queries_dir = queries_dir

        self.max_parallel = max_parallel_queries or settings.pipeline.max_parallel_queries
        self.max_retries = max_retries if max_retries is not None else settings.pipeline.max_retries
        self.base_path = settings.s3.base_path

        self.s3 = s3_client or S3Client(bucket=settings.s3.bucket, region=settings.s3.region)

        self.registry = QueryRegistry(self.queries_dir)
        self.sql_runner = SQLRunner(config_path)

        self.logger.info(
            f"Pipeline initialized with {len(self.registry.queries)} queries, "
            f"max_parallel={self.max_parallel}, max_retries={self.max_retries}"
        )

    def _output_filename(self, customer_id: str, query_name: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{query_name}_{customer_id}_{ts}.json"

    def _save_result(self, customer_id: str, info: QueryInfo, result: Dict[str, Any]) -> str:
        filename = self._output_filename(customer_id, info.name)

        output_data = {
            "metadata": {
                "customer_id": customer_id,
                "query_name": info.name,
                "template_name": info.template_name,
                "description": info.description,
                "executed_at": result.get("executed_at"),
                "success": result.get("success"),
                "row_count": result.get("row_count", 0),
            },
            "data": result.get("results", []),
            "query_info": {
                "sql_query": result.get("sql_query"),
                "parameters": {"customer_id": customer_id},
                "columns": result.get("columns", []),
            },
        }

        if not result.get("success"):
            output_data["error"] = {
                "message": result.get("error"),
                "error_type": result.get("error_type"),
            }

        folder = info.output_folder or info.name.split("_", 1)[1] if "_" in info.name else info.name
        key = self.s3.customer_data_key(customer_id, folder, filename, base_path=self.base_path)
        self.s3.upload_json(output_data, key)
        return f"s3://{self.s3.bucket}/{key}"

    def _execute_single(self, customer_id: str, info: QueryInfo) -> Dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            t0 = datetime.utcnow()
            try:
                if attempt > 0:
                    self.logger.info(f"RETRY {attempt}/{self.max_retries}: {info.name}")
                    time.sleep(2**attempt)

                sql = self.registry.get_query_content(info.name)
                result = self.sql_runner.execute_query(sql, parameters={"customer_id": customer_id})

                if result["success"]:
                    output_path = self._save_result(customer_id, info, result)
                    duration = (datetime.utcnow() - t0).total_seconds()
                    self.logger.info(f"SUCCESS: {info.name} -- {result['row_count']} rows in {duration:.1f}s")
                    return {
                        "query_name": info.name,
                        "success": True,
                        "row_count": result["row_count"],
                        "output_path": output_path,
                        "executed_at": result["executed_at"],
                        "duration_seconds": duration,
                    }

                if attempt == self.max_retries:
                    duration = (datetime.utcnow() - t0).total_seconds()
                    self.logger.error(f"FAILED after {attempt + 1} attempts: {info.name}")
                    return {
                        "query_name": info.name,
                        "success": False,
                        "error": result.get("error"),
                        "executed_at": result.get("executed_at"),
                        "duration_seconds": duration,
                    }

            except Exception as exc:
                if attempt == self.max_retries:
                    duration = (datetime.utcnow() - t0).total_seconds()
                    return {
                        "query_name": info.name,
                        "success": False,
                        "error": str(exc),
                        "duration_seconds": duration,
                    }

        return {"query_name": info.name, "success": False, "error": "Unknown"}

    def run_all_queries(self, customer_id: str) -> Dict[str, Any]:
        start = datetime.utcnow()
        queries = self.registry.get_queries_for_customer(customer_id)

        if not queries:
            return {
                "customer_id": customer_id,
                "success": False,
                "error": "No customer_id queries found",
                "queries_executed": 0,
            }

        self.logger.info(f"Running {len(queries)} queries for customer {customer_id}")

        self.sql_runner.connect_snowflake()

        results: List[Dict[str, Any]] = []
        ok = 0
        fail = 0

        with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
            futures = {pool.submit(self._execute_single, customer_id, info): info for info in queries.values()}
            for future in as_completed(futures):
                try:
                    res = future.result()
                except Exception as exc:
                    info = futures[future]
                    res = {"query_name": info.name, "success": False, "error": str(exc)}
                results.append(res)
                if res["success"]:
                    ok += 1
                else:
                    fail += 1

        end = datetime.utcnow()
        elapsed = (end - start).total_seconds()

        summary = {
            "customer_id": customer_id,
            "success": fail == 0,
            "execution_summary": {
                "total_queries": len(queries),
                "successful_queries": ok,
                "failed_queries": fail,
                "execution_time_seconds": elapsed,
                "started_at": start.isoformat(),
                "completed_at": end.isoformat(),
            },
            "query_results": results,
        }

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_key = self.s3.customer_output_key(
            customer_id, "summary", f"pipeline_summary_{customer_id}_{ts}.json", base_path=self.base_path
        )
        self.s3.upload_json(summary, summary_key)

        self.logger.info(f"Pipeline complete: {ok}/{len(queries)} succeeded in {elapsed:.1f}s")
        return summary

    def cleanup(self) -> None:
        self.sql_runner.close_connection()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
