"""
Shopify Order Profitability Dashboard
Uses Linnworks for accurate dispatch dates (Monday/Thursday)
"""

import os
import base64
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from typing import List

from shopify_client import ShopifyClient
from costing import CostingService, PACKAGING_COSTS, get_packaging_totals
from linnworks_client import LinnworksClient, get_dispatch_info
from metrics import (
    process_orders,
    filter_by_weekday,
    create_orders_dataframe,
    create_weekly_summary,
    calculate_kpis,
    OrderMetrics,
)


# HomeCooks Brand Colors
HC_DARK_TEAL = "#1a5d5e"
HC_MEDIUM_TEAL = "#5fa8b8"
HC_LIGHT_MINT = "#b8e0d4"
HC_WHITE = "#ffffff"
HC_CREAM = "#f5f5f0"

# Retail Profitability Cost Assumptions
RETAIL_COSTS = {
    'freight_per_unit': 0.14,
    'freight_per_case': 0.66,
    'case_picking_rate': 0.14,
    'order_processing_fee': 1.09,
    'order_tracking_fee': 0.27,
    'case_labelling': 0.00,
    'joe_commission_pct': 0.10,  # 10%
    'sku_case_cost': 0.10,
    'sleeve_x6': 0.67,
    'case_production_cost': 15.48,
}

# Delivery Cost Lookup Table (by number of cases)
DELIVERY_COSTS = {
    1: 24.00, 2: 24.00, 3: 24.00, 4: 24.00, 5: 24.00, 6: 24.00,
    7: 26.95, 8: 30.80, 9: 30.80, 10: 31.50,
    11: 34.65, 12: 37.80, 13: 40.95, 14: 44.10, 15: 47.25,
    16: 48.00, 17: 48.45, 18: 51.30, 19: 54.15, 20: 57.00,
    21: 57.75, 22: 60.50, 23: 63.25, 24: 66.00, 25: 68.75,
    26: 68.75, 27: 68.75, 28: 70.00, 29: 72.50, 30: 75.00,
    31: 77.50, 32: 80.00, 33: 82.50, 34: 85.00, 35: 87.50,
    36: 87.50, 37: 87.50, 38: 89.30, 39: 91.65, 40: 94.00,
    41: 96.35, 42: 98.70, 43: 101.05, 44: 103.40, 45: 105.75,
    46: 108.10, 47: 110.45, 48: 112.80, 49: 115.15, 50: 117.50,
    51: 109.65, 52: 111.80, 53: 113.95, 54: 116.10, 55: 118.25,
    56: 120.40, 57: 122.55, 58: 124.70, 59: 126.85, 60: 129.00,
}


def get_delivery_cost(num_cases: int) -> float:
    """Get delivery cost based on number of cases."""
    if num_cases <= 0:
        return 0.0
    if num_cases in DELIVERY_COSTS:
        return DELIVERY_COSTS[num_cases]
    # For cases > 60, extrapolate based on last known values
    if num_cases > 60:
        # Approximate: use £2.15 per case above 60
        return DELIVERY_COSTS[60] + (num_cases - 60) * 2.15
    return 0.0


def calculate_retail_profitability(revenue: float, num_cases: int, num_units: int) -> dict:
    """
    Calculate retail order profitability based on cost assumptions.

    Args:
        revenue: Total order revenue
        num_cases: Number of cases in order (typically = quantity for retail)
        num_units: Number of individual units

    Returns:
        Dict with cost breakdown and profit
    """
    c = RETAIL_COSTS

    # Per-order costs
    order_costs = c['order_processing_fee'] + c['order_tracking_fee']

    # Per-case costs (excluding delivery which uses lookup)
    case_costs = num_cases * (
        c['freight_per_case'] +
        c['case_picking_rate'] +
        c['case_labelling'] +
        c['sku_case_cost'] +
        c['sleeve_x6']
    )

    # COGS (case production cost)
    cogs = num_cases * c['case_production_cost']

    # Per-unit costs
    unit_costs = num_units * c['freight_per_unit']

    # Delivery cost (from lookup table)
    delivery_cost = get_delivery_cost(num_cases)

    # Commission
    commission = revenue * c['joe_commission_pct']

    # Total costs
    total_costs = order_costs + case_costs + cogs + unit_costs + delivery_cost + commission

    # Profit
    profit = revenue - total_costs
    margin_pct = (profit / revenue * 100) if revenue > 0 else 0

    return {
        'revenue': revenue,
        'cogs': cogs,
        'order_costs': order_costs,
        'case_costs': case_costs,
        'unit_costs': unit_costs,
        'delivery_cost': delivery_cost,
        'commission': commission,
        'total_costs': total_costs,
        'profit': profit,
        'margin_pct': margin_pct,
    }


# Page config
st.set_page_config(
    page_title="HomeCooks Profitability",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS with HomeCooks branding
st.markdown(f"""
<style>
    .main-header {{
        background: {HC_DARK_TEAL};
        padding: 15px 20px;
        border-radius: 12px;
        margin-bottom: 15px;
        text-align: center;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 15px;
    }}
    .main-header h1 {{
        color: {HC_WHITE};
        margin: 0;
        font-size: 1.6em;
    }}
    .main-header p {{
        color: {HC_LIGHT_MINT};
        margin: 5px 0 0 0;
        font-size: 0.9em;
    }}
    .main-header img {{
        height: 50px;
        border-radius: 8px;
    }}
    .status-bar {{
        background: {HC_LIGHT_MINT};
        padding: 10px 15px;
        border-radius: 8px;
        border-left: 4px solid {HC_DARK_TEAL};
        margin: 10px 0;
        font-size: 0.9em;
        color: #1a1a1a;
    }}
    .assumptions-box {{
        background: {HC_CREAM};
        padding: 15px;
        border-radius: 10px;
        border: 1px solid {HC_MEDIUM_TEAL};
        margin: 10px 0;
        font-size: 0.85em;
        color: #333333;
    }}
    .assumptions-box h4 {{
        color: {HC_DARK_TEAL};
        margin: 0 0 10px 0;
    }}
    .assumptions-box table {{
        color: #333333;
    }}
</style>
""", unsafe_allow_html=True)


def check_env_vars() -> tuple[bool, List[str]]:
    missing = []
    if not os.environ.get("SHOPIFY_STORE_DOMAIN"):
        missing.append("SHOPIFY_STORE_DOMAIN")
    if not os.environ.get("SHOPIFY_ACCESS_TOKEN"):
        missing.append("SHOPIFY_ACCESS_TOKEN")
    return len(missing) == 0, missing


def format_currency(value: float) -> str:
    return f"£{value:,.2f}"


def get_week_date_range(iso_week: str) -> str:
    try:
        year, week = iso_week.split("-W")
        year, week = int(year), int(week)
        jan4 = date(year, 1, 4)
        start_of_week1 = jan4 - timedelta(days=jan4.weekday())
        monday = start_of_week1 + timedelta(weeks=week-1)
        sunday = monday + timedelta(days=6)
        return f"{monday.day} {monday.strftime('%b')} - {sunday.day} {sunday.strftime('%b')}"
    except:
        return ""


def get_logo_base64():
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.jpeg")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_shopify_orders(store_domain: str, access_token: str, api_version: str,
                          date_min: datetime, date_max: datetime) -> List[dict]:
    client = ShopifyClient(store_domain, access_token, api_version)
    return list(client.get_orders(created_at_min=date_min, created_at_max=date_max, status="any"))


@st.cache_data(ttl=300, show_spinner=False)
def fetch_shopify_orders_by_ids(store_domain: str, access_token: str, api_version: str,
                                 order_ids: tuple) -> List[dict]:
    """Fetch specific Shopify orders by their IDs."""
    import requests

    client = ShopifyClient(store_domain, access_token, api_version)
    orders = []

    # Shopify allows up to 50 IDs per request
    batch_size = 50
    id_list = list(order_ids)

    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        ids_param = ",".join(str(oid) for oid in batch)

        url = f"{client.base_url}/orders.json"
        params = {
            "ids": ids_param,
            "status": "any",
            "fields": "id,name,created_at,processed_at,total_price,total_discounts,"
                      "subtotal_price,total_shipping_price_set,total_tax,currency,"
                      "current_subtotal_price,current_total_discounts,line_items,fulfillments,"
                      "discount_codes,discount_applications,customer,shipping_address,billing_address",
        }

        response = client._get_with_rate_limit(url, params)
        if response.status_code == 200:
            data = response.json()
            orders.extend(data.get("orders", []))

    return orders


@st.cache_data(ttl=300, show_spinner=False)
def fetch_linnworks_orders(date_min: datetime, date_max: datetime) -> List[dict]:
    client = LinnworksClient()
    if client.authenticate():
        return client.get_processed_orders(date_min, date_max)
    return []


@st.cache_data(ttl=600, show_spinner=False)
def fetch_all_retail_orders() -> List[dict]:
    """Fetch ALL historic retail orders from Linnworks (No Shipping Required)."""
    import requests
    from datetime import datetime, timedelta

    client = LinnworksClient()
    if not client.authenticate():
        return []

    # Fetch orders from the last 2 years for comprehensive store history
    date_max = datetime.now()
    date_min = date_max - timedelta(days=730)

    all_orders = client.get_processed_orders(date_min, date_max)

    # Filter for "No Shipping Required"
    retail_summary = [o for o in all_orders if 'no shipping' in (o.get('PostalServiceName') or '').lower()]

    if not retail_summary:
        return []

    # Get full details
    url = f"{client.server}/api/Orders/GetOrdersById"
    headers = {'Authorization': client.session_token, 'Content-Type': 'application/json'}

    retail_orders = []
    batch_size = 50

    for i in range(0, len(retail_summary), batch_size):
        batch = retail_summary[i:i+batch_size]
        pk_ids = [o.get('pkOrderID') for o in batch]

        resp = requests.post(url, headers=headers, json={'pkOrderIds': pk_ids})
        if resp.status_code == 200:
            details = resp.json()

            for detail in details:
                customer = detail.get('CustomerInfo', {})
                address = customer.get('Address', {})
                general = detail.get('GeneralInfo', {})
                totals = detail.get('TotalsInfo', {})
                items = detail.get('Items', [])

                name = address.get('FullName', '')
                company = address.get('Company', '')

                if company and name:
                    store = f"{company} ({name})" if company.lower() != name.lower() else company
                elif company:
                    store = company
                elif name:
                    store = name
                else:
                    store = "Unknown"

                retail_orders.append({
                    'store': store,
                    'ref': general.get('SecondaryReference', general.get('ReferenceNum', '')),
                    'processed': detail.get('ProcessedDateTime', '')[:10] if detail.get('ProcessedDateTime') else '',
                    'num_items': len(items),
                    'qty': sum(item.get('Quantity', 0) for item in items),
                    'total': float(totals.get('TotalCharge', 0)),
                    'skus': ', '.join(set(item.get('SKU', '') for item in items[:5])),
                })

    return retail_orders


def get_store_name(order: dict) -> str:
    """Extract store name from Linnworks order - blend name and company."""
    name = (order.get('cFullName') or '').strip()
    company = (order.get('cCompany') or '').strip()

    # If both exist and are different, combine them
    if name and company:
        if name.lower() == company.lower():
            return name
        else:
            return f"{company} ({name})"
    elif company:
        return company
    elif name:
        return name
    else:
        return "Unknown Store"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_retail_order_details(date_min: datetime, date_max: datetime) -> List[dict]:
    """Fetch retail order details from Linnworks (No Shipping Required)."""
    import requests

    client = LinnworksClient()
    if not client.authenticate():
        return []

    # Get processed orders
    all_orders = client.get_processed_orders(date_min, date_max)

    # Filter for "No Shipping Required"
    retail_summary = [o for o in all_orders if 'no shipping' in (o.get('PostalServiceName') or '').lower()]

    if not retail_summary:
        return []

    # Get full details
    url = f"{client.server}/api/Orders/GetOrdersById"
    headers = {'Authorization': client.session_token, 'Content-Type': 'application/json'}

    retail_orders = []
    batch_size = 50

    for i in range(0, len(retail_summary), batch_size):
        batch = retail_summary[i:i+batch_size]
        pk_ids = [o.get('pkOrderID') for o in batch]

        resp = requests.post(url, headers=headers, json={'pkOrderIds': pk_ids})
        if resp.status_code == 200:
            details = resp.json()

            for detail in details:
                customer = detail.get('CustomerInfo', {})
                address = customer.get('Address', {})
                general = detail.get('GeneralInfo', {})
                totals = detail.get('TotalsInfo', {})
                items = detail.get('Items', [])

                name = address.get('FullName', '')
                company = address.get('Company', '')

                if company and name:
                    store = f"{company} ({name})" if company.lower() != name.lower() else company
                elif company:
                    store = company
                elif name:
                    store = name
                else:
                    store = "Unknown"

                retail_orders.append({
                    'store': store,
                    'ref': general.get('SecondaryReference', general.get('ReferenceNum', '')),
                    'processed': detail.get('ProcessedDateTime', '')[:10] if detail.get('ProcessedDateTime') else '',
                    'num_items': len(items),
                    'qty': sum(item.get('Quantity', 0) for item in items),
                    'total': float(totals.get('TotalCharge', 0)),
                    'skus': ', '.join(set(item.get('SKU', '') for item in items[:5])),
                })

    return retail_orders


def normalize_store_name(name: str) -> str:
    """Normalize store name to help identify duplicates."""
    if not name:
        return "unknown"
    # Lowercase, strip, remove common variations
    normalized = name.lower().strip()
    # Remove common suffixes/prefixes
    for suffix in [' ltd', ' limited', ' plc', ' inc', ' llc', ' store', ' shop']:
        normalized = normalized.replace(suffix, '')
    # Remove punctuation and extra spaces
    normalized = ''.join(c if c.isalnum() or c == ' ' else '' for c in normalized)
    normalized = ' '.join(normalized.split())
    return normalized


def is_excluded_store(store_name):
    """Check if store should be excluded from profitability calculations."""
    store_lower = (store_name or '').lower()
    return 'go puff' in store_lower or 'gopuff' in store_lower or 'on the rocks' in store_lower


def calculate_period_profitability(df_period):
    """Calculate total profitability for a period's orders (excluding Go Puff/On the Rocks)."""
    if df_period.empty:
        return {'revenue': 0, 'profit': 0, 'margin_pct': 0, 'orders': 0}

    # Filter out excluded stores
    df_eligible = df_period[~df_period['Store'].apply(is_excluded_store)]

    if df_eligible.empty:
        return {'revenue': 0, 'profit': 0, 'margin_pct': 0, 'orders': 0}

    total_revenue = 0
    total_profit = 0

    for _, row in df_eligible.iterrows():
        revenue = row['Total']
        num_cases = int(row['Qty'])
        num_units = int(row['Qty'])

        prof = calculate_retail_profitability(revenue, num_cases, num_units)
        total_revenue += revenue
        total_profit += prof['profit']

    margin_pct = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

    return {
        'revenue': total_revenue,
        'profit': total_profit,
        'margin_pct': margin_pct,
        'orders': len(df_eligible)
    }


def render_retail_dashboard(date_min, date_max, date_start, date_end):
    """Render the Retail dashboard - orders with 'No Shipping Required' from Linnworks."""
    try:
        # Fetch ALL-TIME retail orders for store summary
        with st.spinner("Loading all retail orders from Linnworks..."):
            all_retail_orders = fetch_all_retail_orders()

        # Also fetch date-filtered orders for monthly breakdown
        filtered_retail_orders = fetch_retail_order_details(date_min, date_max)

        # Add manual order for Go Puff (chilled)
        manual_order = {
            'store': 'Go Puff (chilled)',
            'ref': 'MANUAL-GP-001',
            'processed': datetime.now().strftime('%Y-%m-%d'),
            'num_items': 1,
            'qty': 100,  # Estimated cases
            'total': 12784.00,
            'skus': 'Various',
        }
        all_retail_orders.append(manual_order)
        filtered_retail_orders.append(manual_order)

        if not all_retail_orders:
            st.info("No retail orders found.")
            return

        # Create DataFrames
        df_all = pd.DataFrame(all_retail_orders)
        df_all.columns = ['Store', 'Reference', 'Date', 'Items', 'Qty', 'Total', 'SKUs']
        df_all['Date'] = pd.to_datetime(df_all['Date'], errors='coerce')

        # Calculate MTD, YTD, LFL, vs Last Month
        today = datetime.now()
        current_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_year_start = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # Last month same period
        if today.month == 1:
            last_month_start = today.replace(year=today.year-1, month=12, day=1)
            last_month_same_day = today.replace(year=today.year-1, month=12, day=min(today.day, 31))
        else:
            last_month_start = today.replace(month=today.month-1, day=1)
            # Handle months with fewer days
            import calendar
            last_month_days = calendar.monthrange(today.year, today.month-1)[1]
            last_month_same_day = today.replace(month=today.month-1, day=min(today.day, last_month_days))

        # Last year same period (LFL) - same month, 1st to same day
        last_year_month_start = today.replace(year=today.year-1, month=today.month, day=1, hour=0, minute=0, second=0, microsecond=0)
        # Handle leap year edge case
        try:
            last_year_same_day = today.replace(year=today.year-1)
        except ValueError:
            # Feb 29 in leap year -> Feb 28
            last_year_same_day = today.replace(year=today.year-1, day=28)

        # Filter data for each period
        df_mtd = df_all[(df_all['Date'] >= current_month_start) & (df_all['Date'] <= today)]
        df_ytd = df_all[(df_all['Date'] >= current_year_start) & (df_all['Date'] <= today)]

        # Last month same period (1st to same day of month)
        df_last_month = df_all[(df_all['Date'] >= last_month_start) & (df_all['Date'] <= last_month_same_day)]

        # Last year same month period (LFL) - 1st to same day of same month last year
        df_lfl = df_all[(df_all['Date'] >= last_year_month_start) & (df_all['Date'] <= last_year_same_day)]

        # YTD last year for comparison
        last_year_ytd_start = current_year_start.replace(year=today.year-1)
        try:
            last_year_ytd_end = today.replace(year=today.year-1)
        except ValueError:
            last_year_ytd_end = today.replace(year=today.year-1, day=28)
        df_ytd_lfl = df_all[(df_all['Date'] >= last_year_ytd_start) & (df_all['Date'] <= last_year_ytd_end)]

        # Calculate revenue metrics
        mtd_revenue = df_mtd['Total'].sum()
        mtd_orders = len(df_mtd)
        ytd_revenue = df_ytd['Total'].sum()

        last_month_revenue = df_last_month['Total'].sum()
        lfl_revenue = df_lfl['Total'].sum()
        ytd_lfl_revenue = df_ytd_lfl['Total'].sum()

        # Calculate profitability for each period
        mtd_profit_data = calculate_period_profitability(df_mtd)
        ytd_profit_data = calculate_period_profitability(df_ytd)
        last_month_profit_data = calculate_period_profitability(df_last_month)
        lfl_profit_data = calculate_period_profitability(df_lfl)
        ytd_lfl_profit_data = calculate_period_profitability(df_ytd_lfl)

        # Calculate revenue variances
        vs_last_month = mtd_revenue - last_month_revenue
        vs_last_month_pct = ((mtd_revenue / last_month_revenue - 1) * 100) if last_month_revenue > 0 else 0
        vs_lfl = mtd_revenue - lfl_revenue
        vs_lfl_pct = ((mtd_revenue / lfl_revenue - 1) * 100) if lfl_revenue > 0 else 0

        # Calculate profitability variances
        mtd_profit_vs_lm = mtd_profit_data['profit'] - last_month_profit_data['profit']
        mtd_profit_vs_lm_pct = ((mtd_profit_data['profit'] / last_month_profit_data['profit'] - 1) * 100) if last_month_profit_data['profit'] > 0 else 0
        mtd_profit_vs_lfl = mtd_profit_data['profit'] - lfl_profit_data['profit']
        mtd_profit_vs_lfl_pct = ((mtd_profit_data['profit'] / lfl_profit_data['profit'] - 1) * 100) if lfl_profit_data['profit'] > 0 else 0

        ytd_profit_vs_lfl = ytd_profit_data['profit'] - ytd_lfl_profit_data['profit']
        ytd_profit_vs_lfl_pct = ((ytd_profit_data['profit'] / ytd_lfl_profit_data['profit'] - 1) * 100) if ytd_lfl_profit_data['profit'] > 0 else 0

        # Status bar
        st.markdown(f"""
        <div class="status-bar">
            <strong>All-time: {len(all_retail_orders)} retail orders</strong> |
            Selected period ({date_start.strftime('%d/%m/%Y')} - {date_end.strftime('%d/%m/%Y')}): {len(filtered_retail_orders)} orders
        </div>
        """, unsafe_allow_html=True)

        # KPI Row 1 - MTD Revenue and Profitability
        st.markdown("### Month to Date Performance")
        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            f"MTD Revenue ({today.strftime('%b')})",
            format_currency(mtd_revenue),
            f"{vs_last_month_pct:+.1f}% vs Last Month" if last_month_revenue > 0 else None
        )
        col2.metric(
            f"MTD Profit ({today.strftime('%b')})",
            format_currency(mtd_profit_data['profit']),
            f"{mtd_profit_vs_lm_pct:+.1f}% vs Last Month" if last_month_profit_data['profit'] > 0 else None,
            delta_color="normal" if mtd_profit_vs_lm >= 0 else "inverse"
        )
        col3.metric(
            "MTD Margin",
            f"{mtd_profit_data['margin_pct']:.1f}%",
            f"{mtd_profit_data['margin_pct'] - last_month_profit_data['margin_pct']:+.1f}pp" if last_month_profit_data['margin_pct'] > 0 else None
        )
        col4.metric(
            "MTD Orders",
            f"{mtd_orders:,}",
            f"{len(df_mtd) - len(df_last_month):+d} vs Last Month" if len(df_last_month) > 0 else None
        )

        # KPI Row 2 - YTD Revenue and Profitability
        st.markdown("### Year to Date Performance")
        col1, col2, col3, col4 = st.columns(4)

        ytd_vs_lfl_pct = ((ytd_revenue / ytd_lfl_revenue - 1) * 100) if ytd_lfl_revenue > 0 else 0

        col1.metric(
            "YTD Revenue",
            format_currency(ytd_revenue),
            f"{ytd_vs_lfl_pct:+.1f}% vs LFL" if ytd_lfl_revenue > 0 else None,
            delta_color="normal" if ytd_revenue >= ytd_lfl_revenue else "inverse"
        )
        col2.metric(
            "YTD Profit",
            format_currency(ytd_profit_data['profit']),
            f"{ytd_profit_vs_lfl_pct:+.1f}% vs LFL" if ytd_lfl_profit_data['profit'] > 0 else None,
            delta_color="normal" if ytd_profit_vs_lfl >= 0 else "inverse"
        )
        col3.metric(
            "YTD Margin",
            f"{ytd_profit_data['margin_pct']:.1f}%",
            f"{ytd_profit_data['margin_pct'] - ytd_lfl_profit_data['margin_pct']:+.1f}pp" if ytd_lfl_profit_data['margin_pct'] > 0 else None
        )
        col4.metric(
            "Unique Stores (All-Time)",
            df_all['Store'].nunique()
        )

        # KPI Row 3 - Revenue Variances
        st.markdown("### Revenue Variance Analysis")
        col1, col2, col3, col4 = st.columns(4)

        vs_lm_color = "normal" if vs_last_month >= 0 else "inverse"
        vs_lfl_color = "normal" if vs_lfl >= 0 else "inverse"

        col1.metric(
            "vs Last Month (Same Period)",
            format_currency(vs_last_month),
            f"{vs_last_month_pct:+.1f}%",
            delta_color=vs_lm_color
        )
        col2.metric(
            f"Last Month ({last_month_start.strftime('%b')} 1-{last_month_same_day.day})",
            format_currency(last_month_revenue),
            f"{len(df_last_month)} orders"
        )
        col3.metric(
            "vs LFL (Same Period Last Year)",
            format_currency(vs_lfl),
            f"{vs_lfl_pct:+.1f}%",
            delta_color=vs_lfl_color
        )
        col4.metric(
            f"LFL ({last_year_month_start.strftime('%b %Y')} 1-{last_year_same_day.day})",
            format_currency(lfl_revenue),
            f"{len(df_lfl)} orders"
        )

        # KPI Row 4 - Profitability Variances
        st.markdown("### Profitability Variance Analysis")
        st.caption("*Excludes Go Puff and On the Rocks orders*")
        col1, col2, col3, col4 = st.columns(4)

        profit_vs_lm_color = "normal" if mtd_profit_vs_lm >= 0 else "inverse"
        profit_vs_lfl_color = "normal" if mtd_profit_vs_lfl >= 0 else "inverse"

        col1.metric(
            "Profit vs Last Month",
            format_currency(mtd_profit_vs_lm),
            f"{mtd_profit_vs_lm_pct:+.1f}%",
            delta_color=profit_vs_lm_color
        )
        col2.metric(
            f"Last Month Profit ({last_month_start.strftime('%b')} 1-{last_month_same_day.day})",
            format_currency(last_month_profit_data['profit']),
            f"{last_month_profit_data['margin_pct']:.1f}% margin"
        )
        col3.metric(
            "Profit vs LFL",
            format_currency(mtd_profit_vs_lfl),
            f"{mtd_profit_vs_lfl_pct:+.1f}%",
            delta_color=profit_vs_lfl_color
        )
        col4.metric(
            f"LFL Profit ({last_year_month_start.strftime('%b %Y')} 1-{last_year_same_day.day})",
            format_currency(lfl_profit_data['profit']),
            f"{lfl_profit_data['margin_pct']:.1f}% margin"
        )

        # Monthly breakdown section - using filtered data
        st.markdown("---")
        st.markdown("### Revenue by Month")
        st.caption(f"Showing data for selected period: {date_start.strftime('%d/%m/%Y')} - {date_end.strftime('%d/%m/%Y')}")

        if filtered_retail_orders:
            df_filtered = pd.DataFrame(filtered_retail_orders)
            df_filtered.columns = ['Store', 'Reference', 'Date', 'Items', 'Qty', 'Total', 'SKUs']
            df_filtered['Date'] = pd.to_datetime(df_filtered['Date'], errors='coerce')
            df_filtered['Month'] = df_filtered['Date'].dt.to_period('M')

            monthly_summary = df_filtered.groupby('Month').agg({
                'Reference': 'count',
                'Qty': 'sum',
                'Total': 'sum'
            }).reset_index()
            monthly_summary.columns = ['Month', 'Orders', 'Units Ordered', 'Revenue']
            monthly_summary = monthly_summary.sort_values('Month', ascending=False)

            # Display monthly cards
            num_months = len(monthly_summary)
            if num_months > 0:
                month_cols = st.columns(min(num_months, 6))
                for idx, row in monthly_summary.iterrows():
                    col_idx = list(monthly_summary.index).index(idx) % len(month_cols)
                    month_str = str(row['Month'])
                    with month_cols[col_idx]:
                        st.markdown(f"""
                        <div style="background:{HC_WHITE}; padding:15px; border-radius:10px; border:2px solid {HC_DARK_TEAL}; text-align:center; margin-bottom:10px;">
                            <div style="color:{HC_DARK_TEAL}; font-weight:bold; font-size:1.1em;">{month_str}</div>
                            <div style="color:#333333; margin-top:8px;"><strong>{format_currency(row['Revenue'])}</strong></div>
                            <div style="color:#666666; font-size:0.9em;">{row['Orders']:,} orders</div>
                            <div style="color:{HC_MEDIUM_TEAL}; font-size:0.9em;">{int(row['Units Ordered']):,} units</div>
                        </div>
                        """, unsafe_allow_html=True)

                # Monthly table
                monthly_display = monthly_summary.copy()
                monthly_display['Month'] = monthly_display['Month'].astype(str)
                st.dataframe(
                    monthly_display,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Revenue": st.column_config.NumberColumn(format="£%.2f"),
                    }
                )
        else:
            st.info("No retail orders in the selected date range.")

        # Store summary section - ALL-TIME DATA
        st.markdown("---")
        st.markdown("### All Stores (All-Time)")
        st.caption("Complete history of all retail stores - showing order count and last order date")

        # Group by store with order count and last order date
        store_summary = df_all.groupby('Store').agg({
            'Reference': 'count',
            'Total': 'sum',
            'Qty': 'sum',
            'Date': 'max'
        }).reset_index()
        store_summary.columns = ['Store', 'Orders', 'Revenue', 'Units', 'Last Order']
        store_summary = store_summary.sort_values('Last Order', ascending=False)

        # Format last order date
        store_summary['Last Order'] = store_summary['Last Order'].dt.strftime('%d/%m/%Y')

        # Add normalized name for duplicate detection
        store_summary['Normalized'] = store_summary['Store'].apply(normalize_store_name)

        # Flag potential duplicates
        duplicate_counts = store_summary['Normalized'].value_counts()
        potential_dups = set(duplicate_counts[duplicate_counts > 1].index)
        store_summary['Possible Duplicate'] = store_summary['Normalized'].apply(
            lambda x: '⚠️' if x in potential_dups else ''
        )

        # Display store summary
        display_stores = store_summary[['Store', 'Orders', 'Revenue', 'Units', 'Last Order', 'Possible Duplicate']].copy()

        st.dataframe(
            display_stores,
            hide_index=True,
            use_container_width=True,
            height=400,
            column_config={
                "Revenue": st.column_config.NumberColumn(format="£%.2f"),
                "Last Order": st.column_config.TextColumn("Last Order Date"),
                "Possible Duplicate": st.column_config.TextColumn("Note", width="small"),
            }
        )

        st.caption(f"**{len(store_summary)}** unique store names | ⚠️ indicates possible duplicate store names")

        # Order details - filtered data
        if filtered_retail_orders:
            st.markdown("---")
            st.markdown("### Recent Order Details")
            st.caption(f"Orders from {date_start.strftime('%d/%m/%Y')} - {date_end.strftime('%d/%m/%Y')}")

            # Format date for display
            df_display = df_filtered.copy()
            df_display['Date'] = df_display['Date'].dt.strftime('%d/%m/%Y')

            st.dataframe(
                df_display[['Date', 'Reference', 'Store', 'Items', 'Qty', 'Total']],
                hide_index=True,
                use_container_width=True,
                height=400,
                column_config={
                    "Total": st.column_config.NumberColumn(format="£%.2f"),
                }
            )

        # Profitability Section - Exclude Go Puff and On the Rocks
        st.markdown("---")
        st.markdown("### Order Profitability")
        st.caption("Excludes Go Puff and On the Rocks orders")

        # Filter out Go Puff and On the Rocks for profitability
        df_profit = df_all[~df_all['Store'].apply(is_excluded_store)].copy()

        if not df_profit.empty:
            # Calculate profitability for each order
            # Assume Qty = number of cases for retail orders
            df_profit['Cases'] = df_profit['Qty']
            df_profit['Units'] = df_profit['Qty']  # Adjust if units differ from cases

            # Calculate profitability metrics
            profit_data = []
            for _, row in df_profit.iterrows():
                prof = calculate_retail_profitability(
                    revenue=row['Total'],
                    num_cases=int(row['Cases']),
                    num_units=int(row['Units'])
                )
                profit_data.append({
                    'Store': row['Store'],
                    'Date': row['Date'],
                    'Reference': row['Reference'],
                    'Cases': int(row['Cases']),
                    'Revenue': prof['revenue'],
                    'COGS': prof['cogs'],
                    'Fulfillment': prof['order_costs'] + prof['case_costs'] + prof['unit_costs'],
                    'Delivery': prof['delivery_cost'],
                    'Commission': prof['commission'],
                    'Profit': prof['profit'],
                    'Margin %': prof['margin_pct'],
                })

            df_profit_display = pd.DataFrame(profit_data)

            # Summary KPIs
            total_revenue = df_profit_display['Revenue'].sum()
            total_cogs = df_profit_display['COGS'].sum()
            total_fulfillment = df_profit_display['Fulfillment'].sum()
            total_delivery = df_profit_display['Delivery'].sum()
            total_commission = df_profit_display['Commission'].sum()
            total_profit = df_profit_display['Profit'].sum()
            avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Revenue", format_currency(total_revenue))
            col2.metric("Total COGS", format_currency(total_cogs))
            col3.metric("Total Delivery", format_currency(total_delivery))
            col4.metric("Total Profit", format_currency(total_profit))
            col5.metric("Avg Margin", f"{avg_margin:.1f}%")

            # Profitability by Store
            st.markdown("#### Profitability by Store")
            store_profit = df_profit_display.groupby('Store').agg({
                'Cases': 'sum',
                'Revenue': 'sum',
                'COGS': 'sum',
                'Fulfillment': 'sum',
                'Delivery': 'sum',
                'Commission': 'sum',
                'Profit': 'sum',
            }).reset_index()
            store_profit['Margin %'] = (store_profit['Profit'] / store_profit['Revenue'] * 100).round(1)
            store_profit = store_profit.sort_values('Profit', ascending=False)

            st.dataframe(
                store_profit,
                hide_index=True,
                use_container_width=True,
                height=400,
                column_config={
                    "Cases": st.column_config.NumberColumn(format="%d"),
                    "Revenue": st.column_config.NumberColumn(format="£%.2f"),
                    "COGS": st.column_config.NumberColumn(format="£%.2f"),
                    "Fulfillment": st.column_config.NumberColumn(format="£%.2f"),
                    "Delivery": st.column_config.NumberColumn(format="£%.2f"),
                    "Commission": st.column_config.NumberColumn(format="£%.2f"),
                    "Profit": st.column_config.NumberColumn(format="£%.2f"),
                    "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                }
            )

            # Cost Assumptions
            with st.expander("📊 Profitability Assumptions"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Per-Case & Per-Order Costs**")
                    st.markdown(f"""
| Cost Component | Value |
|----------------|-------|
| Case Production Cost (COGS) | £{RETAIL_COSTS['case_production_cost']:.2f} |
| Freight Per Case | £{RETAIL_COSTS['freight_per_case']:.2f} |
| Freight Per Unit | £{RETAIL_COSTS['freight_per_unit']:.2f} |
| Case Picking Rate | £{RETAIL_COSTS['case_picking_rate']:.2f} |
| Order Processing Fee | £{RETAIL_COSTS['order_processing_fee']:.2f} |
| Order Tracking Fee | £{RETAIL_COSTS['order_tracking_fee']:.2f} |
| SKU Case Cost | £{RETAIL_COSTS['sku_case_cost']:.2f} |
| Sleeve x 6 | £{RETAIL_COSTS['sleeve_x6']:.2f} |
| Joe Commission | {RETAIL_COSTS['joe_commission_pct']*100:.0f}% |
                    """)
                with col2:
                    st.markdown("**Delivery Costs (by case count)**")
                    st.markdown("""
| Cases | Cost | Cases | Cost |
|-------|------|-------|------|
| 1-6 | £24.00 | 21-25 | £57.75-68.75 |
| 7-10 | £26.95-31.50 | 26-30 | £68.75-75.00 |
| 11-15 | £34.65-47.25 | 31-40 | £77.50-94.00 |
| 16-20 | £48.00-57.00 | 41-50 | £96.35-117.50 |
                    """)
                st.caption("*Go Puff and On the Rocks orders are excluded from profitability calculations*")

        else:
            st.info("No orders available for profitability calculation (excluding Go Puff and On the Rocks).")

    except Exception as e:
        st.error(f"Error loading retail data: {e}")
        st.exception(e)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_d2c_orders_for_period(start_date: datetime, end_date: datetime) -> List[dict]:
    """Fetch D2C orders from Linnworks for a specific period."""
    store = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

    client = LinnworksClient()
    if not client.authenticate():
        return []

    linnworks_orders = client.get_processed_orders(start_date, end_date)

    # Filter out retail orders (No Shipping Required)
    d2c_orders = [o for o in linnworks_orders if 'no shipping' not in (o.get('PostalServiceName') or '').lower()]

    if not d2c_orders:
        return []

    # Get dispatch info
    dispatch_info = get_dispatch_info(d2c_orders)

    # Extract Shopify order IDs
    shopify_order_ids = set()
    for order in d2c_orders:
        ref = order.get('ReferenceNum', '').replace('#', '').strip()
        if ref:
            try:
                shopify_order_ids.add(int(ref))
            except ValueError:
                pass

    if not shopify_order_ids:
        return []

    # Fetch Shopify orders
    shopify_client = ShopifyClient(store, token, version)
    shopify_orders = fetch_shopify_orders_by_ids(store, token, version, tuple(sorted(shopify_order_ids)))

    if not shopify_orders:
        return []

    # Process orders
    costing = CostingService(shopify_client)
    processed, _, _ = process_orders(shopify_orders, costing, dispatch_info, lambda *args: None)

    return processed


def calculate_d2c_period_metrics(orders: List) -> dict:
    """Calculate D2C metrics for a period."""
    if not orders:
        return {'revenue': 0, 'profit': 0, 'margin_pct': 0, 'orders': 0, 'cogs': 0, 'discounts': 0}

    total_revenue = sum(o.net_revenue for o in orders)
    total_profit = sum(o.contribution for o in orders)
    total_cogs = sum(o.cogs for o in orders)
    total_discounts = sum(o.total_discounts for o in orders)
    margin_pct = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

    return {
        'revenue': total_revenue,
        'profit': total_profit,
        'margin_pct': margin_pct,
        'orders': len(orders),
        'cogs': total_cogs,
        'discounts': total_discounts,
    }


def render_d2c_dashboard(date_min, date_max, date_start, date_end, day_filter, inc_mon, inc_thu, inc_all):
    """Render the D2C dashboard content - orders by DISPATCH date from Linnworks."""
    try:
        import calendar

        store = os.environ.get("SHOPIFY_STORE_DOMAIN")
        token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        version = os.environ.get("SHOPIFY_API_VERSION", "2024-07")

        # Calculate date ranges for MTD, YTD, Last Month, LFL
        today = datetime.now()
        current_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_year_start = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # Last month same period
        if today.month == 1:
            last_month_start = today.replace(year=today.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_same_day = today.replace(year=today.year-1, month=12, day=min(today.day, 31))
        else:
            last_month_start = today.replace(month=today.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_days = calendar.monthrange(today.year, today.month-1)[1]
            last_month_same_day = today.replace(month=today.month-1, day=min(today.day, last_month_days))

        # Last year same period (LFL)
        last_year_month_start = today.replace(year=today.year-1, month=today.month, day=1, hour=0, minute=0, second=0, microsecond=0)
        try:
            last_year_same_day = today.replace(year=today.year-1)
        except ValueError:
            last_year_same_day = today.replace(year=today.year-1, day=28)

        # YTD last year
        last_year_ytd_start = current_year_start.replace(year=today.year-1)
        try:
            last_year_ytd_end = today.replace(year=today.year-1)
        except ValueError:
            last_year_ytd_end = today.replace(year=today.year-1, day=28)

        # Fetch orders for all periods
        with st.spinner("Loading D2C orders from Linnworks..."):
            # Current period (selected dates)
            linnworks_orders = fetch_linnworks_orders(date_min, date_max)

            # MTD orders
            mtd_orders = fetch_d2c_orders_for_period(current_month_start, today)

            # YTD orders
            ytd_orders = fetch_d2c_orders_for_period(current_year_start, today)

            # Last month same period
            last_month_orders = fetch_d2c_orders_for_period(last_month_start, last_month_same_day)

            # LFL (same month last year)
            lfl_orders = fetch_d2c_orders_for_period(last_year_month_start, last_year_same_day)

            # YTD LFL
            ytd_lfl_orders = fetch_d2c_orders_for_period(last_year_ytd_start, last_year_ytd_end)

        if not linnworks_orders:
            st.warning("No dispatched orders found for selected date range in Linnworks.")
            return

        # Filter out retail orders (No Shipping Required)
        d2c_linnworks = [o for o in linnworks_orders if 'no shipping' not in (o.get('PostalServiceName') or '').lower()]

        if not d2c_linnworks:
            st.warning("No D2C orders found for selected date range (all were retail).")
            return

        # Calculate metrics for each period
        mtd_metrics = calculate_d2c_period_metrics(mtd_orders)
        ytd_metrics = calculate_d2c_period_metrics(ytd_orders)
        last_month_metrics = calculate_d2c_period_metrics(last_month_orders)
        lfl_metrics = calculate_d2c_period_metrics(lfl_orders)
        ytd_lfl_metrics = calculate_d2c_period_metrics(ytd_lfl_orders)

        # Calculate variances
        vs_last_month_rev = mtd_metrics['revenue'] - last_month_metrics['revenue']
        vs_last_month_rev_pct = ((mtd_metrics['revenue'] / last_month_metrics['revenue'] - 1) * 100) if last_month_metrics['revenue'] > 0 else 0
        vs_lfl_rev = mtd_metrics['revenue'] - lfl_metrics['revenue']
        vs_lfl_rev_pct = ((mtd_metrics['revenue'] / lfl_metrics['revenue'] - 1) * 100) if lfl_metrics['revenue'] > 0 else 0

        vs_last_month_profit = mtd_metrics['profit'] - last_month_metrics['profit']
        vs_last_month_profit_pct = ((mtd_metrics['profit'] / last_month_metrics['profit'] - 1) * 100) if last_month_metrics['profit'] > 0 else 0
        vs_lfl_profit = mtd_metrics['profit'] - lfl_metrics['profit']
        vs_lfl_profit_pct = ((mtd_metrics['profit'] / lfl_metrics['profit'] - 1) * 100) if lfl_metrics['profit'] > 0 else 0

        ytd_vs_lfl_rev_pct = ((ytd_metrics['revenue'] / ytd_lfl_metrics['revenue'] - 1) * 100) if ytd_lfl_metrics['revenue'] > 0 else 0
        ytd_vs_lfl_profit = ytd_metrics['profit'] - ytd_lfl_metrics['profit']
        ytd_vs_lfl_profit_pct = ((ytd_metrics['profit'] / ytd_lfl_metrics['profit'] - 1) * 100) if ytd_lfl_metrics['profit'] > 0 else 0

        # Status bar
        st.markdown(f"""
        <div class="status-bar">
            <strong>D2C Orders</strong> |
            Selected period ({date_start.strftime('%d/%m/%Y')} - {date_end.strftime('%d/%m/%Y')}): {len(d2c_linnworks)} orders |
            Dispatch filter: {day_filter}
        </div>
        """, unsafe_allow_html=True)

        # KPI Row 1 - MTD Revenue and Profitability
        st.markdown("### Month to Date Performance")
        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            f"MTD Revenue ({today.strftime('%b')})",
            format_currency(mtd_metrics['revenue']),
            f"{vs_last_month_rev_pct:+.1f}% vs Last Month" if last_month_metrics['revenue'] > 0 else None
        )
        col2.metric(
            f"MTD Profit ({today.strftime('%b')})",
            format_currency(mtd_metrics['profit']),
            f"{vs_last_month_profit_pct:+.1f}% vs Last Month" if last_month_metrics['profit'] > 0 else None,
            delta_color="normal" if vs_last_month_profit >= 0 else "inverse"
        )
        col3.metric(
            "MTD Margin",
            f"{mtd_metrics['margin_pct']:.1f}%",
            f"{mtd_metrics['margin_pct'] - last_month_metrics['margin_pct']:+.1f}pp" if last_month_metrics['margin_pct'] > 0 else None
        )
        col4.metric(
            "MTD Orders",
            f"{mtd_metrics['orders']:,}",
            f"{mtd_metrics['orders'] - last_month_metrics['orders']:+d} vs Last Month" if last_month_metrics['orders'] > 0 else None
        )

        # KPI Row 2 - YTD Revenue and Profitability
        st.markdown("### Year to Date Performance")
        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "YTD Revenue",
            format_currency(ytd_metrics['revenue']),
            f"{ytd_vs_lfl_rev_pct:+.1f}% vs LFL" if ytd_lfl_metrics['revenue'] > 0 else None,
            delta_color="normal" if ytd_metrics['revenue'] >= ytd_lfl_metrics['revenue'] else "inverse"
        )
        col2.metric(
            "YTD Profit",
            format_currency(ytd_metrics['profit']),
            f"{ytd_vs_lfl_profit_pct:+.1f}% vs LFL" if ytd_lfl_metrics['profit'] > 0 else None,
            delta_color="normal" if ytd_vs_lfl_profit >= 0 else "inverse"
        )
        col3.metric(
            "YTD Margin",
            f"{ytd_metrics['margin_pct']:.1f}%",
            f"{ytd_metrics['margin_pct'] - ytd_lfl_metrics['margin_pct']:+.1f}pp" if ytd_lfl_metrics['margin_pct'] > 0 else None
        )
        col4.metric(
            "YTD Orders",
            f"{ytd_metrics['orders']:,}"
        )

        # KPI Row 3 - Revenue Variances
        st.markdown("### Revenue Variance Analysis")
        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "vs Last Month (Same Period)",
            format_currency(vs_last_month_rev),
            f"{vs_last_month_rev_pct:+.1f}%",
            delta_color="normal" if vs_last_month_rev >= 0 else "inverse"
        )
        col2.metric(
            f"Last Month ({last_month_start.strftime('%b')} 1-{last_month_same_day.day})",
            format_currency(last_month_metrics['revenue']),
            f"{last_month_metrics['orders']} orders"
        )
        col3.metric(
            "vs LFL (Same Period Last Year)",
            format_currency(vs_lfl_rev),
            f"{vs_lfl_rev_pct:+.1f}%",
            delta_color="normal" if vs_lfl_rev >= 0 else "inverse"
        )
        col4.metric(
            f"LFL ({last_year_month_start.strftime('%b %Y')} 1-{last_year_same_day.day})",
            format_currency(lfl_metrics['revenue']),
            f"{lfl_metrics['orders']} orders"
        )

        # KPI Row 4 - Profitability Variances
        st.markdown("### Profitability Variance Analysis")
        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Profit vs Last Month",
            format_currency(vs_last_month_profit),
            f"{vs_last_month_profit_pct:+.1f}%",
            delta_color="normal" if vs_last_month_profit >= 0 else "inverse"
        )
        col2.metric(
            f"Last Month Profit ({last_month_start.strftime('%b')} 1-{last_month_same_day.day})",
            format_currency(last_month_metrics['profit']),
            f"{last_month_metrics['margin_pct']:.1f}% margin"
        )
        col3.metric(
            "Profit vs LFL",
            format_currency(vs_lfl_profit),
            f"{vs_lfl_profit_pct:+.1f}%",
            delta_color="normal" if vs_lfl_profit >= 0 else "inverse"
        )
        col4.metric(
            f"LFL Profit ({last_year_month_start.strftime('%b %Y')} 1-{last_year_same_day.day})",
            format_currency(lfl_metrics['profit']),
            f"{lfl_metrics['margin_pct']:.1f}% margin"
        )

        # Process selected date range for detailed view
        dispatch_info = get_dispatch_info(d2c_linnworks)

        shopify_order_ids = set()
        for order in d2c_linnworks:
            ref = order.get('ReferenceNum', '').replace('#', '').strip()
            if ref:
                try:
                    shopify_order_ids.add(int(ref))
                except ValueError:
                    pass

        if not shopify_order_ids:
            st.warning("Could not extract Shopify order IDs from Linnworks data.")
            return

        with st.spinner(f"Loading {len(shopify_order_ids)} orders from Shopify..."):
            shopify_orders = fetch_shopify_orders_by_ids(store, token, version, tuple(sorted(shopify_order_ids)))

        if not shopify_orders:
            st.warning("Could not fetch order details from Shopify.")
            return

        cache_key = f"proc_{date_min}_{date_max}_v2"

        if cache_key not in st.session_state:
            client = ShopifyClient()
            costing = CostingService(client)
            progress = st.progress(0, "Processing orders...")

            def update(curr, total, sent, skip):
                progress.progress(curr/total, f"Processing {curr}/{total}...")

            processed, total_cnt, skip_cnt = process_orders(shopify_orders, costing, dispatch_info, update)
            progress.empty()

            st.session_state[cache_key] = processed
            st.session_state[f"{cache_key}_stats"] = {"total": total_cnt, "sent": len(processed), "skipped": skip_cnt, "linnworks": len(d2c_linnworks)}
        else:
            processed = st.session_state[cache_key]

        filtered = filter_by_weekday(processed, inc_mon, inc_thu, inc_all)

        if not filtered:
            st.info("No orders match the current filters.")
            return

        # Weekly breakdown
        st.markdown("---")
        st.markdown("### 📅 Weekly Performance")
        st.caption(f"Selected period: {date_start.strftime('%d/%m/%Y')} - {date_end.strftime('%d/%m/%Y')} | Filter: {day_filter}")

        df = create_orders_dataframe(filtered)

        if not df.empty:
            weekly_kpis = df.groupby("week").agg({
                "order_id": "count",
                "net_revenue": "sum",
                "total_discounts": "sum",
                "contribution": "sum",
                "cogs": "sum",
            }).reset_index()
            weekly_kpis.columns = ["Week", "Orders", "Revenue", "Discounts", "Profit", "COGS"]
            weekly_kpis["Margin"] = (weekly_kpis["Profit"] / weekly_kpis["Revenue"] * 100).round(1)
            weekly_kpis["AOV"] = (weekly_kpis["Revenue"] / weekly_kpis["Orders"]).round(2)

            num_weeks = len(weekly_kpis)
            if num_weeks > 0:
                week_cols = st.columns(min(num_weeks, 4))
                for idx, row in weekly_kpis.iterrows():
                    col_idx = idx % len(week_cols)
                    week_num = row['Week'].split('-W')[1] if '-W' in row['Week'] else row['Week']
                    date_range = get_week_date_range(row['Week'])
                    with week_cols[col_idx]:
                        st.markdown(f"""
<div style="background:{HC_DARK_TEAL}; padding:20px; border-radius:12px; text-align:center; margin-bottom:15px;">
<span style="background:{HC_WHITE}; color:{HC_DARK_TEAL}; font-weight:bold; font-size:0.85em; padding:4px 12px; border-radius:20px;">WEEK {week_num}</span>
<p style="color:{HC_LIGHT_MINT}; font-size:0.8em; margin:10px 0 15px 0;">{date_range}</p>
<p style="color:{HC_WHITE}; font-size:1.8em; font-weight:bold; margin:0;">{format_currency(row['Revenue'])}</p>
<p style="color:{HC_LIGHT_MINT}; font-size:0.75em; margin:0 0 15px 0;">REVENUE</p>
<table style="width:100%; color:{HC_WHITE}; font-size:0.9em;">
<tr>
<td style="text-align:center;"><strong>{row['Orders']}</strong><br/><span style="color:{HC_LIGHT_MINT}; font-size:0.8em;">Orders</span></td>
<td style="text-align:center;"><strong>{format_currency(row['Profit'])}</strong><br/><span style="color:{HC_LIGHT_MINT}; font-size:0.8em;">Profit</span></td>
<td style="text-align:center;"><strong>{row['Margin']:.1f}%</strong><br/><span style="color:{HC_LIGHT_MINT}; font-size:0.8em;">Margin</span></td>
</tr>
</table>
<p style="color:{HC_LIGHT_MINT}; font-size:0.75em; margin:15px 0 0 0; border-top:1px solid rgba(255,255,255,0.2); padding-top:10px;">AOV: {format_currency(row['AOV'])} &nbsp;|&nbsp; Discounts: {format_currency(row['Discounts'])}</p>
</div>
                        """, unsafe_allow_html=True)

        # Orders table
        st.markdown("---")
        st.markdown("### Order Details")

        display_df = df.copy()
        display_df["sent_out_at"] = display_df["sent_out_at"].dt.strftime("%d/%m/%Y")

        display_cols = [
            "sent_out_at", "weekday", "order_name", "customer_name",
            "sku_count", "box_type", "box_multiplier",
            "gross_item_value", "total_discounts", "net_revenue",
            "shipping_paid", "cogs", "packaging_total",
            "contribution", "contribution_margin_pct"
        ]

        disp_df = display_df[display_cols].copy()
        disp_df.columns = [
            "Date", "Day", "Order", "Customer",
            "SKUs", "Box", "Mult",
            "Gross Value", "Discount", "Net Revenue",
            "Ship Paid", "COGS", "Packaging",
            "Contribution", "Margin %"
        ]

        st.dataframe(
            disp_df,
            hide_index=True,
            use_container_width=True,
            height=400,
            column_config={
                "Gross Value": st.column_config.NumberColumn(format="£%.2f"),
                "Discount": st.column_config.NumberColumn(format="£%.2f"),
                "Net Revenue": st.column_config.NumberColumn(format="£%.2f"),
                "Ship Paid": st.column_config.NumberColumn(format="£%.2f"),
                "COGS": st.column_config.NumberColumn(format="£%.2f"),
                "Packaging": st.column_config.NumberColumn(format="£%.2f"),
                "Contribution": st.column_config.NumberColumn(format="£%.2f"),
                "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

        # Profitability assumptions in expander
        with st.expander("📊 Profitability Assumptions"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Profitability Calculation**")
                st.markdown("""
| Component | Calculation |
|-----------|-------------|
| Revenue | Gross Item Value - Discounts |
| COGS | Shopify InventoryItem.cost per variant |
| Packaging | Based on SKU count (see below) |
| Profit | Revenue - COGS - Packaging |
                """)
            with col2:
                st.markdown("**Packaging Costs**")
                st.markdown("""
| SKU Count | Box Type | Cost |
|-----------|----------|------|
| < 10 | Small | £12.66 |
| 10-16 | Large | £13.81 |
| > 16 | 2x Large | £27.62 |
                """)

    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.exception(e)


def check_daily_refresh():
    """Check if data should be refreshed (daily at 8am)."""
    now = datetime.now()
    today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)

    # Get last refresh time from session state
    last_refresh = st.session_state.get('last_data_refresh')

    # Refresh if:
    # 1. Never refreshed before
    # 2. Last refresh was before today's 8am and current time is after 8am
    if last_refresh is None:
        st.session_state['last_data_refresh'] = now
        return False  # First load, caches are empty anyway

    last_refresh_dt = datetime.fromisoformat(last_refresh) if isinstance(last_refresh, str) else last_refresh

    if now >= today_8am and last_refresh_dt < today_8am:
        # Clear all caches
        st.cache_data.clear()
        st.session_state['last_data_refresh'] = now
        # Clear processed order cache
        for k in list(st.session_state.keys()):
            if k.startswith("proc_") or k == "loaded":
                del st.session_state[k]
        return True

    return False


def main():
    env_ok, missing = check_env_vars()
    if not env_ok:
        st.error(f"Missing environment variables: {', '.join(missing)}")
        return

    # Check for daily 8am refresh
    if check_daily_refresh():
        st.toast("🔄 Data refreshed (daily 8am update)", icon="✅")
        st.rerun()

    # Sidebar filters
    with st.sidebar:
        logo_b64 = get_logo_base64()
        if logo_b64:
            st.markdown(f'<img src="data:image/jpeg;base64,{logo_b64}" style="width:100%; border-radius:10px; margin-bottom:15px;">', unsafe_allow_html=True)

        st.markdown("## Filters")

        preset = st.selectbox(
            "Date Range",
            ["Last 7 days", "Last 14 days", "Last 30 days", "This week", "Last week", "Today", "Yesterday", "Custom"],
            index=1,
        )

        today = date.today()
        if preset == "Today":
            start, end = today, today
        elif preset == "Yesterday":
            start = end = today - timedelta(days=1)
        elif preset == "Last 7 days":
            start, end = today - timedelta(days=7), today
        elif preset == "Last 14 days":
            start, end = today - timedelta(days=14), today
        elif preset == "Last 30 days":
            start, end = today - timedelta(days=30), today
        elif preset == "This week":
            start = today - timedelta(days=today.weekday())
            end = today
        elif preset == "Last week":
            start = today - timedelta(days=today.weekday() + 7)
            end = start + timedelta(days=6)
        else:
            start, end = today - timedelta(days=14), today

        date_start = st.date_input("From", value=start)
        date_end = st.date_input("To", value=end)

        st.markdown("---")
        st.markdown("### Dispatch Day")
        day_filter = st.radio("Show dispatched on:", ["Monday & Thursday", "Monday only", "Thursday only", "All days"])

        inc_mon = day_filter in ["Monday & Thursday", "Monday only", "All days"]
        inc_thu = day_filter in ["Monday & Thursday", "Thursday only", "All days"]
        inc_all = day_filter == "All days"

        st.markdown("---")
        load = st.button("Refresh Data", type="primary", use_container_width=True)
        if st.button("Clear Cache", use_container_width=True):
            fetch_shopify_orders.clear()
            fetch_shopify_orders_by_ids.clear()
            fetch_linnworks_orders.clear()
            fetch_retail_order_details.clear()
            fetch_all_retail_orders.clear()
            for k in list(st.session_state.keys()):
                if k.startswith("proc_") or k == "loaded":
                    del st.session_state[k]
            st.session_state['last_data_refresh'] = datetime.now()
            st.rerun()

        # Show last refresh time
        last_refresh = st.session_state.get('last_data_refresh')
        if last_refresh:
            refresh_time = last_refresh if isinstance(last_refresh, datetime) else datetime.fromisoformat(last_refresh)
            st.caption(f"📅 Last refresh: {refresh_time.strftime('%d/%m/%Y %H:%M')}")
            st.caption("*Auto-refreshes daily at 8am*")

    # Header
    logo_b64 = get_logo_base64()
    if logo_b64:
        st.markdown(f"""
        <div class="main-header">
            <img src="data:image/jpeg;base64,{logo_b64}" alt="HomeCooks">
            <div>
                <h1>Order Profitability Dashboard</h1>
                <p>Track profitability across D2C and Retail channels</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="main-header">
            <h1>HomeCooks Order Profitability</h1>
            <p>Track profitability across D2C and Retail channels</p>
        </div>
        """, unsafe_allow_html=True)

    # Tabs
    tab_d2c, tab_retail, tab_gopuff = st.tabs(["HomeCooks D2C", "HomeCooks Retail", "Go Puff Sales"])

    date_min = datetime.combine(date_start, datetime.min.time())
    date_max = datetime.combine(date_end, datetime.max.time())

    if load or "loaded" not in st.session_state:
        st.session_state["loaded"] = True

    # D2C Tab
    with tab_d2c:
        st.markdown("*Dispatch dates from Linnworks | Monday & Thursday tracking*")
        if st.session_state.get("loaded"):
            render_d2c_dashboard(date_min, date_max, date_start, date_end, day_filter, inc_mon, inc_thu, inc_all)

    # Retail Tab
    with tab_retail:
        st.markdown("*Retail orders shipped via 'No Shipping Required'*")

        if st.session_state.get("loaded"):
            render_retail_dashboard(date_min, date_max, date_start, date_end)

    # Go Puff Tab
    with tab_gopuff:
        st.markdown("*Go Puff sales data from Google Sheets*")
        render_gopuff_dashboard()


def render_gopuff_dashboard():
    """Render Go Puff Sales Dashboard - data from Google Sheets."""
    import requests
    from io import StringIO
    import time as time_module

    # Refresh button
    col_refresh, col_time = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh Data", help="Pull latest data from Google Sheets", key="gopuff_refresh"):
            st.cache_data.clear()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

    # Fetch data from published Google Sheet with cache-busting
    cache_buster = int(time_module.time())
    sheet_url = f"https://docs.google.com/spreadsheets/d/12-xrEgll_No_7J_P1xqZHa-HAtyRRwmQ5Hp6uWCM6ng/export?format=csv&gid=432589449&_={cache_buster}"
    raw_data_url = f"https://docs.google.com/spreadsheets/d/12-xrEgll_No_7J_P1xqZHa-HAtyRRwmQ5Hp6uWCM6ng/export?format=csv&gid=565428930&_={cache_buster}"

    try:
        response = requests.get(sheet_url, allow_redirects=True, headers={'Cache-Control': 'no-cache'})
        gopuff_df = pd.read_csv(StringIO(response.text))

        raw_response = requests.get(raw_data_url, allow_redirects=True, headers={'Cache-Control': 'no-cache'})
        raw_df = pd.read_csv(StringIO(raw_response.text))

        if not gopuff_df.empty:
            # Extract key metrics
            latest_sales_day = gopuff_df.iloc[1, 0] if len(gopuff_df) > 1 else "N/A"

            # Calculate week commencing
            try:
                sales_date = datetime.strptime(latest_sales_day.split(': ')[1], '%m/%d/%Y')
                week_start = sales_date - timedelta(days=sales_date.weekday())
                week_commencing = week_start.strftime('%d/%m/%Y')
            except:
                week_commencing = "N/A"
                sales_date = None

            # Check promotion period
            def check_promotion(date):
                if not date:
                    return ""
                promo1_start = datetime(2025, 7, 1)
                promo1_end = datetime(2025, 7, 28)
                promo2_start = datetime(2025, 10, 7)
                promo2_end = datetime(2025, 10, 14)

                if promo1_start <= date <= promo1_end:
                    return "🎉 PROMOTION PERIOD (Jul 1-28, 2025)"
                elif promo2_start <= date <= promo2_end:
                    return "🎉 PROMOTION PERIOD (Oct 7-14, 2025)"
                return ""

            promo_label = check_promotion(sales_date)

            # SKU of the day
            sku_of_day = gopuff_df.iloc[2, 0] if len(gopuff_df) > 2 else ""
            sku_day_match = sku_of_day.split('\n')[1] if '\n' in str(sku_of_day) else ""
            sku_day_qty = sku_of_day.split('\n')[-1].replace(' sold', '') if '\n' in str(sku_of_day) else "0"

            # Calculate today's stats from raw data
            date_cols = [col for col in raw_df.columns if col != 'Product Name']
            if date_cols:
                try:
                    latest_date = max([datetime.strptime(d, '%m/%d/%Y') for d in date_cols])
                    latest_date_str = latest_date.strftime('%m/%d/%Y')
                    today_sales = pd.to_numeric(raw_df[latest_date_str], errors='coerce').fillna(0)
                    total_skus = int(len(raw_df))
                    skus_with_sales = int((today_sales > 0).sum())
                    skus_zero_sales = int(total_skus - skus_with_sales)
                    total_units_today = int(today_sales.sum())
                except:
                    total_skus = len(raw_df)
                    skus_with_sales = 0
                    skus_zero_sales = 0
                    total_units_today = 0
            else:
                total_skus = skus_with_sales = skus_zero_sales = total_units_today = 0

            # Weekly top seller
            weekly_top = gopuff_df.iloc[5, 0] if len(gopuff_df) > 5 else ""
            weekly_product = weekly_top.split('\n')[1] if '\n' in str(weekly_top) else ""
            weekly_qty = weekly_top.split('\n')[-1].replace(' sold', '') if '\n' in str(weekly_top) else "0"

            # Calculate highest monthly sales from raw data
            monthly_results = []
            for idx, row in raw_df.iterrows():
                product = row['Product Name']
                monthly_totals = {}
                for date_col in date_cols:
                    try:
                        date_obj = datetime.strptime(date_col, '%m/%d/%Y')
                        month_key = date_obj.strftime('%B %Y')
                        if month_key not in monthly_totals:
                            monthly_totals[month_key] = 0
                        monthly_totals[month_key] += row[date_col]
                    except:
                        pass
                for month, total in monthly_totals.items():
                    monthly_results.append({'Product': product, 'Month': month, 'Total': total})

            if monthly_results:
                monthly_results_df = pd.DataFrame(monthly_results)
                max_monthly = monthly_results_df.loc[monthly_results_df['Total'].idxmax()]
                monthly_product = max_monthly['Product']
                monthly_date = max_monthly['Month']
                monthly_qty = str(int(max_monthly['Total']))
                monthly_promo_note = " 🎉" if monthly_date == "July 2025" else ""
            else:
                monthly_product = monthly_date = "N/A"
                monthly_qty = "0"
                monthly_promo_note = ""

            # All-time top seller
            alltime_top = gopuff_df.iloc[11, 0] if len(gopuff_df) > 11 else ""
            alltime_product = alltime_top.split('\n')[1] if '\n' in str(alltime_top) else ""
            alltime_qty = alltime_top.split('\n')[-1].replace(' sold', '') if '\n' in str(alltime_top) else "0"

            # Display
            st.caption(latest_sales_day)

            if promo_label:
                st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #FFD166 0%, #FF6B6B 100%);
                                padding: 12px 20px; border-radius: 8px; text-align: center;
                                font-weight: bold; color: #1F2937; margin: 10px 0;">
                        {promo_label}
                    </div>
                """, unsafe_allow_html=True)

            st.divider()

            # KPI Cards
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                zero_text = f'<br/><span style="color: #FF6B6B;">{skus_zero_sales} SKUs with 0 sales</span>' if skus_zero_sales > 0 else ''
                st.markdown(f"""
                    <div style="background:{HC_DARK_TEAL}; padding:15px; border-radius:10px; text-align:center;">
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.9em;">🔥 SKU OF THE DAY</div>
                        <div style="color:{HC_MEDIUM_TEAL}; font-size:0.85em; margin:8px 0;">{sku_day_match}</div>
                        <div style="color:{HC_WHITE}; font-size:1.5em; font-weight:bold;">{sku_day_qty} sold</div>
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.75em; margin-top:8px;">
                            <strong>{total_units_today:,} total units today</strong><br/>
                            {skus_with_sales} of {total_skus} SKUs sold{zero_text}
                        </div>
                    </div>
                """, unsafe_allow_html=True)

            with col2:
                st.markdown(f"""
                    <div style="background:{HC_DARK_TEAL}; padding:15px; border-radius:10px; text-align:center;">
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.9em;">📊 WEEKLY TOP SELLER</div>
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.75em;">Week: {week_commencing}</div>
                        <div style="color:{HC_MEDIUM_TEAL}; font-size:0.85em; margin:8px 0;">{weekly_product}</div>
                        <div style="color:{HC_WHITE}; font-size:1.5em; font-weight:bold;">{weekly_qty} sold</div>
                    </div>
                """, unsafe_allow_html=True)

            with col3:
                st.markdown(f"""
                    <div style="background:{HC_DARK_TEAL}; padding:15px; border-radius:10px; text-align:center;">
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.9em;">🏆 MONTHLY TOP SELLER{monthly_promo_note}</div>
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.75em;">{monthly_date}</div>
                        <div style="color:{HC_MEDIUM_TEAL}; font-size:0.85em; margin:8px 0;">{monthly_product}</div>
                        <div style="color:{HC_WHITE}; font-size:1.5em; font-weight:bold;">{monthly_qty} sold</div>
                    </div>
                """, unsafe_allow_html=True)

            with col4:
                st.markdown(f"""
                    <div style="background:{HC_DARK_TEAL}; padding:15px; border-radius:10px; text-align:center;">
                        <div style="color:{HC_LIGHT_MINT}; font-size:0.9em;">🌟 ALL-TIME TOP SELLER</div>
                        <div style="color:{HC_MEDIUM_TEAL}; font-size:0.85em; margin:8px 0;">{alltime_product}</div>
                        <div style="color:{HC_WHITE}; font-size:1.5em; font-weight:bold;">{alltime_qty} sold</div>
                    </div>
                """, unsafe_allow_html=True)

            st.divider()

            # Today's Sales by Product
            st.markdown("### Today's Sales by Product")
            try:
                if date_cols:
                    latest_date = max([datetime.strptime(d, '%m/%d/%Y') for d in date_cols])
                    latest_date_str = latest_date.strftime('%m/%d/%Y')
                    today_sales_list = []
                    total_today = 0

                    for idx, row in raw_df.iterrows():
                        product = row['Product Name']
                        qty = pd.to_numeric(row[latest_date_str], errors='coerce')
                        if pd.notna(qty) and qty > 0:
                            today_sales_list.append({'Product': product, 'Quantity': int(qty)})
                            total_today += qty

                    for item in today_sales_list:
                        item['Percentage'] = f"{(item['Quantity'] / total_today * 100):.1f}%"

                    today_sales_list.sort(key=lambda x: x['Quantity'], reverse=True)

                    if today_sales_list:
                        st.dataframe(pd.DataFrame(today_sales_list), use_container_width=True, hide_index=True, height=400)
                    else:
                        st.info("No sales recorded for today")
            except Exception as e:
                st.error(f"Error loading today's sales: {str(e)}")

            st.divider()

            # Weekly Sales Summary
            st.markdown("### 📅 Weekly Sales (Monday - Sunday)")
            try:
                today = datetime.now()
                current_monday = today - timedelta(days=today.weekday())

                if 'gopuff_week_offset' not in st.session_state:
                    st.session_state.gopuff_week_offset = 0

                col_prev, col_date, col_next = st.columns([1, 3, 1])

                with col_prev:
                    if st.button("◀ Previous Week", key="gopuff_prev"):
                        st.session_state.gopuff_week_offset -= 1
                        st.rerun()

                with col_next:
                    if st.button("Next Week ▶", key="gopuff_next", disabled=(st.session_state.gopuff_week_offset >= 0)):
                        st.session_state.gopuff_week_offset += 1
                        st.rerun()

                monday_start = current_monday + timedelta(weeks=st.session_state.gopuff_week_offset)
                sunday_end = monday_start + timedelta(days=6)

                weekly_sales = {}
                for idx, row in raw_df.iterrows():
                    product = row['Product Name']
                    total = 0
                    for date_col in date_cols:
                        try:
                            date_obj = datetime.strptime(date_col, '%m/%d/%Y')
                            if monday_start <= date_obj <= sunday_end:
                                sales = pd.to_numeric(row[date_col], errors='coerce')
                                if pd.notna(sales):
                                    total += sales
                        except:
                            pass
                    if total > 0:
                        weekly_sales[product] = int(total)

                sorted_weekly = sorted(weekly_sales.items(), key=lambda x: x[1], reverse=True)

                if sorted_weekly:
                    weekly_df = pd.DataFrame(sorted_weekly, columns=['Product', 'Units Sold This Week'])
                    week_label = "This Week" if st.session_state.gopuff_week_offset == 0 else f"{abs(st.session_state.gopuff_week_offset)} week(s) ago"
                    st.caption(f"**{week_label}:** {monday_start.strftime('%b %d')} - {sunday_end.strftime('%b %d, %Y')}")
                    st.dataframe(weekly_df, use_container_width=True, hide_index=True, height=400)

                    col1, col2 = st.columns(2)
                    col1.metric("Total Weekly Units", f"{sum(weekly_sales.values()):,}")
                    col2.metric("SKUs Sold This Week", len(weekly_sales))
                else:
                    st.info(f"No sales for week of {monday_start.strftime('%b %d')} - {sunday_end.strftime('%b %d, %Y')}")

            except Exception as e:
                st.error(f"Error calculating weekly sales: {str(e)}")

            st.divider()

            # All Products Summary
            st.markdown("### 📊 All Products Summary")
            all_products = []
            for i in range(19, 32):
                if i < len(gopuff_df):
                    product = gopuff_df.iloc[i, 3]
                    sold = gopuff_df.iloc[i, 10]
                    if pd.notna(product) and pd.notna(sold):
                        sold_num = str(sold).replace(' sold', '').strip()
                        all_products.append({'Product': product, 'Total Sold': sold_num})

            if all_products:
                st.dataframe(pd.DataFrame(all_products), use_container_width=True, hide_index=True, height=400)

        else:
            st.warning("No data available from Google Sheets")

    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {str(e)}")
        st.caption("Make sure the sheet is published and accessible")


if __name__ == "__main__":
    main()
