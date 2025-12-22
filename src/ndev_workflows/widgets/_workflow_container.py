"""Workflow container widget for batch processing with napari-workflows.

This module provides a Container widget for managing napari-workflows in both
interactive (viewer) and batch processing modes. It integrates with nbatch
for parallel execution of workflows on multiple files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
        from magicclass.widgets import TabbedContainer

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
        from ndevio import helpers, nImage

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
        from ndevio import helpers

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
            self._tasks_select.choices = workflow.processing_task_names()
            self._tasks_select.value = workflow.leafs()

    def _get_workflow_info(self):
        """Load the workflow file and update the roots and leafs.

        Uses the loaded Workflow's metadata for fast preview.
        """
        from .._io import load_workflow

        workflow_path = self.workflow_file.value

        # Load workflow lazily so missing optional deps don't break the UI.
        # load_workflow() does not import task functions when lazy=True.
        try:
            self.workflow = load_workflow(workflow_path, lazy=True)
        except Exception:  # noqa
            self.workflow = None
            return

        metadata = getattr(self.workflow, 'metadata', {}) or {}
        self._workflow_inputs = list(metadata.get('inputs', []))
        self._workflow_roots.value = str(self._workflow_inputs)
        self._update_roots_from_list(self._workflow_inputs)

        self._update_task_choices(
            tasks=self.workflow.processing_task_names(),
            leafs=list(metadata.get('outputs', [])),
        )
        return

    def _update_roots_from_list(self, roots: list[str]):
        """Update root ComboBox widgets from a list of root names.

        Used for v3 format metadata preview.
        """
        from ndevio import helpers

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
        from .._batch import process_workflow_file

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
        from .._io import load_workflow
        from .._spec import ensure_runnable
        from .._workflow import WorkflowNotRunnableError

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
            func = workflow.get_function(task)
            result = workflow.get(name=task)
            yield task_idx, task, result, func

        return

    def _viewer_workflow_yielded(self, value):
        task_idx, task, result, func = value
        self._add_result_to_viewer(task=task, result=result, func=func)
        self._progress_bar.value = task_idx + 1
        return

    def _add_result_to_viewer(self, *, task: str, result, func=None) -> None:
        """Add a workflow result to the viewer using a best-effort layer choice.

        Rules:
        - If the task returns a napari LayerDataTuple ``(data, kwargs, layer_type)``,
          use that (this is the recommended way for non-image outputs like shapes).
        - Otherwise, if the result looks array-like, choose between labels vs image
          conservatively and fall back to add_image.

        Notes
        -----
        We intentionally do NOT try to guess points/shapes from an ``(N, D)`` array
        because that is ambiguous with images. For those cases, return a
        LayerDataTuple from the workflow task.
        """
        if self._viewer is None:
            return

        scale = self._root_scale if self._root_scale is not None else None

        # Preferred: explicit LayerDataTuple
        if (
            isinstance(result, tuple)
            and len(result) == 3
            and isinstance(result[2], str)
        ):
            data, kwargs, layer_type = result
            if kwargs is None:
                kwargs = {}
            if not isinstance(kwargs, dict):
                kwargs = dict(kwargs)

            kwargs.setdefault('name', task)
            if scale is not None and 'scale' not in kwargs:
                kwargs['scale'] = scale

            add_name = f'add_{layer_type}'
            add_fn = getattr(self._viewer, add_name, None)
            if callable(add_fn):
                add_fn(data, **kwargs)
                return

        # Fallback: array-like results -> labels vs image
        looks_array_like = all(
            hasattr(result, attr) for attr in ('shape', 'ndim', 'dtype')
        )
        if looks_array_like:
            import numpy as np

            def _is_probably_labels(arr) -> bool:
                try:
                    if arr.ndim < 2:
                        return False
                    if not (
                        np.issubdtype(arr.dtype, np.integer)
                        or np.issubdtype(arr.dtype, np.bool_)
                    ):
                        return False

                    flat = np.asarray(arr).ravel()
                    if flat.size == 0:
                        return False

                    # Sample to avoid expensive unique() on large arrays.
                    if flat.size > 4096:
                        step = max(1, flat.size // 4096)
                        flat = flat[::step]

                    uniq = np.unique(flat)
                    if uniq.size > 256:
                        return False
                    return not uniq.min(initial=0) < 0
                except Exception:  # noqa
                    return False

            if _is_probably_labels(result):
                self._viewer.add_labels(
                    result,
                    name=task,
                    scale=scale,
                )
                return

            self._viewer.add_image(
                result,
                name=task,
                blending='additive',
                scale=scale,
            )
            return

        # Last resort: try add_image, otherwise show a helpful error.
        try:
            self._viewer.add_image(
                result,
                name=task,
                blending='additive',
                scale=scale,
            )
        except Exception as e:  # noqa
            from napari.utils.notifications import show_error

            show_error(
                f"Cannot add result for task '{task}' to the viewer: {e}. "
                'For non-image outputs, return a LayerDataTuple '
                '(data, kwargs, layer_type) from the workflow task.'
            )

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
