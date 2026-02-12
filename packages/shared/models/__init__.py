"""
Shared Pydantic data models for Shipments Agency Platform.

Defines the canonical schemas for data flowing between agents,
matching the JSON structure produced by cat-data-operations queries.
"""

from .agent_models import (
    AgentManifest,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    HealthStatus,
    RunMetadata,
    RunStatus,
    S3Source,
)

__all__ = [
    "AgentManifest",
    "AgentRequest",
    "AgentResponse",
    "AgentStatus",
    "HealthStatus",
    "RunMetadata",
    "RunStatus",
    "S3Source",
]
