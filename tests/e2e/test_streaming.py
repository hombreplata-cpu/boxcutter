"""
E2E: SSE streaming — strip_comments dry run on an empty directory.

Catches the class of bug where the SSE connection opens but the browser
console never updates, or the Done sentinel is never delivered.

strip_comments needs no DB, so it works with a bare config.
"""


def _run_dry(page, live_server, tmp_path):
    """Navigate to strip_comments, set dir, start a dry run, wait for Done."""
    page.goto(f"{live_server}/tool/strip_comments")
    page.wait_for_load_state("load")
    page.locator("#dir1").fill(str(tmp_path))
    # Invoke the page-level run() function directly to bypass Playwright's
    # click stability checks (the rekordbox-status poll causes layout shifts).
    page.evaluate("run(true)")
    # Wait for the #status element to receive class 'done' — set atomically
    # by the SSE %%DONE%% handler alongside textContent = 'Done'.
    page.wait_for_selector("#status.done", timeout=30000)


def test_strip_comments_streams_output_and_completes(page, live_server, tmp_path):
    _run_dry(page, live_server, tmp_path)

    assert page.locator("#status").inner_text() == "Done"
    assert page.locator("#crash-banner").count() == 0, (
        "Crash banner appeared — script exited non-zero"
    )


def test_strip_comments_sse_console_receives_output(page, live_server, tmp_path):
    """Console div must contain at least one line after a dry run."""
    _run_dry(page, live_server, tmp_path)

    # Console may be auto-collapsed after Done — check innerHTML regardless
    console_html = page.locator("#console").inner_html()
    assert console_html.strip() != "", "Console div is empty — no SSE output was received"
