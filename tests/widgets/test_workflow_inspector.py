"""Tests for WorkflowInspector widget.

Focuses on testing our implementation, not underlying library behavior.
"""

from __future__ import annotations

import pytest

from ndev_workflows.widgets._workflow_inspector import (
    HAS_MATPLOTLIB,
    WorkflowInspector,
)


class TestWorkflowInspector:
    """Core WorkflowInspector widget tests."""

    @pytest.fixture
    def inspector(self, make_napari_viewer, qtbot):
        """Create a WorkflowInspector widget."""
        viewer = make_napari_viewer()
        widget = WorkflowInspector(viewer)
        qtbot.addWidget(widget)
        return widget

    def test_creates_with_expected_tabs(self, inspector):
        """Test widget creates with all expected tabs."""
        tab_names = [
            inspector.tabs.tabText(i) for i in range(inspector.tabs.count())
        ]
        assert 'Graph' in tab_names
        assert 'From Roots' in tab_names
        assert 'From Leaves' in tab_names
        assert 'Raw' in tab_names
        assert 'Info' in tab_names

    def test_starts_in_file_mode(self, inspector):
        """Test inspector starts in file mode by default."""
        assert inspector._use_live_mode is False
        assert inspector._loaded_workflow is None

    def test_timer_starts_and_stops(self, inspector):
        """Test timer lifecycle."""
        assert inspector.timer.isActive()
        inspector.close()
        assert not inspector.timer.isActive()

    def test_load_workflow_file(self, inspector, tmp_path):
        """Test loading a workflow from YAML file."""
        from ndev_workflows import Workflow, save_workflow

        def add_one(x):
            return x + 1

        workflow = Workflow()
        workflow.set('output', add_one, 'input')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        assert inspector._loaded_workflow is not None
        assert inspector._workflow_file == yaml_file
        assert 'test.yaml' in inspector.status_label.text()

    def test_load_nonexistent_file_shows_error(self, inspector, tmp_path):
        """Test loading a missing file shows error in status."""
        bad_path = tmp_path / 'nonexistent.yaml'
        inspector.load_workflow_file(bad_path)
        assert 'Error' in inspector.status_label.text()

    def test_toggle_live_mode(self, inspector, tmp_path):
        """Test toggling between file and live mode."""
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

        # Toggle to live mode - clears loaded workflow
        inspector._on_live_toggled(True)
        assert inspector._use_live_mode is True
        assert inspector._loaded_workflow is None

    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason='requires matplotlib')
    def test_graph_updates_on_workflow_load(self, inspector, tmp_path):
        """Test that graph is drawn when workflow is loaded."""
        from ndev_workflows import Workflow, save_workflow

        def step(x):
            return x

        workflow = Workflow()
        workflow.set('middle', step, 'input')
        workflow.set('output', step, 'middle')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        # Graph should be created with positions
        assert inspector._graph is not None
        assert inspector._positions is not None
        assert len(inspector._positions) > 0

    def test_node_status_detection(self, inspector, tmp_path):
        """Test node status is correctly determined."""
        from ndev_workflows import Workflow, save_workflow

        def step(x):
            return x

        workflow = Workflow()
        workflow.set('middle', step, 'input')
        workflow.set('output', step, 'middle')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        # Get the loaded workflow's roots and leaves
        loaded = inspector._loaded_workflow
        roots = loaded.roots()
        leaves = loaded.leaves()

        # Root should be detected
        assert (
            inspector._get_node_status_cached('input', roots, leaves) == 'root'
        )
        # Leaf should be detected
        assert (
            inspector._get_node_status_cached('output', roots, leaves)
            == 'leaf'
        )
        # Middle node should be valid (in file mode)
        assert (
            inspector._get_node_status_cached('middle', roots, leaves)
            == 'valid'
        )

    def test_info_text_contains_workflow_stats(self, inspector, tmp_path):
        """Test info text includes workflow statistics."""
        from ndev_workflows import Workflow, save_workflow

        def my_func(x):
            return x

        workflow = Workflow()
        workflow.set('output', my_func, 'input')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)
        loaded = inspector._loaded_workflow
        info = inspector._build_info_text(
            loaded, loaded.roots(), loaded.leaves()
        )

        assert 'Total tasks:' in info
        assert 'Roots' in info
        assert 'Leaves' in info

    def test_empty_workflow_shows_message(self, inspector):
        """Test display when no workflow is loaded."""
        inspector._update()
        assert 'No workflow' in inspector.lbl_from_roots.text()


class TestManagerStatusMethods:
    """Test status methods added to WorkflowManager."""

    def test_is_layer_pending(self, make_napari_viewer):
        """Test is_layer_pending method."""
        from ndev_workflows._manager import WorkflowManager

        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        def identity(x):
            return x

        # Set up a workflow step
        manager.workflow.set('output', identity, 'input')

        # Use public invalidate() to mark as pending
        manager.invalidate('output')
        assert manager.is_layer_pending('output') is True
        assert manager.is_layer_pending('other') is False

    def test_pending_updates_property(self, make_napari_viewer):
        """Test pending_updates returns a copy."""
        from ndev_workflows._manager import WorkflowManager

        viewer = make_napari_viewer()
        manager = WorkflowManager.install(viewer)

        def identity(x):
            return x

        manager.workflow.set('test', identity, 'input')
        manager.invalidate('test')

        pending = manager.pending_updates

        assert 'test' in pending
        # Should be a copy - modifying returned list shouldn't affect manager
        pending.append('modified')
        assert 'modified' not in manager.pending_updates


@pytest.mark.skipif(not HAS_MATPLOTLIB, reason='requires matplotlib')
class TestDraggableNodes:
    """Test DraggableNodes interaction handling (requires matplotlib)."""

    @pytest.fixture
    def draggable_nodes(self):
        """Create DraggableNodes with real MplCanvas."""
        from unittest.mock import MagicMock

        from ndev_workflows.widgets._workflow_inspector import (
            DraggableNodes,
            MplCanvas,
        )

        canvas = MplCanvas()
        positions = {'node1': (0.0, 0.0), 'node2': (1.0, 1.0)}
        callback = MagicMock()

        nodes = DraggableNodes(
            canvas, positions, viewer=None, on_positions_changed=callback
        )
        return nodes, callback

    def test_drag_updates_position(self, draggable_nodes):
        """Test that dragging updates node position."""
        from unittest.mock import MagicMock

        nodes, callback = draggable_nodes

        # Simulate pick -> press -> motion -> release
        pick_event = MagicMock()
        pick_event.mouseevent.button = 1
        pick_event.ind = [0]
        nodes._on_pick(pick_event)

        press_event = MagicMock()
        press_event.button = 1
        nodes._on_press(press_event)

        motion_event = MagicMock()
        motion_event.xdata = 0.5
        motion_event.ydata = 0.6
        nodes._on_motion(motion_event)

        assert nodes.positions['node1'] == (0.5, 0.6)
        assert callback.called

        release_event = MagicMock()
        release_event.button = 1
        nodes._on_release(release_event)
        assert nodes._dragging is False

    def test_update_node_status_changes_color(self, draggable_nodes):
        """Test status updates change node colors."""
        nodes, _ = draggable_nodes

        # Should not raise for any status
        for status in ['root', 'leaf', 'valid', 'invalid']:
            nodes.update_node_status('node1', status)

    def test_select_node_with_viewer(self, make_napari_viewer):
        """Test clicking a node selects the layer in viewer."""
        import numpy as np

        from ndev_workflows.widgets._workflow_inspector import (
            DraggableNodes,
            MplCanvas,
        )

        viewer = make_napari_viewer()
        viewer.add_image(np.zeros((10, 10)), name='test_layer')

        canvas = MplCanvas()
        positions = {'test_layer': (0.0, 0.0)}
        nodes = DraggableNodes(canvas, positions, viewer=viewer)

        nodes._select_node(0)

        assert viewer.layers.selection == {viewer.layers['test_layer']}
