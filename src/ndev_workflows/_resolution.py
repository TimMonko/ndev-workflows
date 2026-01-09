"""Layer resolution utilities for workflows.

This module handles resolving layer name references to actual layer objects or data,
with proper type-aware wrapping/unwrapping for batch and interactive workflows.
"""

from __future__ import annotations

import inspect
from functools import partial
from typing import TYPE_CHECKING

from ._types import expects_layer_object

if TYPE_CHECKING:
    pass


class FakeLayer:
    """Minimal Layer wrapper for batch workflows without viewer.

    When a function expects a napari Layer object (with .data and .name attributes)
    but we're running in batch mode without access to real layers, this provides
    the minimal interface to make the function work.
    """

    def __init__(self, data, name: str):
        self.data = data
        self.name = name

    def __repr__(self) -> str:
        return f'FakeLayer(name={self.name}, data.shape={getattr(self.data, "shape", "?")})'


def get_func_and_signature(func):
    """Extract actual function and signature from potentially wrapped function.

    Handles:
    - Regular functions
    - functools.partial wrappers
    - LayerDataTuple unwrapping wrappers

    Returns
    -------
    tuple[callable, inspect.Signature | None]
        The unwrapped function and its signature (or None if unavailable)
    """
    if not isinstance(func, partial):
        try:
            return func, inspect.signature(func)
        except (ValueError, TypeError):
            return func, None

    # Handle partial functions
    actual_func = func.func

    # Check if this is our LayerDataTuple wrapper
    if (
        hasattr(actual_func, '__self__')
        and hasattr(actual_func.__self__, '_unwrap_layer_data_tuple_wrapper')
        and len(func.args) >= 2
    ):
        # Our wrapper: partial(_unwrap_layer_data_tuple_wrapper, actual_func, sig)
        return func.args[0], func.args[1]  # (actual_func, sig)

    # Regular partial
    try:
        return actual_func, inspect.signature(actual_func)
    except (ValueError, TypeError):
        return actual_func, None


def should_pass_layer_object(func, sig, param_name: str) -> bool:
    """Determine if parameter expects Layer object vs raw data.

    Checks stored types first (from YAML), falls back to signature inspection.

    Parameters
    ----------
    func : callable
        Function to check (may have _ndev_param_types attribute)
    sig : inspect.Signature or None
        Function signature
    param_name : str
        Parameter name to check

    Returns
    -------
    bool
        True if parameter expects Layer object, False for raw data
    """
    # Check if function has stored parameter types (from YAML spec)
    param_types = getattr(func, '_ndev_param_types', {})
    if param_name in param_types:
        return param_types[param_name] == 'layer'

    # Fall back to signature inspection
    return expects_layer_object(sig, param_name)


def resolve_param_value(
    value,
    param_name: str,
    func,
    sig,
    tasks: dict,
    layer_objects: dict,
):
    """Resolve a single parameter value based on type requirements.

    Handles:
    - Task references (computed or raw data)
    - Viewer layer references
    - Already-resolved Layer objects
    - Literal values

    Parameters
    ----------
    value : any
        Value to resolve
    param_name : str
        Parameter name (for type checking)
    func : callable
        Function that will receive this parameter
    sig : inspect.Signature or None
        Function signature
    tasks : dict
        Task graph (to check for task references)
    layer_objects : dict
        Mapping of layer names to Layer objects

    Returns
    -------
    any
        Resolved value (Layer object, numpy array, or literal)
    """
    # If value references a task, check if it's computed or raw data
    if isinstance(value, str) and value in tasks:
        referenced_task = tasks[value]
        is_computed_task = isinstance(referenced_task, tuple)

        if is_computed_task:
            # Leave as string reference for dask to resolve
            # NOTE: dask can't resolve kwargs, only positional args!
            return value

        # Raw data in tasks - check if function needs Layer wrapper
        if should_pass_layer_object(func, sig, param_name):
            # Function needs Layer object
            if value in layer_objects:
                return layer_objects[value]  # Use real Layer from viewer
            else:
                # Batch mode: wrap data in FakeLayer
                return FakeLayer(referenced_task, value)
        else:
            # Function wants raw data
            return referenced_task

    # If value references viewer layer, resolve it
    if isinstance(value, str) and value in layer_objects:
        if should_pass_layer_object(func, sig, param_name):
            return layer_objects[value]  # Pass Layer object
        else:
            return layer_objects[value].data  # Pass data array

    # If value is already a Layer object
    if hasattr(value, 'data') and hasattr(value, 'name'):
        if should_pass_layer_object(func, sig, param_name):
            return value  # Keep Layer object
        else:
            return value.data  # Extract data array

    # Literal value (number, bool, string, etc.)
    return value


def resolve_layer_references(tasks: dict, viewer) -> dict:
    """Resolve INPUT layer name strings to actual layers or layer data.

    Resolves string references to viewer layers, determining whether to pass
    the Layer object or just its data based on function signatures and stored
    type annotations from YAML.

    Parameters
    ----------
    tasks : dict
        Task graph with potential layer name references
    viewer : napari.Viewer
        Viewer to get layers from

    Returns
    -------
    dict
        Task graph with layer names resolved appropriately
    """
    resolved_tasks = {}
    layer_objects = {layer.name: layer for layer in viewer.layers}

    for task_name, task_value in tasks.items():
        # Skip non-tuple tasks (raw data)
        if not isinstance(task_value, tuple) or len(task_value) == 0:
            resolved_tasks[task_name] = task_value
            continue

        func = task_value[0]

        # Handle partial functions (keyword arguments)
        if isinstance(func, partial):
            actual_func, sig = get_func_and_signature(func)

            # Resolve each keyword argument
            resolved_kwargs = {}
            for key, value in func.keywords.items():
                resolved_kwargs[key] = resolve_param_value(
                    value, key, actual_func, sig, tasks, layer_objects
                )

            # Create new partial with resolved kwargs
            new_func = partial(func.func, **resolved_kwargs)

            # Wrap for LayerDataTuple handling if needed
            from ._layer_data_tuple import create_unwrapper, needs_unwrapping

            if needs_unwrapping(sig):
                new_func = create_unwrapper(new_func, sig)

            # Copy metadata
            for attr in (
                '_ndev_param_names',
                '_ndev_wrapped_func',
                '_ndev_parent_factory',
            ):
                if hasattr(func, attr):
                    setattr(new_func, attr, getattr(func, attr))

            resolved_tasks[task_name] = (new_func,) + task_value[1:]

        else:
            # Non-partial function, resolve positional args
            actual_func, sig = get_func_and_signature(func)

            try:
                params = list(sig.parameters.values()) if sig else []
            except (ValueError, TypeError, AttributeError):
                params = []

            resolved_args = []
            for i, arg in enumerate(task_value[1:]):
                # Check if this is a computed task reference
                is_computed_task = isinstance(arg, str) and isinstance(
                    tasks.get(arg), tuple
                )

                if (
                    isinstance(arg, str)
                    and arg in layer_objects
                    and not is_computed_task
                ):
                    # Resolve viewer layer reference
                    param_name = (
                        params[i].name if i < len(params) else f'arg{i}'
                    )
                    if i < len(params) and should_pass_layer_object(
                        actual_func, sig, param_name
                    ):
                        resolved_args.append(layer_objects[arg])
                    else:
                        resolved_args.append(layer_objects[arg].data)
                else:
                    resolved_args.append(arg)

            resolved_tasks[task_name] = (func,) + tuple(resolved_args)

    return resolved_tasks
