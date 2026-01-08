"""Workflow manager for napari viewer integration.

This module is derived from napari-workflows by Robert Haase (BSD-3-Clause).
See NOTICE file for attribution.

The WorkflowManager provides a singleton pattern for managing workflows
per napari viewer, with automatic layer updates and undo/redo support.
"""

from __future__ import annotations

import threading
import time
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from ._undo_redo import UndoRedoController
from ._workflow import Workflow

if TYPE_CHECKING:
    from napari import Viewer
    from napari.layers import Layer


# Global registry of WorkflowManager instances per viewer
_managers: WeakValueDictionary[int, WorkflowManager] = WeakValueDictionary()


class WorkflowManager:
    """Manages a workflow attached to a napari viewer.

    The WorkflowManager provides:
    - Singleton pattern (one manager per viewer)
    - Automatic layer updates when sources change
    - Undo/redo functionality
    - Background worker for non-blocking updates
    - Code generation from workflow

    Parameters
    ----------
    viewer : napari.Viewer
        The napari viewer to manage.

    Notes
    -----
    Use ``WorkflowManager.install(viewer)`` to get or create a manager
    for a viewer. Do not instantiate directly.
    """

    def __init__(self, viewer: Viewer) -> None:
        """Initialize the WorkflowManager.

        Parameters
        ----------
        viewer : napari.Viewer
            The napari viewer to manage.
        """
        self._viewer = viewer
        self._workflow = Workflow()
        self._undo_redo = UndoRedoController(self._workflow)

        # Background worker for auto-updates
        self._update_requested = threading.Event()
        self._stop_worker = threading.Event()
        self._pending_updates: list[str] = []
        self._worker_thread: threading.Thread | None = None

        # Auto-update settings
        self._auto_update_enabled = True
        self._update_delay = 0.1  # seconds

        # Hook into napari to intercept widget execution
        self._install_hooks()

        # Start background worker
        self._start_worker()

    def _install_hooks(self) -> None:
        """Install hooks to intercept widget execution.

        This hooks into napari's add_dock_widget to automatically
        connect magicgui widgets to workflow recording.
        """
        # Wrap add_dock_widget to intercept new widgets
        original_add_dock_widget = self._viewer.window.add_dock_widget

        def wrapped_add_dock_widget(
            widget, *, name='', area='right', allowed_areas=None, **kwargs
        ):
            """Wrapped add_dock_widget that connects widgets to recording."""
            result = original_add_dock_widget(
                widget,
                name=name,
                area=area,
                allowed_areas=allowed_areas,
                **kwargs,
            )

            # Try to connect to .called signal if it's a magicgui widget
            actual_widget = widget
            if hasattr(widget, 'widget'):
                # It's a dock widget wrapping the actual widget
                actual_widget = widget.widget

            if hasattr(actual_widget, 'called'):
                # Connect to recording
                actual_widget.called.connect(
                    lambda res: self._on_widget_called(actual_widget, res)
                )
                print(
                    f'[WorkflowManager] Connected {name or "widget"} to workflow recording'
                )

            return result

        self._viewer.window.add_dock_widget = wrapped_add_dock_widget

    def _on_widget_called(self, widget: Any, result: Any) -> None:
        """Handle widget execution to record workflow step.

        Parameters
        ----------
        widget : Any
            The magicgui widget that was executed.
        result : Any
            The result of the widget execution.
        """
        print(f'[WorkflowManager] Widget called: {widget}')
        print(f'[WorkflowManager] Result type: {type(result)}')

        # Extract function
        func = None
        if hasattr(widget, '_function'):
            func = widget._function
        elif hasattr(widget, 'func'):
            func = widget.func
        elif hasattr(widget, '__wrapped__'):
            func = widget.__wrapped__

        # Extract parameters
        params = {}
        if hasattr(widget, 'asdict'):
            params = widget.asdict()
            print(f'[WorkflowManager] Params: {params}')

        # Determine output name
        output_name = None
        if result is not None:
            # Check if result is a Layer object
            if hasattr(result, 'name') and hasattr(result, 'data'):
                output_name = result.name
            # Check if it's a LayerDataTuple (data, kwargs, type)
            elif isinstance(result, (list, tuple)) and len(result) >= 2:
                layer_data, layer_kwargs = result[0], result[1]
                if isinstance(layer_kwargs, dict) and 'name' in layer_kwargs:
                    output_name = layer_kwargs['name']

        # Fallback: Check if a new layer was added (works for any return type)
        # This handles widgets that return raw arrays or custom types
        if output_name is None and len(self._viewer.layers) > 0:
            # Assume the most recently added layer is the output
            output_name = self._viewer.layers[-1].name
            print(
                f'[WorkflowManager] Using fallback - detected new layer: {output_name}'
            )

        print(f'[WorkflowManager] Output name: {output_name}')

        if func and output_name and params:
            self.record_step(func, params, output_name)
            from napari.utils.notifications import show_info

            show_info(f'Recorded workflow step: {output_name}')
        else:
            print(
                f'[WorkflowManager] Skipping - missing func={func is not None}, output={output_name}, params={bool(params)}'
            )

    @classmethod
    def install(cls, viewer: Viewer) -> WorkflowManager:
        """Get or create a WorkflowManager for a viewer.

        Parameters
        ----------
        viewer : napari.Viewer
            The napari viewer.

        Returns
        -------
        WorkflowManager
            The workflow manager for this viewer.
        """
        viewer_id = id(viewer)
        if viewer_id not in _managers:
            manager = cls(viewer)
            _managers[viewer_id] = manager
        return _managers[viewer_id]

    @property
    def workflow(self) -> Workflow:
        """The workflow being managed."""
        return self._workflow

    def record_step(
        self, func: Callable, params: dict[str, Any], output_name: str
    ):
        """Record a processing step into the workflow.

        Parameters
        ----------
        func : Callable
            The function that was executed.
        params : dict[str, Any]
            The parameters passed to the function.
        output_name : str
            The name of the output layer/result.

        Notes
        -----
        This method automatically:
        - Resolves Layer objects to their names
        - Filters out non-serializable parameters (viewer, etc.)
        - Converts task references to string names (for dask resolution)
        - Wraps magicgui functions to accept task refs as positional args
        """
        # Resolve layer objects and arrays to names in params
        resolved_params = {}
        param_to_task_ref = {}  # Track which params are task references

        for key, value in params.items():
            # Skip viewer and other non-serializable napari objects
            if key == 'viewer' or isinstance(value, type(self._viewer)):
                continue

            # Check if it's a Layer object
            if hasattr(value, 'name') and hasattr(value, 'data'):
                resolved_params[key] = value.name
                param_to_task_ref[key] = value.name
            # Check if it's an array that matches a layer's data
            elif hasattr(value, 'shape') and hasattr(value, 'ndim'):
                # Try to find a matching layer by comparing array identity
                layer_name = None
                for layer in self._viewer.layers[
                    ::-1
                ]:  # Check most recent first
                    if hasattr(layer, 'data') and layer.data is value:
                        layer_name = layer.name
                        break
                if layer_name:
                    resolved_params[key] = layer_name
                    param_to_task_ref[key] = layer_name
                    print(
                        f'[WorkflowManager] Resolved array to layer: {layer_name}'
                    )
                else:
                    # Keep as literal (might be a raw input)
                    resolved_params[key] = value
            else:
                resolved_params[key] = value

        # Separate task references from literals
        task_ref_names = []  # Layer names for positional args
        task_ref_params = []  # Parameter names that map to those layer names
        literal_kwargs = {}

        for key, value in resolved_params.items():
            if key in param_to_task_ref:
                # This parameter should get a task reference
                task_ref_params.append(key)
                task_ref_names.append(param_to_task_ref[key])
            else:
                # Literal parameter
                literal_kwargs[key] = value

        # Wrap function to convert positional task refs back to kwargs
        # This is needed for magicgui compatibility
        if task_ref_params:
            from functools import wraps

            # Need to capture literal_kwargs in closure for runtime execution
            _literal_kwargs = literal_kwargs  # Capture in closure

            @wraps(func)
            def wrapper(*task_data):
                # Rebuild kwargs with task data
                kwargs = _literal_kwargs.copy()
                for param_name, data in zip(task_ref_params, task_data):
                    kwargs[param_name] = data
                return func(**kwargs)

            # Attach metadata for YAML serialization
            # This preserves parameter names when saving/loading workflows
            wrapper._ndev_param_names = task_ref_params
            wrapper._ndev_wrapped_func = func

            # Ensure all referenced layers exist in workflow as input tasks
            for layer_name in task_ref_names:
                if layer_name not in self._workflow._tasks:
                    # Add the layer data to workflow
                    layer = self._viewer.layers[layer_name]
                    self._workflow.set(layer_name, layer.data)
                    print(
                        f'[WorkflowManager] Auto-added input layer: {layer_name}'
                    )

            # Store with task refs as positional args AND literal kwargs
            # The kwargs will be stored in a partial for YAML serialization
            self._workflow.set(
                output_name, wrapper, *task_ref_names, **literal_kwargs
            )
        else:
            # No task refs, just literals
            self._workflow.set(output_name, func, **literal_kwargs)

    @property
    def viewer(self) -> Viewer:
        """The napari viewer being managed."""
        return self._viewer

    @property
    def undo_redo(self) -> UndoRedoController:
        """The undo/redo controller."""
        return self._undo_redo

    @property
    def pending_updates(self) -> list[str]:
        """List of task names pending update (read-only copy)."""
        return list(self._pending_updates)

    def is_layer_pending(self, name: str) -> bool:
        """Check if a layer/task is pending update.

        Parameters
        ----------
        name : str
            The task name to check.

        Returns
        -------
        bool
            True if the task is scheduled for update.
        """
        return name in self._pending_updates

    def update(
        self,
        target_layer: str | Layer,
        function: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Update or add a workflow step.

        Parameters
        ----------
        target_layer : str or Layer
            The target layer name or layer object.
        function : Callable
            The function to apply.
        *args : Any
            Arguments for the function (can include layer names).
        **kwargs : Any
            Keyword arguments for the function.

        Notes
        -----
        This saves the current state for undo, updates the workflow,
        and schedules dependent layers for re-execution.
        """
        # Save state for undo
        self._undo_redo.save_state()

        # Get target name
        target_name = (
            target_layer
            if isinstance(target_layer, str)
            else target_layer.name
        )

        # Convert layer objects to names in args
        processed_args = []
        for arg in args:
            if hasattr(arg, 'name'):
                processed_args.append(arg.name)
            else:
                processed_args.append(arg)

        # Update workflow
        self._workflow.set(target_name, function, *processed_args, **kwargs)

        # Schedule update of this and dependent layers
        self._schedule_update(target_name)

    def _schedule_update(self, name: str) -> None:
        """Schedule a layer update in the background.

        Parameters
        ----------
        name : str
            The task name to update.
        """
        if not self._auto_update_enabled:
            return

        # Add to pending updates
        if name not in self._pending_updates:
            self._pending_updates.append(name)

        # Also schedule followers
        for follower in self._workflow.followers_of(name):
            if follower not in self._pending_updates:
                self._pending_updates.append(follower)

        # Signal worker
        self._update_requested.set()

    def _start_worker(self) -> None:
        """Start the background update worker."""
        if self._worker_thread is not None:
            return

        self._stop_worker.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name='WorkflowManager-worker',
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Background worker loop for processing updates."""
        while not self._stop_worker.is_set():
            # Wait for update request
            self._update_requested.wait(timeout=0.5)
            if self._stop_worker.is_set():
                break

            # Small delay to batch updates
            time.sleep(self._update_delay)

            # Process pending updates
            while self._pending_updates:
                name = self._pending_updates.pop(0)
                try:
                    self._execute_update(name)
                except (ValueError, TypeError, RuntimeError, KeyError) as e:
                    warnings.warn(
                        f"Workflow update failed for '{name}': {e}",
                        stacklevel=2,
                    )

            self._update_requested.clear()

    def _execute_update(self, name: str) -> None:
        """Execute a workflow update and refresh the layer.

        Parameters
        ----------
        name : str
            The task name to execute.
        """
        # Check if this is a processing step (not raw data)
        if self._workflow.is_data_task(name):
            return

        # Execute the workflow step
        try:
            result = self._workflow.get(name)
        except (ValueError, TypeError, RuntimeError, KeyError) as e:
            warnings.warn(
                f"Failed to compute '{name}': {e}",
                stacklevel=2,
            )
            return

        # Update the layer if it exists
        try:
            layer = self._viewer.layers[name]
            layer.data = result
        except KeyError:
            # Layer doesn't exist, could add it
            pass
        except (ValueError, TypeError, RuntimeError) as e:
            warnings.warn(
                f"Failed to update layer '{name}': {e}",
                stacklevel=2,
            )

    def stop(self) -> None:
        """Stop the background worker."""
        self._stop_worker.set()
        self._update_requested.set()  # Wake up worker
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

    def invalidate(self, name: str) -> None:
        """Invalidate a task and its followers.

        Parameters
        ----------
        name : str
            The task name to invalidate.

        Notes
        -----
        This schedules the task and all dependent tasks for re-execution.
        """
        self._schedule_update(name)

    def undo(self) -> None:
        """Undo the last workflow change."""
        self._undo_redo.undo()
        # Refresh all layers
        for name in self._workflow:
            if not self._workflow.is_data_task(name):
                self._schedule_update(name)

    def redo(self) -> None:
        """Redo the last undone change."""
        self._undo_redo.redo()
        # Refresh all layers
        for name in self._workflow:
            if not self._workflow.is_data_task(name):
                self._schedule_update(name)

    def clear(self) -> None:
        """Clear the workflow."""
        self._undo_redo.save_state()
        self._workflow.clear()

    def to_python_code(
        self,
        notebook: bool = False,
        use_napari: bool = True,
    ) -> str:
        """Generate Python code from the workflow.

        Parameters
        ----------
        notebook : bool, optional
            If True, format as Jupyter notebook cells. Default False.
        use_napari : bool, optional
            If True, include napari viewer code. Default True.

        Returns
        -------
        str
            Python code that reproduces the workflow.
        """
        lines = []

        # Collect imports
        imports = set()
        for name in self._workflow:
            func = self._workflow.get_function(name)
            if func is not None:
                # Handle partial functions
                if hasattr(func, 'func'):
                    func = func.func
                if hasattr(func, '__module__') and hasattr(func, '__name__'):
                    imports.add(
                        f'from {func.__module__} import {func.__name__}'
                    )

        # Add imports
        if imports:
            lines.extend(sorted(imports))
            lines.append('')

        if use_napari:
            lines.append('import napari')
            lines.append('viewer = napari.Viewer()')
            lines.append('')

        # Generate code for each task in dependency order
        executed = set()

        def generate_task(name: str) -> None:
            if name in executed:
                return

            # First generate dependencies
            for source in self._workflow.sources_of(name):
                generate_task(source)

            task = self._workflow.get_task(name)
            if task is None:
                return

            if self._workflow.is_data_task(name):
                # Data task - placeholder
                lines.append(f'# {name} = <load your data here>')
            else:
                # Processing task
                func = task[0]
                args = task[1:]

                # Get function name
                if hasattr(func, 'func'):
                    func_name = func.func.__name__
                    # Include kwargs from partial
                    if hasattr(func, 'keywords') and func.keywords:
                        kwargs_str = ', '.join(
                            f'{k}={repr(v)}' for k, v in func.keywords.items()
                        )
                        args_str = ', '.join(str(a) for a in args)
                        if args_str:
                            call = f'{func_name}({args_str}, {kwargs_str})'
                        else:
                            call = f'{func_name}({kwargs_str})'
                    else:
                        args_str = ', '.join(str(a) for a in args)
                        call = f'{func_name}({args_str})'
                else:
                    func_name = getattr(func, '__name__', 'unknown_function')
                    args_str = ', '.join(str(a) for a in args)
                    call = f'{func_name}({args_str})'

                lines.append(f'{name} = {call}')

            executed.add(name)

        for name in self._workflow:
            generate_task(name)

        if use_napari:
            lines.append('')
            lines.append('napari.run()')

        code = '\n'.join(lines)

        if notebook:
            # Split into cells at blank lines
            # This is a simple implementation; could be enhanced
            code = code.replace('\n\n', '\n# %%\n')

        return code

    def __del__(self) -> None:
        """Cleanup when manager is deleted."""
        self.stop()
