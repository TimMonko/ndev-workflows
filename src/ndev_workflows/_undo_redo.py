"""Undo/redo functionality for workflows.

This module is derived from napari-workflows by Robert Haase (BSD-3-Clause).
See NOTICE file for attribution.

Provides an UndoRedoController that tracks workflow states and allows
undo/redo operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._workflow import Workflow


class UndoRedoController:
    """Controller for undo/redo operations on workflows.

    The controller maintains two stacks:
    - undo_stack: Previous states that can be restored
    - redo_stack: States undone that can be re-applied

    Parameters
    ----------
    workflow : Workflow
        The workflow to track.
    max_history : int, optional
        Maximum number of states to keep in history. Default 50.

    Examples
    --------
    >>> controller = UndoRedoController(workflow)
    >>> controller.save_state()  # Before making changes
    >>> # ... make changes to workflow ...
    >>> controller.undo()  # Restore previous state
    >>> controller.redo()  # Re-apply the undone changes
    """

    def __init__(self, workflow: Workflow, max_history: int = 50) -> None:
        """Initialize the undo/redo controller.

        Parameters
        ----------
        workflow : Workflow
            The workflow to track.
        max_history : int, optional
            Maximum number of states to keep in history. Default 50.
        """
        self._workflow = workflow
        self._max_history = max_history
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

    @property
    def can_undo(self) -> bool:
        """Whether undo is available."""
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        """Whether redo is available."""
        return len(self._redo_stack) > 0

    @property
    def undo_stack_size(self) -> int:
        """Number of states in undo stack."""
        return len(self._undo_stack)

    @property
    def redo_stack_size(self) -> int:
        """Number of states in redo stack."""
        return len(self._redo_stack)

    def save_state(self) -> None:
        """Save the current workflow state to the undo stack.

        Call this before making changes to the workflow that you want
        to be undoable.

        Notes
        -----
        Saving a new state clears the redo stack.
        """
        from copy import deepcopy

        # Deep copy the tasks dict
        state = deepcopy(self._workflow._tasks)
        self._undo_stack.append(state)

        # Trim history if needed
        while len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

        # Clear redo stack when new state is saved
        self._redo_stack.clear()

    def undo(self) -> bool:
        """Restore the previous workflow state.

        Returns
        -------
        bool
            True if undo was successful, False if stack was empty.
        """
        if not self.can_undo:
            return False

        from copy import deepcopy

        # Save current state to redo stack
        current_state = deepcopy(self._workflow._tasks)
        self._redo_stack.append(current_state)

        # Restore previous state
        previous_state = self._undo_stack.pop()
        self._workflow._tasks = previous_state

        return True

    def redo(self) -> bool:
        """Re-apply a previously undone change.

        Returns
        -------
        bool
            True if redo was successful, False if stack was empty.
        """
        if not self.can_redo:
            return False

        from copy import deepcopy

        # Save current state to undo stack
        current_state = deepcopy(self._workflow._tasks)
        self._undo_stack.append(current_state)

        # Restore redo state
        redo_state = self._redo_stack.pop()
        self._workflow._tasks = redo_state

        return True

    def clear_history(self) -> None:
        """Clear all undo/redo history."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    def get_workflow_copy(self) -> Workflow:
        """Get a copy of the current workflow.

        Returns
        -------
        Workflow
            A deep copy of the tracked workflow.
        """
        return self._workflow.copy()


def copy_workflow_state(workflow: Workflow) -> Workflow:
    """Create a copy of a workflow.

    Parameters
    ----------
    workflow : Workflow
        The workflow to copy.

    Returns
    -------
    Workflow
        A deep copy of the workflow.

    Notes
    -----
    This is a convenience function for external use. The UndoRedoController
    uses internal state copying for efficiency.
    """
    return workflow.copy()
