"""Type classification utilities for parameter type inference.

This module provides shared constants and functions for determining whether
a parameter expects a napari Layer object, raw numpy data, or a literal value.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# Type annotations that indicate a parameter expects a napari Layer object
LAYER_TYPES = (
    'napari.layers.Image',
    'napari.layers.Labels',
    'napari.layers.Points',
    'napari.layers.Shapes',
    'napari.layers.Surface',
    'napari.layers.Vectors',
)

# Type annotations that indicate a parameter expects numpy array data
DATA_TYPES = (
    'napari.types.ImageData',
    'napari.types.LabelsData',
    'napari.types.Image',  # magicgui data annotation
    'napari.types.Labels',  # magicgui data annotation
    'napari.types.PointsData',
    'napari.types.ShapesData',
    'napari.types.SurfaceData',
    'napari.types.VectorsData',
    'numpy.ndarray',
    'np.ndarray',
    'ndarray',
    'ArrayLike',
)


def classify_param_type(annotation_str: str) -> str:
    """Classify a parameter type annotation string.

    Parameters
    ----------
    annotation_str : str
        String representation of a type annotation

    Returns
    -------
    str
        One of: 'layer', 'data', 'literal'
    """
    if any(x in annotation_str for x in LAYER_TYPES):
        return 'layer'
    elif any(x in annotation_str for x in DATA_TYPES):
        return 'data'
    else:
        return 'literal'


def expects_layer_object(sig, param_name: str) -> bool:
    """Check if a parameter expects a napari Layer object vs just data.

    Parameters
    ----------
    sig : inspect.Signature or None
        Function signature
    param_name : str
        Parameter name to check

    Returns
    -------
    bool
        True if parameter expects a Layer object, False if it expects data
    """
    if sig is None or param_name not in sig.parameters:
        return False

    param = sig.parameters[param_name]
    if param.annotation is inspect.Parameter.empty:
        return True  # No type hint - default to layer object

    return classify_param_type(str(param.annotation)) == 'layer'


def extract_param_types(func: Any, param_names: list[str]) -> dict[str, str]:
    """Extract parameter types from function signature.

    For magicgui functions (MagicFactory or FunctionGui), this uses the resolved
    signature which has proper type objects instead of strings. This gives more
    accurate type information since magicgui has already resolved forward refs.

    Parameters
    ----------
    func : callable
        Function to inspect (can be MagicFactory, FunctionGui, or regular function)
    param_names : list[str]
        Parameter names to extract types for

    Returns
    -------
    dict[str, str]
        Mapping of param_name to type string ('layer', 'data', 'literal')
    """
    import typing

    param_types = {}
    sig = None

    try:
        # Check if this is a MagicFactory (which is a partial wrapping FunctionGui)
        # Note: _is_magic_factory exists but can be None, so check type name instead
        if type(func).__name__ == 'MagicFactory':
            # Create FunctionGui widget to get magicgui's resolved signature
            try:
                widget = func()
                sig = (
                    widget.__signature__
                )  # MagicSignature with resolved types
            except Exception:
                # Fallback to raw function if widget creation fails
                raw_func = func.keywords.get('function', func)
                sig = inspect.signature(raw_func)

        # Check if this is already a FunctionGui instance
        elif (
            hasattr(func, '__signature__')
            and type(func).__name__ == 'FunctionGui'
        ):
            sig = func.__signature__  # Already have MagicSignature

        # Regular function - use standard signature
        else:
            sig = inspect.signature(func)

        # Extract type for each parameter
        for param_name in param_names:
            if param_name not in sig.parameters:
                continue

            param = sig.parameters[param_name]
            annotation = param.annotation

            # Handle empty annotation
            if annotation is inspect.Parameter.empty:
                param_types[param_name] = 'data'  # Default for untyped params
                continue

            # Unwrap Annotated[type, metadata] if present
            # magicgui wraps types in Annotated with widget options
            if (
                hasattr(typing, 'get_origin')
                and typing.get_origin(annotation) is typing.Annotated
            ):
                args = typing.get_args(annotation)
                if args:
                    annotation = args[0]  # Get base type

            # Classify the type
            # For magicgui, annotation is already a type object, not a string
            # But classify_param_type expects a string, so convert
            if isinstance(annotation, str):
                type_str = annotation
            elif hasattr(annotation, '__module__') and hasattr(
                annotation, '__name__'
            ):
                # Type object - format as module.name
                # For napari types, use short module path (e.g., napari.layers.Labels not napari.layers.labels.labels.Labels)
                if annotation.__module__.startswith('napari.'):
                    module_parts = annotation.__module__.split('.')
                    if len(module_parts) >= 2:
                        # Use first two parts (napari.layers, napari.types)
                        short_module = '.'.join(module_parts[:2])
                        type_str = f'{short_module}.{annotation.__name__}'
                    else:
                        type_str = (
                            f'{annotation.__module__}.{annotation.__name__}'
                        )
                else:
                    type_str = f'{annotation.__module__}.{annotation.__name__}'
            elif hasattr(annotation, '__name__'):
                # Type without module
                type_str = annotation.__name__
            else:
                # Fallback to string representation
                type_str = str(annotation)

            param_types[param_name] = classify_param_type(type_str)

    except Exception:
        # If signature inspection fails, return empty dict
        # Resolution will fall back to signature inspection at runtime
        return {}

    return param_types


def extract_type_strings(
    func: Any, param_names: list[str], include_return: bool = True
) -> dict[str, str]:
    """Extract full type annotation strings from function signature.

    This extracts the actual type annotations (e.g., 'napari.types.ImageData',
    'float', 'napari.layers.Labels') rather than classifications. Useful for
    storing precise type information in workflow YAML files.

    Parameters
    ----------
    func : callable
        Function to inspect (can be MagicFactory, FunctionGui, or regular function)
    param_names : list[str]
        Parameter names to extract types for
    include_return : bool, optional
        Whether to include the return type under key 'return', by default True

    Returns
    -------
    dict[str, str]
        Mapping of param_name (and optionally 'return') to type string
    """
    import typing

    type_strings = {}
    sig = None

    try:
        # Check if this function was unwrapped from a MagicFactory
        # If so, use the parent factory for type extraction (better type resolution)
        parent_factory = getattr(func, '_ndev_parent_factory', None)
        if (
            parent_factory is not None
            and type(parent_factory).__name__ == 'MagicFactory'
        ):
            func = parent_factory  # Use the factory for type extraction

        # Check if this is a MagicFactory (which is a partial wrapping FunctionGui)
        # Note: _is_magic_factory exists but can be None, so check type name instead
        if type(func).__name__ == 'MagicFactory':
            # Create FunctionGui widget to get magicgui's resolved signature
            try:
                widget = func()
                sig = (
                    widget.__signature__
                )  # MagicSignature with resolved types
            except Exception:
                # Fallback to raw function if widget creation fails
                raw_func = func.keywords.get('function', func)
                sig = inspect.signature(raw_func)

        # Check if this is already a FunctionGui instance
        elif (
            hasattr(func, '__signature__')
            and type(func).__name__ == 'FunctionGui'
        ):
            sig = func.__signature__  # Already have MagicSignature

        # Regular function - use standard signature
        else:
            sig = inspect.signature(func)

        # Helper function to convert annotation to string
        def annotation_to_string(annotation) -> str:
            if annotation is inspect.Parameter.empty:
                return 'Any'

            # Unwrap Annotated[type, metadata] if present
            if (
                hasattr(typing, 'get_origin')
                and typing.get_origin(annotation) is typing.Annotated
            ):
                args = typing.get_args(annotation)
                if args:
                    annotation = args[0]  # Get base type

            # Convert type to string
            if isinstance(annotation, str):
                return annotation
            elif hasattr(annotation, '__module__') and hasattr(
                annotation, '__name__'
            ):
                # Type object - format as module.name
                # For napari types, use short module path
                if annotation.__module__.startswith('napari.'):
                    module_parts = annotation.__module__.split('.')
                    if len(module_parts) >= 2:
                        # Use first two parts (napari.layers, napari.types)
                        short_module = '.'.join(module_parts[:2])
                        return f'{short_module}.{annotation.__name__}'
                return f'{annotation.__module__}.{annotation.__name__}'
            elif hasattr(annotation, '__name__'):
                # Type without module
                return annotation.__name__
            else:
                # Fallback to string representation
                return str(annotation)

        # Extract type for each parameter
        for param_name in param_names:
            if param_name not in sig.parameters:
                continue

            param = sig.parameters[param_name]
            type_strings[param_name] = annotation_to_string(param.annotation)

        # Extract return type if requested
        if (
            include_return
            and sig.return_annotation is not inspect.Signature.empty
        ):
            type_strings['return'] = annotation_to_string(
                sig.return_annotation
            )

    except Exception:
        # If signature inspection fails, return empty dict
        pass

    return type_strings
