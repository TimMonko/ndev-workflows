"""Tests for workflow I/O (save/load)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ndev_workflows import Workflow, load_workflow, save_workflow
from ndev_workflows._io import WorkflowYAMLError
from ndev_workflows._spec import ensure_runnable
from ndev_workflows._workflow import WorkflowNotRunnableError


# Define helper functions at module level for import resolution
def add_helper(x, value=10):
    """Helper function for addition."""
    return x + value


def multiply_helper(x, factor=2.0):
    """Helper function for multiplication."""
    return x * factor


class TestWorkflowSaveLoad:
    """Test YAML save/load functionality."""

    def test_save_and_load_simple(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test saving and loading a simple workflow."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('output', add_helper, 'input', value=20)

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w)

        assert filepath.exists()

        # Load the workflow
        loaded = load_workflow(filepath)
        assert isinstance(loaded, Workflow)
        assert 'output' in loaded

        # Data tasks are not saved
        assert 'input' not in loaded

    def test_save_excludes_data_tasks(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test that raw data tasks are excluded from saved file."""
        w = Workflow()
        w.set('data1', sample_image)
        w.set('data2', np.zeros((10, 10)))
        w.set('processed', add_helper, 'data1', value=5)

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w)

        loaded = load_workflow(filepath)

        # Only processing step should be saved
        assert 'processed' in loaded
        assert 'data1' not in loaded
        assert 'data2' not in loaded

    def test_loaded_workflow_executes(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test that loaded workflow can be executed."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('result', add_helper, 'input', value=100)

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w)

        loaded = load_workflow(filepath)
        loaded.set('input', sample_image)  # Provide data

        result = loaded.get('result')
        expected = sample_image + 100
        np.testing.assert_array_equal(result, expected)

    def test_save_load_chain(self, tmp_path: Path, sample_image: np.ndarray):
        """Test saving/loading a chain of operations."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('step1', add_helper, 'input', value=10)
        w.set('step2', multiply_helper, 'step1', factor=2.0)

        filepath = tmp_path / 'chain.yaml'
        save_workflow(filepath, w)

        loaded = load_workflow(filepath)
        loaded.set('input', sample_image)

        result = loaded.get('step2')
        expected = (sample_image + 10) * 2.0
        np.testing.assert_allclose(result, expected)


class TestWorkflowMetadata:
    """Test metadata extraction from workflow files."""

    def test_get_metadata_from_saved_workflow(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test extracting metadata from a saved workflow."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('processed', multiply_helper, 'input', factor=3.0)

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w, name='Test Workflow')

        metadata = load_workflow(filepath, lazy=True).metadata

        assert metadata['name'] == 'Test Workflow'
        assert metadata['legacy'] is False

    def test_get_metadata_inputs_outputs(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test that inputs and outputs are correctly extracted."""
        w = Workflow()
        # Note: Data tasks are not saved - only function tasks are
        # So 'input' becomes an external reference when loaded
        w.set('input', sample_image)
        w.set('step1', add_helper, 'input', value=10)
        w.set('output', multiply_helper, 'step1', factor=2.0)

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w)

        metadata = load_workflow(filepath, lazy=True).metadata

        # When loaded, 'input' becomes an external input (since data tasks aren't saved)
        # The saved workflow's external_inputs() finds 'input' as referenced but undefined
        assert 'input' in metadata['inputs']
        # Outputs are leafs
        assert 'output' in metadata['outputs']

    def test_get_metadata_tasks(
        self, tmp_path: Path, sample_image: np.ndarray
    ):
        """Test that task names are correctly extracted."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('blur', add_helper, 'input')
        w.set('threshold', multiply_helper, 'blur')

        filepath = tmp_path / 'workflow.yaml'
        save_workflow(filepath, w)

        workflow = load_workflow(filepath, lazy=True)

        assert 'blur' in workflow.processing_task_names()
        assert 'threshold' in workflow.processing_task_names()


class TestWorkflowYAMLError:
    """Test error handling in workflow I/O."""

    def test_load_nonexistent_file(self, tmp_path: Path):
        """Test loading a file that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_workflow(tmp_path / 'nonexistent.yaml')

    def test_load_invalid_yaml(self, tmp_path: Path):
        """Test loading invalid YAML."""
        filepath = tmp_path / 'invalid.yaml'
        filepath.write_text('not: valid: yaml: content: [[[')

        with pytest.raises(WorkflowYAMLError):
            load_workflow(filepath)

    def test_load_with_unimportable_function(self, tmp_path: Path):
        """Test that unimportable functions raise error."""
        filepath = tmp_path / 'bad_workflow.yaml'
        filepath.write_text("""
name: Bad Workflow
inputs: [input]
outputs: [bad]
tasks:
  bad:
    function: nonexistent.module.fake_function
    params:
      arg0: input
""")

        with pytest.raises(WorkflowYAMLError, match='Cannot import'):
            load_workflow(filepath)


class TestPathTypes:
    """Test that both str and Path work for file operations."""

    def test_save_with_path(self, tmp_path: Path, sample_image: np.ndarray):
        """Test save_workflow with Path object."""
        w = Workflow()
        w.set('x', sample_image)
        w.set('y', add_helper, 'x')

        save_workflow(tmp_path / 'test.yaml', w)
        assert (tmp_path / 'test.yaml').exists()

    def test_save_with_str(self, tmp_path: Path, sample_image: np.ndarray):
        """Test save_workflow with string path."""
        w = Workflow()
        w.set('x', sample_image)
        w.set('y', add_helper, 'x')

        save_workflow(str(tmp_path / 'test.yaml'), w)
        assert (tmp_path / 'test.yaml').exists()

    def test_load_with_path(self, tmp_path: Path, sample_image: np.ndarray):
        """Test load_workflow with Path object."""
        w = Workflow()
        w.set('x', sample_image)
        w.set('y', add_helper, 'x')

        filepath = tmp_path / 'test.yaml'
        save_workflow(filepath, w)

        loaded = load_workflow(filepath)
        assert 'y' in loaded

    def test_load_with_str(self, tmp_path: Path, sample_image: np.ndarray):
        """Test load_workflow with string path."""
        w = Workflow()
        w.set('x', sample_image)
        w.set('y', add_helper, 'x')

        filepath = tmp_path / 'test.yaml'
        save_workflow(filepath, w)

        loaded = load_workflow(str(filepath))
        assert 'y' in loaded


@pytest.fixture
def legacy_workflow_path() -> Path:
    """Path to legacy format test file."""
    return Path('tests/resources/Workflow/workflows/legacy_simple.yaml')


class TestLegacyFormatLoading:
    """Test loading legacy napari-workflows format."""

    def test_load_legacy_format(self, legacy_workflow_path: Path):
        """Test that legacy format is detected and loaded."""
        from ndev_workflows._io import is_legacy_format

        assert is_legacy_format(legacy_workflow_path)

        workflow = load_workflow(legacy_workflow_path)
        assert isinstance(workflow, Workflow)

    def test_legacy_format_has_correct_tasks(self, legacy_workflow_path: Path):
        """Test that legacy format loads all tasks."""
        workflow = load_workflow(legacy_workflow_path)

        assert 'blurred' in workflow
        assert 'labels' in workflow

    def test_legacy_format_has_correct_roots(self, legacy_workflow_path: Path):
        """Test that legacy format correctly identifies roots."""
        workflow = load_workflow(legacy_workflow_path)

        roots = workflow.roots()
        assert 'image' in roots

    def test_legacy_format_has_correct_leafs(self, legacy_workflow_path: Path):
        """Test that legacy format correctly identifies leafs."""
        workflow = load_workflow(legacy_workflow_path)

        leafs = workflow.leaves()
        assert 'labels' in leafs

    def test_legacy_format_executes(self, legacy_workflow_path: Path):
        """Test that loaded legacy workflow can execute."""
        workflow = load_workflow(legacy_workflow_path)

        # Set the input
        test_image = np.random.randint(0, 255, (32, 32), dtype=np.uint8)
        workflow.set('image', test_image)

        # Execute
        result = workflow.get('labels')
        assert result is not None
        assert result.shape == test_image.shape

    def test_legacy_format_lazy_loading(self, legacy_workflow_path: Path):
        """Test lazy loading doesn't import functions."""
        workflow = load_workflow(legacy_workflow_path, lazy=True)

        # Should have CallableRef placeholders
        from ndev_workflows._workflow import CallableRef

        task = workflow._tasks['blurred']
        assert isinstance(task[0], CallableRef)

    def test_legacy_metadata(self, legacy_workflow_path: Path):
        """Test getting metadata from legacy format."""
        metadata_obj = load_workflow(legacy_workflow_path, lazy=True).metadata
        assert isinstance(metadata_obj, dict)
        metadata: dict[str, Any] = metadata_obj

        assert metadata['legacy'] is True

        inputs = metadata.get('inputs')
        outputs = metadata.get('outputs')
        assert isinstance(inputs, list)
        assert isinstance(outputs, list)

        assert 'image' in inputs
        assert 'labels' in outputs


def test_ensure_runnable_from_spec_executes():
    spec = {
        'name': 'sqrt test',
        'inputs': ['x'],
        'outputs': ['y'],
        'tasks': {
            'y': {
                'function': 'math.sqrt',
                'params': {'arg0': 'x'},
            }
        },
    }

    w = ensure_runnable(spec)
    w.set('x', 9.0)
    assert w.get('y') == 3.0


def test_ensure_runnable_reports_missing_callable():
    spec = {
        'inputs': ['x'],
        'outputs': ['y'],
        'tasks': {
            'y': {
                'function': 'nonexistent.module.fake_function',
                'params': {'arg0': 'x'},
            }
        },
    }

    with pytest.raises(WorkflowNotRunnableError, match='Cannot import'):
        ensure_runnable(spec)


def test_workflow_method_ensure_runnable_resolves_callable_ref():
    from ndev_workflows._workflow import CallableRef, Workflow

    w = Workflow()
    w._tasks['y'] = (CallableRef('math', 'sqrt'), 'x')
    w.ensure_runnable()
    w.set('x', 16.0)
    assert w.get('y') == 4.0
