#!/usr/bin/env python3
"""Check how many orders used a specific discount code."""

import os
from dotenv import load_dotenv
from shopify_client import ShopifyClient
from datetime import datetime, timedelta

load_dotenv()

def check_discount_code(code: str = "modernmilkman20"):
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    if not store or not token:
        print("Missing SHOPIFY_STORE_DOMAIN or SHOPIFY_ACCESS_TOKEN")
        return

    client = ShopifyClient(store, token, version)

    # Fetch all orders from the last 2 years
    date_max = datetime.now()
    date_min = date_max - timedelta(days=730)

    print(f"Searching for orders with discount code: {code}")
    print(f"Date range: {date_min.strftime('%Y-%m-%d')} to {date_max.strftime('%Y-%m-%d')}")
    print("-" * 60)

    orders = list(client.get_orders(created_at_min=date_min, created_at_max=date_max, status="any"))

    matching_orders = []
    total_revenue = 0
    total_discount = 0

    for order in orders:
        discount_codes = order.get('discount_codes', [])
        for dc in discount_codes:
            if dc.get('code', '').lower() == code.lower():
                matching_orders.append(order)
                total_revenue += float(order.get('total_price', 0))
                total_discount += float(dc.get('amount', 0))
                break

    print(f"\nResults for discount code: {code}")
    print("=" * 60)
    print(f"Total orders using this code: {len(matching_orders)}")
    print(f"Total revenue from these orders: £{total_revenue:,.2f}")
    print(f"Total discount given: £{total_discount:,.2f}")

    if matching_orders:
        print(f"\nOrder details:")
        print("-" * 60)
        for order in matching_orders:
            order_date = order.get('created_at', '')[:10]
            order_name = order.get('name', 'N/A')
            order_total = float(order.get('total_price', 0))
            customer = order.get('customer', {})
            customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Guest"
            print(f"{order_name:<12} {order_date}  £{order_total:>8.2f}  {customer_name}")

if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "modernmilkman20"
    check_discount_code(code)
