"""ndev-workflows: Reproducible processing workflows with napari.

This package provides workflow management and batch processing for napari.
It is a fork of napari-workflows by Robert Haase (BSD-3-Clause license),
enhanced with:
- Safe YAML loading (no arbitrary code execution)
- Human-readable workflow format
- Integration with ndev-settings and nbatch
- npe2-native plugin architecture

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
"""

try:
    from ._version import version as __version__
except ImportError:
    __version__ = 'unknown'

from ._io import load_workflow, save_workflow
from ._workflow import Workflow

__all__ = [
    'Workflow',
    'load_workflow',
    'save_workflow',
]
