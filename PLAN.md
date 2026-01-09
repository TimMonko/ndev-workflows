# ndev-workflows Architecture Implementation Plan

**Date**: 2026-01-09
**Status**: Design Phase - Ready for Implementation

---

## Executive Summary

ndev-workflows aims to be a **safe, backwards-compatible evolution** of napari-workflows that supports:
- **magicgui-based widgets** (Layer → LayerDataTuple pattern)
- **Data → Data functions** (pyclesperanto, nsbatwm pattern)
- **Mixed workflows** combining both patterns
- **Safe YAML** (no code execution via Python object tags)
- **Full type preservation** for roundtrip fidelity and code generation

**Core Decision**: Keep **dask as the execution engine** but add **resolution layers** before and after execution to handle Layer/LayerDataTuple/data conversions.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    ndev-workflows Data Flow                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. WORKFLOW CONSTRUCTION (Workflow.set)                        │
│     ├── Detect MagicFactory → unwrap to underlying function     │
│     ├── Attach _ndev_parent_factory for type extraction         │
│     └── Store as dask-compatible task tuple                     │
│                                                                  │
│  2. YAML SERIALIZATION (_spec.py)                               │
│     ├── Extract full type strings from functions                │
│     ├── Store as comments in YAML (human-readable)              │
│     ├── Detect roots (graph traversal, not string matching)     │
│     └── Detect leaves (tasks with no followers)                 │
│                                                                  │
│  3. INPUT RESOLUTION (Workflow.get → _resolution.py)            │
│     ├── String layer names → resolve via viewer or layers dict  │
│     ├── Check function signatures for Layer vs Data params      │
│     ├── LayerDataTuple → unwrap to data or WorkflowLayer        │
│     └── Wrap data as WorkflowLayer if function expects Layer    │
│                                                                  │
│  4. DASK EXECUTION                                               │
│     └── Standard dask.get() on resolved task graph              │
│                                                                  │
│  5. OUTPUT RESOLUTION (NEW - after each task)                   │
│     ├── Task returns LayerDataTuple → convert to WorkflowLayer  │
│     ├── Task returns list[LayerDataTuple] → split into subtasks │
│     └── Store normalized outputs for next task consumption      │
│                                                                  │
│  6. FINAL RETURN                                                 │
│     └── Return data, WorkflowLayer, or LayerDataTuple as needed │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Architectural Decisions

### 1. Dask is the Right Foundation ✅

**Rationale**:
- Battle-tested execution engine
- Native support for multiple inputs: `(func, 'arg1', 'arg2', 'arg3')`
- Lazy evaluation and potential parallelization
- Familiar to scientific Python users

**Limitation Acknowledged**:
- Only resolves **positional args** (not kwargs in partials)
- No native multi-output support (requires wrapper pattern)
- No type awareness (we handle this in resolution layers)

**Solution**: Keep dask for execution, add manual resolution for types and kwargs (already implemented).

---

### 2. WorkflowLayer (formerly FakeLayer) as Universal Interface ✅

**Purpose**: Bridge between Layer objects, LayerDataTuple format, and raw data.

**Design**:
```python
class WorkflowLayer:
    """Universal layer-like interface for workflow intermediate data.

    Provides a consistent API regardless of whether data originated from:
    - A napari Layer object
    - A LayerDataTuple (data, kwargs, layer_type)
    - Raw numpy array data
    """

    def __init__(self, data, name: str = 'unnamed', metadata: dict = None,
                 layer_type: str = 'image', scale=None):
        self.data = data
        self.name = name
        self.metadata = metadata or {}
        self._layer_type = layer_type
        self.scale = scale

    @classmethod
    def from_layer_data_tuple(cls, ldt: tuple) -> 'WorkflowLayer':
        """Create from (data, kwargs, layer_type) format."""
        data, kwargs, layer_type = ldt
        return cls(
            data=data,
            name=kwargs.get('name', 'unnamed'),
            metadata=kwargs.get('metadata', {}),
            layer_type=layer_type,
            scale=kwargs.get('scale')
        )

    @classmethod
    def from_layer(cls, layer) -> 'WorkflowLayer':
        """Create from napari Layer object."""
        return cls(
            data=layer.data,
            name=layer.name,
            metadata=getattr(layer, 'metadata', {}),
            layer_type=layer.__class__.__name__.lower(),
            scale=getattr(layer, 'scale', None)
        )

    @classmethod
    def from_any(cls, value, name: str = None) -> 'WorkflowLayer':
        """Create from any supported format (auto-detect)."""
        # Already a layer-like object
        if hasattr(value, 'data') and hasattr(value, 'name'):
            return cls.from_layer(value)

        # LayerDataTuple format
        if is_layer_data_tuple(value):
            return cls.from_layer_data_tuple(value)

        # Raw data (numpy array)
        return cls(value, name or 'unnamed')

    def to_layer_data_tuple(self) -> tuple:
        """Convert to (data, kwargs, layer_type) format."""
        kwargs = {'name': self.name}
        if self.metadata:
            kwargs['metadata'] = self.metadata
        if self.scale is not None:
            kwargs['scale'] = self.scale
        return (self.data, kwargs, self._layer_type)
```

**Usage**: All intermediate workflow results stored as `WorkflowLayer`, providing `.data` for Data→Data functions and full layer interface for Layer→LayerDataTuple functions.

---

### 3. Root/Leaf Detection via Graph Traversal (napari-workflows pattern) ✅

**Current Problem**: Incorrectly treating ALL string parameters as inputs, including literal values.

**napari-workflows approach** (correct):
```python
# ROOTS: String parameters that DON'T match any task name
all_string_refs = {ref for task in tasks for ref in get_string_params(task)}
task_names = set(tasks.keys())
roots = all_string_refs - task_names  # External references

# LEAVES: Tasks that aren't referenced by any other task
all_referenced = {ref for task in tasks for ref in get_string_params(task)
                  if ref in task_names}
leaves = task_names - all_referenced  # No followers
```

**Implementation Location**: `_spec.py` in `workflow_to_spec_dict()`

**Key Insight**: Roots are "dangling references" - external data that must be provided at execution time. This naturally handles both layer names AND file paths.

---

### 4. Task Naming Strategy ✅

**Decision**: Task names are **always user-defined**, independent of layer names returned in LayerDataTuple.

**Rationale**:
- Dask graph traversal requires stable task names
- User defines workflow structure via task names
- Layer names (from LayerDataTuple `{'name': 'blurred'}`) are **metadata**, not task identifiers

**Example**:
```python
# User creates workflow
workflow.set("step1", gaussian_filter_widget, "input", sigma=2.0)
# Function returns: (data, {'name': 'input_gaussian_σ=2.0'}, 'image')

# Task name is "step1" (used in graph)
# Layer name is "input_gaussian_σ=2.0" (metadata for display)
```

**When creating layers in viewer**: Use the layer name from LayerDataTuple metadata, but track via task name internally.

---

### 5. Multi-Output Function Handling ⚠️

**Dask Limitation**: Cannot unpack tuples in task keys:
```python
# ❌ This does NOT work:
tasks = {('out1', 'out2'): (func_returns_two, 'input')}
```

**Solution Pattern - Wrapper Functions**:
```python
# Define indexer helpers
def get_item(sequence, index):
    """Extract item from sequence."""
    return sequence[index]

# Split multi-output into subtasks
tasks = {
    '_multi_temp': (func_returns_list, 'input'),  # Returns [ldt1, ldt2, ldt3]
    'output_0': (get_item, '_multi_temp', 0),
    'output_1': (get_item, '_multi_temp', 1),
    'output_2': (get_item, '_multi_temp', 2),
}
```

**When to Apply**:
- Detect functions with return type `list[napari.types.LayerDataTuple]`
- Automatically generate wrapper tasks with `_<name>_temp` and `<name>_0`, `<name>_1`, etc.
- OR: Document as "advanced usage" and let users handle manually

**Current Status**: nsbatwm has NO multi-output functions, so this is **low priority**. Implement only if needed.

---

### 6. Type Annotation Strategy ✅

**Store Full Type Strings in YAML Comments**:
```yaml
blurred:
  callable: skimage.filters.gaussian  # -> napari.types.ImageData
  params:
    arg0: input  # napari.types.ImageData
    sigma: 2.0  # builtins.float
```

**Why Full Types, Not Classifications**:
- Better roundtrip fidelity
- Enables code generation (can emit proper type hints)
- Validates types match when loading workflows
- Human-readable YAML
- Classifications can be derived: `classify_param_type("napari.types.ImageData") → "data"`

**Implementation**: Already complete in `extract_type_strings()` and `workflow_to_spec_dict()`.

---

## Implementation Checklist

### Phase 1: Core Fixes (High Priority)

- [x] **Rename FakeLayer → WorkflowLayer**
  - File: `_resolution.py`
  - Update all imports and references
  - Enhance with `.from_any()`, `.from_layer_data_tuple()`, `.to_layer_data_tuple()`

- [x] **Fix root/leaf detection**
  - File: `_spec.py`
  - Use graph traversal, not string type inspection
  - Roots = string refs not in task names
  - Leaves = tasks not referenced by others

- [ ] **Add output resolution layer**
  - File: `_resolution.py`
  - New function: `resolve_task_output(result, next_task_signature)`
  - If result is LayerDataTuple → convert to WorkflowLayer
  - If result is list[LayerDataTuple] → handle multi-output (or raise NotImplementedError)

- [ ] **Integrate output resolution in Workflow.get()**
  - File: `_workflow.py`
  - After each task execution, resolve output before storing in dask results
  - Pass next task's signature to determine expected format

### Phase 2: Enhancements (Medium Priority)

- [ ] **Improve WorkflowLayer with full Layer API**
  - Add properties: `.scale`, `.colormap`, `.metadata`, etc.
  - Ensure compatibility with functions expecting Layer attributes

- [ ] **Multi-output function support**
  - Detect `list[LayerDataTuple]` return types
  - Generate indexer wrapper tasks
  - Update YAML format to indicate multi-output split
  - OR: Document and defer to "advanced usage"

- [ ] **Better error messages**
  - When root is missing at execution time
  - When type mismatch occurs (expected Layer, got data)
  - When function returns unexpected format

### Phase 3: Testing & Documentation (Low Priority but Important)

- [ ] **Comprehensive test suite**
  - Test Data→Data functions (pyclesperanto style)
  - Test Layer→LayerDataTuple functions (napari-skimage style)
  - Test mixed workflows
  - Test multi-input functions
  - Test root/leaf detection edge cases

- [ ] **Update AGENTS.md**
  - Document WorkflowLayer as universal interface
  - Explain root/leaf detection strategy
  - Clarify task naming vs layer naming
  - Document multi-output limitation

- [ ] **User documentation**
  - How to write workflow-compatible functions
  - Best practices for function signatures
  - When to use Data→Data vs Layer→LayerDataTuple
  - Examples of complex workflows

---

## Function Pattern Support Matrix

| Pattern | Input Type | Output Type | Support Status | How It Works |
|---------|------------|-------------|----------------|--------------|
| **Data → Data** (nsbatwm) | `napari.types.ImageData` | `napari.types.ImageData` | ✅ Native | Direct pass-through |
| **Layer → LayerDataTuple** (napari-skimage) | `napari.layers.Image` | `LayerDataTuple` | ✅ Via WorkflowLayer | Wrap data as WorkflowLayer, unwrap LDT |
| **Layer → Data** | `napari.layers.Labels` | `np.ndarray` | ✅ Via WorkflowLayer | Wrap data, extract `.data` |
| **Data → LayerDataTuple** | `np.ndarray` | `LayerDataTuple` | ✅ Via unwrapping | Unwrap LDT to WorkflowLayer |
| **Multi-output** | Any | `list[LayerDataTuple]` | ⚠️ Wrapper needed | Use indexer tasks (dask limitation) |

---

## Comparison: napari-workflows vs ndev-workflows

| Feature | napari-workflows | ndev-workflows |
|---------|------------------|----------------|
| **Execution Engine** | dask | dask |
| **Function Pattern** | Data → Data only | Data → Data + Layer → LDT |
| **Type System** | None (assumes arrays) | Full type extraction + resolution |
| **YAML Format** | Unsafe Python tags | Safe YAML with module paths |
| **Root Detection** | Graph traversal | Graph traversal ✅ |
| **Leaf Detection** | Followers check | Followers check ✅ |
| **Kwargs Resolution** | Native dask (positional only) | Manual (in `_resolution.py`) |
| **LayerDataTuple** | Not handled | Automatic unwrapping |
| **Universal Interface** | None | WorkflowLayer |
| **Multi-output** | Not handled | Wrapper pattern (planned) |

---

## Open Questions / Decisions Needed

### 1. Multi-Output Auto-Split or Manual?

**Option A - Automatic**:
- Detect `list[LayerDataTuple]` return type
- Auto-generate `_temp`, `_0`, `_1`, `_2` subtasks
- Pros: Seamless user experience
- Cons: Complexity, unclear YAML representation

**Option B - Manual/Advanced**:
- Require users to handle multi-output explicitly
- Document wrapper pattern in advanced usage
- Pros: Simpler implementation
- Cons: Less user-friendly

**Recommendation**: Start with **Option B** (document as advanced), implement **Option A** if user demand exists.

---

### 2. WorkflowLayer Persistence in YAML?

Currently, intermediate results aren't saved to YAML. Should we support saving/loading workflows **with cached intermediate results** (for debugging/inspection)?

**Recommendation**: Defer to future enhancement. YAML represents the **workflow structure**, not execution state.

---

### 3. Viewer Requirement?

Should `Workflow.get()` require a viewer, or support layer dict?

**Current**: `viewer` is optional, layer dict can be passed as `layers` kwarg.

**Recommendation**: Keep optional, document both patterns.

---

## Migration Path from Current State

### Breaking Changes

1. **Rename**: `FakeLayer` → `WorkflowLayer` (internal only, no public API change)
2. **Input Detection**: YAML `inputs` list may change (now graph-based, not type-based)

### Non-Breaking

- Existing workflows should load correctly (backwards compatible YAML parsing)
- Type extraction enhancements are additive

### Testing Strategy

1. Load all existing test YAML files
2. Execute workflows with various function patterns
3. Verify roots/leaves detected correctly
4. Verify LayerDataTuple unwrapping works

---

## Success Criteria

✅ **Workflow is successful when**:

1. Can load and execute napari-workflows YAML files
2. Can execute workflows with nsbatwm functions (Data → Data)
3. Can execute workflows with napari-skimage functions (Layer → LDT)
4. Can execute mixed workflows
5. YAML roots/leaves correctly identified via graph traversal
6. Type comments preserved for all parameters and returns
7. WorkflowLayer seamlessly bridges Layer/LDT/data conversions

---

## Timeline Estimate

- **Phase 1** (Core Fixes): 1-2 days
- **Phase 2** (Enhancements): 2-3 days
- **Phase 3** (Testing & Docs): 2-3 days

**Total**: ~1 week for complete implementation and testing

---

## References

- [napari-workflows source](https://github.com/haesleinhuepf/napari-workflows)
- [Dask documentation](https://docs.dask.org/)
- [napari type annotations](https://napari.org/stable/plugins/guides.html#type-annotations)
- [magicgui signatures](https://pyapp-kit.github.io/magicgui/)

---

**Next Steps**: Begin Phase 1 implementation with FakeLayer → WorkflowLayer rename and root/leaf detection fix.
