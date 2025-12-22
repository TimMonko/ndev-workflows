"""Pytest configuration and shared fixtures for ndev-workflows tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ndev_workflows import Workflow

# =============================================================================
# Helper functions (module-level for import resolution in saved workflows)
# =============================================================================


def add_value(x, value: int = 10):
    """Helper function for addition tests."""
    return x + value


def multiply_value(x, factor: float = 2.0):
    """Helper function for multiplication tests."""
    return x * factor


def threshold_value(x, thresh: float = 128.0):
    """Helper function for thresholding tests."""
    return (x > thresh).astype(np.uint8)


def blur_value(x, sigma: float = 1.0):
    """Helper function for blurring tests."""
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(x.astype(float), sigma=sigma)


# =============================================================================
# Path fixtures
# =============================================================================


@pytest.fixture
def resources_path() -> Path:
    """Path to the test resources directory."""
    return Path(__file__).parent / 'resources'


@pytest.fixture
def workflow_resources_path(resources_path: Path) -> Path:
    """Path to the Workflow test resources."""
    return resources_path / 'Workflow'


@pytest.fixture
def sample_workflow_path(workflow_resources_path: Path) -> Path:
    """Path to the sample 2-roots-2-leafs workflow."""
    return (
        workflow_resources_path
        / 'workflows'
        / 'cpu_workflow-2roots-2leafs.yaml'
    )


@pytest.fixture
def legacy_workflow_path(workflow_resources_path: Path) -> Path:
    """Path to a legacy format workflow."""
    return workflow_resources_path / 'workflows' / 'legacy_simple.yaml'


@pytest.fixture
def images_path(workflow_resources_path: Path) -> Path:
    """Path to the test images directory."""
    return workflow_resources_path / 'Images'


# =============================================================================
# Image fixtures
# =============================================================================


@pytest.fixture
def sample_image() -> np.ndarray:
    """Create a sample 2D image for testing."""
    return np.random.randint(0, 255, (64, 64), dtype=np.uint8)


@pytest.fixture
def sample_3d_image() -> np.ndarray:
    """Create a sample 3D image for testing."""
    return np.random.randint(0, 255, (16, 64, 64), dtype=np.uint8)


# =============================================================================
# Workflow fixtures
# =============================================================================


@pytest.fixture
def empty_workflow() -> Workflow:
    """Create an empty workflow."""
    return Workflow()


@pytest.fixture
def simple_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a simple workflow with one processing step."""
    w = Workflow()
    w.set('input', sample_image)
    w.set('output', add_value, 'input', value=20)
    return w


@pytest.fixture
def chain_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a workflow with a chain of processing steps."""
    w = Workflow()
    w.set('input', sample_image)
    w.set('multiplied', multiply_value, 'input', factor=2.0)
    w.set('added', add_value, 'multiplied', value=5)
    return w


@pytest.fixture
def branching_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a workflow with branching (one input, multiple outputs)."""
    w = Workflow()
    w.set('input', sample_image)
    w.set('blurred_1', blur_value, 'input', sigma=1.0)
    w.set('blurred_2', blur_value, 'input', sigma=2.0)
    w.set('binary', threshold_value, 'blurred_1', thresh=100.0)
    return w


@pytest.fixture
def saveable_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a workflow using module-level functions (can be saved/loaded)."""
    w = Workflow()
    w.set('input', sample_image)
    w.set('step1', add_value, 'input', value=10)
    w.set('step2', multiply_value, 'step1', factor=2.0)
    return w
