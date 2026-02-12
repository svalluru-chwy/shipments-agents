"""
Agent Registry for Shipments Gateway.

Central registry of available agents with health checks and dependency validation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from packages.shared.logging import get_logger
from packages.shared.models import AgentManifest, AgentStatus, HealthStatus

from packages.agents.base import AgentInterface

logger = get_logger(__name__)


class AgentRegistry:
    """
    Registry of agents available to the gateway.

    Agents are registered at startup. The registry provides lookup by name,
    listing, dependency validation, and health check refresh.
    """

    def __init__(self):
        self._agents: Dict[str, AgentInterface] = {}
        self._health: Dict[str, HealthStatus] = {}

    def register(self, agent: AgentInterface) -> None:
        """
        Register an agent by its manifest agent_name.

        Args:
            agent: Agent instance implementing AgentInterface.
        """
        manifest = agent.manifest()
        name = manifest.agent_name or getattr(agent, "agent_name", "unknown")
        self._agents[name] = agent
        self._health[name] = agent.health_check()
        logger.info(f"Registered agent: {name}")

    def get(self, agent_name: str) -> Optional[AgentInterface]:
        """Return the agent for the given name, or None."""
        return self._agents.get(agent_name)

    def list_agents(self) -> List[str]:
        """Return list of registered agent names."""
        return list(self._agents.keys())

    def get_health(self, agent_name: str) -> Optional[HealthStatus]:
        """Return cached health status for an agent."""
        return self._health.get(agent_name)

    def get_all_health(self) -> Dict[str, HealthStatus]:
        """Return cached health for all agents."""
        return dict(self._health)

    def validate_dependencies(self, agent_name: str) -> List[str]:
        """
        Validate that all depends_on agents are registered and available.

        Returns list of dependency issues (empty if all ok).
        """
        agent = self._agents.get(agent_name)
        if not agent:
            return [f"Agent {agent_name} not found"]

        manifest = agent.manifest()
        issues: List[str] = []

        for dep in manifest.depends_on or []:
            if dep not in self._agents:
                issues.append(f"Agent {agent_name} depends on {dep} which is not registered")
            else:
                status = self._health.get(dep)
                if status and status.status != AgentStatus.AVAILABLE:
                    issues.append(f"Agent {agent_name} depends on {dep} which is unavailable")

        return issues

    def refresh_health(self) -> None:
        """Re-run health checks for all registered agents."""
        for name, agent in self._agents.items():
            try:
                self._health[name] = agent.health_check()
            except Exception as e:
                logger.warning(f"Health check failed for {name}: {e}")
                self._health[name] = HealthStatus(
                    agent_name=name,
                    status=AgentStatus.UNAVAILABLE,
                    checks={},
                    message=str(e),
                )
