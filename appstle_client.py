"""
Appstle Subscriptions API Client
Fetches subscription metrics for the D2C dashboard
"""

import os
import requests
from datetime import datetime, timedelta
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

        # Fetch active subscriptions
        active_subs = self.get_active_subscriptions()
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

        # Fetch cancelled subscriptions and count this week
        cancelled_subs = self.get_cancelled_subscriptions()
        cancelled_this_week = 0
        for sub in cancelled_subs:
            cancelled_on = sub.get('cancelledOn')
            if cancelled_on:
                try:
                    cancelled_dt = datetime.fromisoformat(cancelled_on.replace('Z', '+00:00')).replace(tzinfo=None)
                    if week_start <= cancelled_dt <= week_end:
                        cancelled_this_week += 1
                except (ValueError, TypeError):
                    pass

        return {
            'active_subscribers': active_count,
            'new_this_week': new_this_week,
            'cancelled_this_week': cancelled_this_week,
            'week_start': week_start.strftime('%b %d'),
            'week_end': week_end.strftime('%b %d'),
        }


@st.cache_data(ttl=300, show_spinner=False)  # 5 minute cache
def fetch_appstle_metrics() -> Optional[Dict]:
    """
    Fetch Appstle subscription metrics with caching.
    Returns None if API key is not configured or request fails.
    """
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


def get_all_time_high_subscribers() -> int:
    """
    Get the all-time high number of active subscribers.
    Stored in Streamlit session state to persist across refreshes.
    """
    if 'appstle_all_time_high' not in st.session_state:
        st.session_state.appstle_all_time_high = 0
    return st.session_state.appstle_all_time_high


def update_all_time_high(current_count: int) -> bool:
    """
    Update the all-time high if current count exceeds it.
    Returns True if this is a new all-time high.
    """
    if 'appstle_all_time_high' not in st.session_state:
        st.session_state.appstle_all_time_high = 0

    if current_count > st.session_state.appstle_all_time_high:
        st.session_state.appstle_all_time_high = current_count
        return True
    return False
