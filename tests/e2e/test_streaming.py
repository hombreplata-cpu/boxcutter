"""
E2E: SSE streaming — strip_comments dry run on an empty directory.

Catches the class of bug where the SSE connection opens but the browser
console never updates, or the Done sentinel is never delivered.

strip_comments needs no DB, so it works with a bare config.
"""


def test_strip_comments_streams_output_and_completes(page, live_server, tmp_path):
    page.goto(f"{live_server}/tool/strip_comments")
    page.wait_for_load_state("load")

    # Point at an empty temp directory — script will scan 0 files and exit 0
    page.locator("#dir1").fill(str(tmp_path))

    # force=True bypasses stability check — rekordbox-status polling causes
    # DOM layout shifts that would otherwise make the click time out.
    page.locator("button.btn-secondary").click(force=True)

    # Wait for the status label to reach 'Done' (max 30 s)
    page.wait_for_function(
        "document.getElementById('status').textContent === 'Done'",
        timeout=30000,
    )

    assert page.locator("#status").inner_text() == "Done"

    # Crash banner must not be present
    assert (
        page.locator("#crash-banner").count() == 0
    ), "Crash banner appeared — script exited non-zero"


def test_strip_comments_sse_console_receives_output(page, live_server, tmp_path):
    """Console div must contain at least one line after a dry run."""
    page.goto(f"{live_server}/tool/strip_comments")
    page.wait_for_load_state("load")
    page.locator("#dir1").fill(str(tmp_path))
    page.locator("button.btn-secondary").click(force=True)

    # Wait for Done
    page.wait_for_function(
        "document.getElementById('status').textContent === 'Done'",
        timeout=30000,
    )

    # Console may be auto-collapsed after Done — check innerHTML regardless
    console_html = page.locator("#console").inner_html()
    assert console_html.strip() != "", "Console div is empty — no SSE output was received"
