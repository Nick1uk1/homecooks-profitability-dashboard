"""
Linnworks API Client for getting processed/dispatched orders.
"""

import os
import time
import requests
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from dateutil import parser as date_parser


class LinnworksClient:
    """Client for Linnworks API to get processed order dispatch dates."""

    def __init__(self):
        self.app_id = os.environ.get("LINNWORKS_APP_ID", "51e2b5ee-bb88-4a20-b0d6-72b74f3e9642")
        self.app_secret = os.environ.get("LINNWORKS_APP_SECRET", "5daa226d-bb00-43f9-b26c-dfb755323246")
        self.install_token = os.environ.get("LINNWORKS_INSTALL_TOKEN", "1b385b6dee2b50f8717b0520d06f266e")

        self.session_token = None
        self.server = None

    def authenticate(self) -> bool:
        """Authenticate with Linnworks and get session token."""
        auth_url = "https://api.linnworks.net/api/Auth/AuthorizeByApplication"
        auth_data = {
            'applicationId': self.app_id,
            'applicationSecret': self.app_secret,
            'token': self.install_token
        }

        try:
            response = requests.post(auth_url, data=auth_data)
            if response.status_code == 200:
                result = response.json()
                self.session_token = result.get('Token')
                self.server = result.get('Server', 'https://eu-ext.linnworks.net')
                return True
            else:
                print(f"Linnworks auth failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Linnworks auth error: {e}")
            return False

    def get_processed_orders(
        self,
        from_date: datetime,
        to_date: datetime,
    ) -> List[Dict]:
        """
        Fetch processed orders from Linnworks.

        Args:
            from_date: Start date
            to_date: End date

        Returns:
            List of processed order dicts
        """
        if not self.session_token:
            if not self.authenticate():
                return []

        url = f"{self.server}/api/ProcessedOrders/SearchProcessedOrdersPaged"

        # Format dates for Linnworks API (MM-DD-YYYY HH:MM:SS)
        from_str = from_date.strftime('%m-%d-%Y 00:00:00')
        to_str = to_date.strftime('%m-%d-%Y 23:59:59')

        all_orders = []
        page_num = 1

        while True:
            data = {
                'from': from_str,
                'to': to_str,
                'dateType': 'PROCESSED',
                'searchField': '',
                'exactMatch': 'false',
                'searchTerm': '',
                'pageNum': str(page_num),
                'numEntriesPerPage': '500'
            }

            headers = {'Authorization': self.session_token}

            try:
                response = requests.post(url, headers=headers, data=data)

                if response.status_code == 200:
                    result = response.json()
                    orders = result.get('Data', [])

                    if not orders:
                        break

                    all_orders.extend(orders)

                    # Check if there are more pages
                    total_entries = result.get('TotalEntries', 0)
                    if len(all_orders) >= total_entries:
                        break

                    page_num += 1
                    time.sleep(0.2)  # Rate limiting
                else:
                    print(f"Linnworks API error: {response.status_code}")
                    break

            except Exception as e:
                print(f"Linnworks request error: {e}")
                break

        return all_orders

    def get_order_details(self, order_id: str) -> Optional[Dict]:
        """Get detailed order info including line items."""
        if not self.session_token:
            if not self.authenticate():
                return None

        url = f"{self.server}/api/Orders/GetOrdersById"
        headers = {
            'Authorization': self.session_token,
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json={'pkOrderIds': [order_id]}
            )

            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0]
            return None
        except Exception as e:
            print(f"Error getting order details: {e}")
            return None


def parse_linnworks_date(date_str: str) -> Optional[datetime]:
    """Parse Linnworks date string to datetime."""
    if not date_str:
        return None
    try:
        return date_parser.parse(date_str)
    except:
        return None


def build_dispatch_date_map(
    linnworks_orders: List[Dict]
) -> Dict[str, datetime]:
    """
    Build a mapping of order reference numbers to dispatch dates.

    Args:
        linnworks_orders: List of Linnworks processed orders

    Returns:
        Dict mapping reference_num -> processed_date
    """
    dispatch_map = {}

    for order in linnworks_orders:
        ref_num = order.get('ReferenceNum', '')
        processed_date = parse_linnworks_date(order.get('dProcessedOn'))

        if ref_num and processed_date:
            # Clean up reference number (remove # if present)
            clean_ref = ref_num.replace('#', '').strip()
            dispatch_map[clean_ref] = processed_date

            # Also store with original format
            dispatch_map[ref_num] = processed_date

    return dispatch_map


def get_dispatch_info(
    linnworks_orders: List[Dict]
) -> Dict[str, Dict]:
    """
    Get full dispatch info for each order.

    Linnworks stores Shopify order IDs as reference numbers (e.g., 11454306681209).
    We store by both the raw reference and the integer ID for flexible matching.

    Returns dict with:
        - processed_date: When order was processed/dispatched
        - shipping_method: DPD, etc.
        - tracking_number: If available
    """
    dispatch_info = {}

    for order in linnworks_orders:
        ref_num = order.get('ReferenceNum', '')
        if not ref_num:
            continue

        info = {
            'processed_date': parse_linnworks_date(order.get('dProcessedOn')),
            'shipping_method': order.get('PostalServiceName', ''),
            'customer_name': order.get('cFullName', ''),
            'total_charge': order.get('fTotalCharge', 0),
            'num_items': order.get('nItems', 0),
        }

        # Store by raw reference number
        dispatch_info[ref_num] = info

        # Also store by cleaned reference (no # or whitespace)
        clean_ref = ref_num.replace('#', '').strip()
        dispatch_info[clean_ref] = info

        # Also try to store as integer (Shopify order IDs are numeric)
        try:
            order_id_int = int(clean_ref)
            dispatch_info[order_id_int] = info
        except ValueError:
            pass  # Non-numeric reference, skip

    return dispatch_info
