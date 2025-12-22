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

        # Start background worker
        self._start_worker()

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

    @property
    def viewer(self) -> Viewer:
        """The napari viewer being managed."""
        return self._viewer

    @property
    def undo_redo(self) -> UndoRedoController:
        """The undo/redo controller."""
        return self._undo_redo

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
