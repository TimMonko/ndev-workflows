"""Pytest configuration and shared fixtures for ndev-workflows tests."""

from __future__ import annotations

import numpy as np
import pytest

from ndev_workflows import Workflow


@pytest.fixture
def empty_workflow() -> Workflow:
    """Create an empty workflow."""
    return Workflow()


@pytest.fixture
def sample_image() -> np.ndarray:
    """Create a sample 2D image for testing."""
    return np.random.randint(0, 255, (64, 64), dtype=np.uint8)


@pytest.fixture
def simple_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a simple workflow with one processing step."""

    def add_value(image: np.ndarray, value: int = 10) -> np.ndarray:
        return image + value

    w = Workflow()
    w.set('input', sample_image)
    w.set('output', add_value, 'input', value=20)
    return w


@pytest.fixture
def chain_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a workflow with a chain of processing steps."""

    def multiply(image: np.ndarray, factor: float = 2.0) -> np.ndarray:
        return image * factor

    def add(image: np.ndarray, value: int = 10) -> np.ndarray:
        return image + value

    w = Workflow()
    w.set('input', sample_image)
    w.set('multiplied', multiply, 'input', factor=2.0)
    w.set('added', add, 'multiplied', value=5)
    return w


@pytest.fixture
def branching_workflow(sample_image: np.ndarray) -> Workflow:
    """Create a workflow with branching (one input, multiple outputs)."""

    def blur(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
        from scipy.ndimage import gaussian_filter

        return gaussian_filter(image.astype(float), sigma=sigma)

    def threshold(image: np.ndarray, thresh: float = 128.0) -> np.ndarray:
        return (image > thresh).astype(np.uint8)

    w = Workflow()
    w.set('input', sample_image)
    w.set('blurred_1', blur, 'input', sigma=1.0)
    w.set('blurred_2', blur, 'input', sigma=2.0)
    w.set('binary', threshold, 'blurred_1', thresh=100.0)
    return w
