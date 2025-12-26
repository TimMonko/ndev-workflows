"""Category definitions for ndev-assistant.

This module defines the categories used to organize operations in the
visual workflow builder. Categories provide:

- Grouping of related operations
- Icons for the UI
- Input/output type expectations
- Suggested next steps after each category

The category system is compatible with napari-assistant but uses
npe2 menu-based discovery rather than display_name parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class Category:
    """A category of image processing operations.

    Attributes
    ----------
    name : str
        Display name for the category.
    description : str
        Longer description shown as tooltip.
    icon : str
        Icon name or emoji for the UI.
    input_types : tuple[str, ...]
        Expected input layer types (e.g., "image", "labels").
    output_type : str
        Expected output layer type.
    menu_ids : tuple[str, ...]
        npe2 menu IDs that map to this category.
    next_steps : tuple[str, ...]
        Suggested categories to apply after this one.

    """

    name: str
    description: str
    icon: str = "⚙️"
    input_types: tuple[str, ...] = ("image",)
    output_type: str = "image"
    menu_ids: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


# Define the standard categories
# These align with napari-assistant but organized for npe2 discovery
CATEGORIES: dict[str, Category] = {
    "Remove noise": Category(
        name="Remove noise",
        description="Apply filters to reduce noise in images.",
        icon="🔇",
        input_types=("image",),
        output_type="image",
        menu_ids=("napari/layers/filter", "filtering", "noise"),
        next_steps=("Remove background", "Binarize", "Segment"),
    ),
    "Remove background": Category(
        name="Remove background",
        description="Remove or subtract background from images.",
        icon="🌑",
        input_types=("image",),
        output_type="image",
        menu_ids=("background",),
        next_steps=("Binarize", "Segment"),
    ),
    "Filter": Category(
        name="Filter",
        description="Apply general image filters.",
        icon="🎛️",
        input_types=("image",),
        output_type="image",
        menu_ids=("filter",),
        next_steps=("Binarize", "Segment"),
    ),
    "Transform": Category(
        name="Transform",
        description="Apply geometric transformations to images.",
        icon="🔄",
        input_types=("image",),
        output_type="image",
        menu_ids=("napari/layers/transform", "transform"),
        next_steps=("Filter", "Segment"),
    ),
    "Projection": Category(
        name="Projection",
        description="Project 3D data to 2D.",
        icon="📊",
        input_types=("image",),
        output_type="image",
        menu_ids=("projection",),
        next_steps=("Filter", "Segment"),
    ),
    "Binarize": Category(
        name="Binarize",
        description="Convert images to binary masks.",
        icon="◐",
        input_types=("image",),
        output_type="labels",
        menu_ids=("segmentation/binarization", "binarize", "threshold"),
        next_steps=("Label", "Process labels"),
    ),
    "Segment": Category(
        name="Segment",
        description="Segment images into regions.",
        icon="🔲",
        input_types=("image",),
        output_type="labels",
        menu_ids=("napari/layers/segment", "segmentation", "segment"),
        next_steps=("Label", "Process labels"),
    ),
    "Label": Category(
        name="Label",
        description="Create or modify labeled regions.",
        icon="🏷️",
        input_types=("labels",),
        output_type="labels",
        menu_ids=("segmentation/labeling", "labeling", "label"),
        next_steps=("Process labels", "Measurement"),
    ),
    "Process labels": Category(
        name="Process labels",
        description="Post-processing operations on label images.",
        icon="🔧",
        input_types=("labels",),
        output_type="labels",
        menu_ids=("segmentation post-processing", "post-processing"),
        next_steps=("Measurement", "Visualization"),
    ),
    "Morphology": Category(
        name="Morphology",
        description="Morphological analysis operations.",
        icon="🦴",
        input_types=("labels",),
        output_type="labels",
        menu_ids=("morphology", "skeleton"),
        next_steps=("Measurement", "Visualization"),
    ),
    "Measurement": Category(
        name="Measurement",
        description="Measure properties of regions.",
        icon="📏",
        input_types=("image", "labels"),
        output_type="dataframe",
        menu_ids=("napari/layers/measure", "measurement", "measure"),
        next_steps=("Visualization",),
    ),
    "Visualization": Category(
        name="Visualization",
        description="Visualize analysis results.",
        icon="👁️",
        input_types=("image", "labels"),
        output_type="image",
        menu_ids=("visualization",),
        next_steps=(),
    ),
}


def get_category(name: str) -> Category | None:
    """Get a category by name.

    Parameters
    ----------
    name : str
        The category name.

    Returns
    -------
    Category or None
        The category, or None if not found.
    """
    return CATEGORIES.get(name)


def get_category_for_menu(menu_id: str) -> Category | None:
    """Find the category that matches a menu ID.

    Parameters
    ----------
    menu_id : str
        The npe2 menu ID.

    Returns
    -------
    Category or None
        The matching category, or None if no match.
    """
    menu_lower = menu_id.lower()
    for category in CATEGORIES.values():
        for cat_menu in category.menu_ids:
            if cat_menu in menu_lower:
                return category
    return None


def get_next_step_categories(current_category: str) -> list[Category]:
    """Get suggested next categories after the current one.

    Parameters
    ----------
    current_category : str
        The name of the current category.

    Returns
    -------
    list[Category]
        List of suggested next categories.
    """
    category = CATEGORIES.get(current_category)
    if category is None:
        return []

    return [
        CATEGORIES[name]
        for name in category.next_steps
        if name in CATEGORIES
    ]
