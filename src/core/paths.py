"""Shared path predicates for the pipeline."""

# Files the fixer has already written end with this.
FIXED_SUFFIX = "_fixed.py"


def is_fixed_output(file_path: str) -> bool:
    """True if `file_path` is one of our own `_fixed.py` outputs."""
    return file_path.endswith(FIXED_SUFFIX)
