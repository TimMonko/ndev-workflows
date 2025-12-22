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

        if isinstance(func, CallableRef):
            func_path = f'{func.module}.{func.name}'
            kwargs = getattr(func, 'kwargs', {})
        elif isinstance(func, partial):
            func_path = f'{func.func.__module__}.{func.func.__name__}'
            kwargs = dict(func.keywords) if func.keywords else {}
        elif callable(func):
            func_path = f'{func.__module__}.{func.__name__}'
            kwargs = {}
        else:
            # Unknown task encoding
            continue

        saved_task_names.add(task_name)

        params: dict[str, object] = {
            f'arg{i}': arg for i, arg in enumerate(args)
        }
        params.update(kwargs)

        tasks[task_name] = {
            'function': func_path,
            'params': params,
        }

    # Inputs: referenced names that aren't saved as tasks.
    all_referenced: set[str] = set()
    for task_data in tasks.values():
        for param_name, param_value in task_data['params'].items():
            if isinstance(param_value, str) and param_name.startswith('arg'):
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

        module_path, _, func_name = func_path.rpartition('.')

        if lazy:
            func = CallableRef(module_path, func_name)
        else:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)
            except (ImportError, AttributeError) as e:
                raise ImportError(
                    f"Cannot import function '{func_name}' from '{module_path}': {e}"
                ) from e

        # Extract args and kwargs
        args: list[object] = []
        kwargs: dict[str, object] = {}
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
