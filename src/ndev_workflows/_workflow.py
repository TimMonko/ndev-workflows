"""Core Workflow class for ndev-workflows.

The Workflow class represents a dask-compatible task graph that tracks
dependencies between processing steps in napari.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ._types import expects_layer_object as _expects_layer_object

if TYPE_CHECKING:
    pass


class CallableRef:
    """Placeholder for a callable that hasn't been imported yet."""

    def __init__(self, module: str, name: str):
        self.module = module
        self.name = name
        self.kwargs: dict = {}

    def __repr__(self) -> str:
        if self.kwargs:
            return (
                f'CallableRef({self.module}.{self.name}, kwargs={self.kwargs})'
            )
        return f'CallableRef({self.module}.{self.name})'

    def __call__(self, *args, **kwargs):
        raise WorkflowNotRunnableError(
            [
                MissingCallable(
                    module=self.module,
                    name=self.name,
                    error='CallableRef is unresolved (lazy workflow)',
                )
            ]
        )


@dataclass(frozen=True, slots=True)
class MissingCallable:
    module: str
    name: str
    error: str


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


class WorkflowNotRunnableError(RuntimeError):
    def __init__(self, missing: Iterable[MissingCallable]):
        self.missing = tuple(missing)
        lines: list[str] = ['Workflow is not runnable; missing callables:']
        for item in self.missing:
            top = item.module.split('.', 1)[0] if item.module else ''
            suggestion = None
            if top:
                alt = top.replace('_', '-')
                if alt != top:
                    suggestion = f'pip install {alt}'
                else:
                    suggestion = f'pip install {top}'

            msg = f'- Cannot import {item.module}.{item.name}: {item.error}'
            if suggestion:
                msg += f' (try: {suggestion})'
            lines.append(msg)
        super().__init__('\n'.join(lines))


class Workflow:
    """A dask-compatible task graph for image processing workflows.

    The Workflow class stores processing steps as a dictionary of tasks,
    where each task is a tuple of (function, *args). Arguments can reference
    other task names, creating a dependency graph that is lazily evaluated.

    This is compatible with dask's task graph format, allowing workflows
    to be executed with dask's threaded scheduler.

    Parameters
    ----------
    None

    Attributes
    ----------
    _tasks : dict
        Dictionary mapping task names to (function, *args) tuples.

    Examples
    --------
    >>> from ndev_workflows import Workflow
    >>> from skimage.filters import gaussian
    >>> w = Workflow()
    >>> w.set("input", image_data)  # Raw data, not a processing step
    >>> w.set("blurred", gaussian, "input", sigma=2.0)
    >>> result = w.get("blurred")  # Executes the graph
    """

    def __init__(self) -> None:
        """Initialize an empty workflow."""
        self._tasks: dict[str, tuple] = {}
        self.metadata: dict[str, object] = {}

    def set(
        self,
        name: str,
        func_or_data: Callable | Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Add or update a task in the workflow.

        Parameters
        ----------
        name : str
            The name/key for this task. Can be used as a reference in other tasks.
        func_or_data : Callable or Any
            Either a callable (function) to execute, or raw data to store.
            If a callable, it will be executed with the provided args/kwargs.
        *args : Any
            Positional arguments for the function. String args that match
            task names will be resolved to those task outputs.
        **kwargs : Any
            Keyword arguments for the function.

        Notes
        -----
        When storing raw data (not a callable), the data is stored directly
        (not as a tuple). This is compatible with dask's task graph format.

        When storing a callable, the task format is:
        ``(func_or_partial, *args)``
        """
        if not callable(func_or_data):
            # Raw data - store directly (dask-compatible)
            self._tasks[name] = func_or_data
            return

        func: Callable
        # Store only explicitly provided kwargs; do not bake in defaults.
        # This keeps YAML exports minimal/stable and matches typical
        # napari-workflows behavior.
        func = partial(func_or_data, **kwargs) if kwargs else func_or_data

        # Store as dask-compatible task tuple
        self._tasks[name] = (func, *args)

    @property
    def tasks(self):
        """Read-only view of the underlying dask task graph.

        This is the public accessor for the workflow's task graph. The
        underlying storage is ``self._tasks`` for dask-graph compatibility.
        Prefer this property over accessing ``_tasks`` directly.
        """
        return MappingProxyType(self._tasks)

    def get(self, name: str | list[str], viewer=None) -> Any:
        """Execute the workflow graph and return the result for task(s).

        Parameters
        ----------
        name : str or list[str]
            The name of the task to compute, or a list of task names.
        viewer : napari.Viewer, optional
            Viewer instance for resolving layer name references to actual layer data.

        Returns
        -------
        Any
            The computed result of the task. If a list of names is given,
            returns a list of results.

        Raises
        ------
        KeyError
            If a task name is not found in the workflow.

        Notes
        -----
        This uses dask's threaded scheduler to execute the task graph,
        automatically resolving dependencies.
        """
        from dask.threaded import get as dask_get

        # Resolve layer references if viewer provided
        tasks = self._tasks
        if viewer is not None:
            tasks = self._resolve_layer_references(self._tasks, viewer)

        if isinstance(name, list):
            for n in name:
                if n not in tasks:
                    raise KeyError(f"Task '{n}' not found in workflow")
            return [dask_get(tasks, n) for n in name]

        if name not in tasks:
            raise KeyError(f"Task '{name}' not found in workflow")
        return dask_get(tasks, name)

    def _get_func_and_signature(self, func):
        """Extract actual function and signature from potentially wrapped function."""
        import inspect
        from functools import partial

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
            and hasattr(
                actual_func.__self__, '_unwrap_layer_data_tuple_wrapper'
            )
            and len(func.args) >= 2
        ):
            # Our wrapper: partial(_unwrap_layer_data_tuple_wrapper, actual_func, sig)
            return func.args[0], func.args[1]  # (actual_func, sig)

        # Regular partial
        try:
            return actual_func, inspect.signature(actual_func)
        except (ValueError, TypeError):
            return actual_func, None

    def _should_pass_layer_object(self, func, sig, param_name: str) -> bool:
        """Determine if parameter expects Layer object vs raw data.

        Checks stored types first (from YAML), falls back to signature inspection.
        """
        # Check if function has stored parameter types (from YAML spec)
        param_types = getattr(func, '_ndev_param_types', {})
        if param_name in param_types:
            return param_types[param_name] == 'layer'

        # Fall back to signature inspection
        return _expects_layer_object(sig, param_name)

    def _resolve_param_value(
        self,
        value,
        param_name: str,
        func,
        sig,
        tasks: dict,
        layer_objects: dict,
    ):
        """Resolve a single parameter value based on type requirements."""
        # If value references a task, check if it's computed or raw data
        if isinstance(value, str) and value in tasks:
            referenced_task = tasks[value]
            is_computed_task = isinstance(referenced_task, tuple)

            if is_computed_task:
                # Leave as string reference for dask to resolve
                # NOTE: dask can't resolve kwargs, only positional args!
                return value

            # Raw data in tasks - check if function needs Layer wrapper
            if self._should_pass_layer_object(func, sig, param_name):
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
            if self._should_pass_layer_object(func, sig, param_name):
                return layer_objects[value]  # Pass Layer object
            else:
                return layer_objects[value].data  # Pass data array

        # If value is already a Layer object
        if hasattr(value, 'data') and hasattr(value, 'name'):
            if self._should_pass_layer_object(func, sig, param_name):
                return value  # Keep Layer object
            else:
                return value.data  # Extract data array

        # Literal value (number, bool, string, etc.)
        return value

    def _resolve_layer_references(self, tasks: dict, viewer) -> dict:
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
        from functools import partial

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
                actual_func, sig = self._get_func_and_signature(func)

                # Resolve each keyword argument
                resolved_kwargs = {}
                for key, value in func.keywords.items():
                    resolved_kwargs[key] = self._resolve_param_value(
                        value, key, actual_func, sig, tasks, layer_objects
                    )

                # Create new partial with resolved kwargs
                new_func = partial(func.func, **resolved_kwargs)

                # Wrap for LayerDataTuple handling if needed
                if self._needs_layer_data_tuple_unwrapping(sig):
                    new_func = partial(
                        self._unwrap_layer_data_tuple_wrapper,
                        new_func,
                        sig,
                    )

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
                actual_func, sig = self._get_func_and_signature(func)

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
                        if i < len(params) and self._should_pass_layer_object(
                            actual_func, sig, param_name
                        ):
                            resolved_args.append(layer_objects[arg])
                        else:
                            resolved_args.append(layer_objects[arg].data)
                    else:
                        resolved_args.append(arg)

                resolved_tasks[task_name] = (func,) + tuple(resolved_args)

        return resolved_tasks

    def _needs_layer_data_tuple_unwrapping(self, sig) -> bool:
        """Check if function has any parameters expecting Layer objects.

        If yes, we need to wrap it to convert LayerDataTuples to fake layer objects.
        """
        if sig is None:
            return False

        for param_name in sig.parameters:
            if _expects_layer_object(sig, param_name):
                return True
        return False

    def _unwrap_layer_data_tuple_wrapper(self, func, sig, *args, **kwargs):
        """Wrapper that converts LayerDataTuple inputs to layer-like objects.

        If an argument is a tuple matching LayerDataTuple format (data, metadata, type),
        create a FakeLayer object with .data and .name extracted from the tuple.
        """
        # Convert positional args
        new_args = []
        param_names = list(sig.parameters.keys())
        for i, arg in enumerate(args):
            if self._is_layer_data_tuple(arg):
                # Check if this parameter expects a layer object
                if i < len(param_names) and _expects_layer_object(
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
            if self._is_layer_data_tuple(value):
                if _expects_layer_object(sig, key):
                    data, metadata, layer_type = value
                    name = metadata.get('name', 'unnamed')
                    new_kwargs[key] = FakeLayer(data, name)
                else:
                    # Just extract data
                    new_kwargs[key] = value[0]
            else:
                new_kwargs[key] = value

        return func(*new_args, **new_kwargs)

    def _is_layer_data_tuple(self, value) -> bool:
        """Check if value matches LayerDataTuple format: (data, dict, str)."""
        if not isinstance(value, tuple) or len(value) != 3:
            return False
        data, metadata, layer_type = value
        return isinstance(metadata, dict) and isinstance(layer_type, str)

    def roots(self) -> list[str]:
        """Return workflow input names (graph roots).

        Roots are names that are used as inputs to processing tasks and are
        not produced by any other processing task.

        Importantly, roots remain roots even after you provide data via
        ``workflow.set(root_name, data)``.

        Returns
        -------
        list[str]
            List of names that are referenced but not defined as tasks.

        Notes
        -----
        This is *not* the same as :meth:`external_inputs`, which returns only
        undefined inputs (i.e. roots that have not been provided as data tasks).
        """
        # Build a dependency edge list: source -> task_name
        sources_in_order: list[str] = []
        sources_seen: set[str] = set()
        targets: set[str] = set()

        for task_name, task in self._tasks.items():
            if not isinstance(task, tuple) or len(task) <= 1:
                continue

            targets.add(task_name)
            for arg in task[1:]:
                if not isinstance(arg, str):
                    continue
                if arg not in sources_seen:
                    sources_seen.add(arg)
                    sources_in_order.append(arg)

        # Roots are sources that are never targets.
        return [name for name in sources_in_order if name not in targets]

    def leaves(self) -> list[str]:
        """Return the leaf nodes (outputs) of the workflow.

        Leaves are tasks that do not have any followers - nothing
        depends on them. These are typically the final outputs.

        Returns
        -------
        list[str]
            List of task names that are leaves.
        """
        # Collect tasks that ARE referenced by other tasks
        has_followers = set()
        for task in self._tasks.values():
            # Only tuples can have arguments that reference other tasks
            if isinstance(task, tuple) and len(task) > 1:
                for arg in task[1:]:
                    if isinstance(arg, str) and arg in self._tasks:
                        has_followers.add(arg)

        # Leaves are tasks with no followers
        return [name for name in self._tasks if name not in has_followers]

    def leafs(self) -> list[str]:
        """Alias for :meth:`leaves` (napari-workflows spelling)."""
        return self.leaves()

    def get_undefined_inputs(self) -> list[str]:
        """Return undefined input names.

        These are roots that are referenced by processing tasks but have not
        been provided as tasks (typically via ``workflow.set(name, data)``).

        Returns
        -------
        list[str]
            List of names referenced but not defined.

        """
        # Preserve the stable ordering of roots().
        return [name for name in self.roots() if name not in self._tasks]

    def processing_task_names(self) -> list[str]:
        """Return names of processing tasks (excluding raw data tasks)."""
        return [
            name
            for name, task in self._tasks.items()
            if isinstance(task, tuple) and len(task) > 0
        ]

    def ensure_runnable(self) -> Workflow:
        """Resolve any CallableRef placeholders into real imported callables.

        Parameters
        ----------
        Returns
        -------
        Workflow
            Self (mutated in place).

        Raises
        ------
        NotRunnableWorkflowError
            If one or more callables cannot be imported.
        """
        missing: list[MissingCallable] = []

        for task_name, task in list(self._tasks.items()):
            if not isinstance(task, tuple) or len(task) == 0:
                continue

            func = task[0]
            if not isinstance(func, CallableRef):
                continue

            try:
                module = importlib.import_module(func.module)
                real_func = getattr(module, func.name)

                print(
                    f'[ensure_runnable] Loaded {func.name}: type={type(real_func).__name__}'
                )

                # If this was marked as from MagicFactory (stored in CallableRef), extract it
                if (
                    hasattr(func, '_is_magic_factory')
                    and func._is_magic_factory
                ):
                    if type(real_func).__name__ == 'MagicFactory':
                        print(
                            f'[ensure_runnable] Extracting function from MagicFactory: {func.name}'
                        )

                        # IMPORTANT: Get signature from MagicFactory BEFORE extracting
                        # The MagicFactory has proper type annotations, but the extracted
                        # function might not (magicgui's _function is often untyped)
                        try:
                            # Create widget instance to get the annotated function
                            widget = real_func()
                            if hasattr(widget, '_function'):
                                # Use widget's _function which has magicgui's annotations
                                extracted = widget._function
                                print(
                                    f'[ensure_runnable] Extracted via widget._function: {extracted}'
                                )
                                # Try to preserve the original signature
                                try:
                                    extracted.__signature__ = (
                                        inspect.signature(widget)
                                    )
                                    print(
                                        '[ensure_runnable] Preserved MagicFactory signature on extracted function'
                                    )
                                except Exception as e:
                                    print(
                                        f'[ensure_runnable] Could not preserve signature: {e}'
                                    )
                                real_func = extracted
                                print(
                                    '[ensure_runnable] Successfully extracted callable function'
                                )
                            else:
                                print(
                                    '[ensure_runnable] WARNING: widget has no _function attribute'
                                )
                        except Exception as e:
                            print(
                                f'[ensure_runnable] ERROR extracting from MagicFactory: {e}'
                            )
                            # Fallback to old method
                            if (
                                hasattr(real_func, 'keywords')
                                and 'function' in real_func.keywords
                            ):
                                extracted = real_func.keywords['function']
                                print(
                                    f'[ensure_runnable] Fallback extraction: {extracted}'
                                )
                                if callable(extracted):
                                    real_func = extracted

                print(f'[ensure_runnable] Final real_func: {real_func}')

                # Safety check
                if not callable(real_func):
                    raise ValueError(
                        f'Function {func.name} is not callable: {real_func}'
                    )
            except (ImportError, AttributeError) as e:
                missing.append(
                    MissingCallable(
                        module=func.module,
                        name=func.name,
                        error=str(e),
                    )
                )
                continue

            if getattr(func, 'kwargs', None):
                real_func = partial(real_func, **dict(func.kwargs))

            self._tasks[task_name] = (real_func, *task[1:])

        if missing:
            raise WorkflowNotRunnableError(missing)

        return self

    def root_functions(self) -> dict[str, tuple]:
        """Return the functions that operate directly on root inputs.

        These are the first processing steps in the workflow - functions
        that take root tasks (data) as their primary input.

        Returns
        -------
        dict[str, tuple]
            Dictionary mapping task names to their task tuples for all
            tasks that depend directly on root tasks.

        Notes
        -----
        This is useful for initializing workflows when loading, as you
        typically need to connect input data to these root functions.
        """
        root_names = set(self.roots())
        root_funcs = {}

        for name, task in self._tasks.items():
            # Skip data tasks (stored directly, not as tuples)
            if not isinstance(task, tuple):
                continue
            if len(task) == 0 or not callable(task[0]):
                continue

            # Check if any source is a root
            sources = self.sources_of(name)
            if any(src in root_names for src in sources):
                root_funcs[name] = task

        return root_funcs

    def followers_of(self, name: str) -> list[str]:
        """Return tasks that depend on the given task.

        Parameters
        ----------
        name : str
            The name of the task to find followers for.

        Returns
        -------
        list[str]
            List of task names that depend on this task.
        """
        followers = []
        for task_name, task in self._tasks.items():
            if task_name == name:
                continue
            # Only tuples can have arguments that reference other tasks
            if isinstance(task, tuple) and len(task) > 1:
                for arg in task[1:]:
                    if arg == name:
                        followers.append(task_name)
                        break
        return followers

    def sources_of(self, name: str) -> list[str]:
        """Return names that the given task depends on.

        Parameters
        ----------
        name : str
            The name of the task to find sources for.

        Returns
        -------
        list[str]
            List of names that this task references as inputs.
            Includes both defined tasks and external references.
        """
        if name not in self._tasks:
            return []

        task = self._tasks[name]
        sources = []

        # Only tuples can have arguments that reference other tasks
        if isinstance(task, tuple) and len(task) > 1:
            for arg in task[1:]:
                if isinstance(arg, str):
                    sources.append(arg)

        return sources

    def keys(self) -> list[str]:
        """Return all task names in the workflow.

        Returns
        -------
        list[str]
            List of all task names.
        """
        return list(self._tasks.keys())

    def __contains__(self, name: str) -> bool:
        """Check if a task name exists in the workflow."""
        return name in self._tasks

    def __len__(self) -> int:
        """Return the number of tasks in the workflow."""
        return len(self._tasks)

    def __iter__(self):
        """Iterate over task names."""
        return iter(self._tasks)

    def __repr__(self) -> str:
        """Return a string representation of the workflow."""
        n_tasks = len(self._tasks)
        roots = self.roots()
        leaves = self.leaves()
        return f'Workflow({n_tasks} tasks, roots={roots}, leaves={leaves})'

    def copy(self) -> Workflow:
        """Create a deep copy of this workflow.

        Returns
        -------
        Workflow
            A new Workflow with copied tasks.
        """
        new_workflow = Workflow()
        new_workflow._tasks = deepcopy(self._tasks)
        return new_workflow

    def remove(self, name: str) -> None:
        """Remove a task from the workflow.

        Parameters
        ----------
        name : str
            The name of the task to remove.

        Notes
        -----
        This does not check for or update dependencies. Tasks that
        depended on the removed task will fail when executed.
        """
        if name in self._tasks:
            del self._tasks[name]

    def clear(self) -> None:
        """Remove all tasks from the workflow."""
        self._tasks.clear()

    def get_task(self, name: str) -> tuple | None:
        """Get the raw task tuple for a given name.

        Parameters
        ----------
        name : str
            The name of the task.

        Returns
        -------
        tuple or None
            The task tuple (function, *args), or None if not found.
        """
        return self._tasks.get(name)

    def get_function(self, name: str) -> Callable | None:
        """Get the function for a given task.

        Parameters
        ----------
        name : str
            The name of the task.

        Returns
        -------
        Callable or None
            The function (may be a partial), or None if not found
            or if the task is raw data.
        """
        task = self._tasks.get(name)
        if task is None:
            return None
        # Data tasks are stored directly (not as tuples)
        if not isinstance(task, tuple):
            return None
        if len(task) == 0:
            return None
        func = task[0]
        return func if callable(func) else None

    def is_data_task(self, name: str) -> bool:
        """Check if a task represents raw data (not a processing step).

        Parameters
        ----------
        name : str
            The name of the task.

        Returns
        -------
        bool
            True if the task is raw data, False if it's a processing step.
        """
        task = self._tasks.get(name)
        if task is None:
            return False
        # Data tasks are stored directly (not as tuples)
        # Processing tasks are stored as tuples (func, *args)
        if not isinstance(task, tuple):
            return True
        # Edge case: empty tuple would be data, but shouldn't happen
        if len(task) == 0:
            return True
        # If it's a tuple with a callable first element, it's a processing task
        return not callable(task[0])
