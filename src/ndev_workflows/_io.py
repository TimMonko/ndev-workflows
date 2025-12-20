"""YAML-based workflow persistence.

This module provides functions for saving and loading workflows in a
human-readable YAML format that is safe to load (no arbitrary code execution).

For loading legacy napari-workflows files, see `_io_legacy.py`.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ._io_legacy import (
    FunctionReference,
    is_legacy_format,
    load_legacy_lazy,
)
from ._workflow import Workflow

if TYPE_CHECKING:
    pass


class WorkflowYAMLError(Exception):
    """Error during workflow YAML serialization/deserialization."""


def _workflow_to_data(
    workflow: Workflow,
    *,
    name: str | None = None,
    description: str | None = None,
    include_modified: bool = True,
) -> dict:
    """Convert a workflow to the new format data structure.

    This is the central function for serializing workflows. It handles
    both regular workflows (with callable functions) and lazy-loaded
    workflows (with FunctionReference placeholders).

    Parameters
    ----------
    workflow : Workflow
        The workflow to convert.
    name : str, optional
        Human-readable name for the workflow.
    description : str, optional
        Description of what the workflow does.

    Returns
    -------
    dict
        Data structure ready for YAML serialization.
    """
    data = {}
    if name:
        data['name'] = name
    if description:
        data['description'] = description
    if include_modified:
        data['modified'] = datetime.now().date().isoformat()

    # Build tasks
    tasks = {}
    saved_task_names = set()

    for task_name, task in workflow._tasks.items():
        # Skip data tasks (not tuples or empty)
        if not isinstance(task, tuple) or len(task) == 0:
            continue

        func = task[0]
        args = task[1:]

        # Get function path from FunctionReference, partial, or callable
        if isinstance(func, FunctionReference):
            func_path = f'{func.module}.{func.name}'
            kwargs = getattr(func, 'kwargs', {})
        elif isinstance(func, partial):
            func_path = f'{func.func.__module__}.{func.func.__name__}'
            kwargs = dict(func.keywords) if func.keywords else {}
        elif callable(func):
            func_path = f'{func.__module__}.{func.__name__}'
            kwargs = {}
        else:
            continue

        saved_task_names.add(task_name)

        # Build params
        params = {}
        for i, arg in enumerate(args):
            params[f'arg{i}'] = arg
        params.update(kwargs)

        tasks[task_name] = {
            'function': func_path,
            'params': params,
        }

    # Compute inputs: referenced names that aren't saved as tasks
    all_referenced = set()
    for task_data in tasks.values():
        for param_name, param_value in task_data['params'].items():
            if isinstance(param_value, str) and param_name.startswith('arg'):
                all_referenced.add(param_value)

    inputs = [name for name in all_referenced if name not in saved_task_names]

    # Compute outputs: tasks that aren't referenced by other tasks
    outputs = [name for name in saved_task_names if name not in all_referenced]

    data['inputs'] = inputs
    data['outputs'] = outputs
    data['tasks'] = tasks

    return data


def save_workflow(
    filename: str | Path,
    workflow: Workflow,
    *,
    name: str | None = None,
    description: str | None = None,
) -> None:
    """Save a workflow to a YAML file.

    Parameters
    ----------
    filename : str or Path
        Path to save the workflow.
    workflow : Workflow
        The workflow to save.
    name : str, optional
        Human-readable name for the workflow.
    description : str, optional
        Description of what the workflow does.

    Example
    -------
    >>> from ndev_workflows import Workflow, save_workflow
    >>> workflow = Workflow()
    >>> workflow.set("blurred", gaussian, "input", sigma=2.0)
    >>> save_workflow("my_workflow.yaml", workflow, name="Blur Pipeline")
    """
    data = _workflow_to_data(workflow, name=name, description=description)

    with open(filename, 'w') as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def load_workflow(filename: str | Path, *, lazy: bool = False) -> Workflow:
    """Load a workflow from a YAML file.

    Automatically detects legacy napari-workflows format and loads appropriately.

    Parameters
    ----------
    filename : str or Path
        Path to the YAML file.
    lazy : bool, optional
        If True, don't import functions (use FunctionReference placeholders).
        Default is False (import functions).

    Returns
    -------
    Workflow
        The loaded workflow.

    Raises
    ------
    WorkflowYAMLError
        If loading fails or functions cannot be imported (when lazy=False).

    Example
    -------
    >>> from ndev_workflows import load_workflow
    >>> workflow = load_workflow("my_workflow.yaml")
    >>> workflow.set("input", image_data)
    >>> result = workflow.get("output")
    """
    # Legacy format: load lazily, normalize to the new in-memory representation,
    # then optionally resolve imports.
    if is_legacy_format(filename):
        legacy_workflow = load_legacy_lazy(filename)
        legacy_data = _workflow_to_data(
            legacy_workflow, include_modified=False
        )
        return _data_to_workflow(legacy_data, lazy=lazy)

    # New format: parse YAML and build workflow
    try:
        with open(filename) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise WorkflowYAMLError(f'Failed to parse YAML: {e}') from e

    return _data_to_workflow(data, lazy=lazy)


def _resolve_function_references(workflow: Workflow) -> None:
    """Resolve FunctionReference placeholders to actual functions in-place."""
    for task_name, task in workflow._tasks.items():
        if not isinstance(task, tuple) or len(task) == 0:
            continue

        func = task[0]
        if isinstance(func, FunctionReference):
            try:
                resolved = func.resolve()
            except (ImportError, AttributeError) as e:
                raise WorkflowYAMLError(
                    f"Cannot import function '{func.name}' from "
                    f"'{func.module}': {e}"
                ) from e
            workflow._tasks[task_name] = (resolved, *task[1:])


def _data_to_workflow(data: dict, *, lazy: bool = False) -> Workflow:
    """Convert a YAML data dict to a Workflow object."""
    workflow = Workflow()
    tasks = data.get('tasks', {})

    for task_name, task_data in tasks.items():
        func_path = task_data['function']
        params = task_data.get('params', {})

        # Parse function path
        parts = func_path.rsplit('.', 1)
        if len(parts) == 2:
            module_path, func_name = parts
        else:
            module_path = ''
            func_name = func_path

        if lazy:
            func = FunctionReference(module_path, func_name)
        else:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)
            except (ImportError, AttributeError) as e:
                raise WorkflowYAMLError(
                    f"Cannot import function '{func_name}' from "
                    f"'{module_path}': {e}"
                ) from e

        # Extract args and kwargs
        args = []
        kwargs = {}
        for param_name, param_value in params.items():
            if param_name.startswith('arg') and param_name[3:].isdigit():
                idx = int(param_name[3:])
                while len(args) <= idx:
                    args.append(None)
                args[idx] = param_value
            else:
                kwargs[param_name] = param_value

        # Apply kwargs
        if kwargs and not lazy:
            func = partial(func, **kwargs)
        elif kwargs and lazy:
            func.kwargs = kwargs

        workflow._tasks[task_name] = (func, *args)

    return workflow


def get_workflow_metadata(filename: str | Path) -> dict:
    """Get metadata from a workflow file without loading functions.

    Parameters
    ----------
    filename : str or Path
        Path to the YAML file.

    Returns
    -------
    dict
        Metadata including name, description, inputs, outputs.

    Example
    -------
    >>> metadata = get_workflow_metadata("my_workflow.yaml")
    >>> print(metadata['name'], metadata['inputs'], metadata['outputs'])
    """
    # Handle legacy format
    if is_legacy_format(filename):
        legacy_workflow = load_legacy_lazy(filename)
        legacy_data = _workflow_to_data(
            legacy_workflow, include_modified=False
        )
        return {
            'name': None,
            'description': None,
            'modified': None,
            'inputs': legacy_data.get('inputs', []),
            'outputs': legacy_data.get('outputs', []),
            'tasks': list(legacy_data.get('tasks', {}).keys()),
            'legacy': True,
        }

    with open(filename) as f:
        data = yaml.safe_load(f)

    return {
        'name': data.get('name'),
        'description': data.get('description'),
        'modified': data.get('modified'),
        'inputs': data.get('inputs', []),
        'outputs': data.get('outputs', []),
        'tasks': list(data.get('tasks', {}).keys()),
        'legacy': False,
    }


def migrate_legacy(
    input_file: str | Path,
    output_file: str | Path | None = None,
    *,
    name: str | None = None,
) -> Workflow:
    """Migrate a legacy napari-workflows file to the new format.

    Parameters
    ----------
    input_file : str or Path
        Path to the legacy YAML file.
    output_file : str or Path, optional
        Path for the output file. If None, appends '_migrated' to the name.
    name : str, optional
        Name for the migrated workflow.

    Returns
    -------
    Workflow
        The migrated workflow.

    Example
    -------
    >>> workflow = migrate_legacy("old_workflow.yaml", "new_workflow.yaml")
    """
    input_path = Path(input_file)

    if output_file is None:
        output_file = input_path.with_stem(input_path.stem + '_migrated')

    # Load with lazy loading (no imports needed)
    workflow = load_legacy_lazy(input_file)

    # Save in new format
    save_workflow(
        output_file, workflow, name=name or f'Migrated: {input_path.stem}'
    )

    return workflow


# Re-export commonly used items
__all__ = [
    'WorkflowYAMLError',
    'FunctionReference',
    'save_workflow',
    'load_workflow',
    'get_workflow_metadata',
    'migrate_legacy',
    'is_legacy_format',
]
