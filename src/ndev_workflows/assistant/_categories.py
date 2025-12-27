"""Category definitions for ndev-assistant.

This module defines icons for known categories.
Discovery is dynamic, so we only map icons here.
"""

from __future__ import annotations

# Default icon for unknown categories
DEFAULT_ICON = '⚙️'

# Icons for known categories (including legacy ones)
CATEGORY_ICONS: dict[str, str] = {
    'Remove noise': '🔇',
    'Remove background': '🌑',
    'Filter': '🎛️',
    'Transform': '🔄',
    'Projection': '📊',
    'Binarize': '⚫',
    'Segment': '🔲',
    'Label': '🏷️',
    'Process labels': '🔧',
    'Morphology': '🦴',
    'Measurement': '📏',
    'Label neighbor filters': '🏘️',
    'Label filters': '🔍',
    'Visualization': '👁️',
    'Math': '➕',
}


def get_icon_for_category(category: str) -> str:
    """Get the icon for a category name."""
    return CATEGORY_ICONS.get(category, DEFAULT_ICON)
