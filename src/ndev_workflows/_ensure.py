"""Helpers for making workflows runnable.

The key feature here is :func:`ensure_runnable`, which resolves any
:class:`~ndev_workflows._spec.CallableRef` placeholders into real
imported callables.

This is most useful when loading workflows with ``lazy=True`` (or when
migrating legacy workflows) so users can inspect/migrate even when optional
dependencies are missing.
"""

from __future__ import annotations

import importlib
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial

from ._spec import CallableRef, spec_dict_to_workflow
from ._workflow import Workflow


@dataclass(frozen=True, slots=True)
class MissingCallable:
    module: str
    name: str
    error: str
    install_suggestion: str | None = None


class WorkflowNotRunnableError(RuntimeError):
    def __init__(self, missing: Iterable[MissingCallable]):
        self.missing = tuple(missing)
        lines: list[str] = ['Workflow is not runnable; missing callables:']
        for item in self.missing:
            msg = f'- Cannot import {item.module}.{item.name}: {item.error}'
            if item.install_suggestion:
                msg += f' (try: {item.install_suggestion})'
            lines.append(msg)
        super().__init__('\n'.join(lines))


_DEFAULT_INSTALL_SUGGESTIONS: dict[str, str] = {
    'skimage': 'pip install scikit-image',
    'skan': 'pip install skan',
    'napari_workflows': 'pip install napari-workflows',
    'napari': 'pip install napari',
}


def _install_suggestion_for_module(module: str) -> str | None:
    top = module.split('.', 1)[0]
    return _DEFAULT_INSTALL_SUGGESTIONS.get(top)


def ensure_runnable(
    workflow_or_spec: Workflow | dict,
    *,
    on_missing: str = 'raise',
) -> Workflow:
    """Ensure a workflow is runnable by importing any placeholder callables.

    Parameters
    ----------
    workflow_or_spec : Workflow or dict
        Either a Workflow instance (possibly loaded with ``lazy=True``) or a
        new-format spec dict.
    on_missing : {'raise', 'warn'}, optional
        Behavior when one or more callables cannot be imported.

    Returns
    -------
    Workflow
        The same workflow instance (mutated in place) or a new Workflow (if a
        spec dict was provided).

    Raises
    ------
    WorkflowNotRunnableError
        If imports fail and ``on_missing='raise'``.
    ValueError
        If ``on_missing`` is invalid.
    """
    if on_missing not in {'raise', 'warn'}:
        raise ValueError("on_missing must be 'raise' or 'warn'")

    if isinstance(workflow_or_spec, dict):
        workflow = spec_dict_to_workflow(workflow_or_spec, lazy=True)
    else:
        workflow = workflow_or_spec

    missing: list[MissingCallable] = []

    for task_name, task in list(workflow._tasks.items()):
        if not isinstance(task, tuple) or len(task) == 0:
            continue

        func = task[0]
        if not isinstance(func, CallableRef):
            continue

        try:
            module = importlib.import_module(func.module)
            real_func = getattr(module, func.name)
        except (ImportError, AttributeError) as e:
            missing.append(
                MissingCallable(
                    module=func.module,
                    name=func.name,
                    error=str(e),
                    install_suggestion=_install_suggestion_for_module(
                        func.module
                    ),
                )
            )
            continue

        if getattr(func, 'kwargs', None):
            real_func = partial(real_func, **dict(func.kwargs))

        workflow._tasks[task_name] = (real_func, *task[1:])

    if missing:
        err = WorkflowNotRunnableError(missing)
        if on_missing == 'warn':
            warnings.warn(str(err), stacklevel=2)
            return workflow
        raise err

    return workflow
