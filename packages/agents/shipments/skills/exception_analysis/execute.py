"""
Exception Analysis Skill - Analyzes carrier exceptions and delivery issues.
"""

from typing import Dict, Any


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the exception analysis skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "exception_analysis", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    # Analyze exceptions
    exceptions = []
    exception_by_carrier = {}
    exception_by_type = {}
    
    for record in records:
        # S3 uses BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION (not EXCEPTION_FLAG)
        # and boolean true/null for SHIPMENT_WAS_DELAYED (not "Y" string)
        exc_desc = str(record.get("BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION", "") or "")
        has_exception = exc_desc and exc_desc.lower() not in ("no exception", "", "none")
        is_delayed = record.get("SHIPMENT_WAS_DELAYED") is True

        if has_exception or is_delayed:
            exc = {
                "order_id": record.get("ORDER_ID") or record.get("ORDERS_ORDER_ID"),
                "tracking": record.get("SHIPMENT_TRACKING_NUMBER"),
                "carrier": record.get("WAREHOUSE_CARRIER"),
                "type": record.get("INITIAL_DELIVERY_ATTEMPT_EXCEPTION_CD") or exc_desc or "Delay",
                "ctd": record.get("CLICK_TO_DELIVER_DAYS")
            }
            exceptions.append(exc)
            
            carrier = exc["carrier"] or "Unknown"
            exception_by_carrier[carrier] = exception_by_carrier.get(carrier, 0) + 1
            
            exc_type = exc["type"] or "Unknown"
            exception_by_type[exc_type] = exception_by_type.get(exc_type, 0) + 1
    
    total = len(records)
    exception_count = len(exceptions)
    exception_rate = round((exception_count / total) * 100, 1) if total > 0 else 0
    
    observations = [
        f"Total exceptions: {exception_count} out of {total} shipments ({exception_rate}%)"
    ]
    
    for exc in exceptions[:5]:
        observations.append(
            f"Exception: Order {exc['order_id']}, Tracking {exc['tracking']}, Carrier {exc['carrier']}, Type {exc['type']}"
        )
    
    result = {
        "skill": "exception_analysis",
        "observations": observations,
        "exception_summary": {
            "total_exceptions": exception_count,
            "exception_rate": exception_rate,
            "by_carrier": exception_by_carrier,
            "by_type": exception_by_type
        },
        "continued_analysis": f"Exception analysis identified {exception_count} exceptions ({exception_rate}% rate).",
        "enhanced_next_steps": "Monitor carriers with high exception rates." if exception_count > 0 else "No exceptions to address.",
        "grounded_metrics": {
            "total_shipments": total,
            "exception_count": exception_count,
            "exception_rate": exception_rate,
            "by_carrier": exception_by_carrier,
            "by_type": exception_by_type,
            "exception_details": exceptions[:10]
        }
    }
    
    return result
