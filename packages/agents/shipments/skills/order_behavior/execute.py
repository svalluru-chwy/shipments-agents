"""
Order Behavior Skill - Analyzes order frequency and category patterns.
"""

from typing import Dict, Any
from datetime import datetime
from collections import Counter


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the order behavior skill."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "order_behavior", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    # Analyze order patterns
    order_ids = set()
    autoship_orders = 0
    categories = []
    order_dates = []
    
    for record in records:
        # Use ORDERS_ORDER_ID (not ORDER_ID which is often null)
        order_id = record.get("ORDERS_ORDER_ID") or record.get("ORDER_ID")
        if order_id:
            order_ids.add(order_id)
        
        # Check autoship flag - ORDERS_ORDER_AUTO_REORDER_FLAG is boolean
        is_autoship = record.get("ORDERS_ORDER_AUTO_REORDER_FLAG") or record.get("IS_AUTOSHIP")
        if is_autoship == True or is_autoship == "Y" or is_autoship == "true":
            autoship_orders += 1
        
        # Use actual category fields from the data
        category = (
            record.get("LINEITEM_PRODUCT_CAT_L1") or 
            record.get("LINEITEM_PRODUCT_MC1") or
            record.get("MERCH_BUCKET") or 
            record.get("PRODUCT_CATEGORY")
        )
        if category:
            categories.append(category)
        
        # Use ORDERS_ORDER_PLACED_DTTM for order date
        order_date = record.get("ORDERS_ORDER_PLACED_DTTM") or record.get("ORDER_PLACED_DTTM")
        if order_date:
            try:
                if isinstance(order_date, str):
                    order_dates.append(datetime.fromisoformat(order_date.replace("Z", "+00:00")))
                else:
                    order_dates.append(order_date)
            except:
                pass
    
    unique_orders = len(order_ids)
    autoship_rate = round((autoship_orders / len(records)) * 100, 1) if records else 0
    
    # Calculate order frequency
    if len(order_dates) >= 2:
        order_dates.sort()
        date_range = (order_dates[-1] - order_dates[0]).days
        if date_range > 0:
            order_frequency = round(unique_orders / (date_range / 30), 1)  # Orders per month
        else:
            order_frequency = unique_orders
    else:
        order_frequency = unique_orders
    
    # Primary category
    category_counts = Counter(categories)
    primary_category = category_counts.most_common(1)[0][0] if category_counts else None
    
    observations = [
        f"Total unique orders: {unique_orders}",
        f"Autoship rate: {autoship_rate}%",
        f"Order frequency: {order_frequency} orders/month",
        f"Primary category: {primary_category or 'Not specified'}"
    ]
    
    result = {
        "skill": "order_behavior",
        "observations": observations,
        "summary": {
            "autoship_rate": autoship_rate,
            "order_frequency": order_frequency,
            "primary_category": primary_category
        },
        "continued_analysis": f"Order behavior shows {order_frequency} orders/month with {autoship_rate}% autoship rate.",
        "enhanced_next_steps": "Consider autoship promotion for repeat purchases." if autoship_rate < 50 else "Healthy autoship adoption.",
        "grounded_metrics": {
            "total_shipments": len(records),
            "unique_orders": unique_orders,
            "autoship_orders": autoship_orders,
            "autoship_rate": autoship_rate,
            "order_frequency": order_frequency,
            "primary_category": primary_category,
            "category_distribution": dict(category_counts.most_common(5))
        }
    }
    
    return result
