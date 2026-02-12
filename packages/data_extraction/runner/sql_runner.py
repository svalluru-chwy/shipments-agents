"""
SQL Runner -- core Snowflake query execution engine.

Adapted for the Shipments Agency Platform.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any, Dict, Optional

import snowflake.connector

from packages.shared.config import get_settings
from packages.shared.exceptions import ConnectionError
from packages.shared.logging import get_logger


class SQLRunner:
    def __init__(self, config_path: Optional[str] = None):
        self.logger = get_logger(__name__)
        self._settings = get_settings(config_path)
        self.connection: Optional[snowflake.connector.SnowflakeConnection] = None
        self._lock = threading.Lock()
        self._is_connecting = False

    def connect_snowflake(self) -> snowflake.connector.SnowflakeConnection:
        if self.connection and not self._is_connecting:
            return self.connection

        with self._lock:
            if self.connection and not self._is_connecting:
                return self.connection

            if self._is_connecting:
                self._lock.release()
                try:
                    while self._is_connecting and not self.connection:
                        time.sleep(0.1)
                    if self.connection:
                        return self.connection
                finally:
                    self._lock.acquire()

            self._is_connecting = True

        try:
            self.logger.info("Establishing Snowflake connection...")
            sf = self._settings.snowflake
            connect_args: Dict[str, Any] = {
                "account": os.getenv("SNOWFLAKE_ACCOUNT", sf.account),
                "user": os.getenv("SNOWFLAKE_USER", sf.user),
                "authenticator": "externalbrowser",
                "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", sf.warehouse),
                "database": os.getenv("SNOWFLAKE_DATABASE", sf.database),
                "schema": os.getenv("SNOWFLAKE_SCHEMA", sf.schema_),
            }
            role = os.getenv("SNOWFLAKE_ROLE", sf.role)
            if role:
                connect_args["role"] = role
            okta_url = sf.okta_url
            if okta_url:
                connect_args["okta_url"] = okta_url

            required = ["account", "user", "warehouse", "database"]
            missing = [p for p in required if not connect_args.get(p)]
            if missing:
                raise ConnectionError(f"Missing Snowflake params: {missing}")

            with self._lock:
                self.connection = snowflake.connector.connect(**connect_args)
                self._is_connecting = False

            self.logger.info("Successfully connected to Snowflake")
            return self.connection
        except Exception as exc:
            with self._lock:
                self._is_connecting = False
            self.logger.error(f"Snowflake connection failed: {exc}")
            raise ConnectionError(f"Snowflake connection failed: {exc}")

    @staticmethod
    def _serialize_value(val: Any) -> Any:
        if isinstance(val, (datetime, date, dt_time)):
            return val.isoformat()
        if hasattr(val, "isoformat"):
            return val.isoformat()
        if val is None:
            return None
        return val

    def execute_query(
        self,
        sql_query: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            if not self.connection:
                self.connect_snowflake()

            cursor = self.connection.cursor()

            formatted_sql = sql_query
            if parameters:
                for name, value in parameters.items():
                    for variant in (f":{name}", f":{name.upper()}", f":{name.lower()}"):
                        formatted_sql = formatted_sql.replace(variant, str(value))
                self.logger.info(f"Executing query with customer_id={parameters.get('customer_id', 'N/A')}")
            else:
                self.logger.debug(f"Executing query: {sql_query[:200]}...")

            cursor.execute(formatted_sql)

            columns = [col[0] for col in cursor.description] if cursor.description else []
            results = [{col: self._serialize_value(val) for col, val in zip(columns, row)} for row in cursor.fetchall()]
            cursor.close()

            self.logger.info(f"Query returned {len(results)} rows")

            return {
                "success": True,
                "results": results,
                "row_count": len(results),
                "columns": columns,
                "executed_at": datetime.utcnow().isoformat(),
                "sql_query": formatted_sql,
            }
        except Exception as exc:
            self.logger.error(f"Query execution failed: {exc}\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "executed_at": datetime.utcnow().isoformat(),
                "sql_query": sql_query,
            }

    def close_connection(self) -> None:
        if self.connection:
            try:
                self.connection.close()
                self.logger.info("Snowflake connection closed")
            except Exception as exc:
                self.logger.warning(f"Error closing Snowflake connection: {exc}")
            finally:
                self.connection = None

    def __enter__(self):
        self.connect_snowflake()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()
