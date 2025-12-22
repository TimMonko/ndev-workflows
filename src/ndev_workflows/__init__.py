"""ndev-workflows: Reproducible processing workflows with napari.

This package provides workflow management and batch processing for napari.
It is a fork of napari-workflows by Robert Haase (BSD-3-Clause license),
enhanced with:
- Safe YAML loading (no arbitrary code execution)
- Human-readable workflow format
- Integration with ndev-settings and nbatch
- npe2-native plugin architecture

Key Components
--------------
Workflow : class
    Core dask-compatible workflow class for task graph management.
WorkflowManager : class
    Singleton manager for napari viewer integration with undo/redo.
WorkflowContainer : Container widget
    A magicgui Container for interactive workflow management with batch
    processing support via nbatch.
UndoRedoController : class
    Undo/redo state management for workflows.

I/O Functions
-------------
save_workflow, load_workflow : functions
    Human-readable YAML format (recommended).
migrate_legacy : function
    Convert legacy napari-workflows files to new format.

Example
-------
>>> from ndev_workflows import Workflow, save_workflow, load_workflow
>>> w = Workflow()
>>> w.set("blurred", gaussian, "input", sigma=2.0)
>>> save_workflow("my_workflow.yaml", w, name="My Pipeline")
>>>
>>> loaded = load_workflow("my_workflow.yaml")
>>> loaded.set("input", image_data)
>>> result = loaded.get("blurred")

Attribution
-----------
This package includes code derived from napari-workflows:
https://github.com/haesleinhuepf/napari-workflows
Copyright (c) 2021, Robert Haase - BSD 3-Clause License
See NOTICE file for details.
"""

from __future__ import annotations

try:
    from ._version import version as __version__
except ImportError:
    __version__ = 'unknown'

# Core workflow class
# Workflow container widget and batch function - lazy import to avoid
# ndevio dependency issues when ndevio is installed from PyPI
from typing import TYPE_CHECKING

# Batch file processing functionality
from ._batch import process_workflow_file

# I/O functions
from ._io import (
    WorkflowYAMLError,
    is_legacy_format,
    load_workflow,
    migrate_legacy,
    save_workflow,
)

# Workflow manager for napari integration
from ._manager import WorkflowManager

# Runnable checks / resolution
from ._spec import ensure_runnable

# Undo/redo functionality
from ._undo_redo import UndoRedoController, copy_workflow_state
from ._workflow import Workflow, WorkflowNotRunnableError

if TYPE_CHECKING:
    from .widgets._workflow_container import (
        WorkflowContainer,
    )


def __getattr__(name: str):
    """Lazily import WorkflowContainer to speed up package import."""
    if name == 'WorkflowContainer':
        from .widgets._workflow_container import WorkflowContainer

        return WorkflowContainer
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = (
    # Core workflow class
    'Workflow',
    'copy_workflow_state',
    # Workflow manager
    'WorkflowManager',
    # Undo/redo
    'UndoRedoController',
    # I/O functions
    'save_workflow',
    'load_workflow',
    'migrate_legacy',
    'is_legacy_format',
    'WorkflowYAMLError',
    # Runnable checks / resolution
    'ensure_runnable',
    'WorkflowNotRunnableError',
    # Widgets and batch processing
    'WorkflowContainer',
    'process_workflow_file',
)
