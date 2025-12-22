# ndev-workflows

[![License BSD-3](https://img.shields.io/pypi/l/ndev-workflows.svg?color=green)](https://github.com/ndev-kit/ndev-workflows/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/ndev-workflows.svg?color=green)](https://pypi.org/project/ndev-workflows)
[![Python Version](https://img.shields.io/pypi/pyversions/ndev-workflows.svg?color=green)](https://python.org)
[![tests](https://github.com/ndev-kit/ndev-workflows/workflows/tests/badge.svg)](https://github.com/ndev-kit/ndev-workflows/actions)
[![codecov](https://codecov.io/gh/ndev-kit/ndev-workflows/branch/main/graph/badge.svg)](https://codecov.io/gh/ndev-kit/ndev-workflows)
[![napari hub](https://img.shields.io/endpoint?url=https://api.napari-hub.org/shields/ndev-workflows)](https://napari-hub.org/plugins/ndev-workflows)
[![npe2](https://img.shields.io/badge/plugin-npe2-blue?link=https://napari.org/stable/plugins/index.html)](https://napari.org/stable/plugins/index.html)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-purple.json)](https://github.com/copier-org/copier)

**Reproducible processing workflows with napari**

A re-implementation of [napari-workflows](https://github.com/haesleinhuepf/napari-workflows) with backwards compatibility.

---

This [napari] plugin was generated with [copier] using the [napari-plugin-template] (2.0.1).

## What is ndev-workflows?

`ndev-workflows` is the workflow backend for napari image processing pipelines. It's a **drop-in replacement** for [napari-workflows](https://github.com/haesleinhuepf/napari-workflows) by Robert Haase, with these key improvements:

- **Safe YAML loading** — Uses `yaml.safe_load()` (no arbitrary code execution)
- **Backwards compatible** — Automatically loads and migrates legacy napari-workflows files, and detects missing dependencies
- **Same API** — Most code works without changes
- **Future-ready** — Designed for upcoming npe2 workflow contributions (WIP), without relying on npe1, napari-time-slicer, and napari-tools-menu for interactivity

---

## Installation

```bash
pip install ndev-workflows
```

If napari is not already installed, you can install `ndev-workflows` with napari and Qt via:

```bash
pip install "ndev-workflows[all]"
```

---

## Quick Start

```python
from ndev_workflows import Workflow, save_workflow, load_workflow
from skimage.filters import gaussian

# Create workflow
workflow = Workflow()
workflow.set("blurred", gaussian, "input_image", sigma=2.0)
workflow.set("input_image", my_image)

# Execute
result = workflow.get("blurred")

# Save
save_workflow("pipeline.yaml", workflow, name="My Pipeline")

# Load and reuse
loaded = load_workflow("pipeline.yaml")
loaded.set("input_image", new_image)
result = loaded.get("blurred")
```

---

## YAML Format

Saved workflows use a safe, human-readable format:

```yaml
name: Nucleus Segmentation
description: Gaussian blur and thresholding
modified: '2025-12-22'

inputs:
  - raw_image

outputs:
  - labels

tasks:
  blurred:
    function: skimage.filters.gaussian
    params:
      arg0: raw_image
      sigma: 2.0

  labels:
    function: skimage.measure.label
    params:
      arg0: blurred
```

**Key features:**

- No `!python/object` tags (safe to share)
- Functions imported by module path
- Params use `arg0`, `arg1`, etc. for positional args and keyword names for kwargs

**Legacy format**: Old napari-workflows YAML files are automatically detected and migrated when loaded.

---

## Important Notes

### Function Dependencies

⚠️ Workflows **don't bundle functions** — they only store module paths. Recipients need the same packages installed.

If loading fails with `WorkflowNotRunnableError`, install the missing package:

```bash
pip install scikit-image  # for skimage functions
pip install napari-segment-blobs-and-things-with-membranes  # for that plugin
```

### Lazy Loading

Inspect workflows without importing functions:

```python
workflow = load_workflow("untrusted.yaml", lazy=True)
print(workflow.tasks)  # Safe - doesn't execute
```

---

## Integration

### Front-end plugins for interactive workflow building:

- [napari-assistant](https://github.com/haesleinhuepf/napari-assistant)
- [napari-workflow-optimizer](https://github.com/haesleinhuepf/napari-workflow-optimizer)
- [napari-workflow-inspector](https://github.com/haesleinhuepf/napari-workflow-inspector)

### Works with processing plugins:

- [napari-segment-blobs-and-things-with-membranes](https://www.napari-hub.org/plugins/napari-segment-blobs-and-things-with-membranes)
- [pyclesperanto](https://github.com/clesperanto/napari_pyclesperanto_assistant)
- And more!

---

## Contributing

```bash
git clone https://github.com/ndev-kit/ndev-workflows.git
cd ndev-workflows
uv venv
.venv\Scripts\activate
uv pip install -e . --group dev
pytest
```

---

## License

Distributed under the terms of the [BSD-3] license,
"ndev-workflows" is free and open source software
Fork of [napari-workflows](https://github.com/haesleinhuepf/napari-workflows) by Robert Haase.

---

## Issues

[File an issue](https://github.com/ndev-kit/ndev-workflows/issues) with your environment details, YAML file (if applicable), and error messages.
