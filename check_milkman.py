#!/usr/bin/env python3
"""Find all Modern Milkman related discount codes."""

import os
from dotenv import load_dotenv
from shopify_client import ShopifyClient
from datetime import datetime, timedelta
from collections import defaultdict

load_dotenv()

def find_milkman_codes():
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    client = ShopifyClient(store, token, version)

    date_max = datetime.now()
    date_min = date_max - timedelta(days=730)

    print("Searching for Modern Milkman related codes...")
    orders = list(client.get_orders(created_at_min=date_min, created_at_max=date_max, status="any"))

    # Track all codes containing milkman or modern
    milkman_codes = defaultdict(list)

    for order in orders:
        discount_codes = order.get('discount_codes', [])
        for dc in discount_codes:
            code = dc.get('code', '').lower()
            if 'milkman' in code or 'modern' in code or 'mm20' in code or 'mm10' in code:
                customer = order.get('customer') or {}
                customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Guest"
                milkman_codes[dc.get('code', '')].append({
                    'order': order.get('name'),
                    'date': order.get('created_at', '')[:10],
                    'total': float(order.get('total_price', 0)),
                    'discount': float(dc.get('amount', 0)),
                    'customer': customer_name,
                    'email': customer.get('email', ''),
                    'orders_count': customer.get('orders_count', 1),
                })

    if not milkman_codes:
        print("\nNo Modern Milkman related codes found.")
        return

    print(f"\nFound {len(milkman_codes)} Modern Milkman related code(s):\n")
    print("=" * 80)

    total_orders = 0
    total_revenue = 0
    total_discount = 0

    for code, usages in sorted(milkman_codes.items()):
        print(f"\nCode: {code}")
        print("-" * 40)
        code_revenue = sum(u['total'] for u in usages)
        code_discount = sum(u['discount'] for u in usages)
        total_orders += len(usages)
        total_revenue += code_revenue
        total_discount += code_discount

        print(f"Uses: {len(usages)} | Revenue: £{code_revenue:,.2f} | Discount: £{code_discount:,.2f}")
        print()
        for u in usages:
            new_flag = "NEW" if u['orders_count'] == 1 else f"{u['orders_count']} orders"
            print(f"  {u['order']:<14} {u['date']}  £{u['total']:>7.2f}  {u['customer']:<25} ({new_flag})")

    print("\n" + "=" * 80)
    print(f"TOTAL: {total_orders} orders | £{total_revenue:,.2f} revenue | £{total_discount:,.2f} discount given")

if __name__ == "__main__":
    find_milkman_codes()
