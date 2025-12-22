"""Tests for WorkflowContainer widget.

Organized into:
- Unit tests (no napari/Qt dependencies)
- Widget tests (qtbot for async, no viewer)
- Integration tests (full viewer, only when needed)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
from ndevio import nImage

from ndev_workflows.widgets._workflow_container import WorkflowContainer


class MockWorkflow:
    """Mock workflow for testing without loading actual workflow."""

    def roots(self):
        return ['root1', 'root2']

    def leaves(self):
        return ['leaf1', 'leaf2']

    def leafs(self):
        return self.leaves()

    def set(self, name, func_or_data):
        pass

    def get(self, name):
        pass


# =============================================================================
# Unit tests - No Qt/napari viewer dependencies
# =============================================================================


class TestWorkflowContainerBasics:
    """Basic initialization and property tests without viewer."""

    def test_init_no_viewer(self):
        """Test initialization without viewer."""
        container = WorkflowContainer()

        assert container._viewer is None
        assert container._channel_names == []
        assert container._img_dims == ''

    def test_get_workflow_info_loads_workflow(self, sample_workflow_path):
        """Test loading a workflow file populates workflow info."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path

        assert container.workflow is not None
        assert container._workflow_roots.value == str(
            container.workflow.roots()
        )

    def test_workflow_roots_updated(self, sample_workflow_path):
        """Test that root containers are updated from workflow."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path

        roots = container.workflow.roots()
        assert len(container._batch_roots_container) == len(roots)
        assert len(container._viewer_roots_container) == len(roots)

    def test_tasks_select_populated(self, sample_workflow_path):
        """Test that tasks select is populated from workflow."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path

        assert len(container._tasks_select.choices) > 0
        assert container._tasks_select.value == list(
            container.workflow.leaves()
        )

    def test_update_progress_bar(self):
        """Test progress bar update."""
        container = WorkflowContainer()
        container._progress_bar.value = 0
        container._progress_bar.max = 10
        container._update_progress_bar(9)

        assert container._progress_bar.value == 9


class TestWorkflowContainerCallbacks:
    """Test callback methods without running actual batch."""

    def test_on_batch_error_updates_label(self):
        """Test that error callback updates progress bar label."""
        from nbatch import BatchContext

        container = WorkflowContainer()

        mock_item = MagicMock()
        mock_item.name = 'bad_file.tiff'
        ctx = MagicMock(spec=BatchContext)
        ctx.item = mock_item

        test_exception = ValueError('Test error message')
        container._on_batch_error(ctx, test_exception)

        assert 'Error on bad_file.tiff' in container._progress_bar.label
        assert 'Test error message' in container._progress_bar.label

    def test_on_batch_complete_updates_label(self):
        """Test that complete callback updates progress bar label."""
        container = WorkflowContainer()
        container._progress_bar.max = 5

        container._on_batch_complete()

        assert 'Completed 5 Images' in container._progress_bar.label
        assert container.batch_button.enabled is True
        assert container._cancel_button.enabled is False

    def test_on_batch_cancel_updates_label(self):
        """Test that cancel callback updates progress bar label."""
        container = WorkflowContainer()
        container._on_batch_cancel()

        assert container._progress_bar.label == 'Cancelled'
        assert container.batch_button.enabled is True

    def test_on_batch_start_sets_progress(self):
        """Test that start callback initializes progress bar."""
        container = WorkflowContainer()
        container._on_batch_start(total=10)

        assert container._progress_bar.value == 0
        assert container._progress_bar.max == 10
        assert container.batch_button.enabled is False
        assert container._cancel_button.enabled is True


class TestMockWorkflowTests:
    """Tests with mock workflow for faster widget tests (no viewer)."""

    def test_update_roots_with_mock_workflow(self):
        """Test _update_roots with a mock workflow."""
        container = WorkflowContainer()
        container.workflow = MockWorkflow()
        container._channel_names = ['red', 'green', 'blue']

        container._update_roots()

        assert len(container._batch_roots_container) == 2
        assert len(container._viewer_roots_container) == 2

        for idx, root in enumerate(container._batch_roots_container):
            assert root.label == f'Root {idx}: {MockWorkflow().roots()[idx]}'
            assert root.choices == (None, 'red', 'green', 'blue')
            assert root._nullable is True
            assert root.value is None


# =============================================================================
# Batch processing tests (with qtbot for async, no viewer)
# =============================================================================


class TestBatchWorkflow:
    """Test batch workflow execution."""

    def test_batch_workflow_basic(
        self, tmp_path, qtbot, sample_workflow_path, images_path
    ):
        """Test basic batch workflow execution."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path
        container.image_directory.value = images_path

        output_folder = tmp_path / 'Output'
        output_folder.mkdir()
        container.result_directory.value = output_folder

        container._batch_roots_container[0].value = 'membrane'
        container._batch_roots_container[1].value = 'nuclei'

        container.batch_workflow()

        qtbot.waitUntil(
            lambda: not container._batch_runner.is_running, timeout=15000
        )

        assert output_folder.exists()
        assert (output_folder / 'cells3d2ch.tiff').exists()
        assert (output_folder / 'workflow.log.txt').exists()

    def test_batch_workflow_leaf_tasks_only(
        self, tmp_path, qtbot, sample_workflow_path, images_path
    ):
        """Test batch workflow outputs only leaf tasks by default."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path
        container.image_directory.value = images_path

        output_folder = tmp_path / 'Output'
        output_folder.mkdir(exist_ok=True)
        container.result_directory.value = output_folder

        container._batch_roots_container[0].value = 'membrane'
        container._batch_roots_container[1].value = 'nuclei'

        container.batch_workflow()

        qtbot.waitUntil(
            lambda: not container._batch_runner.is_running, timeout=15000
        )

        assert container._progress_bar.value == 1
        assert (output_folder / 'cells3d2ch.tiff').exists()

        img = nImage(output_folder / 'cells3d2ch.tiff')
        assert len(img.channel_names) == 2

    def test_batch_workflow_keep_original_images(
        self, tmp_path, qtbot, sample_workflow_path, images_path
    ):
        """Test batch workflow with keep_original_images."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path
        container.image_directory.value = images_path

        output_folder = tmp_path / 'Output'
        output_folder.mkdir()
        container.result_directory.value = output_folder

        container._batch_roots_container[0].value = 'membrane'
        container._batch_roots_container[1].value = 'nuclei'
        container._keep_original_images.value = True

        container.batch_button.clicked()

        qtbot.waitUntil(
            lambda: not container._batch_runner.is_running, timeout=15000
        )

        img = nImage(output_folder / 'cells3d2ch.tiff')
        assert len(img.channel_names) == 4
        assert img.channel_names == [
            'membrane',
            'nuclei',
            'membrane-label',
            'nucleus-label',
        ]

    def test_batch_workflow_all_tasks(
        self, tmp_path, qtbot, sample_workflow_path, images_path
    ):
        """Test batch workflow with all tasks selected."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path
        container.image_directory.value = images_path

        output_folder = tmp_path / 'Output'
        output_folder.mkdir()
        container.result_directory.value = output_folder

        container._batch_roots_container[0].value = 'membrane'
        container._batch_roots_container[1].value = 'nuclei'
        container._tasks_select.value = list(container.workflow._tasks.keys())

        container.batch_workflow()

        qtbot.waitUntil(
            lambda: not container._batch_runner.is_running, timeout=15000
        )

        img = nImage(output_folder / 'cells3d2ch.tiff')
        assert len(img.channel_names) == 6

    def test_cancel_button_stops_batch(
        self, tmp_path, qtbot, sample_workflow_path, images_path
    ):
        """Test that cancel button stops the batch runner."""
        container = WorkflowContainer()
        container.workflow_file.value = sample_workflow_path
        container.image_directory.value = images_path

        output_folder = tmp_path / 'Output'
        output_folder.mkdir()
        container.result_directory.value = output_folder

        container._batch_roots_container[0].value = 'membrane'
        container._batch_roots_container[1].value = 'nuclei'

        container.batch_workflow()
        assert container._batch_runner.is_running

        container._cancel_button.clicked()

        qtbot.waitUntil(
            lambda: not container._batch_runner.is_running, timeout=15000
        )

        assert not container._batch_runner.is_running


# =============================================================================
# Viewer workflow tests (require napari viewer)
# =============================================================================


class TestViewerWorkflow:
    """Tests that require an actual napari viewer."""

    def test_init_with_viewer(self, make_napari_viewer):
        """Test initialization with viewer."""
        viewer = make_napari_viewer()
        container = WorkflowContainer(viewer)

        assert container._viewer == viewer
        assert container._channel_names == []
        assert container._img_dims == ''

    def test_update_roots_with_viewer(self, make_napari_viewer):
        """Test _update_roots with a viewer updates layer choices."""
        viewer = make_napari_viewer()
        container = WorkflowContainer(viewer)

        container.workflow = MockWorkflow()
        container._channel_names = ['red', 'green', 'blue']

        container._update_roots()

        assert len(container._batch_roots_container) == 2
        assert len(container._viewer_roots_container) == 2

        for idx, root in enumerate(container._viewer_roots_container):
            assert (
                root.label == f'Root {idx}: {container.workflow.roots()[idx]}'
            )
            assert root.choices == (None,)  # No layers yet
            assert root._nullable is True

        # Add layers to viewer
        viewer.open_sample('napari', 'cells3d')
        viewer.add_labels(np.random.randint(0, 2, (10, 10, 10)))

        # Layer choices should update
        for root in container._viewer_roots_container:
            assert len(root.choices) == 4  # None + 3 layers

    def test_viewer_workflow_generator(
        self, make_napari_viewer, sample_workflow_path
    ):
        """Test viewer_workflow yields results."""
        viewer = make_napari_viewer()
        container = WorkflowContainer(viewer)
        container.workflow_file.value = sample_workflow_path

        viewer.open_sample('napari', 'cells3d')
        container._viewer_roots_container[0].value = viewer.layers['membrane']
        container._viewer_roots_container[1].value = viewer.layers['nuclei']

        generator = container.viewer_workflow()

        expected_results = [
            (0, 'membrane-label'),
            (1, 'nucleus-label'),
        ]
        for idx, (task_idx, task, result, _func) in enumerate(generator):
            assert task_idx == expected_results[idx][0]
            assert task == expected_results[idx][1]
            assert isinstance(result, np.ndarray)

    def test_viewer_workflow_yielded_adds_layer(self, make_napari_viewer):
        """Test _viewer_workflow_yielded adds layer to viewer."""
        viewer = make_napari_viewer()
        container = WorkflowContainer(viewer)
        data = np.random.randint(0, 2, (10, 10, 10))

        value = (1, 'test-name', data, None)
        container._viewer_workflow_yielded(value)

        assert container._progress_bar.value == 2  # idx + 1
        assert viewer.layers[0].name == 'test-name'
        assert viewer.layers[0].data.shape == data.shape
        assert np.array_equal(viewer.layers[0].scale, (1, 1, 1))

    def test_viewer_workflow_threaded(
        self, make_napari_viewer, sample_workflow_path, qtbot
    ):
        """Test threaded viewer workflow execution."""
        viewer = make_napari_viewer()
        container = WorkflowContainer(viewer)
        container.workflow_file.value = sample_workflow_path

        viewer.open_sample('napari', 'cells3d')
        container._viewer_roots_container[0].value = viewer.layers['membrane']
        container._viewer_roots_container[1].value = viewer.layers['nuclei']

        container.viewer_workflow_threaded()

        with qtbot.waitSignal(
            container._viewer_worker.finished, timeout=15000
        ):
            pass

        assert container._progress_bar.value == 2
        assert viewer.layers[2].name == 'membrane-label'
        assert viewer.layers[3].name == 'nucleus-label'
