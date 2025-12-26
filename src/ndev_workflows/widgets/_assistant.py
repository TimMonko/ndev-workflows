"""Assistant widget for ndev-workflows.

This widget provides a visual interface for building workflows by discovering
available operations and allowing users to execute them. It automatically
records executed operations into the workflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from magicgui import magicgui
from magicgui.widgets import (
    Container,
    Label,
    PushButton,
    VBox,
)
from napari.utils.notifications import show_info

from ndev_workflows._manager import WorkflowManager
from ndev_workflows.assistant import CATEGORIES, discover_all_operations

if TYPE_CHECKING:
    import napari

class AssistantWidget(Container):
    """Visual workflow builder widget."""

    def __init__(self, viewer: napari.viewer.Viewer):
        super().__init__(labels=False)
        self.viewer = viewer
        self._operations = discover_all_operations()
        self._setup_ui()

    def _setup_ui(self):
        """Build the UI with categories and operations."""
        # Group operations by category
        for category_name, ops in self._operations.items():
            if not ops:
                continue
            
            category_def = CATEGORIES.get(category_name)
            icon = category_def.icon if category_def else "⚙️"
            
            # Category header
            self.append(Label(value=f"<h2>{icon} {category_name}</h2>"))
            
            # Operations buttons
            cat_container = VBox(labels=False)
            for name, func in ops:
                btn = PushButton(text=name)
                btn.clicked.connect(lambda _, f=func, n=name: self._launch_operation(f, n))
                cat_container.append(btn)
            
            self.append(cat_container)

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
        if hasattr(func, "__class__") and func.__class__.__name__ == "MagicFactory":
             widget = func()
        else:
            # Wrap regular function
            widget = magicgui(func)
        
        # Connect to called signal to record the step
        # We use a closure to capture the function and widget
        widget.called.connect(lambda result: self._record_workflow_step(func, widget, result))
        
        # Add to viewer
        self.viewer.window.add_dock_widget(widget, name=name)

    def _record_workflow_step(self, func: Callable, widget, result):
        """Record an executed step into the workflow.

        Parameters
        ----------
        func : Callable
            The function that was executed.
        widget : MagicGui
            The widget instance with parameter values.
        result : Any
            The result of the execution (usually a layer data tuple or layer).
        """
        manager = WorkflowManager.install(self.viewer)
        workflow = manager.workflow
        
        # Determine the output name
        # If result is a layer, use its name. If it's a list of layers, use the first?
        # napari-skimage returns LayerDataTuple or list of them.
        # magicgui usually handles adding them to viewer.
        # But we need the name of the layer that was created/updated.
        
        # This is tricky because magicgui adds the layer, but we don't strictly know 
        # which layer corresponds to the output unless we check what changed or 
        # if the result contains the name.
        
        # For now, let's assume the result is the output data, and we need to find 
        # the layer name from the widget parameters or the result if it has name info.
        
        # If the function returns LayerDataTuple, it has (data, meta, type).
        # meta['name'] might be present.
        
        output_name = "Result" # Default
        
        if isinstance(result, tuple) and len(result) > 1 and isinstance(result[1], dict):
            output_name = result[1].get("name", output_name)
        elif hasattr(result, "name"): # Layer object
            output_name = result.name
            
        # Extract parameters from widget
        params = {}
        for widget_param in widget:
            if widget_param.name in ("call_button", "widget_init"):
                continue
            
            # If the value is a Layer, we want the layer name (reference)
            val = widget_param.value
            if hasattr(val, "name") and hasattr(val, "data"): # It's a Layer
                params[widget_param.name] = val.name
            else:
                params[widget_param.name] = val
                
        # Add to workflow
        # We need the module path for the function
        if hasattr(func, "__module__") and hasattr(func, "__name__"):
            # If it's a MagicFactory, the underlying function is what we want?
            # MagicFactory wraps a function.
            if hasattr(func, "func"):
                real_func = func.func
            else:
                real_func = func
                
            # workflow.set(output_name, real_func, **params)
            # But Workflow.set takes positional args too.
            # We need to map widget params to function args.
            
            # For now, let's assume kwargs are sufficient if the function supports them.
            # Most magicgui functions use named arguments.
            
            try:
                workflow.set(output_name, real_func, **params)
                show_info(f"Recorded step: {output_name}")
            except Exception as e:
                show_info(f"Failed to record step: {e}")
        else:
            show_info("Could not determine function module/name for recording.")

