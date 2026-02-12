"""
FastAPI gateway for Shipments Agency Platform.

Entry point: shipments-gateway (uvicorn)

Provides:
  - Agent registry with load-time health gating
  - Per-agent REST endpoints
  - Per-skill REST endpoints (individual + phase-level)
  - Pipeline orchestration endpoint
  - Data endpoints (customers, full data)
  - Health and admin endpoints
"""

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from packages.shared.config import get_settings
from packages.shared.logging import get_logger
from packages.shared.s3 import S3Client

from packages.agents.shipments import ShipmentSignalsAgent, ShipmentDecoderAgent, ShipmentActionsAgent
from packages.gateway.registry import AgentRegistry
from packages.gateway.orchestrator import PipelineOrchestrator
from packages.gateway.routes import (
    admin_router,
    agents_router,
    data_router,
    health_router,
    pipeline_router,
    skills_router,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan: create S3Client, instantiate agents, register them, create PipelineOrchestrator.
    """
    settings = get_settings()

    # 1. Create S3Client
    s3_client = S3Client(
        bucket=settings.s3.bucket,
        region=settings.s3.region,
    )
    app.state.s3_client = s3_client
    logger.info("S3Client initialized")

    # 2. Instantiate agents
    shipment_signals = ShipmentSignalsAgent(s3_client=s3_client)
    shipment_decoder = ShipmentDecoderAgent(s3_client=s3_client)
    shipment_actions = ShipmentActionsAgent(s3_client=s3_client)

    # 3. Register agents in AgentRegistry
    registry = AgentRegistry()
    registry.register(shipment_signals)
    registry.register(shipment_decoder)
    registry.register(shipment_actions)
    app.state.registry = registry
    logger.info(f"Registered agents: {registry.list_agents()}")

    # 4. Create PipelineOrchestrator
    orchestrator = PipelineOrchestrator(registry=registry)
    app.state.orchestrator = orchestrator
    logger.info("PipelineOrchestrator initialized")

    yield

    # Cleanup (if needed)
    logger.info("Gateway shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    settings = get_settings()
    gw = settings.gateway

    app = FastAPI(
        title="Shipments Gateway",
        description="FastAPI gateway for Shipments Agency Platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=gw.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers
    app.include_router(health_router)
    app.include_router(agents_router)
    app.include_router(pipeline_router)
    app.include_router(skills_router)
    app.include_router(data_router)
    app.include_router(admin_router)

    return app


app = create_app()


def main() -> None:
    """Uvicorn entry point for shipments-gateway."""
    import uvicorn

    settings = get_settings()
    gw = settings.gateway

    uvicorn.run(
        "packages.gateway.main:app",
        host=gw.host,
        port=gw.port,
        workers=gw.workers,
        reload=False,
    )


if __name__ == "__main__":
    main()
