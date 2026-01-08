"""Workflow Inspector widget for visualizing workflow graph structure.

This module provides a visual inspector for workflow graphs, showing
the dependency structure between processing steps with color-coded
status indicators.

Based on napari-workflow-inspector by Robert Haase (BSD-3-Clause).
Adapted for ndev-workflows architecture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    import napari.viewer


def _check_matplotlib():
    """Check if matplotlib is available."""
    try:
        import matplotlib  # noqa: F401

        return True
    except ImportError:
        return False


HAS_MATPLOTLIB = _check_matplotlib()


class MplCanvas:
    """Matplotlib canvas for embedding in Qt widgets.

    Lazily imports matplotlib to avoid import errors when not installed.
    """

    def __init__(self):
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg as FigureCanvas,
        )
        from matplotlib.figure import Figure

        self.fig = Figure()
        self.axes = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.04, bottom=0.04, right=0.97, top=0.96)
        # Dark theme to match napari
        self.fig.patch.set_facecolor('#262930')
        self.axes.set_facecolor('#262930')

        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.canvas.updateGeometry()

    def draw(self):
        """Redraw the canvas."""
        self.canvas.draw()

    def clear(self):
        """Clear the axes."""
        self.axes.clear()
        self.axes.set_facecolor('#262930')


class DraggableNodes:
    """Interactive draggable nodes in the workflow graph.

    Allows clicking on nodes to select the corresponding layer in napari,
    and dragging nodes to rearrange the graph layout.
    """

    # Colors for different node states
    VALID_COLOR = [0, 1, 0, 1]  # Green
    INVALID_COLOR = [1, 0, 1, 1]  # Magenta
    ROOT_COLOR = [0.8, 0.8, 0.8, 1]  # Light gray
    LEAF_COLOR = [0.3, 0.7, 1.0, 1]  # Light blue

    UNSELECTED_EDGE = [0, 0, 0, 1]  # Black
    SELECTED_EDGE = [1, 1, 1, 1]  # White

    def __init__(
        self,
        canvas: MplCanvas,
        positions: dict,
        viewer: napari.viewer.Viewer | None = None,
        on_positions_changed: Callable | None = None,
    ):
        """Initialize draggable nodes.

        Parameters
        ----------
        canvas : MplCanvas
            The matplotlib canvas to draw on.
        positions : dict
            Dictionary mapping node names to (x, y) positions.
        viewer : napari.Viewer, optional
            The napari viewer for layer selection. If None, clicking is disabled.
        on_positions_changed : callable, optional
            Callback when node positions change (for redrawing edges/labels).
        """
        self.viewer = viewer
        self.canvas = canvas
        self.positions = positions.copy()  # Make a mutable copy
        self.on_positions_changed = on_positions_changed

        self._dragging = False
        self._drag_index = None
        self._selected_index = None

        # Cache keys list for consistent indexing
        self._keys: list[str] = list(positions.keys())

        self.x = [positions[key][0] for key in self._keys]
        self.y = [positions[key][1] for key in self._keys]

        # Create scatter plot of nodes
        self.points = self.canvas.axes.scatter(
            self.x,
            self.y,
            picker=True,
            s=200,
            facecolor=[self.VALID_COLOR] * len(self.x),
            edgecolor=[self.UNSELECTED_EDGE] * len(self.x),
            zorder=10,  # Draw nodes on top
        )

        self.edgecolors = self.points.get_edgecolors().copy()

        # Connect mouse events for dragging and store connection IDs for cleanup
        self._cids = [
            self.canvas.canvas.mpl_connect('pick_event', self._on_pick),
            self.canvas.canvas.mpl_connect(
                'button_press_event', self._on_press
            ),
            self.canvas.canvas.mpl_connect(
                'button_release_event', self._on_release
            ),
            self.canvas.canvas.mpl_connect(
                'motion_notify_event', self._on_motion
            ),
        ]

    def disconnect(self):
        """Disconnect all event handlers to prevent memory leaks."""
        for cid in self._cids:
            self.canvas.canvas.mpl_disconnect(cid)
        self._cids.clear()

    def _on_pick(self, event):
        """Handle pick event on a node."""
        if event.mouseevent.button == 1:  # Left click
            ind = event.ind[0] if hasattr(event.ind, '__len__') else event.ind
            self._drag_index = ind
            self._select_node(ind)

    def _on_press(self, event):
        """Handle mouse button press."""
        if event.button == 1 and self._drag_index is not None:
            self._dragging = True

    def _on_release(self, event):
        """Handle mouse button release."""
        if event.button == 1:
            self._dragging = False
            self._drag_index = None

    def _on_motion(self, event):
        """Handle mouse motion for dragging."""
        if not self._dragging or self._drag_index is None:
            return
        if event.xdata is None or event.ydata is None:
            return

        # Update the position
        idx = self._drag_index
        if idx >= len(self._keys):
            return

        node_name = self._keys[idx]

        # Update stored position
        self.positions[node_name] = (event.xdata, event.ydata)
        self.x[idx] = event.xdata
        self.y[idx] = event.ydata

        # Update scatter plot
        offsets = self.points.get_offsets()
        offsets[idx] = [event.xdata, event.ydata]
        self.points.set_offsets(offsets)

        # Notify parent to redraw edges and labels
        if self.on_positions_changed:
            self.on_positions_changed()
        else:
            self.canvas.draw()

    def _select_node(self, index):
        """Select a node and its corresponding layer."""
        if index >= len(self._keys):
            return

        # Reset previous selection
        edgecolors = self.edgecolors.copy()

        # Highlight new selection
        edgecolors[index] = self.SELECTED_EDGE
        self.points.set_edgecolors(edgecolors)
        self._selected_index = index
        self.canvas.draw()

        if self.viewer is None:
            return

        node_name = self._keys[index]

        if node_name in self.viewer.layers:
            layer = self.viewer.layers[node_name]
            self.viewer.layers.selection = {layer}

    def update_node_status(self, node_name: str, status: str):
        """Update the visual status of a node.

        Parameters
        ----------
        node_name : str
            The name of the node to update.
        status : str
            One of 'valid', 'invalid', 'root', or 'leaf'.
        """
        try:
            idx = self._keys.index(node_name)
        except ValueError:
            return

        facecolors = self.points.get_facecolors()
        if status == 'invalid':
            facecolors[idx] = self.INVALID_COLOR
        elif status == 'root':
            facecolors[idx] = self.ROOT_COLOR
        elif status == 'leaf':
            facecolors[idx] = self.LEAF_COLOR
        else:
            facecolors[idx] = self.VALID_COLOR
        self.points.set_facecolors(facecolors)


class MatplotlibWidget(QWidget):
    """Qt widget containing a matplotlib canvas with navigation toolbar.

    Includes standard matplotlib navigation tools:
    - Home: Reset to original view
    - Back/Forward: Navigate view history
    - Pan: Pan the view with mouse
    - Zoom: Zoom to rectangle
    - Configure: Adjust subplot parameters
    - Save: Save the figure to file
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import (
            NavigationToolbar2QT as NavigationToolbar,
        )

        self.canvas = MplCanvas()

        # Create toolbar with navigation buttons
        self.toolbar = NavigationToolbar(self.canvas.canvas, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas.canvas)


class WorkflowInspector(QWidget):
    """Widget for inspecting and visualizing workflow structure.

    Supports two modes:
    - **File mode**: Load and inspect a workflow YAML file
    - **Live mode**: Watch the current viewer's WorkflowManager

    Provides multiple views:
    - Graph: Interactive networkx visualization
    - From Roots: Tree view from inputs to outputs
    - From Leaves: Tree view from outputs to inputs
    - Raw: Text representation of the workflow
    - Info: Workflow statistics and metadata

    Parameters
    ----------
    viewer : napari.Viewer
        The napari viewer instance.

    Example
    -------
    >>> inspector = WorkflowInspector(viewer)
    >>> viewer.window.add_dock_widget(inspector, name='Workflow Inspector')
    >>> # Load a workflow file
    >>> inspector.load_workflow_file("my_workflow.yaml")
    """

    def __init__(self, viewer: napari.viewer.Viewer):
        super().__init__()
        self._viewer = viewer
        self._graph = None
        self._positions = None
        self._graph_drawing = None

        # Graph drawing elements (for dynamic updates when dragging)
        self._edge_collection = None
        self._label_texts = None

        # Workflow source: file or live manager
        self._workflow_file: Path | None = None
        self._loaded_workflow = None  # Workflow loaded from file
        self._use_live_mode = False  # Whether to watch WorkflowManager

        self._init_ui()
        self._start_timer()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)

        # Mode selection section
        mode_layout = QHBoxLayout()

        self.load_btn = QPushButton('Load YAML...')
        self.load_btn.clicked.connect(self._on_load_clicked)
        mode_layout.addWidget(self.load_btn)

        self.live_btn = QPushButton('Watch Live')
        self.live_btn.setCheckable(True)
        self.live_btn.setToolTip('Watch the viewer WorkflowManager')
        self.live_btn.toggled.connect(self._on_live_toggled)
        mode_layout.addWidget(self.live_btn)

        self.save_btn = QPushButton('Save Workflow...')
        self.save_btn.setToolTip('Save the current workflow to YAML file')
        self.save_btn.clicked.connect(self._on_save_clicked)
        mode_layout.addWidget(self.save_btn)

        layout.addLayout(mode_layout)

        # Status label
        self.status_label = QLabel('No workflow loaded')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Tab widget for different views
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Graph tab (requires matplotlib)
        if HAS_MATPLOTLIB:
            self.graph_widget = MatplotlibWidget()
            self.tabs.addTab(self.graph_widget, 'Graph')
        else:
            self.graph_widget = None
            no_mpl_label = QLabel(
                'Graph view requires matplotlib.\n\n'
                'Install with: pip install ndev-workflows[plot]'
            )
            no_mpl_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabs.addTab(no_mpl_label, 'Graph')

        # From Roots tab
        self.roots_scroll = QScrollArea()
        self.roots_scroll.setWidgetResizable(True)
        self.lbl_from_roots = QLabel()
        self.lbl_from_roots.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_from_roots.setTextFormat(Qt.TextFormat.RichText)
        self.roots_scroll.setWidget(self.lbl_from_roots)
        self.tabs.addTab(self.roots_scroll, 'From Roots')

        # From Leaves tab
        self.leaves_scroll = QScrollArea()
        self.leaves_scroll.setWidgetResizable(True)
        self.lbl_from_leaves = QLabel()
        self.lbl_from_leaves.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_from_leaves.setTextFormat(Qt.TextFormat.RichText)
        self.leaves_scroll.setWidget(self.lbl_from_leaves)
        self.tabs.addTab(self.leaves_scroll, 'From Leaves')

        # Raw tab
        self.raw_scroll = QScrollArea()
        self.raw_scroll.setWidgetResizable(True)
        self.lbl_raw = QLabel()
        self.lbl_raw.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_raw.setMinimumSize(800, 600)
        self.raw_scroll.setWidget(self.lbl_raw)
        self.tabs.addTab(self.raw_scroll, 'Raw')

        # Info tab (replaces Undo/Redo for file mode)
        self.info_scroll = QScrollArea()
        self.info_scroll.setWidgetResizable(True)
        self.lbl_info = QLabel()
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_info.setMinimumSize(800, 600)
        self.info_scroll.setWidget(self.lbl_info)
        self.tabs.addTab(self.info_scroll, 'Info')

        # Spacer
        layout.addItem(
            QSpacerItem(
                20,
                40,
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Expanding,
            )
        )

    def _on_load_clicked(self):
        """Handle load button click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Load Workflow',
            '',
            'YAML files (*.yaml *.yml);;All files (*)',
        )
        if file_path:
            self.load_workflow_file(file_path)

    def _on_live_toggled(self, checked: bool):
        """Handle live mode toggle."""
        self._use_live_mode = checked
        if checked:
            self._loaded_workflow = None
            self._workflow_file = None
            self.status_label.setText('Watching live WorkflowManager...')
        else:
            if self._workflow_file:
                self.status_label.setText(f'File: {self._workflow_file.name}')
            else:
                self.status_label.setText('No workflow loaded')
        self._update()

    def _on_save_clicked(self):
        """Handle save button click."""
        from ndev_workflows import save_workflow
        from ndev_workflows._manager import WorkflowManager

        # Get workflow to save
        workflow = None
        if self._use_live_mode:
            # Get from live WorkflowManager
            manager = WorkflowManager.install(self._viewer)
            workflow = manager.workflow
        elif self._loaded_workflow:
            # Use loaded workflow
            workflow = self._loaded_workflow
        else:
            self.status_label.setText('No workflow to save')
            return

        # Open save dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Save Workflow',
            '',
            'YAML files (*.yaml *.yml);;All files (*)',
        )

        if file_path:
            try:
                save_workflow(Path(file_path), workflow)
                self.status_label.setText(f'Saved: {Path(file_path).name}')
            except Exception as e:
                self.status_label.setText(f'Error saving: {e}')

    def load_workflow_file(self, file_path: str | Path):
        """Load a workflow from a YAML file.

        Uses lazy loading since we only need the workflow structure for
        visualization, not to execute the functions.

        Parameters
        ----------
        file_path : str or Path
            Path to the workflow YAML file.
        """
        from ndev_workflows import load_workflow
        from ndev_workflows._io import WorkflowYAMLError

        file_path = Path(file_path)
        try:
            # Load in lazy mode - we don't need to import functions to visualize
            self._loaded_workflow = load_workflow(file_path, lazy=True)
            self._workflow_file = file_path
            self.status_label.setText(f'File: {file_path.name}')
            self._use_live_mode = False
            self.live_btn.setChecked(False)
            self._graph = None  # Force graph redraw
            self._update()
        except (OSError, ValueError, TypeError, WorkflowYAMLError) as e:
            self.status_label.setText(f'Error: {e}')

    def _start_timer(self):
        """Start the update timer."""
        self.timer = QTimer()
        self.timer.setInterval(500)  # 500ms update interval
        self.timer.timeout.connect(self._update)
        self.timer.start()

    def _get_workflow(self):
        """Get the current workflow to inspect.

        Returns
        -------
        Workflow or None
            The workflow to inspect, or None if not available.
        """
        if self._use_live_mode:
            manager = self._get_manager()
            return manager.workflow if manager else None
        return self._loaded_workflow

    def _get_manager(self):
        """Get the WorkflowManager for the current viewer (live mode only).

        Returns
        -------
        WorkflowManager or None
            The manager if in live mode, otherwise None.
        """
        if not self._use_live_mode:
            return None
        try:
            from ndev_workflows._manager import WorkflowManager

            return WorkflowManager.install(self._viewer)
        except (ImportError, AttributeError, RuntimeError):
            return None

    def _get_node_status_cached(
        self,
        node_name: str,
        roots: list[str],
        leaves: list[str],
    ) -> str:
        """Determine the status of a node using cached roots/leaves.

        Parameters
        ----------
        node_name : str
            The name of the node/task.
        roots : list[str]
            Cached list of root nodes.
        leaves : list[str]
            Cached list of leaf nodes.

        Returns
        -------
        str
            One of 'root', 'leaf', 'invalid', or 'valid'.
        """
        # Check if it's a root (input)
        if node_name in roots:
            return 'root'

        # Check if it's a leaf (output)
        if node_name in leaves:
            return 'leaf'

        # In live mode, check for pending updates
        if self._use_live_mode:
            manager = self._get_manager()
            if manager and manager.is_layer_pending(node_name):
                return 'invalid'

            # Check if layer exists in viewer
            if node_name not in self._viewer.layers:
                return 'invalid'

        return 'valid'

    def _update(self):
        """Update all views with current workflow state."""
        workflow = self._get_workflow()

        if workflow is None or len(workflow) == 0:
            self.lbl_from_roots.setText('No workflow loaded or empty workflow')
            self.lbl_from_leaves.setText(
                'No workflow loaded or empty workflow'
            )
            self.lbl_raw.setText('No workflow loaded or empty workflow')
            self.lbl_info.setText('Load a YAML file or enable live mode')
            if self.graph_widget is not None:
                self.graph_widget.canvas.clear()
                self.graph_widget.canvas.draw()
            return

        # Cache roots and leaves to avoid repeated computation
        roots = workflow.roots()
        leaves = workflow.leaves()

        # From Roots view
        roots_text = self._build_tree_html(
            roots, workflow.followers_of, workflow, roots, leaves
        )
        self.lbl_from_roots.setText(self._wrap_html(roots_text))

        # From Leaves view
        leaves_text = self._build_tree_html(
            leaves, workflow.sources_of, workflow, roots, leaves
        )
        self.lbl_from_leaves.setText(self._wrap_html(leaves_text))

        # Raw view
        self.lbl_raw.setText(repr(workflow))

        # Info view
        info_text = self._build_info_text(workflow, roots, leaves)
        self.lbl_info.setText(info_text)

        # Update graph (only if matplotlib available)
        if self.graph_widget is None:
            return

        new_graph = self._create_nx_graph(workflow)
        if self._graph is None or self._graph_changed(new_graph):
            self._graph = new_graph
            self._draw_graph(workflow)
        else:
            self._update_graph_colors(workflow, roots, leaves)

    def _build_tree_html(
        self,
        items: list[str],
        get_next: Callable,
        workflow,
        roots: list[str],
        leaves: list[str],
    ) -> str:
        """Build an HTML tree representation.

        Parameters
        ----------
        items : list[str]
            Starting items for the tree.
        get_next : callable
            Function to get next items (followers_of or sources_of).
        workflow : Workflow
            The workflow object.
        roots : list[str]
            Cached list of root nodes.
        leaves : list[str]
            Cached list of leaf nodes.

        Returns
        -------
        str
            HTML string representing the tree.
        """
        import html

        visited = set()

        def build(item_list: list[str], level: int = 0) -> str:
            output = ''
            for item in item_list:
                if item in visited:
                    continue
                visited.add(item)

                status = self._get_node_status_cached(item, roots, leaves)
                color = {
                    'root': '#dddddd',  # Light gray
                    'leaf': '#5599ff',  # Light blue
                    'invalid': '#dd00dd',  # Magenta
                    'valid': '#00dd00',  # Green
                }.get(status, '#dddddd')

                indent = '&nbsp;&nbsp;&nbsp;' * level
                escaped_name = html.escape(item)
                output += f'<font color="{color}">{indent}→ {escaped_name}</font><br>'

                next_items = get_next(item)
                if next_items:
                    output += build(next_items, level + 1)

            return output

        return build(items)

    def _wrap_html(self, content: str) -> str:
        """Wrap content in HTML tags."""
        return f'<html><pre>{content}</pre></html>'

    def _build_info_text(
        self, workflow, roots: list[str], leaves: list[str]
    ) -> str:
        """Build workflow info text.

        Parameters
        ----------
        workflow : Workflow
            The workflow object.
        roots : list[str]
            Cached list of root nodes.
        leaves : list[str]
            Cached list of leaf nodes.

        Returns
        -------
        str
            Text representation of workflow info.
        """
        lines = []

        # Source info
        if self._workflow_file:
            lines.append(f'Source: {self._workflow_file}')
        elif self._use_live_mode:
            lines.append('Source: Live WorkflowManager')
        lines.append('')

        # Workflow stats
        lines.append('─── Workflow Statistics ───')
        lines.append(f'  Total tasks: {len(workflow)}')
        lines.append(f'  Roots (inputs): {len(roots)}')
        lines.append(f'  Leaves (outputs): {len(leaves)}')
        lines.append('')

        # Root details
        lines.append('─── Roots (Inputs) ───')
        for root in roots:
            lines.append(f'  • {root}')
        if not roots:
            lines.append('  (none)')
        lines.append('')

        # Leaf details
        lines.append('─── Leaves (Outputs) ───')
        for leaf in leaves:
            lines.append(f'  • {leaf}')
        if not leaves:
            lines.append('  (none)')
        lines.append('')

        # Processing steps
        processing = workflow.processing_task_names()
        lines.append(f'─── Processing Steps ({len(processing)}) ───')
        for name in processing:
            task = workflow.get_task(name)
            if task and len(task) > 0:
                func = task[0]
                func_name = getattr(func, '__name__', str(func))
                if hasattr(func, 'func'):
                    func_name = func.func.__name__
                sources = workflow.sources_of(name)
                src_str = ', '.join(sources) if sources else '(none)'
                lines.append(f'  • {name}: {func_name}({src_str})')
        lines.append('')

        # Metadata
        if hasattr(workflow, 'metadata') and workflow.metadata:
            lines.append('─── Metadata ───')
            for key, value in workflow.metadata.items():
                lines.append(f'  {key}: {value}')
            lines.append('')

        # Live mode info
        if self._use_live_mode:
            manager = self._get_manager()
            if manager:
                undo_redo = manager.undo_redo
                lines.append('─── Live Mode Info ───')
                lines.append(f'  Can undo: {undo_redo.can_undo}')
                lines.append(f'  Can redo: {undo_redo.can_redo}')
                lines.append(
                    f'  Undo stack: {undo_redo.undo_stack_size} states'
                )
                lines.append(
                    f'  Redo stack: {undo_redo.redo_stack_size} states'
                )
                pending = manager.pending_updates
                if pending:
                    lines.append(f'  Pending updates: {pending}')

        return '\n'.join(lines)

    def _create_nx_graph(self, workflow):
        """Create a networkx graph from the workflow.

        Parameters
        ----------
        workflow : Workflow
            The workflow to convert.

        Returns
        -------
        nx.DiGraph
            A directed graph representing the workflow.
        """
        import networkx as nx

        graph = nx.DiGraph()

        # Add all tasks as nodes
        for name in workflow:
            graph.add_node(name)

        # Add edges based on dependencies
        for name in workflow:
            for follower in workflow.followers_of(name):
                graph.add_edge(name, follower)

        return graph

    def _graph_changed(self, new_graph) -> bool:
        """Check if the graph structure has changed."""
        if self._graph is None:
            return True
        return set(self._graph.nodes) != set(new_graph.nodes) or set(
            self._graph.edges
        ) != set(new_graph.edges)

    def _draw_graph(self, workflow):
        """Draw the workflow graph."""
        import networkx as nx

        if self._graph is None or len(self._graph.nodes) == 0:
            self.graph_widget.canvas.clear()
            self.graph_widget.canvas.draw()
            return

        ax = self.graph_widget.canvas.axes
        ax.clear()
        ax.set_facecolor('#262930')

        # Cleanup old graph drawing to prevent memory leaks
        if self._graph_drawing is not None:
            self._graph_drawing.disconnect()
            self._graph_drawing = None

        # Calculate positions
        try:
            self._positions = nx.drawing.layout.kamada_kawai_layout(
                self._graph
            )
        except (ValueError, TypeError, RuntimeError):
            # Fall back to spring layout if kamada_kawai fails
            self._positions = nx.spring_layout(self._graph)

        # Draw edges (store reference for redrawing)
        self._edge_collection = nx.draw_networkx_edges(
            self._graph,
            pos=self._positions,
            ax=ax,
            width=2,
            edge_color='white',
            arrows=True,
            arrowsize=15,
        )

        # Draw labels (store reference for redrawing)
        props = {'boxstyle': 'round', 'facecolor': 'white', 'alpha': 0.2}
        self._label_texts = nx.draw_networkx_labels(
            self._graph,
            pos=self._positions,
            ax=ax,
            font_color='white',
            bbox=props,
            verticalalignment='bottom',
        )
        # Set high z-order for labels so they render on top
        for text in self._label_texts.values():
            text.set_zorder(20)

        # Create draggable nodes (viewer only in live mode)
        viewer = self._viewer if self._use_live_mode else None
        self._graph_drawing = DraggableNodes(
            self.graph_widget.canvas,
            self._positions,
            viewer,
            on_positions_changed=self._on_node_positions_changed,
        )

        self._update_graph_colors(workflow)
        self.graph_widget.canvas.draw()

    def _on_node_positions_changed(self):
        """Callback when node positions change due to dragging."""
        import networkx as nx

        if self._graph is None or self._graph_drawing is None:
            return

        ax = self.graph_widget.canvas.axes

        # Update positions from draggable nodes
        self._positions = self._graph_drawing.positions

        # Remove old edges
        if self._edge_collection is not None:
            # Handle both FancyArrowPatch list and LineCollection
            if hasattr(self._edge_collection, '__iter__'):
                for edge in self._edge_collection:
                    edge.remove()
            else:
                self._edge_collection.remove()

        # Remove old labels
        if self._label_texts is not None:
            for text in self._label_texts.values():
                text.remove()

        # Redraw edges with new positions
        self._edge_collection = nx.draw_networkx_edges(
            self._graph,
            pos=self._positions,
            ax=ax,
            width=2,
            edge_color='white',
            arrows=True,
            arrowsize=15,
        )

        # Redraw labels with new positions
        props = {'boxstyle': 'round', 'facecolor': 'white', 'alpha': 0.2}
        self._label_texts = nx.draw_networkx_labels(
            self._graph,
            pos=self._positions,
            ax=ax,
            font_color='white',
            bbox=props,
            verticalalignment='bottom',
        )
        # Set high z-order for labels so they render on top
        for text in self._label_texts.values():
            text.set_zorder(20)

        self.graph_widget.canvas.draw()

    def _update_graph_colors(
        self,
        workflow,
        roots: list[str] | None = None,
        leaves: list[str] | None = None,
    ):
        """Update node colors based on current status.

        Parameters
        ----------
        workflow : Workflow
            The workflow object.
        roots : list[str], optional
            Cached list of root nodes.
        leaves : list[str], optional
            Cached list of leaf nodes.
        """
        if self._graph is None or self._graph_drawing is None:
            return

        # Use cached values or compute if not provided
        if roots is None:
            roots = workflow.roots()
        if leaves is None:
            leaves = workflow.leaves()

        for node in self._graph.nodes:
            status = self._get_node_status_cached(node, roots, leaves)
            self._graph_drawing.update_node_status(node, status)

        self.graph_widget.canvas.draw()

    def closeEvent(self, a0):
        """Stop the timer and cleanup when closing."""
        self.timer.stop()
        # Disconnect matplotlib event handlers to prevent memory leaks
        if self._graph_drawing is not None:
            self._graph_drawing.disconnect()
            self._graph_drawing = None
        super().closeEvent(a0)
