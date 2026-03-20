"""
Shopify API Client with pagination and rate limit handling.
"""

import os
import time
import re
from typing import Optional, Generator
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ShopifyClient:
    """Client for Shopify Admin API with pagination and rate limiting."""

    def __init__(
        self,
        store_domain: Optional[str] = None,
        access_token: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.store_domain = store_domain or os.environ.get("SHOPIFY_STORE_DOMAIN")
        self.access_token = access_token or os.environ.get("SHOPIFY_ACCESS_TOKEN")
        self.api_version = api_version or os.environ.get("SHOPIFY_API_VERSION", "2024-07")

        if not self.store_domain:
            raise ValueError("SHOPIFY_STORE_DOMAIN environment variable is required")
        if not self.access_token:
            raise ValueError("SHOPIFY_ACCESS_TOKEN environment variable is required")

        # Clean domain
        self.store_domain = self.store_domain.replace("https://", "").replace("http://", "").rstrip("/")

        self.base_url = f"https://{self.store_domain}/admin/api/{self.api_version}"

        # Setup session with retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        })

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Handle rate limiting with exponential backoff."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "2")
            try:
                wait_time = float(retry_after)
            except ValueError:
                wait_time = 2.0
            time.sleep(wait_time + 0.5)

    def _get_with_rate_limit(self, url: str, params: Optional[dict] = None) -> requests.Response:
        """Make GET request with rate limit handling."""
        max_retries = 5
        for attempt in range(max_retries):
            response = self.session.get(url, params=params)
            if response.status_code == 429:
                self._handle_rate_limit(response)
                continue
            return response
        return response

    def _parse_link_header(self, link_header: str) -> Optional[str]:
        """Parse Link header to get next page URL."""
        if not link_header:
            return None

        # Find rel="next" link
        links = link_header.split(",")
        for link in links:
            if 'rel="next"' in link:
                match = re.search(r'<([^>]+)>', link)
                if match:
                    return match.group(1)
        return None

    def _paginate(self, endpoint: str, params: Optional[dict] = None, resource_key: str = None) -> Generator[dict, None, None]:
        """Generator that handles pagination through all results."""
        url = f"{self.base_url}/{endpoint}"

        while url:
            response = self._get_with_rate_limit(url, params)
            response.raise_for_status()

            data = response.json()

            # Yield each item from the resource
            items = data.get(resource_key, []) if resource_key else data
            for item in items:
                yield item

            # Get next page URL from Link header
            link_header = response.headers.get("Link", "")
            url = self._parse_link_header(link_header)
            params = None  # Params are included in the link URL

    def get_orders(
        self,
        created_at_min: Optional[datetime] = None,
        created_at_max: Optional[datetime] = None,
        status: str = "any",
        limit: int = 250,
    ) -> Generator[dict, None, None]:
        """
        Fetch orders with pagination.

        Args:
            created_at_min: Minimum creation date
            created_at_max: Maximum creation date
            status: Order status filter
            limit: Results per page (max 250)

        Yields:
            Order dictionaries
        """
        params = {
            "status": status,
            "limit": min(limit, 250),
            "fields": "id,name,created_at,processed_at,total_price,total_discounts,"
                      "subtotal_price,total_shipping_price_set,total_tax,currency,"
                      "current_subtotal_price,current_total_discounts,line_items,fulfillments,"
                      "discount_codes,discount_applications,customer,shipping_address,billing_address",
        }

        if created_at_min:
            params["created_at_min"] = created_at_min.isoformat()
        if created_at_max:
            params["created_at_max"] = created_at_max.isoformat()

        yield from self._paginate("orders.json", params, "orders")

    def get_variant(self, variant_id: int) -> Optional[dict]:
        """Fetch a single variant by ID."""
        url = f"{self.base_url}/variants/{variant_id}.json"
        response = self._get_with_rate_limit(url)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json().get("variant")

    def get_inventory_item(self, inventory_item_id: int) -> Optional[dict]:
        """Fetch a single inventory item by ID."""
        url = f"{self.base_url}/inventory_items/{inventory_item_id}.json"
        response = self._get_with_rate_limit(url)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json().get("inventory_item")

    def get_variant_cost(self, variant_id: int) -> Optional[float]:
        """
        Get the cost for a variant by looking up its inventory item.

        Args:
            variant_id: The variant ID

        Returns:
            The cost as a float, or None if not found
        """
        variant = self.get_variant(variant_id)
        if not variant:
            return None

        inventory_item_id = variant.get("inventory_item_id")
        if not inventory_item_id:
            return None

        inventory_item = self.get_inventory_item(inventory_item_id)
        if not inventory_item:
            return None

        cost = inventory_item.get("cost")
        if cost is not None:
            try:
                return float(cost)
            except (ValueError, TypeError):
                return None

        return None

    def get_customer_order_history(self, customer_id: int) -> list:
        """
        Fetch all orders for a specific customer.

        Args:
            customer_id: The Shopify customer ID

        Returns:
            List of order dictionaries with id, name, created_at
        """
        if not customer_id:
            return []

        params = {
            "customer_id": customer_id,
            "status": "any",
            "limit": 250,
            "fields": "id,name,created_at,processed_at",
        }

        orders = list(self._paginate("orders.json", params, "orders"))
        return orders


    def get_products(
        self,
        status: str = "active",
        limit: int = 250,
    ) -> Generator[dict, None, None]:
        """
        Fetch all products with pagination.

        Args:
            status: Product status filter (active, archived, draft, any)
            limit: Results per page (max 250)

        Yields:
            Product dictionaries
        """
        params = {
            "status": status,
            "limit": min(limit, 250),
        }

        yield from self._paginate("products.json", params, "products")

    def get_product_metafields(self, product_id: int) -> list:
        """
        Fetch all metafields for a product.

        Args:
            product_id: The Shopify product ID

        Returns:
            List of metafield dictionaries
        """
        url = f"{self.base_url}/products/{product_id}/metafields.json"
        response = self._get_with_rate_limit(url)

        if response.status_code == 404:
            return []

        response.raise_for_status()
        return response.json().get("metafields", [])


def test_connection() -> bool:
    """Test if Shopify connection works."""
    try:
        client = ShopifyClient()
        # Try to fetch one order to verify connection
        url = f"{client.base_url}/orders.json?limit=1"
        response = client._get_with_rate_limit(url)
        return response.status_code == 200
    except Exception:
        return False
