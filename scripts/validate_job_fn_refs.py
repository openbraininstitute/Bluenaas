#!/usr/bin/env python3
"""
Script to validate that all JobFn enum values reference actual module functions.
"""

import importlib
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.job import JobFn


def validate_job_fn() -> bool:
    """Validate all JobFn enum values reference actual functions."""
    errors = []

    for job_fn in JobFn:
        module_path, function_name = job_fn.value.rsplit(".", 1)

        try:
            # Import the module
            module = importlib.import_module(module_path)

            # Check if function exists
            if not hasattr(module, function_name):
                errors.append(f"Function '{function_name}' not found in module '{module_path}'")
                continue

            # Verify it's callable
            func = getattr(module, function_name)
            if not callable(func):
                errors.append(f"'{function_name}' in module '{module_path}' is not callable")

        except ImportError as e:
            errors.append(f"Could not import module '{module_path}': {e}")

    if errors:
        print("JobFn validation errors found:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print(f"✓ All {len(JobFn)} JobFn references are valid")
        return True


if __name__ == "__main__":
    success = validate_job_fn()
    sys.exit(0 if success else 1)
