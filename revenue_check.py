"""
Revenue discrepancy diagnostic script.
Compares Shopify orders vs Dashboard calculations.
"""

import os
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

load_dotenv()

from shopify_client import ShopifyClient
from linnworks_client import LinnworksClient, get_dispatch_info
from costing import CostingService
from metrics import process_orders

def main():
    # Calculate last week (Mon-Sun)
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)

    print(f"=" * 60)
    print(f"REVENUE CHECK: {last_monday.strftime('%b %d')} - {last_sunday.strftime('%b %d, %Y')}")
    print(f"=" * 60)

    # Initialize clients
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    shopify_client = ShopifyClient(store, token, version)

    # PART 1: Get orders PLACED during this period from Shopify
    print(f"\n--- SHOPIFY ORDERS (by created_at date) ---")

    start_dt = datetime.combine(last_monday, datetime.min.time())
    end_dt = datetime.combine(last_sunday, datetime.max.time())

    shopify_orders_by_created = list(shopify_client.get_orders(
        created_at_min=start_dt,
        created_at_max=end_dt,
        status="any"
    ))

    # Calculate totals from Shopify
    shopify_total_price = 0
    shopify_subtotal = 0
    shopify_discounts = 0
    shopify_current_subtotal = 0
    shopify_shipping = 0
    shopify_tax = 0

    print(f"\nOrders placed during this week: {len(shopify_orders_by_created)}")
    print(f"\n{'Order':<12} {'Total':<12} {'Subtotal':<12} {'Discounts':<12} {'Shipping':<12} {'Status':<12}")
    print("-" * 72)

    for order in shopify_orders_by_created:
        total = float(order.get('total_price', 0))
        subtotal = float(order.get('subtotal_price', 0))
        discounts = float(order.get('total_discounts', 0))
        current_sub = float(order.get('current_subtotal_price', 0) or subtotal)

        shipping_set = order.get('total_shipping_price_set', {})
        shop_money = shipping_set.get('shop_money', {})
        shipping = float(shop_money.get('amount', 0)) if shop_money else 0

        tax = float(order.get('total_tax', 0))
        status = order.get('financial_status', 'unknown')

        shopify_total_price += total
        shopify_subtotal += subtotal
        shopify_discounts += discounts
        shopify_current_subtotal += current_sub
        shopify_shipping += shipping
        shopify_tax += tax

        print(f"{order.get('name', 'N/A'):<12} £{total:<11.2f} £{subtotal:<11.2f} £{discounts:<11.2f} £{shipping:<11.2f} {status:<12}")

    print("-" * 72)
    print(f"{'TOTALS':<12} £{shopify_total_price:<11.2f} £{shopify_subtotal:<11.2f} £{shopify_discounts:<11.2f} £{shopify_shipping:<11.2f}")

    print(f"\n--- SHOPIFY BREAKDOWN ---")
    print(f"total_price (what customer paid):     £{shopify_total_price:,.2f}")
    print(f"subtotal_price (products before disc): £{shopify_subtotal:,.2f}")
    print(f"total_discounts:                       £{shopify_discounts:,.2f}")
    print(f"current_subtotal_price (net products): £{shopify_current_subtotal:,.2f}")
    print(f"shipping:                              £{shopify_shipping:,.2f}")
    print(f"tax:                                   £{shopify_tax:,.2f}")
    print(f"")
    print(f"Formula check: subtotal - discounts = £{shopify_subtotal - shopify_discounts:,.2f}")
    print(f"Formula check: subtotal - discounts + shipping + tax = £{shopify_subtotal - shopify_discounts + shopify_shipping + shopify_tax:,.2f}")

    # PART 2: Get orders DISPATCHED during this period (what dashboard shows)
    print(f"\n\n--- DASHBOARD ORDERS (by Linnworks dispatch date) ---")

    lw_client = LinnworksClient()
    if not lw_client.authenticate():
        print("Failed to authenticate with Linnworks")
        return

    start_dt = datetime.combine(last_monday, datetime.min.time())
    end_dt = datetime.combine(last_sunday, datetime.max.time())

    linnworks_orders = lw_client.get_processed_orders(start_dt, end_dt)

    # Filter to D2C only
    d2c_orders = [o for o in linnworks_orders if 'no shipping' not in (o.get('PostalServiceName') or '').lower()]

    print(f"Total Linnworks orders dispatched: {len(linnworks_orders)}")
    print(f"D2C orders (with shipping): {len(d2c_orders)}")

    # Get Shopify order IDs
    shopify_order_ids = set()
    for order in d2c_orders:
        ref = order.get('ReferenceNum', '').replace('#', '').strip()
        if ref:
            try:
                shopify_order_ids.add(int(ref))
            except ValueError:
                pass

    print(f"Shopify order IDs extracted: {len(shopify_order_ids)}")

    if shopify_order_ids:
        # Fetch these specific orders from Shopify
        from app import fetch_shopify_orders_by_ids
        shopify_orders = fetch_shopify_orders_by_ids(store, token, version, tuple(sorted(shopify_order_ids)))

        # Get dispatch info and process
        dispatch_info = get_dispatch_info(d2c_orders)
        costing = CostingService(shopify_client)
        processed, total_cnt, skip_cnt = process_orders(shopify_orders, costing, dispatch_info)

        print(f"Orders processed by dashboard: {len(processed)}")
        print(f"Orders skipped (not dispatched): {skip_cnt}")

        # Calculate dashboard totals
        dash_gross = sum(o.gross_item_value for o in processed)
        dash_discounts = sum(o.total_discounts for o in processed)
        dash_net = sum(o.net_revenue for o in processed)
        dash_shipping = sum(o.shipping_paid for o in processed)

        print(f"\n--- DASHBOARD BREAKDOWN ---")
        print(f"gross_item_value (products):    £{dash_gross:,.2f}")
        print(f"total_discounts:                £{dash_discounts:,.2f}")
        print(f"net_revenue (what dashboard shows): £{dash_net:,.2f}")
        print(f"shipping_paid (tracked separately): £{dash_shipping:,.2f}")

        # COMPARISON
        print(f"\n\n{'=' * 60}")
        print(f"COMPARISON")
        print(f"{'=' * 60}")
        print(f"")
        print(f"Shopify 'Total Sales' (total_price):  £{shopify_total_price:,.2f}")
        print(f"Dashboard 'Net Revenue':              £{dash_net:,.2f}")
        print(f"Difference:                           £{shopify_total_price - dash_net:,.2f}")
        print(f"")
        print(f"--- BREAKDOWN OF DIFFERENCE ---")
        print(f"")

        # Orders placed but not dispatched
        orders_placed_ids = {o.get('id') for o in shopify_orders_by_created}
        orders_dispatched_ids = shopify_order_ids
        not_dispatched = orders_placed_ids - orders_dispatched_ids
        dispatched_but_placed_earlier = orders_dispatched_ids - orders_placed_ids

        print(f"Orders PLACED this week but NOT DISPATCHED yet: {len(not_dispatched)}")
        if not_dispatched:
            not_disp_total = sum(float(o.get('total_price', 0)) for o in shopify_orders_by_created if o.get('id') in not_dispatched)
            print(f"  -> Value of these orders: £{not_disp_total:,.2f}")

        print(f"Orders DISPATCHED this week but PLACED earlier: {len(dispatched_but_placed_earlier)}")

        print(f"")
        print(f"Shipping (included in Shopify, excluded in dashboard): £{shopify_shipping:,.2f}")
        print(f"Tax (included in Shopify total_price): £{shopify_tax:,.2f}")
        print(f"Discounts in Shopify orders: £{shopify_discounts:,.2f}")
        print(f"Discounts in Dashboard: £{dash_discounts:,.2f}")


if __name__ == "__main__":
    main()
