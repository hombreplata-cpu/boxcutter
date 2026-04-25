"""
E2E: Setup page — path saving persists across page reloads.

Catches the class of bug where POST /api/config appears to succeed
but the values are not written (or are written to the wrong file).
"""


def test_setup_saves_and_reloads_paths(page, live_server, tmp_path):
    fake_db = str(tmp_path / "master.db")
    fake_music = str(tmp_path / "Music")

    # --- Save ---
    page.goto(f"{live_server}/setup")
    page.wait_for_load_state("load")

    page.locator("input[name='db_path']").fill(fake_db)
    page.locator("input[name='music_root']").fill(fake_music)

    # expect_navigation() waits for the POST response to arrive before we
    # issue the next goto, preventing "navigation interrupted by another
    # navigation" errors when requestSubmit fires a redirect.
    with page.expect_navigation():
        page.evaluate("document.querySelector('form').requestSubmit()")

    # --- Reload and verify values persisted ---
    page.goto(f"{live_server}/setup")
    page.wait_for_load_state("load")

    saved_db = page.locator("input[name='db_path']").input_value()
    saved_music = page.locator("input[name='music_root']").input_value()

    assert saved_db == fake_db, f"db_path not persisted — got {saved_db!r}"
    assert saved_music == fake_music, f"music_root not persisted — got {saved_music!r}"
