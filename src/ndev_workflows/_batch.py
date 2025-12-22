"""Batch-processing helpers for ndev-workflows."""

from __future__ import annotations

from pathlib import Path

from nbatch import batch


@batch(on_error='continue')
def process_workflow_file(
    image_file: Path,
    result_dir: Path,
    workflow_file: Path,
    root_index_list: list[int],
    task_names: list[str],
    keep_original_images: bool,
    root_list: list[str],
    squeezed_img_dims: str,
) -> Path:
    """Process a single image file through a workflow.

    Loads a fresh workflow instance per file for thread safety.

    Parameters
    ----------
    image_file : Path
        Path to the image file to process.
    result_dir : Path
        Directory to save results.
    workflow_file : Path
        Path to the workflow YAML file.
    root_index_list : list[int]
        Indices of channels to use as workflow roots.
    task_names : list[str]
        Names of workflow tasks to execute.
    keep_original_images : bool
        Whether to concatenate original images with results.
    root_list : list[str]
        Names of root channels (for output naming).
    squeezed_img_dims : str
        Squeezed dimension order of the image.

    Returns
    -------
    Path
        Path to the saved output file.
    """
    import dask.array as da
    import numpy as np
    from bioio.writers import OmeTiffWriter
    from bioio_base import transforms
    from ndevio import nImage

    from ._io import load_workflow
    from ._spec import ensure_runnable

    workflow = load_workflow(workflow_file, lazy=True)
    workflow = ensure_runnable(workflow)

    img = nImage(image_file)

    # Capture roots before modifying workflow (stable list of graph inputs)
    root_names = workflow.roots()

    root_stack = []
    for idx, root_index in enumerate(root_index_list):
        if 'S' in img.dims.order:
            root_img = img.get_image_data('TSZYX', S=root_index)
        else:
            root_img = img.get_image_data('TCZYX', C=root_index)

        root_stack.append(root_img)
        workflow.set(name=root_names[idx], func_or_data=np.squeeze(root_img))

    result = workflow.get(name=task_names)

    result_stack = np.asarray(result)
    result_stack = transforms.reshape_data(
        data=result_stack,
        given_dims='C' + squeezed_img_dims,
        return_dims='TCZYX',
    )

    if result_stack.dtype == np.int64:
        result_stack = result_stack.astype(np.int32)

    if keep_original_images:
        dask_images = da.concatenate(root_stack, axis=1)  # along "C"
        result_stack = da.concatenate([dask_images, result_stack], axis=1)
        result_names = root_list + task_names
    else:
        result_names = task_names

    output_path = result_dir / (image_file.stem + '.tiff')
    OmeTiffWriter.save(
        data=result_stack,
        uri=output_path,
        dim_order='TCZYX',
        channel_names=result_names,
        image_name=image_file.stem,
        physical_pixel_sizes=img.physical_pixel_sizes,
    )

    return output_path
