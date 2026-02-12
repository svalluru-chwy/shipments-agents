"""
Health routes for Shipments Gateway.

/health - overall gateway health
/agents - list all agents with health status
"""

from fastapi import APIRouter, Request

from packages.shared.models import AgentStatus

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("")
async def health(request: Request):
    """
    Overall gateway health.

    Returns ok if the gateway is running.
    """
    return {"status": "ok", "service": "shipments-gateway"}


@health_router.get("/agents")
async def agents_health(request: Request):
    """
    List all agents with their health status.
    """
    registry = getattr(request.app.state, "registry", None)
    if not registry:
        return {"agents": [], "message": "Registry not initialized"}

    agents = []
    for name in registry.list_agents():
        status = registry.get_health(name)
        agents.append({
            "agent_name": name,
            "status": status.status.value if status else "unknown",
            "message": status.message if status else "",
            "checks": status.checks if status else {},
        })

    all_ok = all(
        a["status"] == AgentStatus.AVAILABLE.value
        for a in agents
    )
    return {
        "agents": agents,
        "overall": "ok" if all_ok else "degraded",
    }
