"""Function discovery for ndev-assistant.

This module provides npe2-based function discovery for the visual workflow
builder. It discovers functions via:

1. npe2 menu contributions (preferred, modern approach)
2. display_name prefix patterns (legacy backwards compatibility)

The menu-based discovery is more robust and doesn't require plugins to
follow a specific naming convention.

Example
-------
>>> from ndev_assistant._discovery import discover_all_operations
>>> operations = discover_all_operations()
>>> for category, funcs in operations.items():
...     print(f"{category}: {len(funcs)} functions")
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    pass


# Mapping from npe2 menu IDs to assistant categories
# These are napari's built-in menu locations plus custom ones
MENU_TO_CATEGORY = {
    # napari built-in menus (where they exist)
    "napari/layers/filter": "Remove noise",
    "napari/layers/segment": "Segment",
    "napari/layers/transform": "Transform",
    "napari/layers/measure": "Measurement",
    # Common custom submenus
    "filtering": "Remove noise",
    "segmentation": "Segment",
    "labeling": "Label",
    "measurement": "Measurement",
    "skeleton": "Skeleton",
    "morphology": "Morphology",
    "visualization": "Visualization",
}

# Legacy display_name prefixes from napari-assistant
DISPLAY_NAME_PREFIXES = {
    "Filtering / noise removal >": "Remove noise",
    "Filtering / background removal >": "Remove background",
    "Filtering >": "Filter",
    "Image math >": "Math",
    "Transform >": "Transform",
    "Projection >": "Projection",
    "Segmentation / binarization >": "Binarize",
    "Segmentation / labeling >": "Label",
    "Segmentation post-processing >": "Process labels",
    "Measurement >": "Measurement",
    "Label neighbor filters >": "Label neighbor filters",
    "Label filters >": "Label filters",
    "Visualization >": "Visualization",
}


def discover_from_menus() -> dict[str, list[tuple[str, Callable]]]:
    """Discover functions from npe2 menu contributions.

    This is the preferred discovery method. It looks at the `menus`
    contribution in each plugin's manifest and maps menu locations
    to assistant categories.

    Returns
    -------
    dict[str, list[tuple[str, Callable]]]
        Dictionary mapping category names to lists of (name, function) tuples.

    Example
    -------
    >>> menu_ops = discover_from_menus()
    >>> print(menu_ops.get("Morphology", []))
    [('Skeletonize Labels', <function>), ...]
    """
    try:
        import npe2
    except ImportError:
        print("npe2 not installed, skipping menu discovery")
        return {}

    pm = npe2.PluginManager.instance()
    operations: dict[str, list[tuple[str, Callable]]] = defaultdict(list)

    for pname, manifest in pm._manifests.items():
        if not manifest.contributions.menus:
            continue

        # Get command ID to function mapping
        command_map = {}
        if manifest.contributions.commands:
            for cmd in manifest.contributions.commands:
                command_map[cmd.id] = cmd

        # Process menu contributions
        for menu_id, menu_items in manifest.contributions.menus.items():
            # Determine category from menu ID
            category = _get_category_from_menu_id(menu_id, pname)
            if category is None:
                continue

            _process_menu_items(
                menu_items,
                manifest,
                command_map,
                category,
                operations
            )

    return dict(operations)


def _process_menu_items(
    menu_items,
    manifest,
    command_map,
    category,
    operations,
    processed_submenus=None
):
    if processed_submenus is None:
        processed_submenus = set()

    for item in menu_items:
        # Handle submenus
        if hasattr(item, "submenu"):
            submenu_id = item.submenu
            if submenu_id in processed_submenus:
                continue
            processed_submenus.add(submenu_id)
            
            # Find the submenu definition in menus
            if submenu_id in manifest.contributions.menus:
                _process_menu_items(
                    manifest.contributions.menus[submenu_id],
                    manifest,
                    command_map,
                    category,
                    operations,
                    processed_submenus
                )
            continue

        # Handle commands
        cmd_id = item.command if hasattr(item, "command") else None
        if cmd_id and cmd_id in command_map:
            cmd = command_map[cmd_id]
            try:
                func = _load_command_function(cmd)
                if func is not None:
                    operations[category].append((cmd.title, func))
            except Exception as e:
                print(f"Failed to load {cmd_id}: {e}")


def discover_from_display_names() -> dict[str, list[tuple[str, Callable]]]:
    """Discover functions from display_name prefix patterns.

    This is the legacy discovery method for backwards compatibility
    with plugins that follow the napari-assistant display_name convention.

    Returns
    -------
    dict[str, list[tuple[str, Callable]]]
        Dictionary mapping category names to lists of (name, function) tuples.
    """
    try:
        import npe2
    except ImportError:
        print("npe2 not installed, skipping display_name discovery")
        return {}

    pm = npe2.PluginManager.instance()
    operations: dict[str, list[tuple[str, Callable]]] = defaultdict(list)

    for pname, manifest in pm._manifests.items():
        if not manifest.contributions.widgets:
            continue

        for widget in manifest.contributions.widgets:
            display_name = widget.display_name or ""

            # Check if display_name matches any known prefix
            for prefix, category in DISPLAY_NAME_PREFIXES.items():
                if display_name.startswith(prefix):
                    # Extract the operation name (after the >)
                    op_name = display_name[len(prefix) :].strip()
                    try:
                        func = _load_widget_function(pname, widget)
                        if func is not None:
                            operations[category].append((op_name, func))
                    except Exception as e:
                        print(f"Failed to load widget {display_name}: {e}")
                    break

    return dict(operations)


@lru_cache(maxsize=1)
def discover_all_operations() -> dict[str, list[tuple[str, Callable]]]:
    """Discover functions from all available sources.

    Combines npe2 menu discovery (preferred) with legacy display_name
    discovery for backwards compatibility.

    Returns
    -------
    dict[str, list[tuple[str, Callable]]]
        Dictionary mapping category names to lists of (name, function) tuples.

    Example
    -------
    >>> operations = discover_all_operations()
    >>> for category, funcs in sorted(operations.items()):
    ...     print(f"{category}: {len(funcs)} operations")
    """
    # Start with display_name patterns (legacy)
    all_ops: dict[str, list[tuple[str, Callable]]] = defaultdict(list)

    display_name_ops = discover_from_display_names()
    for category, funcs in display_name_ops.items():
        all_ops[category].extend(funcs)

    # Add menu-based discovery (preferred, may override)
    menu_ops = discover_from_menus()
    for category, funcs in menu_ops.items():
        all_ops[category].extend(funcs)

    # Remove duplicates (same function name in same category)
    for category in all_ops:
        seen_names = set()
        unique_funcs = []
        for name, func in all_ops[category]:
            if name not in seen_names:
                seen_names.add(name)
                unique_funcs.append((name, func))
        all_ops[category] = unique_funcs

    return dict(all_ops)


def clear_discovery_cache():
    """Clear the discovery cache to force re-discovery.

    Call this if plugins have been installed/uninstalled and you need
    to refresh the available operations.
    """
    discover_all_operations.cache_clear()


def _get_category_from_menu_id(menu_id: str, plugin_name: str) -> str | None:
    """Get assistant category from a menu ID.

    Parameters
    ----------
    menu_id : str
        The npe2 menu ID (e.g., "napari/layers/segment", "my-plugin/filtering")
    plugin_name : str
        The name of the plugin (used as fallback category)

    Returns
    -------
    str or None
        The category name, or None if not found.
    """
    # Check exact match first
    if menu_id in MENU_TO_CATEGORY:
        return MENU_TO_CATEGORY[menu_id]

    # Check if any known menu ID is in the string
    for known_menu, category in MENU_TO_CATEGORY.items():
        if known_menu in menu_id.lower():
            return category

    # Use plugin name as category for custom menus
    # (e.g., "ndev-morphology" menu -> "ndev-morphology" category)
    if "/" in menu_id:
        # Extract the submenu part after plugin name
        parts = menu_id.split("/")
        if len(parts) >= 2:
            return parts[-1].replace("-", " ").replace("_", " ").title()

    return plugin_name.replace("-", " ").replace("_", " ").title()


def _load_command_function(cmd) -> Callable | None:
    """Load the Python function for a command.

    Parameters
    ----------
    cmd : npe2 Command
        The command contribution.

    Returns
    -------
    Callable or None
        The loaded function, or None if loading failed.
    """
    if not hasattr(cmd, "python_name") or not cmd.python_name:
        return None

    try:
        module_path, func_name = cmd.python_name.rsplit(":", 1)
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except Exception:
        return None


def _load_widget_function(plugin_name: str, widget) -> Callable | None:
    """Load the factory function for a widget.

    Parameters
    ----------
    plugin_name : str
        The name of the plugin.
    widget : npe2 WidgetContribution
        The widget contribution.

    Returns
    -------
    Callable or None
        The loaded function, or None if loading failed.
    """
    try:
        import npe2

        for contrib in npe2.PluginManager.instance().iter_widgets():
            if (
                contrib.plugin_name == plugin_name
                and contrib.display_name == widget.display_name
            ):
                return contrib.get_callable()
    except Exception:
        pass
    return None
