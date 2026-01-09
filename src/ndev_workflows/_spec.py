"""Workflow <-> YAML spec conversion.

This module is *purely* about translating between:
- in-memory :class:`ndev_workflows.Workflow` graphs, and
- the new, safe, human-readable YAML "spec" dict.

It intentionally does not read/write files. Disk I/O lives in `_io.py`.
Legacy YAML parsing lives in `_io_legacy.py`.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from functools import partial
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from ._io_legacy import load_legacy_lazy
from ._types import extract_param_types as _extract_param_types_impl
from ._workflow import CallableRef, Workflow


def _extract_comment(obj, key: str) -> str | None:
    """Extract end-of-line comment from ruamel.yaml CommentedMap.

    Returns None if no comment exists or obj doesn't support comments.
    """
    if not hasattr(obj, 'ca') or not hasattr(obj.ca, 'items'):
        return None

    comment_data = obj.ca.items.get(key)
    if comment_data and comment_data[2]:  # [2] is the end-of-line comment
        return comment_data[2].value.strip().lstrip('#').strip()

    return None


def workflow_to_spec_dict(
    workflow: Workflow,
    *,
    name: str | None = None,
    description: str | None = None,
    include_modified: bool = True,
) -> dict:
    """Convert a workflow to the new YAML spec dict."""
    spec: dict = {}
    if name:
        spec['name'] = name
    if description:
        spec['description'] = description
    if include_modified:
        spec['modified'] = datetime.now().date().isoformat()

    tasks: dict[str, dict] = {}
    saved_task_names: set[str] = set()

    for task_name, task in workflow.tasks.items():
        # Skip data tasks (not tuples) and empty tuples.
        if not isinstance(task, tuple) or len(task) == 0:
            continue

        func = task[0]
        args = task[1:]

        # Extract the actual callable and kwargs, handling partial wrapping
        callable_type = (
            'callable'  # Default (changed from 'function' for accuracy)
        )
        if isinstance(func, CallableRef):
            func_path = f'{func.module}.{func.name}'
            kwargs = getattr(func, 'kwargs', {})
            actual_func = func  # For metadata extraction
            if hasattr(func, '_is_magic_factory') and func._is_magic_factory:
                callable_type = 'magic_factory'
        elif isinstance(func, partial):
            actual_func = (
                func.func
            )  # The wrapped function (might have metadata)
            # Check if this came from a MagicFactory
            parent_factory = getattr(actual_func, '_ndev_parent_factory', None)
            if parent_factory is not None:
                callable_type = 'magic_factory'
            func_path = f'{actual_func.__module__}.{actual_func.__name__}'
            kwargs = dict(func.keywords) if func.keywords else {}
        elif callable(func):
            actual_func = func
            parent_factory = getattr(func, '_ndev_parent_factory', None)
            if parent_factory is not None:
                callable_type = 'magic_factory'
            func_path = f'{func.__module__}.{func.__name__}'
            kwargs = {}
        else:
            # Unknown task encoding
            continue

        saved_task_names.add(task_name)

        # Check if function has attached parameter names (from ndev-workflows recording)
        # Look on the actual function, not the partial wrapper
        param_names = getattr(actual_func, '_ndev_param_names', None)
        if param_names and len(param_names) == len(args):
            # Use actual parameter names instead of arg0, arg1
            params: dict[str, object] = {
                name: arg for name, arg in zip(param_names, args)
            }
        else:
            # Fallback to arg0, arg1, etc.
            params: dict[str, object] = {
                f'arg{i}': arg for i, arg in enumerate(args)
            }
        params.update(kwargs)

        # Capture parameter types for proper resolution during execution
        param_types = _extract_param_types_impl(
            actual_func, list(params.keys())
        )

        # Build task spec using CommentedMap for comment support
        task_spec = CommentedMap()
        task_spec['callable'] = func_path

        # Attach callable_type as comment on the callable line
        if callable_type != 'callable':
            task_spec.yaml_add_eol_comment(callable_type, 'callable')

        # Build params as CommentedMap with type comments
        params_with_comments = CommentedMap(params)
        if param_types:
            for param_name, param_type in param_types.items():
                if param_name in params_with_comments:
                    params_with_comments.yaml_add_eol_comment(
                        param_type, param_name
                    )

        task_spec['params'] = params_with_comments

        tasks[task_name] = task_spec

    # Inputs: referenced names that aren't saved as tasks.
    # Check all string parameters (task references) regardless of parameter name
    all_referenced: set[str] = set()
    for task_data in tasks.values():
        for param_value in task_data['params'].values():
            if isinstance(param_value, str):
                # Check if this string matches a task name (task reference)
                if (
                    param_value in workflow.tasks
                    or param_value in saved_task_names
                ):
                    all_referenced.add(param_value)

    inputs = [n for n in all_referenced if n not in saved_task_names]
    outputs = [n for n in saved_task_names if n not in all_referenced]

    spec['inputs'] = inputs
    spec['outputs'] = outputs
    spec['tasks'] = tasks

    return spec


def spec_dict_to_workflow(spec: dict, *, lazy: bool = False) -> Workflow:
    """Convert a new-format YAML spec dict to a Workflow object."""
    workflow = Workflow()
    workflow.metadata = {
        'name': spec.get('name'),
        'description': spec.get('description'),
        'modified': spec.get('modified'),
        'inputs': spec.get('inputs', []),
        'outputs': spec.get('outputs', []),
    }
    tasks = spec.get('tasks', {})

    for task_name, task_data in tasks.items():
        # Support both 'callable' (new) and 'function' (legacy) for backward compatibility
        func_path = task_data.get('callable') or task_data.get('function')
        params = task_data.get('params', {})

        # Get callable_type from comment, default to 'callable'
        callable_type = _extract_comment(task_data, 'callable') or 'callable'

        # Extract parameter types from comments
        param_types = {
            name: _extract_comment(params, name) for name in params.keys()
        }
        param_types = {
            k: v for k, v in param_types.items() if v
        }  # Remove None values

        module_path, _, func_name = func_path.rpartition('.')

        if lazy:
            func = CallableRef(module_path, func_name)
            func._is_magic_factory = callable_type == 'magic_factory'
        else:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)

                # If this is a MagicFactory, extract the underlying function
                if callable_type == 'magic_factory':
                    if (
                        type(func).__name__ == 'MagicFactory'
                        and hasattr(func, 'keywords')
                        and 'function' in func.keywords
                    ):
                        func = func.keywords['function']

                # Attach parameter types to function for use during resolution
                if param_types:
                    func._ndev_param_types = param_types

            except (ImportError, AttributeError) as e:
                raise ImportError(
                    f"Cannot import function '{func_name}' from '{module_path}': {e}"
                ) from e

        # Separate task references (strings that will be resolved by dask)
        # from literal parameters
        task_refs: list[str] = []  # Task names to resolve
        task_ref_params: list[str] = []  # Parameter names for those tasks
        literal_kwargs: dict[str, object] = {}

        for param_name, param_value in params.items():
            # Check for old-style arg0, arg1 format
            if param_name.startswith('arg') and param_name[3:].isdigit():
                # Legacy positional arg
                if isinstance(param_value, str):
                    task_refs.append(param_value)
                    task_ref_params.append(param_name)  # Will use arg0, arg1
                else:
                    literal_kwargs[param_name] = param_value
            elif isinstance(param_value, str) and param_value in tasks:
                # New-style: parameter name with task reference
                task_refs.append(param_value)
                task_ref_params.append(param_name)
            else:
                # Literal parameter
                literal_kwargs[param_name] = param_value

        # Create wrapper if there are task references (for magicgui compatibility)
        if task_refs:
            if not lazy:
                from functools import wraps

                original_func = func

                @wraps(original_func)
                def wrapper(*task_data):
                    # Rebuild kwargs with task data
                    kwargs_with_data = {}
                    for param_name, data in zip(task_ref_params, task_data):
                        kwargs_with_data[param_name] = data
                    return original_func(**kwargs_with_data)

                wrapper._ndev_param_names = task_ref_params
                wrapper._ndev_wrapped_func = original_func

                # Store wrapper with literal kwargs in partial (matching recording behavior)
                if literal_kwargs:
                    func = partial(wrapper, **literal_kwargs)
                else:
                    func = wrapper
            else:
                # For lazy loading, store metadata
                func._ndev_param_names = task_ref_params
                func.kwargs = literal_kwargs

            workflow._tasks[task_name] = (func, *task_refs)
        else:
            # No task refs, just apply literal kwargs
            if literal_kwargs and not lazy:
                func = partial(func, **literal_kwargs)
            elif literal_kwargs and lazy:
                func.kwargs = literal_kwargs
            workflow._tasks[task_name] = (func,)

    return workflow


def ensure_runnable(
    workflow_or_spec: Workflow | dict,
) -> Workflow:
    """Ensure a workflow is runnable.

    Accepts either a Workflow (possibly loaded with ``lazy=True``) or a
    new-format spec dict.
    """
    if isinstance(workflow_or_spec, dict):
        workflow = spec_dict_to_workflow(workflow_or_spec, lazy=True)
    else:
        workflow = workflow_or_spec
    return workflow.ensure_runnable()


def legacy_yaml_to_spec_dict(
    filename: str | Path,
    *,
    name: str | None = None,
    description: str | None = None,
    include_modified: bool = False,
) -> dict:
    """Load a legacy napari-workflows YAML and convert it to the new spec dict.

    This function is intentionally *lazy*: it never imports referenced
    functions.
    """
    legacy_workflow = load_legacy_lazy(filename)
    return workflow_to_spec_dict(
        legacy_workflow,
        name=name,
        description=description,
        include_modified=include_modified,
    )
