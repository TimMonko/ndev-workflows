"""LayerDataTuple unwrapping utilities.

This module handles the conversion of LayerDataTuple format (used by napari widgets)
to the format expected by workflow functions (either Layer objects or raw data).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ._resolution import FakeLayer
from ._types import expects_layer_object

if TYPE_CHECKING:
    pass


def is_layer_data_tuple(value) -> bool:
    """Check if value matches LayerDataTuple format: (data, dict, str).

    Parameters
    ----------
    value : any
        Value to check

    Returns
    -------
    bool
        True if value is a LayerDataTuple (data, metadata, layer_type)
    """
    if not isinstance(value, tuple) or len(value) != 3:
        return False
    _data, metadata, layer_type = value
    return isinstance(metadata, dict) and isinstance(layer_type, str)


def needs_unwrapping(sig) -> bool:
    """Check if function has any parameters expecting Layer objects.

    If yes, we need to wrap it to convert LayerDataTuples to fake layer objects.

    Parameters
    ----------
    sig : inspect.Signature or None
        Function signature

    Returns
    -------
    bool
        True if function needs LayerDataTuple unwrapping
    """
    if sig is None:
        return False

    for param_name in sig.parameters:
        if expects_layer_object(sig, param_name):
            return True
    return False


def unwrap_layer_data_tuples(func, sig, *args, **kwargs):
    """Wrapper that converts LayerDataTuple inputs to layer-like objects.

    If an argument is a tuple matching LayerDataTuple format (data, metadata, type),
    create a FakeLayer object with .data and .name extracted from the tuple.

    Parameters
    ----------
    func : callable
        Function to wrap
    sig : inspect.Signature
        Function signature
    *args : any
        Positional arguments (may include LayerDataTuples)
    **kwargs : any
        Keyword arguments (may include LayerDataTuples)

    Returns
    -------
    any
        Result of calling func with unwrapped arguments
    """
    # Convert positional args
    new_args = []
    param_names = list(sig.parameters.keys())
    for i, arg in enumerate(args):
        if is_layer_data_tuple(arg):
            # Check if this parameter expects a layer object
            if i < len(param_names) and expects_layer_object(
                sig, param_names[i]
            ):
                data, metadata, layer_type = arg
                name = metadata.get('name', 'unnamed')
                new_args.append(FakeLayer(data, name))
            else:
                # Just extract data
                new_args.append(arg[0])
        else:
            new_args.append(arg)

    # Convert kwargs
    new_kwargs = {}
    for key, value in kwargs.items():
        if is_layer_data_tuple(value):
            if expects_layer_object(sig, key):
                data, metadata, layer_type = value
                name = metadata.get('name', 'unnamed')
                new_kwargs[key] = FakeLayer(data, name)
            else:
                # Just extract data
                new_kwargs[key] = value[0]
        else:
            new_kwargs[key] = value

    return func(*new_args, **new_kwargs)


def create_unwrapper(func, sig):
    """Create a partial wrapper for LayerDataTuple unwrapping.

    Parameters
    ----------
    func : callable
        Function to wrap
    sig : inspect.Signature
        Function signature

    Returns
    -------
    functools.partial
        Wrapped function that will unwrap LayerDataTuples
    """
    return partial(unwrap_layer_data_tuples, func, sig)
