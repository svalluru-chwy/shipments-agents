"""
Agent-level data models used across the platform.

These define the standard interface contract that every agent implements:
request/response shapes, manifest declarations, health checks, and run metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AgentStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Skill manifest (OpenClaw-inspired)
# ---------------------------------------------------------------------------


class S3Source(BaseModel):
    """One S3 data source that an agent reads."""

    folder: str
    description: Optional[str] = None
    required: bool = True


class AgentManifest(BaseModel):
    """
    Machine-readable declaration of an agent's capabilities.

    Inspired by OpenClaw's SKILL.md frontmatter -- declares inputs, outputs,
    requirements, and dependencies so the registry can validate at load time.
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    agent_name: str = ""

    # What the agent needs to run
    s3_sources: List[S3Source] = []
    required_env: List[str] = []
    required_config: List[str] = []

    # What the agent produces
    output_types: List[str] = []  # e.g. ["markdown", "json"]
    output_path_template: str = ""

    # Dependency on other agents (must run first)
    depends_on: List[str] = []


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class AgentRequest(BaseModel):
    """Standardized request payload for any agent."""

    customer_id: str
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    options: Dict[str, Any] = {}

    # Optional pre-loaded data from a previous agent in the pipeline.
    # When provided, the agent should use this instead of fetching from S3.
    upstream_data: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    """Standardized response from any agent."""

    run_id: str
    agent_name: str
    customer_id: str
    status: RunStatus = RunStatus.COMPLETED
    result: Dict[str, Any] = {}
    error: Optional[str] = None
    metadata: Optional["RunMetadata"] = None

    # Structured output that can be passed directly to a downstream agent
    structured_output: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Health & metadata
# ---------------------------------------------------------------------------


class HealthStatus(BaseModel):
    agent_name: str
    status: AgentStatus = AgentStatus.AVAILABLE
    checks: Dict[str, bool] = {}
    message: str = ""


class RunMetadata(BaseModel):
    """Tracking metadata for a single agent run."""

    run_id: str
    agent_name: str
    customer_id: str
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    tokens_used: Optional[int] = None
    s3_outputs: List[str] = []
