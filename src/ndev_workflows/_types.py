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

    Parameters
    ----------
    func : callable
        Function to inspect
    param_names : list[str]
        Parameter names to extract types for

    Returns
    -------
    dict[str, str]
        Mapping of param_name to type string ('layer', 'data', 'literal')
    """
    param_types = {}

    try:
        # For MagicFactory, create widget to get annotated signature
        if hasattr(func, '_is_magic_factory') and func._is_magic_factory:
            try:
                widget = func()
                sig = inspect.signature(widget)
            except Exception:
                sig = inspect.signature(func)
        else:
            sig = inspect.signature(func)

        for param_name in param_names:
            if param_name not in sig.parameters:
                continue

            param = sig.parameters[param_name]
            if param.annotation is inspect.Parameter.empty:
                param_types[param_name] = 'data'  # Default for untyped params
            else:
                param_types[param_name] = classify_param_type(
                    str(param.annotation)
                )

    except Exception:
        # If signature inspection fails, return empty dict
        # Resolution will fall back to signature inspection at runtime
        return {}

    return param_types
