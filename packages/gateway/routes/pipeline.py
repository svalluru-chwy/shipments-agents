"""
Pipeline routes for Shipments Gateway.

/pipeline/run - run full pipeline for one customer
/pipeline/batch - run pipeline for multiple customers
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request

pipeline_router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@pipeline_router.post("/run")
async def pipeline_run(
    request: Request,
    customer_id: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True),
    options: Optional[Dict[str, Any]] = Body(None, embed=True),
):
    """
    Run the full shipment pipeline for one customer.

    Runs: shipment_signals -> shipment_decoder -> shipment_actions.
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result = await orchestrator.run(
        customer_id=customer_id,
        run_id=run_id,
        options=options,
    )
    return result


@pipeline_router.post("/batch")
async def pipeline_batch(
    request: Request,
    customer_ids: List[str] = Body(..., embed=True),
    options: Optional[Dict[str, Any]] = Body(None, embed=True),
):
    """
    Run the pipeline for multiple customers.
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result = await orchestrator.run_batch(
        customer_ids=customer_ids,
        options=options,
    )
    return result
