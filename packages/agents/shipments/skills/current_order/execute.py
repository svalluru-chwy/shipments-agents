"""
Current Order Skill - Tracks active/in-progress orders and predicts delays.
"""

from typing import Dict, Any
from datetime import datetime, timedelta


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the current order skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    # Load customer contacts to check for duplicate outreach
    customer_contacts = state.get("customer_contacts", {})
    contact_records = []
    if isinstance(customer_contacts, dict):
        contact_records = customer_contacts.get("data", [])
    elif isinstance(customer_contacts, list):
        contact_records = customer_contacts
    
    if not records:
        # Even with no shipment data, provide VOC context
        now = datetime.now()
        cutoff_date = now - timedelta(days=90)
        shipment_contacts_90d = 0
        
        for contact in contact_records:
            # S3 uses SESSION_START_DTTM (not CONTACT_DATE)
            contact_date_str = contact.get("SESSION_START_DTTM")
            # S3 uses CATEGORY_LEVEL_1/2/3 (not CONTACT_REASON)
            contact_reason = " ".join(filter(None, [
                str(contact.get("CATEGORY_LEVEL_1", "") or ""),
                str(contact.get("CATEGORY_LEVEL_2", "") or ""),
                str(contact.get("CATEGORY_LEVEL_3", "") or ""),
            ])).lower()
            
            if any(keyword in contact_reason for keyword in ["ship", "deliver", "track", "delay", "transit", "package"]):
                if contact_date_str:
                    try:
                        contact_dt = datetime.fromisoformat(str(contact_date_str).replace("Z", "+00:00"))
                        if contact_dt.replace(tzinfo=None) >= cutoff_date:
                            shipment_contacts_90d += 1
                    except:
                        pass
        
        return {
            "skill": "current_order",
            "error": "No shipment data",
            "observations": [
                "No shipment data available",
                f"Customer shipment-related contacts in last 90 days: {shipment_contacts_90d}"
            ],
            "grounded_metrics": {
                "total_orders": 0,
                "voc_context": {
                    "shipment_contacts_last_90_days": shipment_contacts_90d
                }
            }
        }
    
    # Find active orders (not yet delivered)
    active_orders = []
    at_risk = []
    
    now = datetime.now()
    
    for record in records:
        # CRITICAL FIX: Use correct field name from S3 data
        status = record.get("BULK_TRACK_LAST_STATUS_CODE_DESCRIPTION", "").upper()
        delivery_date = record.get("BULK_TRACK_DELIVERY_DTTM")
        ship_date = record.get("ACTUAL_SHIP_DATE")
        
        # Check if not delivered (delivery_date is None means still in transit)
        # MUST be AND not OR: only include if delivery date is null AND status is not delivered
        if delivery_date is None and status not in ["DELIVERED", "COMPLETE"]:
            order = {
                "order_id": record.get("ORDER_ID"),
                "tracking": record.get("SHIPMENT_TRACKING_NUMBER"),
                "carrier": record.get("WAREHOUSE_CARRIER"),
                "status": status,
                "ship_date": ship_date,
                "expected_delivery": record.get("EXPECTED_DELIVERY_DATE")
            }
            active_orders.append(order)
            
            # Check if at risk (>5 days in transit)
            if ship_date:
                try:
                    if isinstance(ship_date, str):
                        ship_dt = datetime.fromisoformat(ship_date.replace("Z", "+00:00"))
                    else:
                        ship_dt = ship_date
                    
                    days_in_transit = (now - ship_dt.replace(tzinfo=None)).days
                    if days_in_transit > 5:
                        order["days_in_transit"] = days_in_transit
                        order["risk_level"] = "HIGH" if days_in_transit > 7 else "MEDIUM"
                        at_risk.append(order)
                except:
                    pass
    
    total_active = len(active_orders)
    total_at_risk = len(at_risk)
    
    # Check if customer has contacted us about shipment issues recently (last 90 days)
    shipment_contacts_90d = 0
    recent_shipment_contacts = []
    if contact_records:
        cutoff_date = now - timedelta(days=90)
        for contact in contact_records:
            # S3 uses SESSION_START_DTTM (not CONTACT_DATE)
            contact_date_str = contact.get("SESSION_START_DTTM")
            # S3 uses CATEGORY_LEVEL_1/2/3 (not CONTACT_REASON)
            contact_reason = " ".join(filter(None, [
                str(contact.get("CATEGORY_LEVEL_1", "") or ""),
                str(contact.get("CATEGORY_LEVEL_2", "") or ""),
                str(contact.get("CATEGORY_LEVEL_3", "") or ""),
            ])).lower()
            contact_reason_display = " > ".join(filter(None, [
                str(contact.get("CATEGORY_LEVEL_1", "") or ""),
                str(contact.get("CATEGORY_LEVEL_2", "") or ""),
            ]))
            
            # Check if shipment/delivery related
            if any(keyword in contact_reason for keyword in ["ship", "deliver", "track", "delay", "transit", "package"]):
                if contact_date_str:
                    try:
                        if isinstance(contact_date_str, str):
                            contact_dt = datetime.fromisoformat(contact_date_str.replace("Z", "+00:00"))
                        else:
                            contact_dt = contact_date_str
                        
                        if contact_dt.replace(tzinfo=None) >= cutoff_date:
                            shipment_contacts_90d += 1
                            recent_shipment_contacts.append({
                                "date": contact_date_str,
                                "reason": contact_reason_display or "Unknown"
                            })
                    except:
                        pass
    
    observations = [
        f"Analyzed {len(records)} total shipments for active/in-transit orders",
        f"Total active orders: {total_active}",
        f"Orders at risk (HIGH/CRITICAL): {total_at_risk}"
    ]
    
    # Add delivery status context
    delivered_count = len([r for r in records if r.get("BULK_TRACK_DELIVERY_DTTM")])
    if delivered_count == len(records):
        observations.append(f"All {delivered_count} shipments have been delivered")
    
    # Add VOC context with detail
    total_contacts = len(contact_records)
    observations.append(f"Checked {total_contacts} customer contacts for shipment-related issues")
    
    if shipment_contacts_90d > 0:
        observations.append(f"Found {shipment_contacts_90d} shipment-related contact(s) in last 90 days")
        # Add details of recent contacts
        for contact in recent_shipment_contacts[:2]:
            observations.append(f"  • Contact on {contact['date'][:10]}: {contact['reason'][:60]}")
    else:
        observations.append("No shipment-related contacts found in last 90 days")
    
    for order in at_risk[:3]:
        observations.append(
            f"At-risk order: {order['order_id']}, {order.get('days_in_transit', 'N/A')} days in transit, status: {order['status']}"
        )
    
    result = {
        "skill": "current_order",
        "observations": observations,
        "order_summary": {
            "active_orders": total_active,
            "at_risk_orders": total_at_risk
        },
        "risk_assessment": {
            "high_risk_count": len([o for o in at_risk if o.get("risk_level") == "HIGH"]),
            "medium_risk_count": len([o for o in at_risk if o.get("risk_level") == "MEDIUM"])
        },
        "continued_analysis": f"Current order tracking shows {total_active} active orders with {total_at_risk} at risk.",
        "enhanced_next_steps": (
            f"Proactive outreach recommended for at-risk orders. Note: Customer {'has' if shipment_contacts_90d > 0 else 'has not'} contacted about delivery issues recently."
            if at_risk else "No orders at risk."
        ),
        "grounded_metrics": {
            "total_shipments_analyzed": len(records),
            "delivered_shipments": len([r for r in records if r.get("BULK_TRACK_DELIVERY_DTTM")]),
            "total_active_orders": total_active,
            "at_risk_orders": total_at_risk,
            "active_order_details": active_orders[:10],
            "at_risk_details": at_risk,
            "voc_context": {
                "total_contacts_checked": len(contact_records),
                "shipment_contacts_last_90_days": shipment_contacts_90d,
                "recent_contacts": recent_shipment_contacts[:3]
            }
        }
    }
    
    return result
