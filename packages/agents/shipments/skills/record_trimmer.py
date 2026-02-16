"""
Shared record trimming utility for shipment skills.

Reduces 274-field shipment records to the ~26 fields relevant to LLM analysis.
This cuts per-record JSON from ~12,500 chars to ~1,200 chars (~90% reduction),
keeping LLM prompts within reliable context windows.

Usage:
    from packages.agents.shipments.skills.record_trimmer import trim_record, trim_records

    trimmed = trim_records(raw_records)
"""

from typing import Any, Dict, List


# ── Fields to keep (26 total) ──────────────────────────────────────────────
# Grouped by purpose.  ONTIME_DELIVERY_FLAG is intentionally excluded
# (unreliable -- see channel_log.txt Entry 15).

TRIMMED_FIELDS: List[str] = [
    # Identity + Timing
    "ORDERS_ORDER_ID",
    "SHIPMENT_TRACKING_NUMBER",
    "CUSTOMER_ID",
    "ORDER_PLACED_DTTM",
    "ACTUAL_SHIP_DATE",
    "BULK_TRACK_DELIVERY_DTTM",
    "BULK_TRACK_ESTIMATED_DELIVERY_DTTM",
    "SHIPMENT_ESTIMATED_DELIVERY_DATE",
    # Performance
    "CLICK_TO_DELIVER_DAYS",
    "SHIP_TO_DELIVER_DAYS",
    "SHIPMENT_WAS_DELAYED",
    # Status
    "SHIPMENT_STATUS",
    "BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION",
    # Carrier + Routing
    "WAREHOUSE_CARRIER",
    "FFMCENTER_NAME",
    "ACTUAL_SHIP_ROUTE",
    "POSTCODE",
    "ACTUAL_ZONE",
    # Product
    "LINEITEM_PRODUCT_NAMES",
    "LINEITEM_PRODUCT_CAT_L1",
    "LINEITEM_PRODUCT_MC2",
    "SHIPMENT_CONTAINS_FRESH",
    "ORDERS_ORDER_AUTO_REORDER_FLAG",
    # Package + Exception
    "BULK_TRACK_LB_PACKAGE_WEIGHT",
    "SHIPMENT_COUNT_OF_ITEMS_IN_BOX",
    "BULK_TRACK_DELIVERY_ATTEMPT_EXCEPTION",
]


def trim_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trim a single shipment record to the relevant field set.

    Only fields that exist and are not None are included, keeping the
    output compact.  Returns a new dict (does not mutate the original).
    """
    trimmed: Dict[str, Any] = {}
    for field in TRIMMED_FIELDS:
        value = record.get(field)
        if value is not None:
            trimmed[field] = value
    return trimmed


def trim_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trim a list of shipment records.  Returns a new list."""
    return [trim_record(r) for r in records]
