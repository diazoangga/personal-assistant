"""Pytest configuration and shared fixtures."""

import os
import tempfile

import pytest


@pytest.fixture
def temp_file():
    """Create a temporary file that gets cleaned up."""
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def temp_dir():
    """Create a temporary directory that gets cleaned up."""
    import shutil
    
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)
