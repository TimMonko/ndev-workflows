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

from ._io_legacy import load_legacy_lazy
from ._workflow import CallableRef, Workflow


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

        # Extract the actual function and kwargs, handling partial wrapping
        if isinstance(func, CallableRef):
            func_path = f'{func.module}.{func.name}'
            kwargs = getattr(func, 'kwargs', {})
            actual_func = func  # For metadata extraction
            is_magic_factory = False
        elif isinstance(func, partial):
            actual_func = (
                func.func
            )  # The wrapped function (might have metadata)
            # Check if this came from a MagicFactory
            parent_factory = getattr(actual_func, '_ndev_parent_factory', None)
            is_magic_factory = parent_factory is not None
            func_path = f'{actual_func.__module__}.{actual_func.__name__}'
            if is_magic_factory:
                func_path += '[MagicFactory]'  # Mark for special loading
            kwargs = dict(func.keywords) if func.keywords else {}
        elif callable(func):
            actual_func = func
            parent_factory = getattr(func, '_ndev_parent_factory', None)
            is_magic_factory = parent_factory is not None
            func_path = f'{func.__module__}.{func.__name__}'
            if is_magic_factory:
                func_path += '[MagicFactory]'
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

        tasks[task_name] = {
            'function': func_path,
            'params': params,
        }

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
        func_path = task_data['function']
        params = task_data.get('params', {})

        # Check if this is a MagicFactory-wrapped function
        is_magic_factory = func_path.endswith('[MagicFactory]')
        if is_magic_factory:
            func_path = func_path[: -len('[MagicFactory]')]

        module_path, _, func_name = func_path.rpartition('.')

        if lazy:
            func = CallableRef(module_path, func_name)
            func._is_magic_factory = (
                is_magic_factory  # Store for later extraction
            )
        else:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)

                # If this was marked as from MagicFactory, extract the underlying function
                if is_magic_factory:
                    if type(func).__name__ == 'MagicFactory' and hasattr(
                        func, 'function'
                    ):
                        print(
                            f'[spec_dict_to_workflow] Extracting function from MagicFactory: {func_name}'
                        )
                        func = func.function
                    else:
                        # The function itself might be the unwrapped version already
                        print(
                            f'[spec_dict_to_workflow] {func_name} marked as MagicFactory but got {type(func).__name__}'
                        )
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
