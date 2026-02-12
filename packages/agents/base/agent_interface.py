"""
Agent interface -- the contract every agent in the platform must implement.

Inspired by OpenClaw's plugin registration pattern: each agent declares
a manifest (capabilities), implements a run method, and exposes a health check.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.shared.models import AgentManifest, AgentRequest, AgentResponse, HealthStatus


class AgentInterface(ABC):
    """
    Abstract base class defining the standard contract for all agents.

    Every agent must implement:
      - ``manifest()``     -- declare inputs, outputs, dependencies
      - ``run()``          -- execute the agent for a customer
      - ``health_check()`` -- verify that required dependencies are available
    """

    @abstractmethod
    def manifest(self) -> AgentManifest:
        """Return the agent's skill manifest describing its capabilities."""
        ...

    @abstractmethod
    async def run(self, request: AgentRequest) -> AgentResponse:
        """
        Execute the agent for a given customer.

        Args:
            request: Standardized request with ``customer_id`` and optional
                     ``upstream_data`` from a prior agent in the pipeline.

        Returns:
            Standardized response with results and metadata.
        """
        ...

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """
        Check whether the agent's required dependencies are available.

        The gateway calls this at startup to populate the agent registry
        and mark agents as available / unavailable.
        """
        ...
