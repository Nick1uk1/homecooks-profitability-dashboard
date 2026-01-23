"""
Debug script to investigate Appstle subscription count discrepancies.
Run with: streamlit run debug_appstle.py
"""

import os
import streamlit as st
from datetime import datetime, date, timedelta
from appstle_client import AppstleClient

st.title("Appstle Debug")

# Get API key
api_key = None
try:
    api_key = st.secrets.get("APPSTLE_API_KEY")
except Exception:
    pass

if not api_key:
    api_key = os.environ.get("APPSTLE_API_KEY")

if not api_key:
    st.error("No APPSTLE_API_KEY found")
    st.stop()

client = AppstleClient(api_key)

# Date inputs
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start date", date(2026, 1, 19))
with col2:
    end_date = st.date_input("End date", date(2026, 1, 25))

if st.button("Run Analysis"):
    with st.spinner("Fetching data from Appstle API..."):
        # Fetch each status separately
        st.subheader("Subscriptions by Status")

        active = client.get_active_subscriptions()
        st.write(f"**ACTIVE:** {len(active)}")

        skipped = client.get_skipped_subscriptions()
        st.write(f"**SKIPPED:** {len(skipped)}")

        paused = client.get_paused_subscriptions()
        st.write(f"**PAUSED:** {len(paused)}")

        cancelled = client.get_cancelled_subscriptions()
        st.write(f"**CANCELLED:** {len(cancelled)}")

        st.write("---")
        st.write(f"**Active (ACTIVE only):** {len(active)}")
        st.write(f"**Active (ACTIVE + SKIPPED):** {len(active) + len(skipped)}")
        st.write(f"**Active (ACTIVE + PAUSED):** {len(active) + len(paused)}")
        st.write(f"**Active (ACTIVE + SKIPPED + PAUSED):** {len(active) + len(skipped) + len(paused)}")

        # Combine for analysis
        all_subs = active + skipped + cancelled  # Current definition

        # Check all statuses in fetched data
        all_statuses = {}
        for sub in all_subs:
            status = sub.get('status', 'UNKNOWN')
            all_statuses[status] = all_statuses.get(status, 0) + 1

        st.subheader("Status breakdown in fetched data")
        st.write(all_statuses)

        # New subscriptions analysis
        st.subheader(f"NEW Subscriptions ({start_date} to {end_date})")

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        new_all = []
        new_by_status = {}

        for sub in all_subs:
            created = sub.get('createdAt')
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00')).replace(tzinfo=None)
                    if start_dt <= created_dt <= end_dt:
                        new_all.append(sub)
                        status = sub.get('status', 'UNKNOWN')
                        new_by_status[status] = new_by_status.get(status, 0) + 1
                except Exception as e:
                    st.write(f"Error parsing date {created}: {e}")

        st.write(f"**Total NEW (all statuses):** {len(new_all)}")
        st.write(f"**NEW by status:** {new_by_status}")

        # Only count new that are still active
        new_active_only = len([s for s in new_all if s.get('status', '').upper() == 'ACTIVE'])
        new_active_skipped = len([s for s in new_all if s.get('status', '').upper() in ['ACTIVE', 'SKIPPED']])

        st.write(f"**NEW (only ACTIVE status):** {new_active_only}")
        st.write(f"**NEW (ACTIVE + SKIPPED):** {new_active_skipped}")

        # Cancelled analysis
        st.subheader(f"CANCELLED ({start_date} to {end_date})")

        cancelled_in_period = 0
        for sub in all_subs:
            cancelled_on = sub.get('cancelledOn')
            if cancelled_on:
                try:
                    cancelled_dt = datetime.fromisoformat(cancelled_on.replace('Z', '+00:00')).replace(tzinfo=None)
                    if start_dt <= cancelled_dt <= end_dt:
                        cancelled_in_period += 1
                except:
                    pass

        st.write(f"**Cancelled in period:** {cancelled_in_period}")

        # Show sample subscription data
        st.subheader("Sample subscription data (first ACTIVE)")
        if active:
            sample = active[0]
            st.json({k: v for k, v in sample.items() if k in ['id', 'status', 'createdAt', 'cancelledOn', 'customerEmail']})
