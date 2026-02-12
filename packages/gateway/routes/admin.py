"""
Admin routes for Shipments Gateway.

POST /admin/refresh-health - re-run health checks
GET /admin/config - return non-sensitive config summary
"""

from fastapi import APIRouter, Request

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/refresh-health")
async def refresh_health(request: Request):
    """
    Re-run health checks for all registered agents.
    """
    registry = getattr(request.app.state, "registry", None)
    if not registry:
        return {"message": "Registry not initialized", "refreshed": False}

    registry.refresh_health()
    return {"message": "Health checks refreshed", "refreshed": True}


@admin_router.get("/config")
async def get_config(request: Request):
    """
    Return non-sensitive config summary.
    """
    from packages.shared.config import get_settings

    settings = get_settings()

    return {
        "s3": {
            "bucket": settings.s3.bucket,
            "region": settings.s3.region,
            "base_path": settings.s3.base_path,
        },
        "gateway": {
            "host": settings.gateway.host,
            "port": settings.gateway.port,
            "cors_origins": settings.gateway.cors_origins,
        },
        "skills": {
            "max_parallel_skills": settings.skills.max_parallel_skills,
            "default_peer_level": settings.skills.default_peer_level,
        },
    }
