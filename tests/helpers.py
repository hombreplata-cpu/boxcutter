"""Shared test utilities — imported by conftest.py and individual test modules."""

from unittest.mock import MagicMock


def make_proc_mock():
    """Return a mock Popen process whose stdout terminates immediately (exit 0)."""
    proc = MagicMock()
    proc.stdout.readline.return_value = ""
    proc.stdout.close = MagicMock()
    proc.wait = MagicMock(return_value=0)
    proc.returncode = 0
    return proc


def run_sse(client, url, query_string):
    """Issue a GET and drain the SSE stream so Popen is actually invoked."""
    resp = client.get(url, query_string=query_string)
    _ = resp.get_data()
    return resp
