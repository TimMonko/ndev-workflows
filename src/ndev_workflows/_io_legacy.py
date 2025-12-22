"""Legacy format (napari-workflows) persistence.

This module handles loading workflows saved with the original napari-workflows
package. These files use Python pickle-style YAML tags that require unsafe loading.

For new workflows, use the functions in `_io.py` which use a plain YAML format.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import yaml

from ._workflow import CallableRef, Workflow


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
    with open(filename, encoding='utf-8', errors='replace') as f:
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
        The loaded workflow with CallableRef placeholders.

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
        """Return a CallableRef instead of importing."""
        # suffix is like 'skimage.filters.gaussian'
        parts = suffix.rsplit('.', 1)
        if len(parts) == 2:
            module, name = parts
        else:
            module = ''
            name = suffix
        return CallableRef(module, name)

    def construct_legacy_workflow(loader, node):
        mapping = loader.construct_mapping(node, deep=True)
        workflow = Workflow()
        workflow._tasks = mapping.get('_tasks', {})
        return workflow

    def construct_functools_partial(loader, node):
        """Construct a CallableRef from legacy functools.partial tags.

        Legacy napari-workflows YAML may encode keyword arguments as
        ``!!python/object/apply:functools.partial``.

        We keep this loader *lazy* by returning a CallableRef and storing
        the keyword arguments on it.
        """
        seq = loader.construct_sequence(node, deep=True)
        if not seq:
            return None

        func = seq[0]

        # Common encodings:
        #   [func, args_tuple_or_list, kwargs_dict]
        #   [func, kwargs_dict]
        kwargs = {}
        if len(seq) >= 3 and isinstance(seq[2], dict):
            kwargs = seq[2]
        elif len(seq) == 2 and isinstance(seq[1], dict):
            kwargs = seq[1]

        if isinstance(func, CallableRef):
            func.kwargs = dict(kwargs)
            return func

        # Fallback: if we somehow got a real callable, keep it callable.
        # This is still safe because SafeLoader will not construct arbitrary
        # callables unless we registered constructors for them.
        if kwargs and callable(func):
            return partial(func, **kwargs)
        return func

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
    LazyLoader.add_constructor(
        'tag:yaml.org,2002:python/object/apply:functools.partial',
        construct_functools_partial,
    )

    with open(filename, 'rb') as stream:
        return yaml.load(stream, Loader=LazyLoader)
