"""Tests for the core Workflow class."""

from __future__ import annotations

import numpy as np
import pytest

from ndev_workflows import Workflow


class TestWorkflowBasics:
    """Test basic Workflow functionality."""

    def test_create_empty_workflow(self):
        """Test creating an empty workflow."""
        w = Workflow()
        assert len(w) == 0
        assert w.keys() == []

    def test_set_raw_data(self, sample_image: np.ndarray):
        """Test setting raw data in workflow."""
        w = Workflow()
        w.set('input', sample_image)

        assert 'input' in w
        assert len(w) == 1

    def test_set_processing_step(self, sample_image: np.ndarray):
        """Test setting a processing step."""

        def double(x):
            return x * 2

        w = Workflow()
        w.set('input', sample_image)
        w.set('doubled', double, 'input')

        assert 'input' in w
        assert 'doubled' in w
        assert len(w) == 2

    def test_get_executes_task(self, sample_image: np.ndarray):
        """Test that get() executes the task graph."""

        def add_one(x):
            return x + 1

        w = Workflow()
        w.set('input', sample_image)
        w.set('output', add_one, 'input')

        result = w.get('output')
        expected = sample_image + 1
        np.testing.assert_array_equal(result, expected)

    def test_get_missing_task_raises(self, empty_workflow: Workflow):
        """Test that get() raises KeyError for missing task."""
        with pytest.raises(KeyError, match='not found'):
            empty_workflow.get('nonexistent')

    def test_kwargs_passed_correctly(self, sample_image: np.ndarray):
        """Test that kwargs are passed to the function."""

        def scale(x, factor=1.0):
            return x * factor

        w = Workflow()
        w.set('input', sample_image)
        w.set('scaled', scale, 'input', factor=3.0)

        result = w.get('scaled')
        expected = sample_image * 3.0
        np.testing.assert_array_equal(result, expected)


class TestWorkflowGraphOperations:
    """Test workflow graph analysis operations."""

    def test_roots_returns_external_references(self, sample_image: np.ndarray):
        """Test roots() returns names referenced but not defined."""

        def process(x):
            return x * 2

        w = Workflow()
        # Only set a function that references 'input', don't define 'input'
        w.set('output', process, 'input')

        roots = w.roots()
        # 'input' is referenced but not defined, so it's a root
        assert 'input' in roots
        assert len(roots) == 1

    def test_roots_empty_when_all_defined(self, simple_workflow: Workflow):
        """Test roots() includes data inputs (graph roots)."""
        # simple_workflow has 'input' defined as data and used by a task,
        # so it is a graph root (even though it's not an external input).
        roots = simple_workflow.roots()
        assert roots == ['input']

    def test_leafs_single_output(self, simple_workflow: Workflow):
        """Test leafs() with single output."""
        leafs = simple_workflow.leaves()
        assert 'output' in leafs
        assert len(leafs) == 1

    def test_leafs_multiple_outputs(self, branching_workflow: Workflow):
        """Test leafs() with multiple outputs."""
        leafs = branching_workflow.leaves()
        # blurred_2 and binary are both leafs (nothing depends on them)
        assert 'blurred_2' in leafs
        assert 'binary' in leafs
        assert 'input' not in leafs

    def test_followers_of(self, branching_workflow: Workflow):
        """Test followers_of() returns dependent tasks."""
        followers = branching_workflow.followers_of('input')
        assert 'blurred_1' in followers
        assert 'blurred_2' in followers

    def test_sources_of(self, chain_workflow: Workflow):
        """Test sources_of() returns dependencies."""
        sources = chain_workflow.sources_of('added')
        assert 'multiplied' in sources

        sources = chain_workflow.sources_of('multiplied')
        assert 'input' in sources

    def test_sources_of_root(self, chain_workflow: Workflow):
        """Test sources_of() returns empty for root."""
        sources = chain_workflow.sources_of('input')
        assert sources == []

    def test_external_inputs_none_when_complete(
        self, simple_workflow: Workflow
    ):
        """Test external_inputs() returns empty for complete workflow."""
        external = simple_workflow.get_undefined_inputs()
        assert external == []

    def test_external_inputs_finds_missing(self, sample_image: np.ndarray):
        """Test external_inputs() finds undefined references."""

        def process(x):
            return x * 2

        w = Workflow()
        # Create a task that references 'missing_input' which doesn't exist
        w.set('result', process, 'missing_input')

        external = w.get_undefined_inputs()
        assert 'missing_input' in external
        assert len(external) == 1

    def test_root_functions(self, sample_image: np.ndarray):
        """Test root_functions() returns functions that operate on roots."""

        def step1(x):
            return x + 1

        def step2(x):
            return x * 2

        w = Workflow()
        # Don't define 'input' - it will be a root (external reference)
        w.set('processed', step1, 'input')  # Operates on root 'input'
        w.set('final', step2, 'processed')  # Operates on non-root

        root_funcs = w.root_functions()
        # 'processed' depends on 'input' which is a root (undefined)
        assert 'processed' in root_funcs
        # 'final' depends on 'processed' which is defined, not a root
        assert 'final' not in root_funcs


class TestWorkflowCopyAndModify:
    """Test workflow copy and modification operations."""

    def test_copy_creates_independent_workflow(
        self, simple_workflow: Workflow
    ):
        """Test that copy() creates an independent copy."""
        copied = simple_workflow.copy()

        assert len(copied) == len(simple_workflow)
        assert copied.keys() == simple_workflow.keys()

        # Modify original
        simple_workflow.set('new_task', lambda x: x, 'input')

        # Copy should be unaffected
        assert 'new_task' in simple_workflow
        assert 'new_task' not in copied

    def test_remove_task(self, simple_workflow: Workflow):
        """Test removing a task."""
        simple_workflow.remove('output')
        assert 'output' not in simple_workflow
        assert 'input' in simple_workflow

    def test_clear_removes_all(self, simple_workflow: Workflow):
        """Test clear() removes all tasks."""
        simple_workflow.clear()
        assert len(simple_workflow) == 0

    def test_is_data_task(self, simple_workflow: Workflow):
        """Test is_data_task() correctly identifies raw data."""
        assert simple_workflow.is_data_task('input') is True
        assert simple_workflow.is_data_task('output') is False

    def test_get_function(self, simple_workflow: Workflow):
        """Test get_function() returns the function."""
        func = simple_workflow.get_function('output')
        assert callable(func)

        # Data task should return None
        func = simple_workflow.get_function('input')
        assert func is None


class TestWorkflowChainExecution:
    """Test execution of chained workflows."""

    def test_chain_execution(self, sample_image: np.ndarray):
        """Test executing a chain of operations."""

        def add(x, value=0):
            return x + value

        def multiply(x, factor=1):
            return x * factor

        w = Workflow()
        w.set('input', sample_image)
        w.set('step1', add, 'input', value=10)
        w.set('step2', multiply, 'step1', factor=2)
        w.set('step3', add, 'step2', value=5)

        result = w.get('step3')
        expected = (sample_image + 10) * 2 + 5
        np.testing.assert_array_equal(result, expected)

    def test_branching_execution(self, sample_image: np.ndarray):
        """Test executing a branching workflow."""

        def add(x, value=0):
            return x + value

        w = Workflow()
        w.set('input', sample_image)
        w.set('branch1', add, 'input', value=10)
        w.set('branch2', add, 'input', value=20)

        result1 = w.get('branch1')
        result2 = w.get('branch2')

        np.testing.assert_array_equal(result1, sample_image + 10)
        np.testing.assert_array_equal(result2, sample_image + 20)


class TestWorkflowRepr:
    """Test workflow string representation."""

    def test_repr_empty(self, empty_workflow: Workflow):
        """Test repr of empty workflow."""
        r = repr(empty_workflow)
        assert 'Workflow' in r
        assert '0 tasks' in r

    def test_repr_with_tasks(self, simple_workflow: Workflow):
        """Test repr with tasks."""
        r = repr(simple_workflow)
        assert 'Workflow' in r
        assert '2 tasks' in r
