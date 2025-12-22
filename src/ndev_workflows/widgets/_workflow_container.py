"""Workflow container widget for batch processing with napari-workflows.

This module provides a Container widget for managing napari-workflows in both
interactive (viewer) and batch processing modes. It integrates with nbatch
for parallel execution of workflows on multiple files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from magicclass.widgets import TabbedContainer
from magicgui.widgets import (
    CheckBox,
    ComboBox,
    Container,
    FileEdit,
    LineEdit,
    ProgressBar,
    PushButton,
    Select,
)
from ndevio import helpers

from ndev_workflows import (
    WorkflowNotRunnableError,
    ensure_runnable,
    get_workflow_metadata,
    load_workflow,
    process_workflow_file,
)

if TYPE_CHECKING:
    import napari


class WorkflowContainer(Container):
    """Container widget for managing napari-workflows.

    Provides both interactive (viewer) and batch processing modes for
    executing napari-workflows. Integrates with nbatch for parallel
    batch processing with progress tracking and error handling.

    Parameters
    ----------
    viewer : napari.viewer.Viewer, optional
        The napari viewer instance. If None, viewer-based workflow
        execution will be disabled.

    Attributes
    ----------
    workflow : napari_workflows.Workflow or None
        The currently loaded workflow.
    image_files : list[Path]
        List of image files for batch processing.

    Example
    -------
    >>> container = WorkflowContainer(viewer)
    >>> viewer.window.add_dock_widget(container)
    >>> # Select workflow file, image directory, and run batch

    """

    def __init__(self, viewer: napari.viewer.Viewer = None):
        """Initialize the WorkflowContainer widget.

        Parameters
        ----------
        viewer : napari.viewer.Viewer, optional
            The napari viewer instance.

        """
        super().__init__()
        self._viewer = viewer if viewer is not None else None
        self._channel_names = []
        self._img_dims = ''
        self._squeezed_img_dims = ''
        self.image_files = []
        self.workflow = None
        self._workflow_inputs = []  # Declared inputs from YAML (stable)
        self._root_scale = None

        self._init_widgets()
        self._init_batch_runner()
        self._init_viewer_container()
        self._init_batch_container()
        self._init_tasks_container()
        self._init_layout()
        self._connect_events()

    def _init_batch_runner(self):
        """Initialize the BatchRunner for batch processing."""
        from nbatch import BatchRunner

        self._batch_runner = BatchRunner(
            on_start=self._on_batch_start,
            on_item_complete=self._on_batch_item_complete,
            on_complete=self._on_batch_complete,
            on_error=self._on_batch_error,
            on_cancel=self._on_batch_cancel,
        )

    def _on_batch_start(self, total: int):
        """Callback when batch starts - initialize progress bar."""
        self._progress_bar.label = f'Workflow on {total} images'
        self._progress_bar.value = 0
        self._progress_bar.max = total
        self.batch_button.enabled = False
        self._cancel_button.enabled = True

    def _get_viewer_layers(self):
        """Get layers from the viewer."""
        if self._viewer is None:
            return []
        return list(self._viewer.layers)

    def _init_widgets(self):
        """Initialize non-Container widgets."""
        self.workflow_file = FileEdit(
            label='Workflow File',
            filter='*.yaml',
            tooltip='Select a workflow file to load',
        )
        self._workflow_roots = LineEdit(label='Workflow Roots:')
        self._progress_bar = ProgressBar(label='Progress:')

    def _init_viewer_container(self):
        """Initialize the viewer container tab widgets."""
        self.viewer_button = PushButton(text='Viewer Workflow')
        self._viewer_roots_container = Container(layout='vertical', label=None)
        self._viewer_roots_container.native.layout().addStretch()
        self._viewer_container = Container(
            layout='vertical',
            widgets=[
                self.viewer_button,
                self._viewer_roots_container,
            ],
            label='Viewer',
            labels=None,
        )

    def _init_batch_container(self):
        """Initialize the batch container tab widgets."""
        self.image_directory = FileEdit(label='Image Directory', mode='d')
        self.result_directory = FileEdit(label='Result Directory', mode='d')
        self._keep_original_images = CheckBox(
            label='Keep Original Images',
            value=False,
            tooltip='If checked, the original images will be '
            'concatenated with the results',
        )
        self.batch_button = PushButton(label='Batch Workflow')
        self._cancel_button = PushButton(label='Cancel')
        self._cancel_button.enabled = False
        self._batch_info_container = Container(
            layout='vertical',
            widgets=[
                self.image_directory,
                self.result_directory,
                self._keep_original_images,
                self.batch_button,
                self._cancel_button,
            ],
        )

        self._batch_roots_container = Container(layout='vertical', label=None)
        self._batch_roots_container.native.layout().addStretch()

        self._batch_container = Container(
            layout='vertical',
            widgets=[
                self._batch_info_container,
                self._batch_roots_container,
            ],
            label='Batch',
            labels=None,
        )

    def _init_tasks_container(self):
        """Initialize the tasks container."""
        self._tasks_select = Select(
            choices=[],
            nullable=False,
            allow_multiple=True,
        )
        self._tasks_container = Container(
            layout='vertical',
            widgets=[self._tasks_select],
            label='Tasks',
        )

    def _init_layout(self):
        """Initialize the layout of the widgets."""
        self.extend(
            [
                self.workflow_file,
                self._workflow_roots,
                self._progress_bar,
            ]
        )
        self._tabs = TabbedContainer(
            widgets=[
                self._viewer_container,
                self._batch_container,
                self._tasks_container,
            ],
            label=None,
            labels=None,
        )
        self.native.layout().addWidget(self._tabs.native)
        self.native.layout().addStretch()

    def _connect_events(self):
        """Connect the events of the widgets to respective methods."""
        self.image_directory.changed.connect(self._get_image_info)
        self.workflow_file.changed.connect(self._get_workflow_info)
        self.batch_button.clicked.connect(self.batch_workflow)
        self._cancel_button.clicked.connect(self._batch_runner.cancel)
        self.viewer_button.clicked.connect(self.viewer_workflow_threaded)

        if self._viewer is not None:
            self._viewer.layers.events.removed.connect(
                self._update_layer_choices
            )
            self._viewer.layers.events.inserted.connect(
                self._update_layer_choices
            )

    def _get_image_info(self):
        """Get channels and dims from first image in the directory."""
        from ndevio import nImage

        self.image_dir, self.image_files = helpers.get_directory_and_files(
            self.image_directory.value,
        )
        img = nImage(self.image_files[0])

        self._channel_names = helpers.get_channel_names(img)

        for widget in self._batch_roots_container:
            widget.choices = self._channel_names

        self._squeezed_img_dims = helpers.get_squeezed_dim_order(img)
        return self._squeezed_img_dims

    def _update_layer_choices(self):
        """Update the choices of the layers for the viewer workflow."""
        for widget in self._viewer_roots_container:
            widget.choices = self._get_viewer_layers()
        return

    def _update_roots(self):
        """Get the roots from the workflow and update the ComboBox widgets."""
        self._batch_roots_container.clear()
        self._viewer_roots_container.clear()

        for idx, root in enumerate(self.workflow.roots()):
            short_root = helpers.elide_string(root, max_length=12)

            batch_root_combo = ComboBox(
                label=f'Root {idx}: {short_root}',
                choices=self._channel_names,
                nullable=True,
                value=None,
            )
            self._batch_roots_container.append(batch_root_combo)

            viewer_root_combo = ComboBox(
                label=f'Root {idx}: {short_root}',
                choices=self._get_viewer_layers(),
                nullable=True,
                value=None,
            )
            self._viewer_roots_container.append(viewer_root_combo)

        return

    def _update_task_choices(self, workflow=None, tasks=None, leafs=None):
        """Update the choices of the tasks with the workflow tasks.

        Parameters
        ----------
        workflow : Workflow, optional
            Workflow object to extract tasks from. Used when full workflow is loaded.
        tasks : list[str], optional
            List of task names. Used with v3 metadata preview.
        leafs : list[str], optional
            Default selected tasks (outputs). Used with v3 metadata.
        """
        if tasks is not None:
            self._tasks_select.choices = tasks
            self._tasks_select.value = leafs if leafs else tasks[-1:]
        elif workflow is not None:
            self._tasks_select.choices = workflow.tasks()
            self._tasks_select.value = workflow.leafs()

    def _get_workflow_info(self):
        """Load the workflow file and update the roots and leafs.

        Uses get_workflow_metadata for fast preview, then loads full workflow.
        """
        workflow_path = self.workflow_file.value

        # Get metadata for fast preview (works for both legacy and new formats)
        try:
            metadata = get_workflow_metadata(workflow_path)
            self._workflow_inputs = metadata.get(
                'inputs', []
            )  # Store for reuse
            self._workflow_roots.value = str(self._workflow_inputs)
            self._update_roots_from_list(self._workflow_inputs)
            self._update_task_choices(
                tasks=metadata.get('tasks', []),
                leafs=metadata.get('outputs', []),
            )
        except Exception:  # noqa
            pass

        # Load full workflow lazily so missing optional deps don't break the UI.
        self.workflow = load_workflow(workflow_path, lazy=True)
        return

    def _update_roots_from_list(self, roots: list[str]):
        """Update root ComboBox widgets from a list of root names.

        Used for v3 format metadata preview.
        """
        self._batch_roots_container.clear()
        self._viewer_roots_container.clear()

        for idx, root in enumerate(roots):
            short_root = helpers.elide_string(root, max_length=12)

            batch_root_combo = ComboBox(
                label=f'Root {idx}: {short_root}',
                choices=self._channel_names,
                nullable=True,
                value=None,
            )
            self._batch_roots_container.append(batch_root_combo)

            viewer_root_combo = ComboBox(
                label=f'Root {idx}: {short_root}',
                choices=self._get_viewer_layers(),
                nullable=True,
                value=None,
            )
            self._viewer_roots_container.append(viewer_root_combo)

        return

    def _update_progress_bar(self, value):
        self._progress_bar.value = value
        return

    def _on_batch_item_complete(self, result, ctx):
        """Callback when a batch item completes successfully."""
        self._progress_bar.value = ctx.index + 1

    def _on_batch_complete(self):
        """Callback when the entire batch completes."""
        total = self._progress_bar.max
        errors = self._batch_runner.error_count
        if errors > 0:
            self._progress_bar.label = (
                f'Completed {total - errors} Images ({errors} Errors)'
            )
        else:
            self._progress_bar.label = f'Completed {total} Images'
        self.batch_button.enabled = True
        self._cancel_button.enabled = False

    def _on_batch_error(self, ctx, exception):
        """Callback when a batch item fails.

        Note: Error logging is handled by BatchRunner's internal logger.
        This callback only updates the UI.
        """
        self._progress_bar.label = f'Error on {ctx.item.name}: {exception}'

    def _on_batch_cancel(self):
        """Callback when the batch is cancelled."""
        self._progress_bar.label = 'Cancelled'
        self.batch_button.enabled = True
        self._cancel_button.enabled = False

    def batch_workflow(self):
        """Run the workflow on all images in the image directory."""
        result_dir = self.result_directory.value
        image_files = self.image_files

        root_list = [widget.value for widget in self._batch_roots_container]
        root_index_list = [self._channel_names.index(r) for r in root_list]
        task_names = self._tasks_select.value

        self._batch_runner.run(
            process_workflow_file,
            image_files,
            result_dir=result_dir,
            workflow_file=self.workflow_file.value,
            root_index_list=root_index_list,
            task_names=task_names,
            keep_original_images=self._keep_original_images.value,
            root_list=root_list,
            squeezed_img_dims=self._squeezed_img_dims,
            log_file=result_dir / 'workflow.log.txt',
            log_header={
                'Image Directory': str(self.image_directory.value),
                'Result Directory': str(result_dir),
                'Workflow File': str(self.workflow_file.value),
                'Roots': str(root_list),
                'Tasks': str(task_names),
            },
            threaded=True,
        )

    def viewer_workflow(self):
        """Run the workflow on the viewer layers."""
        # Reload workflow for fresh state (previous run may have set data)
        workflow = load_workflow(self.workflow_file.value, lazy=True)

        try:
            workflow = ensure_runnable(workflow)
        except WorkflowNotRunnableError as e:
            from napari.utils.notifications import show_error

            show_error(str(e))
            return

        root_layer_list = [
            widget.value for widget in self._viewer_roots_container
        ]
        self._root_scale = root_layer_list[0].scale

        # Use stored input names (stable, from YAML metadata)
        for root_idx, root_layer in enumerate(root_layer_list):
            workflow.set(
                name=self._workflow_inputs[root_idx],
                func_or_data=root_layer.data,
            )

        for task_idx, task in enumerate(self._tasks_select.value):
            result = workflow.get(name=task)
            yield task_idx, task, result

        return

    def _viewer_workflow_yielded(self, value):
        task_idx, task, result = value
        # TODO: estimate layer type and call proper add function (could be label)
        self._viewer.add_image(
            result,
            name=task,
            blending='additive',
            scale=self._root_scale if self._root_scale is not None else None,
        )
        self._progress_bar.value = task_idx + 1
        return

    def viewer_workflow_threaded(self):
        """Run the viewer workflow with threading and progress bar updates."""
        from napari.qt import create_worker

        self._progress_bar.label = 'Workflow on Viewer Layers'
        self._progress_bar.value = 0
        self._progress_bar.max = len(self._tasks_select.value)

        self._viewer_worker = create_worker(self.viewer_workflow)
        self._viewer_worker.yielded.connect(self._viewer_workflow_yielded)
        self._viewer_worker.start()
        return
