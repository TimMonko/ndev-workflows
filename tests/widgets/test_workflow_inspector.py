"""Tests for WorkflowInspector widget.

Tests are organized into:
- Unit tests (basic functionality without Qt event loop)
- Widget tests (with qtbot for async Qt testing)
"""

from __future__ import annotations

import pytest

from ndev_workflows import Workflow
from ndev_workflows._manager import WorkflowManager


# =============================================================================
# Unit tests - Basic functionality
# =============================================================================


class TestWorkflowInspectorBasics:
    """Basic tests for WorkflowInspector without full Qt integration."""

    def test_import(self):
        """Test that WorkflowInspector can be imported."""
        from ndev_workflows.widgets._workflow_inspector import (
            WorkflowInspector,
        )

        assert WorkflowInspector is not None

    def test_mpl_canvas_import(self):
        """Test MplCanvas can be imported (may fail if matplotlib missing)."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MplCanvas

        assert MplCanvas is not None


class TestManagerStatusMethods:
    """Test the new status methods added to WorkflowManager."""

    def test_get_layer_status_root(self, make_napari_viewer):
        """Test get_layer_status returns 'root' for root tasks."""
        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        # Add a simple workflow with a root
        def identity(x):
            return x

        manager.workflow.set('output', identity, 'input')

        status = manager.get_layer_status('input')
        assert status == 'root'

    def test_get_layer_status_valid(self, make_napari_viewer):
        """Test get_layer_status returns 'valid' for computed tasks."""
        import numpy as np

        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        # Add a simple workflow
        def identity(x):
            return x

        manager.workflow.set('input', np.zeros((10, 10)))
        manager.workflow.set('output', identity, 'input')

        # Clear pending updates to simulate completed computation
        manager._pending_updates.clear()

        status = manager.get_layer_status('output')
        assert status == 'valid'

    def test_is_layer_pending(self, make_napari_viewer):
        """Test is_layer_pending method."""
        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        # Manually add to pending
        manager._pending_updates.append('test_layer')

        assert manager.is_layer_pending('test_layer') is True
        assert manager.is_layer_pending('other_layer') is False

    def test_pending_updates_property(self, make_napari_viewer):
        """Test pending_updates property returns a copy."""
        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        manager._pending_updates.append('test')
        pending = manager.pending_updates

        # Should be a copy, not the original
        assert pending == ['test']
        pending.append('modified')
        assert manager._pending_updates == ['test']


# =============================================================================
# Widget tests - Require qtbot
# =============================================================================


class TestWorkflowInspectorWidget:
    """Widget tests requiring qtbot for Qt event loop."""

    @pytest.fixture
    def inspector(self, make_napari_viewer, qtbot):
        """Create a WorkflowInspector widget."""
        pytest.importorskip('matplotlib')
        pytest.importorskip('networkx')

        from ndev_workflows.widgets._workflow_inspector import (
            WorkflowInspector,
        )

        viewer = make_napari_viewer()
        widget = WorkflowInspector(viewer)
        qtbot.addWidget(widget)
        return widget

    def test_inspector_creates(self, inspector):
        """Test inspector widget can be created."""
        assert inspector is not None
        assert inspector.tabs is not None

    def test_inspector_has_tabs(self, inspector):
        """Test inspector has expected tabs."""
        assert inspector.tabs.count() == 5
        assert inspector.tabs.tabText(0) == 'Graph'
        assert inspector.tabs.tabText(1) == 'From Roots'
        assert inspector.tabs.tabText(2) == 'From Leaves'
        assert inspector.tabs.tabText(3) == 'Raw'
        assert inspector.tabs.tabText(4) == 'Info'

    def test_timer_starts(self, inspector):
        """Test that update timer starts."""
        assert inspector.timer.isActive()

    def test_timer_stops_on_close(self, inspector, qtbot):
        """Test timer stops when widget is closed."""
        inspector.close()
        assert not inspector.timer.isActive()

    def test_create_nx_graph_empty(self, inspector):
        """Test graph creation with empty workflow."""
        import networkx as nx

        workflow = Workflow()
        graph = inspector._create_nx_graph(workflow)

        assert isinstance(graph, nx.DiGraph)
        assert len(graph.nodes) == 0

    def test_create_nx_graph_simple(self, inspector):
        """Test graph creation with simple workflow."""
        import networkx as nx

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('output', identity, 'input')

        graph = inspector._create_nx_graph(workflow)

        assert isinstance(graph, nx.DiGraph)
        assert 'output' in graph.nodes
        # Note: 'input' is a reference, not a task, so may not be in nodes
        # depending on implementation

    def test_build_tree_html(self, inspector, make_napari_viewer):
        """Test HTML tree building."""

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('output', identity, 'input')

        html = inspector._build_tree_html(
            ['input'], workflow.followers_of, workflow
        )

        # Should contain the input name
        assert 'input' in html or '→' in html

    def test_wrap_html(self, inspector):
        """Test HTML wrapping."""
        content = 'test content'
        wrapped = inspector._wrap_html(content)

        assert '<html>' in wrapped
        assert '<pre>' in wrapped
        assert content in wrapped


class TestWorkflowInspectorFileMode:
    """Tests for file loading functionality."""

    @pytest.fixture
    def inspector(self, make_napari_viewer, qtbot):
        """Create a WorkflowInspector widget."""
        pytest.importorskip('matplotlib')
        pytest.importorskip('networkx')

        from ndev_workflows.widgets._workflow_inspector import (
            WorkflowInspector,
        )

        viewer = make_napari_viewer()
        widget = WorkflowInspector(viewer)
        qtbot.addWidget(widget)
        return widget

    def test_initial_mode_is_file(self, inspector):
        """Test inspector starts in file mode (not live mode)."""
        # Default is file mode since live mode requires napari-assistant
        assert inspector._use_live_mode is False
        assert inspector._loaded_workflow is None

    def test_load_workflow_file(self, inspector, tmp_path):
        """Test loading a workflow from YAML file."""
        from ndev_workflows import Workflow, save_workflow

        # Create a test workflow file
        def add_one(x):
            return x + 1

        workflow = Workflow()
        workflow.set('output', add_one, 'input')

        yaml_file = tmp_path / 'test_workflow.yaml'
        save_workflow(yaml_file, workflow)

        # Load the file
        inspector.load_workflow_file(yaml_file)

        # Should stay in file mode
        assert inspector._use_live_mode is False
        assert inspector._loaded_workflow is not None
        assert inspector._workflow_file == yaml_file

    def test_load_sets_status_label(self, inspector, tmp_path):
        """Test loading updates status label."""
        from ndev_workflows import Workflow, save_workflow

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('out', identity, 'in')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        assert 'test.yaml' in inspector.status_label.text()

    def test_toggle_to_live_mode(self, inspector, tmp_path):
        """Test toggling to live mode."""
        from ndev_workflows import Workflow, save_workflow

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('out', identity, 'in')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        # Load file
        inspector.load_workflow_file(yaml_file)
        assert inspector._use_live_mode is False
        assert inspector._loaded_workflow is not None

        # Toggle to live
        inspector._on_live_toggled(True)
        assert inspector._use_live_mode is True
        assert inspector._loaded_workflow is None

    def test_get_workflow_in_file_mode(self, inspector, tmp_path):
        """Test _get_workflow returns loaded workflow in file mode."""
        from ndev_workflows import Workflow, save_workflow

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('out', identity, 'in')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        result = inspector._get_workflow()
        assert result is not None
        assert 'out' in result
