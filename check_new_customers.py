#!/usr/bin/env python3
"""Check if customers from modernmilkman20 orders are new or returning."""

import os
from dotenv import load_dotenv
from shopify_client import ShopifyClient
from datetime import datetime, timedelta

load_dotenv()

def check_new_customers():
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    client = ShopifyClient(store, token, version)

    # Fetch all orders from the last 2 years
    date_max = datetime.now()
    date_min = date_max - timedelta(days=730)

    orders = list(client.get_orders(created_at_min=date_min, created_at_max=date_max, status="any"))

    # Find modernmilkman20 orders and their customers
    modernmilkman_customers = {}
    for order in orders:
        discount_codes = order.get('discount_codes', [])
        for dc in discount_codes:
            if dc.get('code', '').lower() == 'modernmilkman20':
                customer = order.get('customer', {})
                customer_id = customer.get('id')
                if customer_id:
                    customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                    customer_email = customer.get('email', '')
                    modernmilkman_customers[customer_id] = {
                        'name': customer_name,
                        'email': customer_email,
                        'order_name': order.get('name'),
                        'order_date': order.get('created_at', '')[:10],
                        'orders_count': customer.get('orders_count', 1)
                    }
                break

    print("modernmilkman20 Customer Analysis")
    print("=" * 70)

    new_customers = 0
    returning_customers = 0

    for customer_id, info in modernmilkman_customers.items():
        # Count how many orders this customer has in our data
        customer_orders = [o for o in orders if (o.get('customer') or {}).get('id') == customer_id]
        total_orders = len(customer_orders)

        # Check orders_count from Shopify (lifetime orders)
        lifetime_orders = info['orders_count']

        is_new = lifetime_orders == 1 or total_orders == 1
        status = "NEW" if is_new else "RETURNING"

        if is_new:
            new_customers += 1
        else:
            returning_customers += 1

        print(f"{info['order_name']:<14} {info['name']:<25} {status:<10} (Lifetime orders: {lifetime_orders})")

    print("-" * 70)
    print(f"New customers: {new_customers}")
    print(f"Returning customers: {returning_customers}")

if __name__ == "__main__":
    check_new_customers()
