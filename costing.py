"""
Costing module for variant cost lookups with caching.
"""

from typing import Optional, Dict, Tuple
from dataclasses import dataclass
import streamlit as st

from shopify_client import ShopifyClient


@dataclass
class CostLookupResult:
    """Result of a cost lookup."""
    cost: Optional[float]
    found: bool
    sku: Optional[str] = None
    variant_id: Optional[int] = None


class CostCache:
    """
    In-memory cache for variant costs.
    Uses both session state and st.cache_data for persistence.
    """

    def __init__(self):
        # Initialize session state cache if not exists
        if "cost_cache" not in st.session_state:
            st.session_state.cost_cache = {}
        if "missing_costs" not in st.session_state:
            st.session_state.missing_costs = set()

    @property
    def cache(self) -> Dict[int, Optional[float]]:
        return st.session_state.cost_cache

    @property
    def missing_costs(self) -> set:
        return st.session_state.missing_costs

    def get(self, variant_id: int) -> Tuple[Optional[float], bool]:
        """
        Get cost from cache.

        Returns:
            Tuple of (cost, is_cached)
        """
        if variant_id in self.cache:
            return self.cache[variant_id], True
        return None, False

    def set(self, variant_id: int, cost: Optional[float]) -> None:
        """Set cost in cache."""
        self.cache[variant_id] = cost
        if cost is None:
            self.missing_costs.add(variant_id)

    def clear(self) -> None:
        """Clear the cache."""
        st.session_state.cost_cache = {}
        st.session_state.missing_costs = set()


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_variant_cost(_client_config: tuple, variant_id: int) -> Optional[float]:
    """
    Fetch variant cost from Shopify API.
    Cached for 1 hour.

    Args:
        _client_config: Tuple of (store_domain, access_token, api_version) for cache key
        variant_id: The variant ID to look up

    Returns:
        The cost as float or None
    """
    store_domain, access_token, api_version = _client_config
    client = ShopifyClient(store_domain, access_token, api_version)
    return client.get_variant_cost(variant_id)


class CostingService:
    """Service for looking up and caching variant costs."""

    def __init__(self, client: ShopifyClient):
        self.client = client
        self.cache = CostCache()
        # Create config tuple for cache key
        self._client_config = (
            client.store_domain,
            client.access_token,
            client.api_version,
        )

    def get_variant_cost(self, variant_id: int) -> CostLookupResult:
        """
        Get cost for a variant, using cache when available.

        Args:
            variant_id: The variant ID

        Returns:
            CostLookupResult with cost and found status
        """
        if not variant_id:
            return CostLookupResult(cost=None, found=False, variant_id=variant_id)

        # Check in-memory cache first
        cached_cost, is_cached = self.cache.get(variant_id)
        if is_cached:
            return CostLookupResult(
                cost=cached_cost,
                found=cached_cost is not None,
                variant_id=variant_id,
            )

        # Fetch from API (with st.cache_data caching)
        cost = _fetch_variant_cost(self._client_config, variant_id)

        # Store in in-memory cache
        self.cache.set(variant_id, cost)

        return CostLookupResult(
            cost=cost,
            found=cost is not None,
            variant_id=variant_id,
        )

    def get_line_item_cost(self, line_item: dict) -> CostLookupResult:
        """
        Get cost for a line item.

        Args:
            line_item: Shopify line item dict

        Returns:
            CostLookupResult with cost and metadata
        """
        variant_id = line_item.get("variant_id")
        sku = line_item.get("sku")

        result = self.get_variant_cost(variant_id)
        result.sku = sku
        result.variant_id = variant_id

        return result

    def calculate_line_cogs(self, line_item: dict) -> Tuple[float, bool, Optional[float]]:
        """
        Calculate COGS for a line item.

        Args:
            line_item: Shopify line item dict

        Returns:
            Tuple of (line_cogs, has_cost, unit_cost)
        """
        quantity = int(line_item.get("quantity", 0))
        cost_result = self.get_line_item_cost(line_item)

        if cost_result.found and cost_result.cost is not None:
            unit_cost = cost_result.cost
            line_cogs = unit_cost * quantity
            return line_cogs, True, unit_cost
        else:
            # Missing cost - treat as 0 but flag it
            return 0.0, False, None

    def clear_cache(self) -> None:
        """Clear all caches."""
        self.cache.clear()
        _fetch_variant_cost.clear()


# Packaging cost constants
PACKAGING_COSTS = {
    "small": {
        "Box": 1.11,
        "Wool": 1.00,
        "Coolant": 0.60,
        "Shipping": 6.45,
        "Pick & Pack": 3.50,
    },
    "large": {
        "Box": 1.36,
        "Wool": 1.50,
        "Coolant": 1.00,
        "Shipping": 6.45,
        "Pick & Pack": 3.50,
    },
}


def get_packaging_totals() -> Dict[str, float]:
    """Get total packaging costs for each box type."""
    return {
        "small": sum(PACKAGING_COSTS["small"].values()),
        "large": sum(PACKAGING_COSTS["large"].values()),
    }


def determine_box_type(item_count: int) -> Tuple[str, int]:
    """
    Determine box type and multiplier based on total items in box.

    Args:
        item_count: Total number of items (sum of quantities)

    Returns:
        Tuple of (box_type, box_multiplier)
    """
    if item_count <= 10:
        return "small", 1
    elif item_count <= 16:
        return "large", 1
    else:
        # Over 16 items = 2 large boxes
        return "large", 2


def calculate_packaging_cost(item_count: int) -> Tuple[float, str, int, Dict[str, float]]:
    """
    Calculate total packaging cost for an order.

    Args:
        item_count: Total number of items (sum of quantities)

    Returns:
        Tuple of (total_cost, box_type, multiplier, breakdown_dict)
    """
    box_type, multiplier = determine_box_type(item_count)
    base_costs = PACKAGING_COSTS[box_type]

    # Apply multiplier to each cost component
    breakdown = {k: v * multiplier for k, v in base_costs.items()}
    total = sum(breakdown.values())

    return total, box_type, multiplier, breakdown
