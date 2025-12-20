"""Legacy format (napari-workflows) persistence.

This module handles loading workflows saved with the original napari-workflows
package. These files use Python pickle-style YAML tags that require unsafe loading.

For new workflows, use the functions in `_io.py` which use a plain YAML format.
"""

from __future__ import annotations

import importlib
from functools import partial
from pathlib import Path

import yaml

from ._workflow import Workflow


class FunctionReference:
    """Placeholder for a function that hasn't been imported yet.

    Used during workflow loading when the function's module
    isn't installed or we want to avoid importing it.

    Parameters
    ----------
    module : str
        The module path (e.g., 'skimage.filters').
    name : str
        The function name (e.g., 'gaussian').

    Attributes
    ----------
    module : str
        The module path.
    name : str
        The function name.
    kwargs : dict
        Keyword arguments to be passed to the function (from partial).
    """

    def __init__(self, module: str, name: str):
        self.module = module
        self.name = name
        self.kwargs: dict = {}

    def __repr__(self) -> str:
        if self.kwargs:
            return f'FunctionReference({self.module}.{self.name}, kwargs={self.kwargs})'
        return f'FunctionReference({self.module}.{self.name})'

    def __call__(self, *args, **kwargs):
        raise NotImplementedError(
            f'Cannot call {self.module}.{self.name} - function not resolved. '
            f'Use func_ref.resolve() to import, or install the required module.'
        )

    def resolve(self):
        """Attempt to import and return the actual function.

        Returns
        -------
        callable
            The imported function, wrapped in partial if kwargs present.

        Raises
        ------
        ImportError
            If the module cannot be imported.
        AttributeError
            If the function doesn't exist in the module.
        """
        module = importlib.import_module(self.module)
        func = getattr(module, self.name)
        if self.kwargs:
            return partial(func, **self.kwargs)
        return func


def is_legacy_format(filename: str | Path) -> bool:
    """Check if a workflow file is in legacy napari-workflows format.

    Parameters
    ----------
    filename : str or Path
        Path to the YAML file.

    Returns
    -------
    bool
        True if the file uses legacy !!python/object format.
    """
    with open(filename) as f:
        first_line = f.readline()
    return '!!python/object:napari_workflows' in first_line


def load_legacy_lazy(filename: str | Path) -> Workflow:
    """Load a legacy workflow without importing function modules.

    This is useful for inspecting or migrating workflows when the
    original function modules are not installed.

    Parameters
    ----------
    filename : str or Path
        Path to the YAML file.

    Returns
    -------
    Workflow
        The loaded workflow with FunctionReference placeholders.

    Notes
    -----
    The returned workflow cannot be executed (functions are placeholders),
    but it can be inspected, migrated, or its structure can be examined.
    """

    class LazyLoader(yaml.SafeLoader):
        pass

    def construct_python_tuple(loader, node):
        return tuple(loader.construct_sequence(node))

    def construct_python_name(loader, suffix, node):
        """Return a FunctionReference instead of importing."""
        # suffix is like 'skimage.filters.gaussian'
        parts = suffix.rsplit('.', 1)
        if len(parts) == 2:
            module, name = parts
        else:
            module = ''
            name = suffix
        return FunctionReference(module, name)

    def construct_legacy_workflow(loader, node):
        mapping = loader.construct_mapping(node, deep=True)
        workflow = Workflow()
        workflow._tasks = mapping.get('_tasks', {})
        return workflow

    LazyLoader.add_constructor(
        'tag:yaml.org,2002:python/tuple', construct_python_tuple
    )
    LazyLoader.add_multi_constructor(
        'tag:yaml.org,2002:python/name:', construct_python_name
    )
    LazyLoader.add_constructor(
        'tag:yaml.org,2002:python/object:napari_workflows._workflow.Workflow',
        construct_legacy_workflow,
    )

    with open(filename, 'rb') as stream:
        return yaml.load(stream, Loader=LazyLoader)
