"""Exercise the actual browser synchronizer without a browser/network dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_client_preferences():
    if not shutil.which('node'):
        pytest.skip('Node is needed for isolated JavaScript checks')
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', 'tests/js/preferences.test.cjs'], cwd=root, check=True, timeout=15)
