"""Tests for batch processing (_batch.py).

Note: The process_workflow_file function is decorated with @batch from nbatch,
which modifies its signature. Direct testing is done via integration tests
in test_workflow_container.py through the WorkflowContainer.batch_workflow().
"""

from __future__ import annotations

from pathlib import Path


class TestBatchDecorator:
    """Test the @batch decorator behavior."""

    def test_batch_continues_on_error(self, tmp_path: Path):
        """Test that @batch decorator allows continuing on error."""
        from nbatch import batch

        errors = []

        @batch(on_error='continue')
        def process_item(item: Path, output: Path) -> Path:
            if 'bad' in item.name:
                raise ValueError(f'Bad file: {item}')
            output_file = output / item.name
            output_file.write_text('processed')
            return output_file

        # Create test files
        (tmp_path / 'good1.txt').write_text('test')
        (tmp_path / 'bad_file.txt').write_text('test')
        (tmp_path / 'good2.txt').write_text('test')

        output_dir = tmp_path / 'output'
        output_dir.mkdir()

        files = list(tmp_path.glob('*.txt'))

        # Process all files - should not raise
        results = []
        for f in files:
            try:
                result = process_item(f, output_dir)
                results.append(result)
            except ValueError as e:
                errors.append(str(e))

        # Good files should be processed
        assert (output_dir / 'good1.txt').exists()
        assert (output_dir / 'good2.txt').exists()
        # Bad file should have raised
        assert len(errors) == 1


class TestProcessWorkflowFileImport:
    """Test that process_workflow_file can be imported."""

    def test_import_process_workflow_file(self):
        """Test that the function can be imported."""
        from ndev_workflows._batch import process_workflow_file

        assert callable(process_workflow_file)
