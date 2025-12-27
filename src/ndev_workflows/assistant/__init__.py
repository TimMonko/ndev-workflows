"""Assistant module for ndev-workflows.

This module provides the visual workflow builder (Assistant) functionality,
including function discovery and categorization.
"""

from ._categories import get_icon_for_category
from ._discovery import clear_discovery_cache, discover_all_operations

__all__ = [
    'get_icon_for_category',
    'discover_all_operations',
    'clear_discovery_cache',
]
