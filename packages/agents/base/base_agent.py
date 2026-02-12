"""
Base agent -- shared functionality inherited by all concrete agents.

Provides:
  - OpenAI client initialization
  - Shared S3 client access
  - Run metadata tracking
  - Pre/post hooks (OpenClaw-inspired)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

from packages.shared.config import Settings, get_settings
from packages.shared.exceptions import AgentError
from packages.shared.logging import get_logger
from packages.shared.models import (
    AgentManifest,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    HealthStatus,
    RunMetadata,
    RunStatus,
)
from packages.shared.s3 import S3Client

from .agent_interface import AgentInterface


class BaseAgent(AgentInterface):
    """
    Base class providing shared infrastructure for all agents.

    Concrete agents should:
      1. Override ``manifest()`` to declare their skill manifest.
      2. Override ``_execute(request)`` to implement their core logic.
      3. Optionally override ``health_check()`` for custom dependency checks.
    """

    agent_name: str = "base"

    def __init__(
        self,
        s3_client: Optional[S3Client] = None,
        settings: Optional[Settings] = None,
    ):
        load_dotenv()
        self.settings = settings or get_settings()
        self.logger = get_logger(f"agents.{self.agent_name}")
        self.s3 = s3_client or S3Client(
            bucket=self.settings.s3.bucket,
            region=self.settings.s3.region,
        )
        self._openai: Optional[OpenAI] = None

    # ------------------------------------------------------------------
    # OpenAI client (lazy init)
    # ------------------------------------------------------------------

    @property
    def openai_client(self) -> OpenAI:
        if self._openai is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise AgentError("OPENAI_API_KEY not set", agent_name=self.agent_name)
            self._openai = OpenAI(api_key=api_key)
        return self._openai

    # ------------------------------------------------------------------
    # AgentInterface implementation
    # ------------------------------------------------------------------

    def manifest(self) -> AgentManifest:
        """Override in subclass."""
        return AgentManifest(name=self.agent_name, agent_name=self.agent_name)

    async def run(self, request: AgentRequest) -> AgentResponse:
        """
        Orchestrate a single agent run with metadata tracking and hooks.

        Delegates to ``_execute`` which subclasses must implement.
        """
        meta = RunMetadata(
            run_id=request.run_id,
            agent_name=self.agent_name,
            customer_id=request.customer_id,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        self.logger.info(f"[{self.agent_name}] Starting run {request.run_id} for customer {request.customer_id}")

        try:
            # --- before_run hook ---
            await self._before_run(request)

            # --- core execution ---
            result = await self._execute(request)

            # --- after_run hook ---
            await self._after_run(request, result)

            meta.status = RunStatus.COMPLETED
            meta.completed_at = datetime.now(UTC)
            if meta.started_at is not None:
                meta.duration_seconds = (meta.completed_at - meta.started_at).total_seconds()

            self.logger.info(f"[{self.agent_name}] Run {request.run_id} completed in {meta.duration_seconds:.1f}s")

            return AgentResponse(
                run_id=request.run_id,
                agent_name=self.agent_name,
                customer_id=request.customer_id,
                status=RunStatus.COMPLETED,
                result=result,
                metadata=meta,
                structured_output=result.get("structured_output"),
            )

        except Exception as exc:
            meta.status = RunStatus.FAILED
            meta.completed_at = datetime.now(UTC)
            if meta.started_at is not None:
                meta.duration_seconds = (meta.completed_at - meta.started_at).total_seconds()

            self.logger.error(f"[{self.agent_name}] Run {request.run_id} failed: {exc}")

            return AgentResponse(
                run_id=request.run_id,
                agent_name=self.agent_name,
                customer_id=request.customer_id,
                status=RunStatus.FAILED,
                error=str(exc),
                metadata=meta,
            )

    def health_check(self) -> HealthStatus:
        """Default health check: verify S3 and OpenAI key."""
        checks: Dict[str, bool] = {}

        # S3
        checks["s3"] = self.s3.health_check()

        # OpenAI key
        checks["openai_key"] = bool(os.getenv("OPENAI_API_KEY"))

        all_ok = all(checks.values())
        return HealthStatus(
            agent_name=self.agent_name,
            status=AgentStatus.AVAILABLE if all_ok else AgentStatus.UNAVAILABLE,
            checks=checks,
            message="" if all_ok else f"Failed checks: {[k for k, v in checks.items() if not v]}",
        )

    # ------------------------------------------------------------------
    # Hooks (override in subclasses for custom pre/post logic)
    # ------------------------------------------------------------------

    async def _before_run(self, request: AgentRequest) -> None:
        """Hook called before the core execution. Override for validation, etc."""
        pass

    async def _after_run(self, request: AgentRequest, result: Dict[str, Any]) -> None:
        """Hook called after successful execution. Override for S3 upload, etc."""
        pass

    # ------------------------------------------------------------------
    # Core execution (must be implemented by subclasses)
    # ------------------------------------------------------------------

    async def _execute(self, request: AgentRequest) -> Dict[str, Any]:
        """
        Implement the agent's core logic.

        Args:
            request: The agent request.

        Returns:
            A dict containing the agent's output. Include a ``structured_output``
            key if the output should be passed to a downstream agent.
        """
        raise NotImplementedError(f"{self.agent_name} must implement _execute()")

    # ------------------------------------------------------------------
    # S3 data loading helpers
    # ------------------------------------------------------------------

    def load_customer_json(self, customer_id: str, folder: str) -> Optional[Dict[str, Any]]:
        """
        Load the latest JSON file for a customer from S3.

        Args:
            customer_id: Customer identifier.
            folder: Sub-folder under ``data/`` (e.g., ``main_shipment_query``).

        Returns:
            Parsed JSON dict, or None if not found.
        """
        key = self.s3.find_latest_customer_file(customer_id, f"data/{folder}", base_path=self.settings.s3.base_path)
        if not key:
            self.logger.warning(f"No data found for {customer_id} in data/{folder}")
            return None
        return self.s3.download_json(key)

    def load_customer_text(self, customer_id: str, folder: str, suffix: str = ".md") -> Optional[str]:
        """Load the latest text/markdown file for a customer from S3."""
        key = self.s3.find_latest_customer_file(
            customer_id, folder, base_path=self.settings.s3.base_path, suffix=suffix
        )
        if not key:
            self.logger.warning(f"No text found for {customer_id} in {folder}")
            return None
        return self.s3.download_text(key)
