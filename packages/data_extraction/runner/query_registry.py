"""
Query Registry -- discovers and catalogs SQL query files.

Adapted for the Shipments Agency Platform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from packages.shared.logging import get_logger


@dataclass
class QueryInfo:
    name: str
    file_path: str
    template_name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[List[str]] = None
    output_folder: Optional[str] = None


class QueryRegistry:
    def __init__(self, queries_dir: str):
        self.logger = get_logger(__name__)
        self.queries_dir = Path(queries_dir)
        self.queries: Dict[str, QueryInfo] = {}
        self._discover_queries()

    def _discover_queries(self) -> None:
        if not self.queries_dir.exists():
            self.logger.error(f"Queries directory not found: {self.queries_dir}")
            return

        sql_files = sorted(self.queries_dir.glob("*.sql"))
        self.logger.info(f"Discovered {len(sql_files)} SQL files in {self.queries_dir}")

        for sql_file in sql_files:
            try:
                info = self._extract_metadata(sql_file)
                self.queries[info.name] = info
                self.logger.debug(f"Registered query: {info.name}")
            except Exception as exc:
                self.logger.warning(f"Failed to register {sql_file.name}: {exc}")

        self.logger.info(f"Registered {len(self.queries)} queries")

    @staticmethod
    def _extract_metadata(sql_file: Path) -> QueryInfo:
        content = sql_file.read_text(encoding="utf-8")

        template_match = re.search(r"-- Template:\s*(\w+)", content, re.IGNORECASE)
        template_name = template_match.group(1) if template_match else None

        desc_match = re.search(r"-- Description:\s*(.+)", content, re.IGNORECASE)
        description = desc_match.group(1).strip() if desc_match else None

        parameters = list(set(re.findall(r":(\w+)", content)))

        if template_name:
            output_folder = template_name
        else:
            base_name = sql_file.stem
            output_folder = re.sub(r"^\d+_", "", base_name)

        return QueryInfo(
            name=sql_file.stem,
            file_path=str(sql_file),
            template_name=template_name,
            description=description,
            parameters=parameters,
            output_folder=output_folder,
        )

    def get_query_content(self, query_name: str) -> str:
        if query_name not in self.queries:
            raise ValueError(f"Query not found: {query_name}")
        return Path(self.queries[query_name].file_path).read_text(encoding="utf-8")

    def get_all_queries(self) -> Dict[str, QueryInfo]:
        return self.queries.copy()

    def get_queries_for_customer(self, customer_id: str) -> Dict[str, QueryInfo]:
        return {
            name: info for name, info in self.queries.items() if info.parameters and "customer_id" in info.parameters
        }

    def list_queries(self) -> List[str]:
        return list(self.queries.keys())

    def get_query_info(self, query_name: str) -> QueryInfo:
        if query_name not in self.queries:
            raise ValueError(f"Query not found: {query_name}")
        return self.queries[query_name]
