"""
Metrics calculation module for order profitability.
Uses Linnworks for dispatch dates (when orders were actually sent out).
"""

from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field
from dateutil import parser as date_parser
import pandas as pd

from costing import CostingService, calculate_packaging_cost
from linnworks_client import LinnworksClient, get_dispatch_info


@dataclass
class LineItemMetrics:
    """Metrics for a single line item."""
    sku: Optional[str]
    variant_id: Optional[int]
    title: str
    quantity: int
    unit_price: float
    gross_value: float  # unit_price * quantity
    line_discount: float
    net_revenue: float  # gross_value - line_discount
    unit_cost: Optional[float]
    line_cogs: float
    has_cost: bool


@dataclass
class OrderMetrics:
    """Complete metrics for a single order."""
    order_id: int
    order_name: str
    customer_id: Optional[int]
    customer_name: str
    created_at: datetime
    processed_at: Optional[datetime]
    sent_out_at: datetime
    sent_out_weekday: str
    sent_out_week: str  # ISO week format: "2024-W01"
    currency: str

    # Revenue breakdown
    gross_item_value: float
    total_discounts: float
    net_revenue: float
    shipping_paid: float  # What customer paid for shipping

    # Costs
    cogs: float
    packaging_total: float
    box_type: str
    box_multiplier: int
    packaging_breakdown: Dict[str, float]

    # Profit metrics
    gross_profit: float
    contribution: float
    gross_margin_pct: float
    contribution_margin_pct: float

    # SKU info
    sku_count: int
    total_units: int

    # Line items
    line_items: List[LineItemMetrics] = field(default_factory=list)
    missing_cost_count: int = 0
    missing_cost_skus: List[str] = field(default_factory=list)

    # First-time order flag (customer's first order)
    is_first_order: bool = False


def parse_datetime(dt_string: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    if not dt_string:
        return None
    try:
        return date_parser.parse(dt_string)
    except (ValueError, TypeError):
        return None


def is_order_fulfilled(order: dict) -> bool:
    """
    Check if an order has been fulfilled (actually sent out).

    Returns True only if the order has at least one fulfillment.
    """
    fulfillments = order.get("fulfillments", [])
    return len(fulfillments) > 0


def get_sent_out_at(order: dict) -> Optional[datetime]:
    """
    Get the sent out timestamp for an order.

    Returns the earliest fulfillment.created_at, or None if not fulfilled.
    """
    fulfillments = order.get("fulfillments", [])

    if not fulfillments:
        # Not fulfilled - return None
        return None

    # Find earliest fulfillment created_at
    fulfillment_dates = []
    for f in fulfillments:
        created = parse_datetime(f.get("created_at"))
        if created:
            fulfillment_dates.append(created)

    if fulfillment_dates:
        return min(fulfillment_dates)

    return None


def get_iso_week(dt: datetime) -> str:
    """Get ISO week string from datetime."""
    iso_cal = dt.isocalendar()
    return f"{iso_cal.year}-W{iso_cal.week:02d}"


def count_distinct_skus(line_items: List[dict]) -> int:
    """
    Count distinct SKUs in line items.

    Uses SKU when present, otherwise variant_id.
    """
    identifiers = set()
    for item in line_items:
        sku = item.get("sku")
        if sku:
            identifiers.add(f"sku:{sku}")
        else:
            variant_id = item.get("variant_id")
            if variant_id:
                identifiers.add(f"vid:{variant_id}")

    return len(identifiers)


def calculate_line_item_discounts(order: dict, line_items: List[dict]) -> Dict[int, float]:
    """
    Calculate discount allocated to each line item.

    If discount_allocations are available on line items, use those.
    Otherwise, allocate order-level discounts proportionally.
    """
    line_discounts = {}

    # Calculate gross value for each line item
    line_gross = {}
    total_gross = 0.0
    for idx, item in enumerate(line_items):
        price = float(item.get("price", 0))
        quantity = int(item.get("quantity", 0))
        gross = price * quantity
        line_gross[idx] = gross
        total_gross += gross

    # Check if line items have discount_allocations
    has_allocations = False
    for idx, item in enumerate(line_items):
        allocations = item.get("discount_allocations", [])
        if allocations:
            has_allocations = True
            total_allocation = sum(float(a.get("amount", 0)) for a in allocations)
            line_discounts[idx] = total_allocation

    if has_allocations:
        # Fill in 0 for items without allocations
        for idx in range(len(line_items)):
            if idx not in line_discounts:
                line_discounts[idx] = 0.0
        return line_discounts

    # No allocations - distribute order-level discount proportionally
    total_discount = float(order.get("current_total_discounts") or order.get("total_discounts") or 0)

    if total_gross > 0 and total_discount > 0:
        for idx in range(len(line_items)):
            proportion = line_gross[idx] / total_gross
            line_discounts[idx] = total_discount * proportion
    else:
        for idx in range(len(line_items)):
            line_discounts[idx] = 0.0

    return line_discounts


def calculate_order_revenue(order: dict) -> Tuple[float, float, float]:
    """
    Calculate revenue components for an order.

    Returns:
        Tuple of (gross_item_value, total_discounts, net_revenue)
    """
    line_items = order.get("line_items", [])

    # Calculate gross item value from line items
    gross_item_value = 0.0
    for item in line_items:
        price = float(item.get("price", 0))
        quantity = int(item.get("quantity", 0))
        gross_item_value += price * quantity

    # Get total discounts
    # Prefer current_total_discounts if available
    total_discounts = float(
        order.get("current_total_discounts") or
        order.get("total_discounts") or
        0
    )

    # Calculate net revenue
    # current_subtotal_price should already be net of discounts
    current_subtotal = order.get("current_subtotal_price")

    if current_subtotal is not None:
        # Use current_subtotal_price as it's already net
        net_revenue = float(current_subtotal)
        # Recalculate discount to match
        calculated_discount = gross_item_value - net_revenue
        if calculated_discount > 0:
            total_discounts = calculated_discount
    else:
        # Fall back to subtotal_price - total_discounts
        subtotal = float(order.get("subtotal_price") or gross_item_value)
        net_revenue = subtotal - total_discounts

        # If net_revenue matches subtotal, discounts may already be applied
        if abs(net_revenue - subtotal) < 0.01 and total_discounts > 0:
            # Check if subtotal already has discount applied
            if abs(gross_item_value - subtotal - total_discounts) < 0.01:
                # subtotal already has discounts, don't double count
                net_revenue = subtotal

    return gross_item_value, total_discounts, net_revenue


def process_order(
    order: dict,
    costing_service: CostingService,
    dispatch_info: Optional[Dict[str, Dict]] = None
) -> Optional[OrderMetrics]:
    """
    Process a single order and calculate all metrics.

    Uses Linnworks dispatch dates when available, otherwise falls back to Shopify fulfillment.

    Args:
        order: Shopify order dict
        costing_service: Service for cost lookups
        dispatch_info: Dict mapping order names to Linnworks dispatch info

    Returns:
        OrderMetrics with all calculated values, or None if order not dispatched
    """
    # Basic order info
    order_id = order.get("id")
    order_name = order.get("name", "")
    created_at = parse_datetime(order.get("created_at")) or datetime.now()
    processed_at = parse_datetime(order.get("processed_at"))
    currency = order.get("currency", "GBP")

    # Try to get dispatch date from Linnworks first
    # Linnworks stores Shopify order ID as the reference number
    sent_out_at = None

    if dispatch_info:
        # Look up by order ID (Linnworks uses Shopify order ID as reference)
        lw_info = dispatch_info.get(order_id)

        # Also try string version of order ID
        if not lw_info:
            lw_info = dispatch_info.get(str(order_id))

        # Fallback to order name (for legacy data)
        if not lw_info:
            clean_order_name = order_name.replace('#', '').strip()
            lw_info = dispatch_info.get(clean_order_name) or dispatch_info.get(order_name)

        if lw_info and lw_info.get('processed_date'):
            sent_out_at = lw_info['processed_date']

    # If no Linnworks date, fall back to Shopify fulfillment
    if sent_out_at is None:
        if is_order_fulfilled(order):
            sent_out_at = get_sent_out_at(order)

    # If still no dispatch date, skip this order
    if sent_out_at is None:
        return None

    # Weekday and week from sent out date
    sent_out_weekday = sent_out_at.strftime("%A")
    sent_out_week = get_iso_week(sent_out_at)

    # Customer info - try multiple sources
    customer_name = ""
    customer_id = None

    # Try customer object first
    customer = order.get("customer") or {}
    is_first_order = False
    if customer:
        customer_id = customer.get('id')
        first = customer.get('first_name', '') or ''
        last = customer.get('last_name', '') or ''
        customer_name = f"{first} {last}".strip()
        # Check if this is the customer's first order
        is_first_order = customer.get('orders_count', 1) == 1

    # Try shipping address
    if not customer_name:
        shipping = order.get("shipping_address") or {}
        customer_name = shipping.get("name", "") or ""
        if not customer_name:
            first = shipping.get('first_name', '') or ''
            last = shipping.get('last_name', '') or ''
            customer_name = f"{first} {last}".strip()

    # Try billing address
    if not customer_name:
        billing = order.get("billing_address") or {}
        customer_name = billing.get("name", "") or ""
        if not customer_name:
            first = billing.get('first_name', '') or ''
            last = billing.get('last_name', '') or ''
            customer_name = f"{first} {last}".strip()

    if not customer_name:
        customer_name = "Unknown"

    # Shipping paid by customer
    shipping_price_set = order.get("total_shipping_price_set", {})
    shop_money = shipping_price_set.get("shop_money", {})
    shipping_paid = float(shop_money.get("amount", 0)) if shop_money else 0

    # Line items
    line_items = order.get("line_items", [])

    # SKU count (distinct)
    sku_count = count_distinct_skus(line_items)

    # Total units
    total_units = sum(int(item.get("quantity", 0)) for item in line_items)

    # Revenue calculations
    gross_item_value, total_discounts, net_revenue = calculate_order_revenue(order)

    # Calculate line item discounts
    line_discount_map = calculate_line_item_discounts(order, line_items)

    # Process line items and calculate COGS
    processed_line_items = []
    total_cogs = 0.0
    missing_cost_count = 0
    missing_cost_skus = []

    for idx, item in enumerate(line_items):
        sku = item.get("sku")
        variant_id = item.get("variant_id")
        title = item.get("title", "Unknown")
        quantity = int(item.get("quantity", 0))
        unit_price = float(item.get("price", 0))

        # Line revenue
        gross_value = unit_price * quantity
        line_discount = line_discount_map.get(idx, 0.0)
        line_net_revenue = gross_value - line_discount

        # COGS lookup
        line_cogs, has_cost, unit_cost = costing_service.calculate_line_cogs(item)
        total_cogs += line_cogs

        if not has_cost:
            missing_cost_count += 1
            missing_cost_skus.append(sku or f"variant:{variant_id}" or "unknown")

        processed_line_items.append(LineItemMetrics(
            sku=sku,
            variant_id=variant_id,
            title=title,
            quantity=quantity,
            unit_price=unit_price,
            gross_value=gross_value,
            line_discount=line_discount,
            net_revenue=line_net_revenue,
            unit_cost=unit_cost,
            line_cogs=line_cogs,
            has_cost=has_cost,
        ))

    # Packaging costs - based on total units (items in box), not distinct SKUs
    packaging_total, box_type, box_multiplier, packaging_breakdown = calculate_packaging_cost(total_units)

    # Profit calculations
    gross_profit = net_revenue - total_cogs
    contribution = net_revenue - total_cogs - packaging_total

    # Margin calculations (guard against divide by zero)
    if net_revenue > 0:
        gross_margin_pct = (gross_profit / net_revenue) * 100
        contribution_margin_pct = (contribution / net_revenue) * 100
    else:
        gross_margin_pct = 0.0
        contribution_margin_pct = 0.0

    return OrderMetrics(
        order_id=order_id,
        order_name=order_name,
        customer_id=customer_id,
        customer_name=customer_name,
        created_at=created_at,
        processed_at=processed_at,
        sent_out_at=sent_out_at,
        sent_out_weekday=sent_out_weekday,
        sent_out_week=sent_out_week,
        currency=currency,
        gross_item_value=gross_item_value,
        total_discounts=total_discounts,
        net_revenue=net_revenue,
        shipping_paid=shipping_paid,
        cogs=total_cogs,
        packaging_total=packaging_total,
        box_type=box_type,
        box_multiplier=box_multiplier,
        packaging_breakdown=packaging_breakdown,
        gross_profit=gross_profit,
        contribution=contribution,
        gross_margin_pct=gross_margin_pct,
        contribution_margin_pct=contribution_margin_pct,
        sku_count=sku_count,
        total_units=total_units,
        line_items=processed_line_items,
        missing_cost_count=missing_cost_count,
        missing_cost_skus=missing_cost_skus,
        is_first_order=is_first_order,
    )


def process_orders(
    orders: List[dict],
    costing_service: CostingService,
    dispatch_info: Optional[Dict[str, Dict]] = None,
    progress_callback: Optional[callable] = None,
) -> tuple[List[OrderMetrics], int, int]:
    """
    Process multiple orders.

    Uses Linnworks dispatch dates when available.

    Args:
        orders: List of Shopify order dicts
        costing_service: Service for cost lookups
        dispatch_info: Dict mapping order names to Linnworks dispatch info
        progress_callback: Optional callback for progress updates

    Returns:
        Tuple of (List of OrderMetrics, total_orders, skipped_not_dispatched)
    """
    results = []
    total = len(orders)
    skipped = 0

    for idx, order in enumerate(orders):
        metrics = process_order(order, costing_service, dispatch_info)

        if metrics is not None:
            results.append(metrics)
        else:
            skipped += 1

        if progress_callback:
            progress_callback(idx + 1, total, len(results), skipped)

    return results, total, skipped


def filter_by_weekday(
    orders: List[OrderMetrics],
    include_monday: bool = True,
    include_thursday: bool = True,
    include_all: bool = False,
) -> List[OrderMetrics]:
    """
    Filter orders by sent_out weekday.

    Args:
        orders: List of OrderMetrics
        include_monday: Include Monday orders
        include_thursday: Include Thursday orders
        include_all: Include all weekdays (overrides other flags)

    Returns:
        Filtered list of OrderMetrics
    """
    if include_all:
        return orders

    allowed_days = set()
    if include_monday:
        allowed_days.add("Monday")
    if include_thursday:
        allowed_days.add("Thursday")

    return [o for o in orders if o.sent_out_weekday in allowed_days]


def create_orders_dataframe(orders: List[OrderMetrics]) -> pd.DataFrame:
    """
    Create a pandas DataFrame from OrderMetrics list.
    """
    data = []
    for o in orders:
        data.append({
            "sent_out_at": o.sent_out_at,
            "weekday": o.sent_out_weekday,
            "week": o.sent_out_week,
            "order_name": o.order_name,
            "customer_id": o.customer_id,
            "customer_name": o.customer_name,
            "order_id": o.order_id,
            "sku_count": o.sku_count,
            "total_units": o.total_units,
            "box_type": o.box_type,
            "box_multiplier": o.box_multiplier,
            "gross_item_value": o.gross_item_value,
            "total_discounts": o.total_discounts,
            "net_revenue": o.net_revenue,
            "shipping_paid": o.shipping_paid,
            "cogs": o.cogs,
            "packaging_total": o.packaging_total,
            "gross_profit": o.gross_profit,
            "contribution": o.contribution,
            "gross_margin_pct": o.gross_margin_pct,
            "contribution_margin_pct": o.contribution_margin_pct,
            "missing_cost_count": o.missing_cost_count,
            "currency": o.currency,
            "is_first_order": o.is_first_order,
        })

    return pd.DataFrame(data)


def create_weekly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create weekly summary grouped by week and weekday.
    """
    if df.empty:
        return pd.DataFrame()

    # Group by week and weekday
    grouped = df.groupby(["week", "weekday"]).agg({
        "order_id": "count",
        "total_units": "sum",
        "gross_item_value": "sum",
        "total_discounts": "sum",
        "net_revenue": "sum",
        "cogs": "sum",
        "packaging_total": "sum",
        "contribution": "sum",
    }).reset_index()

    grouped.columns = [
        "week", "weekday", "orders", "units", "gross_value",
        "discounts", "net_revenue", "cogs", "packaging", "contribution"
    ]

    # Calculate contribution margin
    grouped["contribution_margin_pct"] = (
        grouped["contribution"] / grouped["net_revenue"] * 100
    ).fillna(0)

    # Pivot to show Monday and Thursday columns
    pivot = grouped.pivot(
        index="week",
        columns="weekday",
        values=["orders", "units", "net_revenue", "contribution", "contribution_margin_pct"]
    )

    # Flatten column names
    pivot.columns = [f"{col[1]}_{col[0]}" for col in pivot.columns]
    pivot = pivot.reset_index()

    return pivot


def calculate_kpis(orders: List[OrderMetrics]) -> Dict[str, Any]:
    """
    Calculate summary KPIs across all orders.
    """
    if not orders:
        return {
            "total_orders": 0,
            "total_units": 0,
            "gross_item_value": 0,
            "total_discounts": 0,
            "net_revenue": 0,
            "total_cogs": 0,
            "total_packaging": 0,
            "total_contribution": 0,
            "avg_contribution_margin": 0,
            "missing_costs_count": 0,
        }

    total_orders = len(orders)
    total_units = sum(o.total_units for o in orders)
    gross_item_value = sum(o.gross_item_value for o in orders)
    total_discounts = sum(o.total_discounts for o in orders)
    net_revenue = sum(o.net_revenue for o in orders)
    total_cogs = sum(o.cogs for o in orders)
    total_packaging = sum(o.packaging_total for o in orders)
    total_contribution = sum(o.contribution for o in orders)

    avg_contribution_margin = (total_contribution / net_revenue * 100) if net_revenue > 0 else 0
    missing_costs_count = sum(o.missing_cost_count for o in orders)

    return {
        "total_orders": total_orders,
        "total_units": total_units,
        "gross_item_value": gross_item_value,
        "total_discounts": total_discounts,
        "net_revenue": net_revenue,
        "total_cogs": total_cogs,
        "total_packaging": total_packaging,
        "total_contribution": total_contribution,
        "avg_contribution_margin": avg_contribution_margin,
        "missing_costs_count": missing_costs_count,
    }
