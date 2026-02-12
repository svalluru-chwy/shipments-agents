"""
Agent routes for Shipments Gateway.

/agents/{agent_name}/run - run a single agent
/agents/{agent_name}/manifest - get agent manifest
/agents/{agent_name}/health - get agent health status
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from packages.shared.models import AgentRequest, AgentResponse

agents_router = APIRouter(prefix="/agents", tags=["agents"])


@agents_router.post("/{agent_name}/run")
async def run_agent(
    request: Request,
    agent_name: str,
    customer_id: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True),
    options: Optional[Dict[str, Any]] = Body(None, embed=True),
    upstream_data: Optional[Dict[str, Any]] = Body(None, embed=True),
):
    """
    Run a single agent for a customer.

    Body/query params: customer_id, run_id (optional), options (optional), upstream_data (optional).
    """
    registry = getattr(request.app.state, "registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    agent = registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")

    import uuid
    agent_request = AgentRequest(
        customer_id=customer_id,
        run_id=run_id or str(uuid.uuid4()),
        options=options or {},
        upstream_data=upstream_data,
    )

    response: AgentResponse = await agent.run(agent_request)

    return {
        "run_id": response.run_id,
        "agent_name": response.agent_name,
        "customer_id": response.customer_id,
        "status": response.status.value,
        "result": response.result,
        "error": response.error,
        "metadata": response.metadata.model_dump() if response.metadata else None,
    }


@agents_router.get("/{agent_name}/manifest")
async def agent_manifest(request: Request, agent_name: str):
    """Get the manifest for an agent."""
    registry = getattr(request.app.state, "registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    agent = registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")

    manifest = agent.manifest()
    return manifest.model_dump()


@agents_router.get("/{agent_name}/health")
async def agent_health(request: Request, agent_name: str):
    """Get the health status for an agent."""
    registry = getattr(request.app.state, "registry", None)
    if not registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    agent = registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")

    status = registry.get_health(agent_name)
    if not status:
        status = agent.health_check()

    return status.model_dump()
