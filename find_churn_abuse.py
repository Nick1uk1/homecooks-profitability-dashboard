#!/usr/bin/env python3
"""Find customers who cancel/rejoin frequently or may be pretending to be new."""

import os
from dotenv import load_dotenv
from shopify_client import ShopifyClient
from datetime import datetime, timedelta
from collections import defaultdict

load_dotenv()

def analyze_customers():
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    client = ShopifyClient(store, token, version)

    # Fetch all orders from the last 2 years
    date_max = datetime.now()
    date_min = date_max - timedelta(days=730)

    print("Fetching orders...")
    orders = list(client.get_orders(created_at_min=date_min, created_at_max=date_max, status="any"))
    print(f"Found {len(orders)} orders\n")

    # Track customers by various identifiers
    customers_by_email = defaultdict(list)
    customers_by_name = defaultdict(list)
    customers_by_address = defaultdict(list)
    customers_by_phone = defaultdict(list)

    # Track discount code usage
    new_customer_codes = ['welcome', 'new', 'first', 'intro', 'modernmilkman', 'friend', 'refer']
    discount_usage = defaultdict(list)

    for order in orders:
        customer = order.get('customer') or {}
        customer_id = customer.get('id')
        email = (customer.get('email') or '').lower().strip()
        first_name = (customer.get('first_name') or '').lower().strip()
        last_name = (customer.get('last_name') or '').lower().strip()
        full_name = f"{first_name} {last_name}".strip()
        phone = (customer.get('phone') or '').replace(' ', '').replace('-', '')

        shipping = order.get('shipping_address') or {}
        address1 = (shipping.get('address1') or '').lower().strip()
        postcode = (shipping.get('zip') or '').upper().replace(' ', '')
        address_key = f"{address1}|{postcode}" if address1 and postcode else None

        order_info = {
            'order_name': order.get('name'),
            'order_date': order.get('created_at', '')[:10],
            'total': float(order.get('total_price', 0)),
            'email': email,
            'name': full_name,
            'customer_id': customer_id,
            'discount_codes': [dc.get('code', '').lower() for dc in order.get('discount_codes', [])],
            'address': address_key,
            'phone': phone,
        }

        if email:
            customers_by_email[email].append(order_info)
        if full_name and len(full_name) > 3:
            customers_by_name[full_name].append(order_info)
        if address_key and len(address_key) > 10:
            customers_by_address[address_key].append(order_info)
        if phone and len(phone) > 8:
            customers_by_phone[phone].append(order_info)

        # Track new customer discount usage
        for dc in order_info['discount_codes']:
            for keyword in new_customer_codes:
                if keyword in dc:
                    discount_usage[email or full_name].append({
                        'code': dc,
                        'order': order.get('name'),
                        'date': order.get('created_at', '')[:10],
                    })
                    break

    # Find potential issues
    print("=" * 80)
    print("POTENTIAL DUPLICATE ACCOUNTS (Same address, different email)")
    print("=" * 80)

    duplicates_found = False
    for address, orders_list in customers_by_address.items():
        emails = set(o['email'] for o in orders_list if o['email'])
        if len(emails) > 1:
            duplicates_found = True
            print(f"\nAddress: {address}")
            for email in emails:
                email_orders = [o for o in orders_list if o['email'] == email]
                names = set(o['name'] for o in email_orders)
                print(f"  Email: {email}")
                print(f"    Names: {', '.join(names)}")
                print(f"    Orders: {len(email_orders)}")
                for o in email_orders[-3:]:  # Show last 3 orders
                    codes = ', '.join(o['discount_codes']) if o['discount_codes'] else 'none'
                    print(f"      {o['order_name']} ({o['order_date']}) £{o['total']:.2f} - codes: {codes}")

    if not duplicates_found:
        print("No duplicate accounts found")

    print("\n" + "=" * 80)
    print("CUSTOMERS USING MULTIPLE 'NEW CUSTOMER' DISCOUNT CODES")
    print("=" * 80)

    multi_discount_found = False
    for customer, usages in discount_usage.items():
        if len(usages) > 1:
            multi_discount_found = True
            print(f"\n{customer}:")
            for u in usages:
                print(f"  {u['order']} ({u['date']}) - Code: {u['code']}")

    if not multi_discount_found:
        print("No customers found using multiple new customer codes")

    print("\n" + "=" * 80)
    print("SAME PHONE NUMBER, DIFFERENT EMAILS")
    print("=" * 80)

    phone_dups_found = False
    for phone, orders_list in customers_by_phone.items():
        if not phone:
            continue
        emails = set(o['email'] for o in orders_list if o['email'])
        if len(emails) > 1:
            phone_dups_found = True
            print(f"\nPhone: {phone}")
            for email in emails:
                email_orders = [o for o in orders_list if o['email'] == email]
                print(f"  {email}: {len(email_orders)} orders")

    if not phone_dups_found:
        print("No phone duplicates found")

    print("\n" + "=" * 80)
    print("HIGH-FREQUENCY ORDERERS (potential subscription churn patterns)")
    print("=" * 80)

    # Look for gaps in ordering patterns that might indicate cancel/rejoin
    for email, orders_list in customers_by_email.items():
        if len(orders_list) < 4:
            continue

        # Sort by date
        sorted_orders = sorted(orders_list, key=lambda x: x['order_date'])

        # Calculate gaps between orders
        gaps = []
        for i in range(1, len(sorted_orders)):
            date1 = datetime.strptime(sorted_orders[i-1]['order_date'], '%Y-%m-%d')
            date2 = datetime.strptime(sorted_orders[i]['order_date'], '%Y-%m-%d')
            gap_days = (date2 - date1).days
            gaps.append(gap_days)

        # Look for irregular patterns (some short gaps, some long gaps > 60 days)
        short_gaps = [g for g in gaps if g < 21]
        long_gaps = [g for g in gaps if g > 60]

        if short_gaps and long_gaps:
            name = sorted_orders[0]['name']
            print(f"\n{name} ({email})")
            print(f"  Total orders: {len(orders_list)}")
            print(f"  Order pattern (days between orders): {gaps}")
            print(f"  Possible cancel/rejoin: {len(long_gaps)} gap(s) > 60 days")

            # Check discount codes used
            all_codes = []
            for o in sorted_orders:
                all_codes.extend(o['discount_codes'])
            if all_codes:
                print(f"  Discount codes used: {', '.join(set(all_codes))}")

if __name__ == "__main__":
    analyze_customers()
