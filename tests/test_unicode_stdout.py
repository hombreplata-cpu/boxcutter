"""
REG-003 regression: scripts that print user-supplied audio metadata must not
crash on combining diacritics or other non-cp1252 chars. The fix is the
configure_io() helper in scripts/utils.py + the launcher's belt reconfigure.
"""

import io
import sys

from utils import configure_io


def test_configure_io_makes_stdout_replace_unencodable_chars(monkeypatch):
    # Simulate Windows cp1252 stdout: a TextIOWrapper that raises on ̂.
    raw = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)

    configure_io()

    # After configure_io, stdout should accept a combining circumflex without
    # raising (encoded as UTF-8 OR replaced — either is fine; what matters is
    # no UnicodeEncodeError reaches the caller).
    sys.stdout.write("track title with ̂ combining circumflex\n")
    sys.stdout.flush()


def test_configure_io_is_idempotent():
    # Calling twice in a row must not raise even if streams are already utf-8.
    configure_io()
    configure_io()


def test_configure_io_handles_detached_stream(monkeypatch):
    # Some test harnesses replace stdout with an object that has no reconfigure.
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    configure_io()  # must not raise
