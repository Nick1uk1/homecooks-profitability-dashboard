"""
Appstle Subscriptions API Client
Fetches subscription metrics for the D2C dashboard
"""

import os
import requests
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
import streamlit as st


class AppstleClient:
    """Client for Appstle Subscriptions API."""

    BASE_URL = "https://subscription-admin.appstle.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json'
        })

    def get_active_subscriptions(self, page_size: int = 500) -> List[Dict]:
        """Fetch all active subscriptions."""
        all_subscriptions = []
        page = 0

        while True:
            response = self.session.get(
                f"{self.BASE_URL}/api/external/v2/subscription-contract-details",
                params={'status': 'ACTIVE', 'size': page_size, 'page': page},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            all_subscriptions.extend(data)

            if len(data) < page_size:
                break
            page += 1

        return all_subscriptions

    def get_cancelled_subscriptions(self, page_size: int = 500) -> List[Dict]:
        """Fetch all cancelled subscriptions."""
        all_subscriptions = []

        for page in range(10):  # Max 10 pages (5000 records)
            response = self.session.get(
                f"{self.BASE_URL}/api/external/v2/subscription-contract-details",
                params={'status': 'CANCELLED', 'size': page_size, 'page': page},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            all_subscriptions.extend(data)

            if len(data) < page_size:
                break

        return all_subscriptions

    def get_paused_subscriptions(self, page_size: int = 500) -> List[Dict]:
        """Fetch all paused subscriptions."""
        all_subscriptions = []
        page = 0

        while True:
            response = self.session.get(
                f"{self.BASE_URL}/api/external/v2/subscription-contract-details",
                params={'status': 'PAUSED', 'size': page_size, 'page': page},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            all_subscriptions.extend(data)

            if len(data) < page_size:
                break
            page += 1

        return all_subscriptions

    def get_all_subscriptions(self) -> List[Dict]:
        """Fetch all subscriptions (active and cancelled)."""
        all_subs = []
        all_subs.extend(self.get_active_subscriptions())
        all_subs.extend(self.get_cancelled_subscriptions())
        return all_subs

    def calculate_historical_high(self, all_subs: List[Dict]) -> tuple:
        """
        Calculate the all-time high subscriber count from historical data.
        Returns (peak_count, peak_date).
        """
        # Build events list: (date, +1 for created, -1 for cancelled)
        events = []

        for sub in all_subs:
            created = sub.get('createdAt')
            cancelled = sub.get('cancelledOn')

            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00')).replace(tzinfo=None)
                    events.append((created_dt.date(), 1))
                except (ValueError, TypeError):
                    pass

            if cancelled:
                try:
                    cancelled_dt = datetime.fromisoformat(cancelled.replace('Z', '+00:00')).replace(tzinfo=None)
                    events.append((cancelled_dt.date(), -1))
                except (ValueError, TypeError):
                    pass

        if not events:
            return (0, None)

        # Sort by date
        events.sort(key=lambda x: x[0])

        # Calculate running total and find peak
        running_total = 0
        peak_count = 0
        peak_date = None
        daily_counts = {}

        for event_date, change in events:
            running_total += change
            daily_counts[event_date] = running_total

            if running_total > peak_count:
                peak_count = running_total
                peak_date = event_date

        return (peak_count, peak_date)

    def get_subscription_metrics(self) -> Dict:
        """
        Get subscription metrics including:
        - Active subscribers count
        - New this calendar week
        - Cancelled this calendar week
        - All-time high active subscribers
        """
        # Get current calendar week boundaries (Monday to Sunday)
        # Use date objects to avoid timezone confusion
        today = date.today()

        # Calculate days since Monday (Monday=0 for our week start)
        # Python weekday: Monday=0, Tuesday=1, ..., Sunday=6
        days_since_monday = today.weekday()  # Monday=0, Sunday=6

        week_start_date = today - timedelta(days=days_since_monday)
        week_end_date = week_start_date + timedelta(days=6)

        # Convert to datetime for comparison (start of day to end of day)
        week_start = datetime.combine(week_start_date, datetime.min.time())
        week_end = datetime.combine(week_end_date, datetime.max.time())

        # Fetch all subscriptions
        all_subs = self.get_all_subscriptions()

        # Count active subscriptions
        active_subs = [s for s in all_subs if s.get('status', '').lower() == 'active']
        active_count = len(active_subs)

        # Count new subscriptions this week (by createdAt) - count ALL subs created this week
        # regardless of current status (matches Appstle Analytics)
        new_this_week = 0
        for sub in all_subs:
            created_at = sub.get('createdAt')
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    if week_start <= created_dt <= week_end:
                        new_this_week += 1
                except (ValueError, TypeError):
                    pass

        # Count cancellations this week
        # Count any subscription with cancelledOn date in this week (regardless of current status,
        # in case they cancelled and resubscribed)
        cancelled_this_week = 0
        for sub in all_subs:
            cancelled_on = sub.get('cancelledOn')
            if cancelled_on:
                try:
                    cancelled_dt = datetime.fromisoformat(cancelled_on.replace('Z', '+00:00')).replace(tzinfo=None)
                    if week_start <= cancelled_dt <= week_end:
                        cancelled_this_week += 1
                except (ValueError, TypeError):
                    pass

        # Calculate historical all-time high
        historical_high, peak_date = self.calculate_historical_high(all_subs)

        return {
            'active_subscribers': active_count,
            'new_this_week': new_this_week,
            'cancelled_this_week': cancelled_this_week,
            'week_start': week_start_date.strftime('%b %d'),
            'week_end': week_end_date.strftime('%b %d'),
            'all_time_high': historical_high,
            'all_time_high_date': peak_date.strftime('%b %d, %Y') if peak_date else None,
        }


@st.cache_data(ttl=300, show_spinner=False)  # 5 minute cache
def fetch_appstle_metrics() -> Optional[Dict]:
    """
    Fetch Appstle subscription metrics with caching.
    Returns None if API key is not configured or request fails.
    """
    # Try st.secrets first (Streamlit Cloud), then fall back to env var
    api_key = None
    try:
        api_key = st.secrets.get("APPSTLE_API_KEY")
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get("APPSTLE_API_KEY")

    if not api_key:
        return None

    try:
        client = AppstleClient(api_key)
        return client.get_subscription_metrics()
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch Appstle metrics: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Unexpected error fetching Appstle metrics: {str(e)}")
        return None


def analyze_cancellation_patterns(all_subs: List[Dict]) -> Dict:
    """
    Analyze when subscribers cancel - after how many orders.

    Returns dict with:
    - cancelled_after_first: count cancelled after only 1 order
    - cancelled_after_first_pct: percentage
    - avg_orders_before_cancel: average orders before cancellation
    - order_distribution: dict of order count -> cancellation count
    """
    cancelled_subs = [s for s in all_subs if s.get('status', '').lower() == 'cancelled']

    if not cancelled_subs:
        return {
            'cancelled_after_first': 0,
            'cancelled_after_first_pct': 0,
            'avg_orders_before_cancel': 0,
            'order_distribution': {},
            'total_cancelled': 0,
        }

    order_counts = []
    order_distribution = {}

    for sub in cancelled_subs:
        # Try different field names that Appstle might use
        order_count = (
            sub.get('orderCount') or
            sub.get('billingPolicyOrderCount') or
            sub.get('totalOrders') or
            sub.get('numberOfOrders') or
            sub.get('ordersCount') or
            1  # Default to 1 if not found
        )

        try:
            order_count = int(order_count)
        except (ValueError, TypeError):
            order_count = 1

        order_counts.append(order_count)
        order_distribution[order_count] = order_distribution.get(order_count, 0) + 1

    cancelled_after_first = sum(1 for c in order_counts if c <= 1)
    avg_orders = sum(order_counts) / len(order_counts) if order_counts else 0

    return {
        'cancelled_after_first': cancelled_after_first,
        'cancelled_after_first_pct': (cancelled_after_first / len(cancelled_subs) * 100) if cancelled_subs else 0,
        'avg_orders_before_cancel': round(avg_orders, 1),
        'order_distribution': dict(sorted(order_distribution.items())),
        'total_cancelled': len(cancelled_subs),
    }


def is_all_time_high(current_count: int, historical_high: int) -> bool:
    """
    Check if current count is a new all-time high.
    Returns True only if current count exceeds the historical high.
    """
    return current_count > historical_high


@st.cache_data(ttl=3600, show_spinner=False)  # 1 hour cache
def fetch_subscription_metrics_for_period(start_date_str: str, end_date_str: str) -> Optional[Dict]:
    """
    Fetch subscription metrics for a specific date range.
    Dates passed as strings for cache compatibility.

    Returns:
        Dict with 'new', 'cancelled', and 'active_total' counts, or None on error.
    """
    # Parse dates
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

    # Get API key
    api_key = None
    try:
        api_key = st.secrets.get("APPSTLE_API_KEY")
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get("APPSTLE_API_KEY")

    if not api_key:
        return None

    try:
        client = AppstleClient(api_key)
        all_subs = client.get_all_subscriptions()

        # Count new subscriptions in period (all statuses - matches Appstle Analytics)
        new_count = 0
        for sub in all_subs:
            created = sub.get('createdAt')
            if created:
                try:
                    created_date = datetime.fromisoformat(created.replace('Z', '+00:00')).date()
                    if start_date <= created_date <= end_date:
                        new_count += 1
                except (ValueError, TypeError):
                    pass

        # Count cancellations in period
        # Count any subscription with cancelledOn date in range (regardless of current status)
        cancelled_count = 0
        for sub in all_subs:
            cancelled = sub.get('cancelledOn')
            if cancelled:
                try:
                    cancelled_date = datetime.fromisoformat(cancelled.replace('Z', '+00:00')).date()
                    if start_date <= cancelled_date <= end_date:
                        cancelled_count += 1
                except (ValueError, TypeError):
                    pass

        # Active total
        active_count = len([s for s in all_subs if s.get('status', '').lower() == 'active'])

        return {
            'new': new_count,
            'cancelled': cancelled_count,
            'active_total': active_count,
        }
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)  # 1 hour cache
def fetch_cancellation_analysis() -> Optional[Dict]:
    """
    Fetch and analyze cancellation patterns.
    Returns analysis of when/why subscribers cancel.
    """
    api_key = None
    try:
        api_key = st.secrets.get("APPSTLE_API_KEY")
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get("APPSTLE_API_KEY")

    if not api_key:
        return None

    try:
        client = AppstleClient(api_key)
        all_subs = client.get_all_subscriptions()
        return analyze_cancellation_patterns(all_subs)
    except Exception:
        return None
