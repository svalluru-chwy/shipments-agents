"""Gateway routes."""

from .admin import admin_router
from .agents import agents_router
from .data import data_router
from .health import health_router
from .pipeline import pipeline_router
from .skills import skills_router

__all__ = [
    "admin_router",
    "agents_router",
    "data_router",
    "health_router",
    "pipeline_router",
    "skills_router",
]
