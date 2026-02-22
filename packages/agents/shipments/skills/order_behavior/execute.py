"""
Order Behavior Skill - Analyzes order frequency and category patterns.
"""

from typing import Dict, Any, List
from datetime import datetime
from collections import Counter

from packages.agents.shipments.skills.llm_skill_base import LLMSkillExecutor


def _compute_baseline_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute baseline order behavior metrics (deterministic)."""
    order_ids = set()
    autoship_orders = 0
    categories = []
    order_dates = []
    total = len(records)
    
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
    
    return {
        "total_shipments": total,
        "unique_orders": unique_orders,
        "autoship_orders": autoship_orders,
        "autoship_rate": autoship_rate,
        "order_frequency": order_frequency,
        "primary_category": primary_category,
        "category_distribution": dict(category_counts.most_common(5))
    }


def _deterministic_fallback(records: List[Dict[str, Any]], baseline: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback if LLM fails."""
    metrics = _compute_baseline_metrics(records)
    
    observations = [
        f"Total unique orders: {metrics['unique_orders']}",
        f"Autoship rate: {metrics['autoship_rate']}%",
        f"Order frequency: {metrics['order_frequency']} orders/month"
    ]
    
    return {
        "skill": "order_behavior",
        "observations": observations,
        "summary": {
            "autoship_rate": metrics["autoship_rate"],
            "order_frequency": metrics["order_frequency"],
            "primary_category": metrics["primary_category"]
        },
        "continued_analysis": f"Order behavior (deterministic fallback): {metrics['order_frequency']} orders/month.",
        "enhanced_next_steps": "Monitor order patterns.",
        "grounded_metrics": metrics
    }


def execute(state: Dict[str, Any], target_key: str = "", peer_level: str = "SEGMENT") -> Dict[str, Any]:
    """Execute the order behavior skill with LLM analysis."""
    shipment_data = state.get("shipment_data", {})
    records = shipment_data.get("records", [])
    
    if not records:
        return {"skill": "order_behavior", "error": "No shipment data", "grounded_metrics": {"total_shipments": 0}}
    
    baseline_metrics = _compute_baseline_metrics(records)
    context = {"customer_id": state.get("customer_id", "unknown")}
    
    executor = LLMSkillExecutor(skill_name="order_behavior", reasoning_effort="low")
    result = executor.execute_with_llm(
        records=records,
        baseline=baseline_metrics,
        context=context,
        deterministic_fallback=_deterministic_fallback,
        max_records=50
    )
    
    return result

