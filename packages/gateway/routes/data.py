"""
Data routes for Shipments Gateway.

GET /data/customers - list customers with available analysis
GET /data/customers/{customer_id} - customer metadata
POST /data/customers/{customer_id}/full - all customer data in one call
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

data_router = APIRouter(prefix="/data", tags=["data"])

# Shipment-specific data folders (from data extraction pipeline)
SHIPMENT_DATA_FOLDERS = [
    "main_shipment_query",
    "customer_contacts_query",
    "customer_zip_performance",
    "benchmark_zip_performance",
    "shipment_inspector_query",
    "order_shipment_summary_stats",
    "customer_information_query",
]


def _get_s3_client(request: Request):
    """Get S3Client from app state."""
    return getattr(request.app.state, "s3_client", None)


def _get_settings():
    from packages.shared.config import get_settings
    return get_settings()


@data_router.get("/customers")
async def list_customers(request: Request):
    """
    List customers with available shipment analysis data.

    Scans S3 under base_path for customer folders that contain data.
    """
    s3_client = _get_s3_client(request)
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    settings = _get_settings()
    base_path = settings.s3.base_path
    prefix = f"{base_path}/"

    customer_ids: List[str] = []
    seen: set = set()

    try:
        paginator = s3_client._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=s3_client.bucket, Prefix=prefix, Delimiter="/"):
            for prefix_obj in page.get("CommonPrefixes", []):
                name = prefix_obj.get("Prefix", "").rstrip("/").split("/")[-1]
                if name and name not in seen and not name.startswith("."):
                    seen.add(name)
                    customer_ids.append(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list customers: {e}") from e

    return {"customers": sorted(customer_ids), "count": len(customer_ids)}


@data_router.get("/customers/{customer_id}")
async def get_customer_metadata(request: Request, customer_id: str):
    """
    Get metadata for a customer - which data folders are available.
    """
    s3_client = _get_s3_client(request)
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    settings = _get_settings()
    base_path = settings.s3.base_path

    available: Dict[str, bool] = {}
    for folder in SHIPMENT_DATA_FOLDERS:
        key = s3_client.find_latest_customer_file(
            customer_id,
            f"data/{folder}",
            base_path=base_path,
            suffix=".json",
        )
        available[folder] = key is not None

    return {
        "customer_id": customer_id,
        "available_folders": available,
        "has_data": any(available.values()),
    }


@data_router.post("/customers/{customer_id}/full")
async def get_customer_full_data(request: Request, customer_id: str):
    """
    Get all customer shipment data in one call.

    Loads from all shipment-specific S3 folders and returns combined payload.
    """
    s3_client = _get_s3_client(request)
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")

    settings = _get_settings()
    base_path = settings.s3.base_path

    result: Dict[str, Any] = {
        "customer_id": customer_id,
        "data": {},
        "metadata": {},
    }

    for folder in SHIPMENT_DATA_FOLDERS:
        key = s3_client.find_latest_customer_file(
            customer_id,
            f"data/{folder}",
            base_path=base_path,
            suffix=".json",
        )
        if key:
            try:
                data = s3_client.download_json(key)
                result["data"][folder] = data
                if isinstance(data, dict) and "metadata" in data:
                    result["metadata"][folder] = data["metadata"]
            except Exception:
                result["data"][folder] = {"error": "Failed to load"}
        else:
            result["data"][folder] = None

    result["loaded_folders"] = [f for f in SHIPMENT_DATA_FOLDERS if result["data"].get(f) is not None]
    return result
