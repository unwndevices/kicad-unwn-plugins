"""Shared pytest fixtures.

GUI tests need a ``QApplication`` but no real display, so we force Qt's
``offscreen`` platform before PySide6 is imported anywhere. The ``qapp`` fixture
is opt-in: tests that don't request it stay PySide6-free.
"""

from __future__ import annotations

import os

import pytest

# Must be set before the first PySide6 import; importing it here is harmless for
# the non-GUI tests (they simply never create widgets).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """A single process-wide QApplication for the GUI tests."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
