"""Tests for UndoRedoController."""

from __future__ import annotations

import numpy as np

from ndev_workflows import Workflow
from ndev_workflows._undo_redo import UndoRedoController


def add_value(x, value=10):
    """Test function for addition."""
    return x + value


class TestUndoRedoBasics:
    """Test basic undo/redo functionality."""

    def test_controller_creation(self, empty_workflow: Workflow):
        """Test creating an UndoRedoController."""
        controller = UndoRedoController(empty_workflow)

        assert controller.can_undo is False
        assert controller.can_redo is False
        assert controller.undo_stack_size == 0
        assert controller.redo_stack_size == 0

    def test_save_state(self, empty_workflow: Workflow):
        """Test saving state."""
        controller = UndoRedoController(empty_workflow)

        controller.save_state()

        assert controller.can_undo is True
        assert controller.undo_stack_size == 1

    def test_undo_restores_state(self, sample_image: np.ndarray):
        """Test that undo restores previous state."""
        w = Workflow()
        controller = UndoRedoController(w)

        # Initial empty state
        controller.save_state()

        # Add a task
        w.set('input', sample_image)

        # Check task was added
        assert 'input' in w

        # Undo
        result = controller.undo()

        assert result is True
        assert 'input' not in w
        assert controller.can_redo is True

    def test_redo_reapplies_change(self, sample_image: np.ndarray):
        """Test that redo reapplies undone change."""
        w = Workflow()
        controller = UndoRedoController(w)

        # Save empty state
        controller.save_state()

        # Add task
        w.set('input', sample_image)

        # Undo
        controller.undo()
        assert 'input' not in w

        # Redo
        result = controller.redo()

        assert result is True
        assert 'input' in w
        assert controller.can_undo is True

    def test_undo_empty_stack_returns_false(self, empty_workflow: Workflow):
        """Test undo with empty stack returns False."""
        controller = UndoRedoController(empty_workflow)

        result = controller.undo()

        assert result is False

    def test_redo_empty_stack_returns_false(self, empty_workflow: Workflow):
        """Test redo with empty stack returns False."""
        controller = UndoRedoController(empty_workflow)

        result = controller.redo()

        assert result is False


class TestUndoRedoSequence:
    """Test undo/redo with multiple operations."""

    def test_multiple_undos(self, sample_image: np.ndarray):
        """Test multiple undo operations."""
        w = Workflow()
        controller = UndoRedoController(w)

        # State 0: empty
        controller.save_state()

        # State 1: add input
        w.set('input', sample_image)
        controller.save_state()

        # State 2: add step1
        w.set('step1', add_value, 'input')
        controller.save_state()

        # State 3: add step2
        w.set('step2', add_value, 'step1', value=20)

        assert len(w) == 3

        # Undo to state 2
        controller.undo()
        assert 'step2' not in w
        assert 'step1' in w

        # Undo to state 1
        controller.undo()
        assert 'step1' not in w
        assert 'input' in w

        # Undo to state 0
        controller.undo()
        assert 'input' not in w
        assert len(w) == 0

    def test_undo_redo_sequence(self, sample_image: np.ndarray):
        """Test alternating undo/redo."""
        w = Workflow()
        controller = UndoRedoController(w)

        controller.save_state()
        w.set('a', sample_image)
        controller.save_state()
        w.set('b', add_value, 'a')

        # Undo
        controller.undo()
        assert 'b' not in w
        assert 'a' in w

        # Redo
        controller.redo()
        assert 'b' in w

        # Undo again
        controller.undo()
        assert 'b' not in w

    def test_new_change_clears_redo_stack(self, sample_image: np.ndarray):
        """Test that making a new change clears redo stack."""
        w = Workflow()
        controller = UndoRedoController(w)

        controller.save_state()
        w.set('a', sample_image)

        # Undo
        controller.undo()
        assert controller.can_redo is True

        # Make new change
        controller.save_state()
        w.set('b', sample_image)

        # Redo should no longer be available
        assert controller.can_redo is False


class TestUndoRedoMaxHistory:
    """Test history size limits."""

    def test_max_history_enforced(self, sample_image: np.ndarray):
        """Test that max_history limits undo stack size."""
        w = Workflow()
        controller = UndoRedoController(w, max_history=3)

        # Add 5 states
        for i in range(5):
            controller.save_state()
            w.set(f'step{i}', sample_image)

        # Should only have 3 states
        assert controller.undo_stack_size == 3

    def test_clear_history(self, sample_image: np.ndarray):
        """Test clearing history."""
        w = Workflow()
        controller = UndoRedoController(w)

        controller.save_state()
        w.set('a', sample_image)
        controller.save_state()

        # Undo to create redo stack
        controller.undo()

        assert controller.can_undo is True
        assert controller.can_redo is True

        # Clear history
        controller.clear_history()

        assert controller.can_undo is False
        assert controller.can_redo is False


class TestUndoRedoWorkflowCopy:
    """Test workflow copying via undo/redo controller."""

    def test_get_workflow_copy(self, simple_workflow: Workflow):
        """Test getting a workflow copy."""
        controller = UndoRedoController(simple_workflow)

        copy = controller.get_workflow_copy()

        assert copy is not simple_workflow
        assert len(copy) == len(simple_workflow)
        assert copy.keys() == simple_workflow.keys()
