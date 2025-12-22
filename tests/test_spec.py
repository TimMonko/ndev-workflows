"""Tests for workflow spec conversion (_spec.py)."""

from __future__ import annotations

from functools import partial

import numpy as np
import pytest

from ndev_workflows import Workflow
from ndev_workflows._spec import (
    ensure_runnable,
    spec_dict_to_workflow,
    workflow_to_spec_dict,
)
from ndev_workflows._workflow import CallableRef, WorkflowNotRunnableError


# Use module-level functions from tests.conftest for serialization tests
def add_value(x, value: int = 10):
    """Helper function for addition tests."""
    return x + value


def multiply_value(x, factor: float = 2.0):
    """Helper function for multiplication tests."""
    return x * factor


class TestWorkflowToSpecDict:
    """Tests for workflow_to_spec_dict conversion."""

    def test_converts_simple_workflow(self, sample_image: np.ndarray):
        """Test converting a simple workflow to spec dict."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('output', add_value, 'input', value=20)

        spec = workflow_to_spec_dict(w)

        assert 'tasks' in spec
        assert 'output' in spec['tasks']
        # Function path should contain 'add_value'
        assert 'add_value' in spec['tasks']['output']['function']
        assert spec['tasks']['output']['params']['arg0'] == 'input'
        assert spec['tasks']['output']['params']['value'] == 20

    def test_excludes_data_tasks(self, sample_image: np.ndarray):
        """Test that data (non-callable) tasks are not included."""
        w = Workflow()
        w.set('data1', sample_image)
        w.set('data2', np.zeros((10, 10)))
        w.set('processed', add_value, 'data1', value=5)

        spec = workflow_to_spec_dict(w)

        # Data tasks should not be in tasks dict
        assert 'data1' not in spec['tasks']
        assert 'data2' not in spec['tasks']
        assert 'processed' in spec['tasks']

    def test_identifies_inputs_and_outputs(self, sample_image: np.ndarray):
        """Test that inputs and outputs are correctly identified."""
        w = Workflow()
        w.set('input', sample_image)
        w.set('step1', add_value, 'input', value=10)
        w.set('output', multiply_value, 'step1', factor=2.0)

        spec = workflow_to_spec_dict(w)

        # 'input' is referenced but not saved as a task
        assert 'input' in spec['inputs']
        # 'output' is a leaf (nothing depends on it)
        assert 'output' in spec['outputs']

    def test_includes_metadata(self, sample_image: np.ndarray):
        """Test that name and description are included."""
        w = Workflow()
        w.set('x', sample_image)
        w.set('y', add_value, 'x')

        spec = workflow_to_spec_dict(w, name='Test', description='A test')

        assert spec['name'] == 'Test'
        assert spec['description'] == 'A test'
        assert 'modified' in spec

    def test_handles_callable_ref(self):
        """Test converting a workflow with CallableRef placeholders."""
        w = Workflow()
        ref = CallableRef('math', 'sqrt')
        ref.kwargs = {'x': 9}
        w._tasks['result'] = (ref, 'input')

        spec = workflow_to_spec_dict(w)

        assert 'result' in spec['tasks']
        assert spec['tasks']['result']['function'] == 'math.sqrt'


class TestSpecDictToWorkflow:
    """Tests for spec_dict_to_workflow conversion."""

    def test_creates_workflow_from_spec(self):
        """Test creating a workflow from a spec dict."""
        spec = {
            'inputs': ['x'],
            'outputs': ['y'],
            'tasks': {
                'y': {
                    'function': 'math.sqrt',
                    'params': {'arg0': 'x'},
                }
            },
        }

        w = spec_dict_to_workflow(spec, lazy=False)

        assert 'y' in w
        w.set('x', 16.0)
        assert w.get('y') == 4.0

    def test_lazy_creates_callable_refs(self):
        """Test lazy loading creates CallableRef placeholders."""
        spec = {
            'inputs': ['x'],
            'outputs': ['y'],
            'tasks': {
                'y': {
                    'function': 'math.sqrt',
                    'params': {'arg0': 'x'},
                }
            },
        }

        w = spec_dict_to_workflow(spec, lazy=True)

        assert 'y' in w
        task = w._tasks['y']
        assert isinstance(task[0], CallableRef)

    def test_kwargs_attached_to_callable_ref(self):
        """Test that kwargs are attached to CallableRef when lazy."""
        spec = {
            'inputs': ['x'],
            'outputs': ['y'],
            'tasks': {
                'y': {
                    'function': 'builtins.round',
                    'params': {'arg0': 'x', 'ndigits': 2},
                }
            },
        }

        w = spec_dict_to_workflow(spec, lazy=True)

        task = w._tasks['y']
        ref = task[0]
        assert ref.kwargs == {'ndigits': 2}

    def test_eager_creates_partial_with_kwargs(self):
        """Test that eager loading creates partial functions with kwargs."""
        spec = {
            'inputs': ['x'],
            'outputs': ['y'],
            'tasks': {
                'y': {
                    'function': 'builtins.round',
                    'params': {'arg0': 'x', 'ndigits': 3},
                }
            },
        }

        w = spec_dict_to_workflow(spec, lazy=False)

        task = w._tasks['y']
        func = task[0]
        assert isinstance(func, partial)
        assert func.keywords == {'ndigits': 3}

    def test_preserves_metadata(self):
        """Test that metadata is preserved."""
        spec = {
            'name': 'Test Workflow',
            'description': 'A test',
            'modified': '2025-01-01',
            'inputs': ['x'],
            'outputs': ['y'],
            'tasks': {
                'y': {
                    'function': 'math.sqrt',
                    'params': {'arg0': 'x'},
                }
            },
        }

        w = spec_dict_to_workflow(spec, lazy=True)

        assert w.metadata['name'] == 'Test Workflow'
        assert w.metadata['description'] == 'A test'


class TestEnsureRunnable:
    """Tests for ensure_runnable function."""

    def test_from_spec_dict(self):
        """Test ensure_runnable from a spec dict."""
        spec = {
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

        w.set('x', 25.0)
        assert w.get('y') == 5.0

    def test_from_lazy_workflow(self):
        """Test ensure_runnable from a lazy workflow."""
        w = Workflow()
        ref = CallableRef('math', 'sqrt')
        w._tasks['y'] = (ref, 'x')

        w = ensure_runnable(w)

        w.set('x', 36.0)
        assert w.get('y') == 6.0

    def test_raises_for_missing_callable(self):
        """Test that missing callables raise WorkflowNotRunnableError."""
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

    def test_already_runnable_workflow_unchanged(
        self, simple_workflow: Workflow
    ):
        """Test that already runnable workflow passes through."""
        result = ensure_runnable(simple_workflow)

        assert 'output' in result
        # The workflow should still work
        assert result.get('output') is not None


class TestRoundTrip:
    """Test round-trip conversion workflow -> spec -> workflow."""

    def test_roundtrip_preserves_functionality(self, sample_image: np.ndarray):
        """Test that converting to spec and back preserves behavior."""
        # Create original workflow
        original = Workflow()
        original.set('input', sample_image)
        original.set('step1', add_value, 'input', value=10)
        original.set('step2', multiply_value, 'step1', factor=3.0)

        # Convert to spec and back
        spec = workflow_to_spec_dict(original)
        restored = spec_dict_to_workflow(spec, lazy=False)

        # Provide input and execute
        restored.set('input', sample_image)
        result = restored.get('step2')

        expected = (sample_image + 10) * 3.0
        np.testing.assert_allclose(result, expected)
