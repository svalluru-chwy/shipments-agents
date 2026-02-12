"""
FastAPI gateway for Shipments Agency Platform.

Provides:
  - Agent registry with load-time gating
  - Per-agent REST endpoints
  - Per-skill REST endpoints (individual + phase-level)
  - Orchestration endpoint (run pipeline across agents)
  - Health checks
"""
