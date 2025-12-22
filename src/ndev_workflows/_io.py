"""YAML-based workflow persistence.

This module provides functions for saving and loading workflows in a
human-readable YAML format that is safe to load (no arbitrary code execution).

For loading legacy napari-workflows files, see `_io_legacy.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ._io_legacy import is_legacy_format
from ._spec import (
    ensure_runnable,
    legacy_yaml_to_spec_dict,
    spec_dict_to_workflow,
    workflow_to_spec_dict,
)
from ._workflow import Workflow, WorkflowNotRunnableError

if TYPE_CHECKING:
    pass


class WorkflowYAMLError(Exception):
    """Error during workflow YAML serialization/deserialization."""


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
    data = workflow_to_spec_dict(workflow, name=name, description=description)

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
        If True, don't import functions (use CallableRef placeholders).
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
    # Always normalize to a spec dict first, then apply the same
    # lazy/eager workflow construction logic.
    if is_legacy_format(filename):
        spec = legacy_yaml_to_spec_dict(filename, include_modified=False)
        is_legacy = True
    else:
        try:
            with open(filename) as f:
                spec = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise WorkflowYAMLError(f'Failed to parse YAML: {e}') from e
        is_legacy = False

    workflow = spec_dict_to_workflow(spec, lazy=True)
    workflow.metadata['legacy'] = is_legacy
    if lazy:
        return workflow

    try:
        return ensure_runnable(workflow)
    except WorkflowNotRunnableError as e:
        raise WorkflowYAMLError(str(e)) from e


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

    migrated_name = name or f'Migrated: {input_path.stem}'

    # Convert legacy YAML to new spec dict lazily, then save the spec.
    spec = legacy_yaml_to_spec_dict(
        input_file,
        name=migrated_name,
        include_modified=True,
    )

    with open(output_file, 'w') as f:
        yaml.safe_dump(spec, f, default_flow_style=False, sort_keys=False)

    # Return a normalized lazy workflow (new-format in-memory representation).
    return spec_dict_to_workflow(spec, lazy=True)


# Re-export commonly used items
__all__ = [
    'WorkflowYAMLError',
    'save_workflow',
    'load_workflow',
    'migrate_legacy',
    'is_legacy_format',
]
