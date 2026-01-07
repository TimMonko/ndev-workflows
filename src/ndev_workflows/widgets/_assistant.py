"""Assistant widget for ndev-workflows.

This widget provides a visual interface for building workflows by discovering
available operations and allowing users to execute them. It automatically
records executed operations into the workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from magicgui import magicgui
from qtpy.QtWidgets import (
    QFrame,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from superqt import QCollapsible

from ndev_workflows._manager import WorkflowManager
from ndev_workflows.assistant import discover_all_operations

if TYPE_CHECKING:
    import napari


class AssistantWidget(QWidget):
    """Visual workflow builder widget."""

    def __init__(self, viewer: napari.viewer.Viewer):
        super().__init__()
        self.viewer = viewer

        # CRITICAL: Install WorkflowManager FIRST to set up global hooks
        # This ensures all widgets added by Assistant are automatically recorded
        self._manager = WorkflowManager.install(viewer)

        self._operations = discover_all_operations()
        self._setup_ui()

    def _setup_ui(self):
        """Build the UI with categories and operations."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Scroll area for categories
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout()
        content.setLayout(content_layout)
        scroll.setWidget(content)

        layout.addWidget(scroll)

        # Group operations by category
        # Sort categories to keep consistent order
        sorted_categories = sorted(self._operations.keys())

        for category_name in sorted_categories:
            ops = self._operations[category_name]
            if not ops:
                continue

            # Collapsible category
            collapsible = QCollapsible(f'{category_name}')

            # Container for buttons
            cat_widget = QWidget()
            cat_layout = QVBoxLayout()
            cat_widget.setLayout(cat_layout)
            cat_layout.setContentsMargins(10, 0, 0, 0)  # Indent

            for name, func in ops:
                btn = QPushButton(name)
                btn.setStyleSheet('text-align: left;')
                # Use closure to capture func and name
                btn.clicked.connect(
                    lambda checked, f=func, n=name: self._launch_operation(
                        f, n
                    )
                )
                cat_layout.addWidget(btn)

            collapsible.addWidget(cat_widget)
            content_layout.addWidget(collapsible)

        # Add stretch at the end
        content_layout.addStretch()

    def _launch_operation(self, func: Callable, name: str):
        """Launch an operation widget and connect it to the workflow recorder.

        Parameters
        ----------
        func : Callable
            The function to execute.
        name : str
            The name of the operation.
        """
        # Create the widget
        # Check if it's a magic_factory (MagicFactory) or regular function
        if (
            hasattr(func, '__class__')
            and func.__class__.__name__ == 'MagicFactory'
        ):
            widget = func()
        else:
            # Wrap regular function
            widget = magicgui(func)

        # DON'T connect here - let the global WorkflowManager hook handle it
        # The global hook in WorkflowManager._install_hooks() will automatically
        # connect ALL widgets added via add_dock_widget

        # Add to viewer - the global hook will connect automatically
        self.viewer.window.add_dock_widget(widget, name=name)
