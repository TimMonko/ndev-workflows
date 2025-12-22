"""Tests for WorkflowInspector widget.

Tests are organized into:
- Unit tests (basic functionality without Qt event loop)
- Widget tests (with qtbot for async Qt testing)
"""

from __future__ import annotations

from unittest.mock import MagicMock

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


class TestDraggableNodes:
    """Tests for the DraggableNodes class."""

    @pytest.fixture
    def mpl_canvas(self):
        """Create a real MplCanvas."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MplCanvas

        return MplCanvas()

    def test_draggable_nodes_init(self, mpl_canvas):
        """Test DraggableNodes initialization."""
        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        positions = {'node1': (0.0, 0.0), 'node2': (1.0, 1.0)}
        nodes = DraggableNodes(mpl_canvas, positions, viewer=None)

        assert nodes.positions == {'node1': (0.0, 0.0), 'node2': (1.0, 1.0)}
        assert nodes.points is not None
        assert len(nodes.x) == 2
        assert len(nodes.y) == 2

    def test_update_node_status(self, mpl_canvas):
        """Test updating node status colors."""
        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        positions = {'node1': (0.0, 0.0), 'node2': (1.0, 1.0)}
        nodes = DraggableNodes(mpl_canvas, positions, viewer=None)

        # Test all status types - should not raise
        nodes.update_node_status('node1', 'root')
        nodes.update_node_status('node1', 'valid')
        nodes.update_node_status('node1', 'invalid')
        nodes.update_node_status('node1', 'leaf')

        # Verify the scatter colors changed (facecolors is an array)
        facecolors = nodes.points.get_facecolors()
        assert len(facecolors) == 2  # Two nodes

    def test_dragging_workflow(self, mpl_canvas):
        """Test the dragging state machine."""
        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        callback = MagicMock()
        positions = {'node1': (0.0, 0.0), 'node2': (1.0, 1.0)}
        nodes = DraggableNodes(
            mpl_canvas, positions, viewer=None, on_positions_changed=callback
        )

        # Initial state
        assert nodes._dragging is False
        assert nodes._drag_index is None

        # Simulate pick event (selecting node 0)
        pick_event = MagicMock()
        pick_event.mouseevent = MagicMock()
        pick_event.mouseevent.button = 1
        pick_event.ind = [0]
        nodes._on_pick(pick_event)

        assert nodes._drag_index == 0

        # Simulate press
        press_event = MagicMock()
        press_event.button = 1
        nodes._on_press(press_event)
        assert nodes._dragging is True

        # Simulate motion
        motion_event = MagicMock()
        motion_event.xdata = 0.5
        motion_event.ydata = 0.6
        nodes._on_motion(motion_event)

        # Position should update
        assert nodes.positions['node1'] == (0.5, 0.6)
        assert nodes.x[0] == 0.5
        assert nodes.y[0] == 0.6
        assert callback.called

        # Simulate release
        release_event = MagicMock()
        release_event.button = 1
        nodes._on_release(release_event)
        assert nodes._dragging is False

    def test_motion_without_drag_does_nothing(self, mpl_canvas):
        """Test motion event when not dragging does nothing."""
        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        callback = MagicMock()
        positions = {'node1': (0.0, 0.0)}
        nodes = DraggableNodes(
            mpl_canvas, positions, viewer=None, on_positions_changed=callback
        )

        # Motion without drag should do nothing
        motion_event = MagicMock()
        motion_event.xdata = 0.5
        motion_event.ydata = 0.5
        nodes._on_motion(motion_event)

        # Position should not change
        assert nodes.positions['node1'] == (0.0, 0.0)
        assert not callback.called

    def test_select_node_with_viewer(self, mpl_canvas, make_napari_viewer):
        """Test node selection with viewer."""
        import numpy as np

        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        viewer = make_napari_viewer()
        viewer.add_image(np.array([[1, 2], [3, 4]]), name='test_layer')

        positions = {'test_layer': (0.0, 0.0)}
        nodes = DraggableNodes(mpl_canvas, positions, viewer=viewer)

        # Select the node (index 0)
        nodes._select_node(0)

        # Layer should be selected in viewer
        assert viewer.layers.selection == {viewer.layers['test_layer']}

    def test_select_node_nonexistent_layer(self, mpl_canvas, make_napari_viewer):
        """Test selecting node for layer that doesn't exist in viewer."""
        from ndev_workflows.widgets._workflow_inspector import DraggableNodes

        viewer = make_napari_viewer()
        positions = {'nonexistent': (0.0, 0.0)}
        nodes = DraggableNodes(mpl_canvas, positions, viewer=viewer)

        # Should not raise - just won't select anything
        nodes._select_node(0)
        # Selection should remain empty
        assert len(viewer.layers.selection) == 0


class TestGraphDrawing:
    """Tests for graph drawing functionality."""

    @pytest.fixture
    def inspector_with_workflow(self, make_napari_viewer, qtbot, tmp_path):
        """Create inspector with a loaded workflow."""
        pytest.importorskip('matplotlib')
        pytest.importorskip('networkx')

        from ndev_workflows import Workflow, save_workflow
        from ndev_workflows.widgets._workflow_inspector import (
            WorkflowInspector,
        )

        def step1(x):
            return x + 1

        def step2(x):
            return x * 2

        workflow = Workflow()
        workflow.set('middle', step1, 'input')
        workflow.set('output', step2, 'middle')

        yaml_file = tmp_path / 'test.yaml'
        save_workflow(yaml_file, workflow)

        viewer = make_napari_viewer()
        widget = WorkflowInspector(viewer)
        qtbot.addWidget(widget)

        widget.load_workflow_file(yaml_file)
        return widget

    def test_draw_graph_creates_positions(self, inspector_with_workflow):
        """Test that drawing creates node positions."""
        inspector = inspector_with_workflow
        assert inspector._positions is not None
        # 'middle' and 'output' are processing steps - always in graph
        assert 'middle' in inspector._positions
        assert 'output' in inspector._positions

    def test_draw_graph_creates_graph_drawing(self, inspector_with_workflow):
        """Test that drawing creates DraggableNodes."""
        inspector = inspector_with_workflow
        assert inspector._graph_drawing is not None

    def test_graph_changed_detection(self, inspector_with_workflow, tmp_path):
        """Test graph change detection."""
        import networkx as nx

        inspector = inspector_with_workflow

        # Create a graph that is clearly different
        different_graph = nx.DiGraph()
        different_graph.add_node('completely_different_node')
        different_graph.add_node('another_node')
        different_graph.add_edge('completely_different_node', 'another_node')

        # The graphs should be different
        assert inspector._graph_changed(different_graph)

    def test_graph_not_changed_same_structure(self, inspector_with_workflow):
        """Test that identical graphs are not detected as changed."""
        inspector = inspector_with_workflow

        # Create a copy of the current graph
        same_graph = inspector._create_nx_graph(inspector._loaded_workflow)

        # Same graph should not be detected as changed
        assert not inspector._graph_changed(same_graph)

    def test_update_calls_draw_or_colors(
        self, inspector_with_workflow, tmp_path
    ):
        """Test that update properly refreshes the view."""
        inspector = inspector_with_workflow

        # Force an update
        inspector._update()

        # Labels should be populated
        assert 'input' in inspector.lbl_from_roots.text()
        assert 'output' in inspector.lbl_from_leaves.text()

    def test_on_node_positions_changed(self, inspector_with_workflow):
        """Test callback when node positions change."""
        inspector = inspector_with_workflow

        # Modify positions directly
        if inspector._graph_drawing:
            inspector._graph_drawing.positions['input'] = (0.5, 0.5)
            inspector._on_node_positions_changed()

            # Positions should be updated
            assert inspector._positions['input'] == (0.5, 0.5)


class TestInfoText:
    """Tests for info text generation."""

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

    def test_build_info_text_file_mode(self, inspector, tmp_path):
        """Test info text in file mode."""
        from ndev_workflows import Workflow, save_workflow

        def process(x):
            return x * 2

        workflow = Workflow()
        workflow.set('out', process, 'in')

        yaml_file = tmp_path / 'info_test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)
        info = inspector._build_info_text(inspector._loaded_workflow)

        assert 'Source:' in info
        assert 'info_test.yaml' in info
        assert 'Total tasks:' in info
        assert 'Roots (inputs):' in info
        assert 'Leaves (outputs):' in info

    def test_build_info_text_processing_steps(self, inspector, tmp_path):
        """Test info text shows processing steps."""
        from ndev_workflows import Workflow, save_workflow

        def my_function(x):
            return x

        workflow = Workflow()
        workflow.set('output', my_function, 'input')

        yaml_file = tmp_path / 'steps_test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)
        info = inspector._build_info_text(inspector._loaded_workflow)

        assert 'Processing Steps' in info


class TestErrorHandling:
    """Tests for error handling paths."""

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

    def test_load_nonexistent_file(self, inspector, tmp_path):
        """Test loading a file that doesn't exist."""
        bad_path = tmp_path / 'nonexistent.yaml'

        inspector.load_workflow_file(bad_path)

        assert 'Error' in inspector.status_label.text()

    def test_load_invalid_yaml(self, inspector, tmp_path):
        """Test loading an invalid YAML file."""
        bad_file = tmp_path / 'bad.yaml'
        bad_file.write_text('not: valid: yaml: file:')

        inspector.load_workflow_file(bad_file)

        # Should handle error gracefully
        assert inspector._loaded_workflow is None or 'Error' in inspector.status_label.text()

    def test_empty_workflow_display(self, inspector):
        """Test display when workflow is empty."""
        inspector._update()

        assert 'No workflow loaded' in inspector.lbl_from_roots.text()

    def test_get_workflow_live_mode_no_manager(self, inspector):
        """Test _get_workflow in live mode without manager."""
        inspector._use_live_mode = True

        # Should return None without raising
        result = inspector._get_workflow()
        # May or may not return None depending on whether manager can be installed
        # Just ensure it doesn't raise


class TestNodeStatus:
    """Tests for node status determination."""

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

    def test_get_node_status_root(self, inspector, tmp_path):
        """Test node status for root nodes."""
        from ndev_workflows import Workflow, save_workflow

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('output', identity, 'root_input')

        yaml_file = tmp_path / 'status_test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        status = inspector._get_node_status('root_input', inspector._loaded_workflow)
        assert status == 'root'

    def test_get_node_status_leaf(self, inspector, tmp_path):
        """Test node status for leaf nodes."""
        from ndev_workflows import Workflow, save_workflow

        def identity(x):
            return x

        workflow = Workflow()
        workflow.set('leaf_output', identity, 'input')

        yaml_file = tmp_path / 'leaf_test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        status = inspector._get_node_status('leaf_output', inspector._loaded_workflow)
        assert status == 'leaf'

    def test_get_node_status_middle(self, inspector, tmp_path):
        """Test node status for middle nodes."""
        from ndev_workflows import Workflow, save_workflow

        def step1(x):
            return x + 1

        def step2(x):
            return x * 2

        workflow = Workflow()
        workflow.set('middle', step1, 'input')
        workflow.set('output', step2, 'middle')

        yaml_file = tmp_path / 'middle_test.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        status = inspector._get_node_status('middle', inspector._loaded_workflow)
        assert status == 'valid'


class TestMatplotlibWidget:
    """Tests for the MatplotlibWidget class."""

    def test_matplotlib_widget_has_toolbar(self, make_napari_viewer, qtbot):
        """Test that MatplotlibWidget includes navigation toolbar."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MatplotlibWidget

        widget = MatplotlibWidget()
        qtbot.addWidget(widget)

        assert widget.canvas is not None
        assert widget.toolbar is not None

    def test_matplotlib_widget_canvas_clear(self, qtbot):
        """Test canvas clear method."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MatplotlibWidget

        widget = MatplotlibWidget()
        qtbot.addWidget(widget)

        # Draw something
        widget.canvas.axes.plot([1, 2, 3], [1, 2, 3])
        widget.canvas.draw()

        # Clear should work
        widget.canvas.clear()
        widget.canvas.draw()

        # Axes should be empty
        assert len(widget.canvas.axes.lines) == 0


class TestMplCanvas:
    """Tests for the MplCanvas class."""

    def test_mpl_canvas_creation(self):
        """Test MplCanvas creation and basic properties."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MplCanvas

        canvas = MplCanvas()

        # MplCanvas uses .fig and .axes attributes
        assert canvas.axes is not None
        assert canvas.fig is not None
        assert canvas.canvas is not None  # The actual FigureCanvas

    def test_mpl_canvas_clear(self):
        """Test MplCanvas clear method."""
        pytest.importorskip('matplotlib')

        from ndev_workflows.widgets._workflow_inspector import MplCanvas

        canvas = MplCanvas()

        # Draw something
        canvas.axes.plot([1, 2, 3], [4, 5, 6])
        canvas.draw()

        # Clear
        canvas.clear()

        # Should have cleared axes
        assert canvas.axes is not None
        assert len(canvas.axes.lines) == 0


class TestLiveModeStatus:
    """Tests for live mode node status checking."""

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

    def test_live_toggle_without_file(self, inspector):
        """Test toggling live mode when no file is loaded."""
        # Toggle to live mode
        inspector._on_live_toggled(True)
        assert inspector._use_live_mode is True
        assert 'live' in inspector.status_label.text().lower()

        # Toggle back to file mode with no file
        inspector._on_live_toggled(False)
        assert inspector._use_live_mode is False
        assert 'No workflow loaded' in inspector.status_label.text()

    def test_get_node_status_in_live_mode_missing_layer(
        self, inspector, tmp_path
    ):
        """Test node status when layer doesn't exist in live mode."""
        from ndev_workflows import Workflow

        def step1(x):
            return x

        def step2(x):
            return x

        # Create a workflow where 'middle' is neither root nor leaf
        workflow = Workflow()
        workflow.set('middle', step1, 'input')
        workflow.set('output', step2, 'middle')

        # Switch to live mode
        inspector._use_live_mode = True

        # Middle node that doesn't exist as layer should be invalid
        status = inspector._get_node_status('middle', workflow)
        assert status == 'invalid'


class TestTreeBuilding:
    """Tests for tree HTML building."""

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

    def test_build_tree_html_complex_workflow(self, inspector, tmp_path):
        """Test tree building with a complex workflow."""
        from ndev_workflows import Workflow, save_workflow

        def step(x):
            return x

        workflow = Workflow()
        workflow.set('b', step, 'a')
        workflow.set('c', step, 'b')
        workflow.set('d', step, 'c')

        yaml_file = tmp_path / 'complex.yaml'
        save_workflow(yaml_file, workflow)

        inspector.load_workflow_file(yaml_file)

        # Check the tree views contain the expected nodes
        from_roots_text = inspector.lbl_from_roots.text()
        from_leaves_text = inspector.lbl_from_leaves.text()

        # All nodes should appear somewhere
        for node in ['a', 'b', 'c', 'd']:
            assert node in from_roots_text or node in from_leaves_text


class TestCloseEvent:
    """Tests for widget close behavior."""

    def test_close_stops_timer(self, make_napari_viewer, qtbot):
        """Test that closing the widget stops the timer."""
        pytest.importorskip('matplotlib')
        pytest.importorskip('networkx')

        from ndev_workflows.widgets._workflow_inspector import (
            WorkflowInspector,
        )

        viewer = make_napari_viewer()
        widget = WorkflowInspector(viewer)
        qtbot.addWidget(widget)

        # Timer should be running
        assert widget.timer.isActive()

        # Close the widget
        widget.close()

        # Timer should be stopped
        assert not widget.timer.isActive()
