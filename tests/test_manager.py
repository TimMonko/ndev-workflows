"""Tests for WorkflowManager (_manager.py).

WorkflowManager requires napari, so tests use minimal viewer mocking
where possible and make_napari_viewer for integration tests.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from ndev_workflows._manager import WorkflowManager, _managers


# Use module-level functions for tests
def add_value(x, value: int = 10):
    """Helper function for addition tests."""
    return x + value


def multiply_value(x, factor: float = 2.0):
    """Helper function for multiplication tests."""
    return x * factor


class MockLayer:
    """Minimal mock for napari layer."""

    def __init__(self, name: str, data=None):
        self.name = name
        self.data = data


class MockLayers(dict):
    """Mock for viewer.layers that supports dict-like access."""


class MockViewer:
    """Minimal mock viewer for testing without Qt."""

    def __init__(self):
        self.layers = MockLayers()


@pytest.fixture
def mock_viewer() -> MockViewer:
    """Create a mock viewer."""
    return MockViewer()


@pytest.fixture(autouse=True)
def clear_managers():
    """Clear global managers registry before each test."""
    _managers.clear()
    yield
    _managers.clear()


class TestWorkflowManagerCreation:
    """Test WorkflowManager instantiation and singleton pattern."""

    def test_install_creates_manager(self, mock_viewer: MockViewer):
        """Test that install creates a new manager."""
        manager = WorkflowManager.install(mock_viewer)

        assert manager is not None
        assert isinstance(manager, WorkflowManager)
        assert manager.viewer is mock_viewer

    def test_install_returns_existing_manager(self, mock_viewer: MockViewer):
        """Test that install returns existing manager for same viewer."""
        manager1 = WorkflowManager.install(mock_viewer)
        manager2 = WorkflowManager.install(mock_viewer)

        assert manager1 is manager2

    def test_different_viewers_get_different_managers(self):
        """Test that different viewers get different managers."""
        viewer1 = MockViewer()
        viewer2 = MockViewer()

        manager1 = WorkflowManager.install(viewer1)
        manager2 = WorkflowManager.install(viewer2)

        assert manager1 is not manager2

    def test_manager_has_empty_workflow(self, mock_viewer: MockViewer):
        """Test that new manager has empty workflow."""
        manager = WorkflowManager.install(mock_viewer)

        assert len(manager.workflow) == 0

    def test_manager_has_undo_redo_controller(self, mock_viewer: MockViewer):
        """Test that manager has undo/redo controller."""
        manager = WorkflowManager.install(mock_viewer)

        assert manager.undo_redo is not None
        assert manager.undo_redo.can_undo is False


class TestWorkflowManagerUpdate:
    """Test workflow update functionality."""

    def test_update_adds_task(self, mock_viewer: MockViewer):
        """Test that update adds a task to the workflow."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.update('output', add_value, 'input', value=5)

        assert 'output' in manager.workflow

    def test_update_saves_undo_state(self, mock_viewer: MockViewer):
        """Test that update saves state for undo."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))
        manager.workflow.set('input', data)

        assert manager.undo_redo.can_undo is False

        manager.update('output', add_value, 'input', value=5)

        assert manager.undo_redo.can_undo is True

    def test_update_with_layer_object(self, mock_viewer: MockViewer):
        """Test that update converts layer objects to names."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))
        manager.workflow.set('input_layer', data)

        # Create mock layer
        layer = MockLayer('input_layer', data)

        manager.update('output', add_value, layer, value=5)

        # Should have stored the layer name, not the object
        sources = manager.workflow.sources_of('output')
        assert 'input_layer' in sources


class TestWorkflowManagerUndoRedo:
    """Test undo/redo integration."""

    def test_undo_reverts_workflow(self, mock_viewer: MockViewer):
        """Test that undo reverts the workflow."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))
        manager.workflow.set('input', data)

        # Add a task
        manager.update('output', add_value, 'input', value=5)
        assert 'output' in manager.workflow

        # Undo
        manager.undo()
        assert 'output' not in manager.workflow

    def test_redo_reapplies_change(self, mock_viewer: MockViewer):
        """Test that redo reapplies the undone change."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))
        manager.workflow.set('input', data)

        manager.update('output', add_value, 'input', value=5)
        manager.undo()
        assert 'output' not in manager.workflow

        manager.redo()
        assert 'output' in manager.workflow


class TestWorkflowManagerClear:
    """Test workflow clearing."""

    def test_clear_removes_all_tasks(self, mock_viewer: MockViewer):
        """Test that clear removes all tasks."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input')
        assert len(manager.workflow) == 2

        manager.clear()
        assert len(manager.workflow) == 0

    def test_clear_saves_undo_state(self, mock_viewer: MockViewer):
        """Test that clear is undoable."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input')

        manager.clear()
        assert len(manager.workflow) == 0

        manager.undo()
        assert len(manager.workflow) == 2


class TestWorkflowManagerInvalidate:
    """Test task invalidation."""

    def test_invalidate_schedules_update(self, mock_viewer: MockViewer):
        """Test that invalidate schedules an update."""
        manager = WorkflowManager.install(mock_viewer)
        manager._auto_update_enabled = False  # Disable for test

        manager.invalidate('test')

        # Since auto-update is disabled, pending should be empty
        assert 'test' not in manager._pending_updates


class TestWorkflowManagerStop:
    """Test worker thread management."""

    def test_stop_terminates_worker(self, mock_viewer: MockViewer):
        """Test that stop terminates the background worker."""
        manager = WorkflowManager.install(mock_viewer)

        assert manager._worker_thread is not None
        assert manager._worker_thread.is_alive()

        manager.stop()

        # Give thread time to stop
        time.sleep(0.2)

        # After stop, thread should be None or not alive
        if manager._worker_thread is not None:
            assert not manager._worker_thread.is_alive()


class TestWorkflowManagerCodeGeneration:
    """Test Python code generation."""

    def test_to_python_code_includes_imports(self, mock_viewer: MockViewer):
        """Test that generated code includes imports."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input', value=5)

        code = manager.to_python_code(use_napari=False)

        # Function defined in this module, so import will reference test_manager
        assert 'import add_value' in code
        assert 'add_value' in code

    def test_to_python_code_includes_napari(self, mock_viewer: MockViewer):
        """Test that generated code includes napari when requested."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input', value=5)

        code = manager.to_python_code(use_napari=True)

        assert 'import napari' in code
        assert 'viewer = napari.Viewer()' in code
        assert 'napari.run()' in code

    def test_to_python_code_data_placeholder(self, mock_viewer: MockViewer):
        """Test that data tasks get placeholder comments."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input')

        code = manager.to_python_code(use_napari=False)

        assert '# input = <load your data here>' in code

    def test_to_python_code_notebook_format(self, mock_viewer: MockViewer):
        """Test notebook format adds cell markers."""
        manager = WorkflowManager.install(mock_viewer)
        data = np.zeros((10, 10))

        manager.workflow.set('input', data)
        manager.workflow.set('output', add_value, 'input')

        code = manager.to_python_code(use_napari=True, notebook=True)

        assert '# %%' in code


class TestWorkflowManagerWithNapari:
    """Integration tests requiring actual napari viewer."""

    @pytest.fixture
    def napari_manager(self, make_napari_viewer):
        """Create a manager with real napari viewer."""
        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)
        yield manager
        manager.stop()

    def test_execute_update_updates_layer(self, napari_manager):
        """Test that executing update refreshes layer data."""
        data = np.random.randint(0, 255, (64, 64), dtype=np.uint8)

        # Add a layer directly to viewer
        napari_manager.viewer.add_image(data, name='input')

        # Add the data to workflow
        napari_manager.workflow.set('input', data)
        napari_manager.workflow.set('output', add_value, 'input', value=10)

        # Add output layer
        output_layer = napari_manager.viewer.add_image(
            np.zeros_like(data), name='output'
        )

        # Execute the update
        napari_manager._execute_update('output')

        # Check layer data was updated
        expected = data + 10
        np.testing.assert_array_equal(output_layer.data, expected)
