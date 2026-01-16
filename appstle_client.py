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
        """Fetch all subscriptions (active, cancelled, paused)."""
        all_subs = []
        all_subs.extend(self.get_active_subscriptions())
        all_subs.extend(self.get_cancelled_subscriptions())
        all_subs.extend(self.get_paused_subscriptions())
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
        # Get current calendar week boundaries (Sunday to Saturday)
        today = datetime.now()
        # Find the most recent Sunday (start of week)
        days_since_sunday = today.weekday() + 1  # Monday=0, so Sunday was (weekday + 1) days ago
        if days_since_sunday == 7:  # If today is Sunday
            days_since_sunday = 0
        week_start = today.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_sunday)
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

        # Fetch all subscriptions
        all_subs = self.get_all_subscriptions()

        # Count active subscriptions
        active_subs = [s for s in all_subs if s.get('status', '').lower() == 'active']
        active_count = len(active_subs)

        # Count new subscriptions this week (by createdAt)
        new_this_week = 0
        for sub in active_subs:
            created_at = sub.get('createdAt')
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
                    if week_start <= created_dt <= week_end:
                        new_this_week += 1
                except (ValueError, TypeError):
                    pass

        # Count cancellations this week
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
            'week_start': week_start.strftime('%b %d'),
            'week_end': week_end.strftime('%b %d'),
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


def is_all_time_high(current_count: int, historical_high: int) -> bool:
    """
    Check if current count is a new all-time high.
    Returns True only if current count exceeds the historical high.
    """
    return current_count > historical_high
