"""Assistant module for ndev-workflows.

This module provides the visual workflow builder (Assistant) functionality,
including function discovery and categorization.
"""

from ._categories import CATEGORIES, Category, get_category
from ._discovery import discover_all_operations, clear_discovery_cache

__all__ = [
    "CATEGORIES",
    "Category",
    "get_category",
    "discover_all_operations",
    "clear_discovery_cache",
]
