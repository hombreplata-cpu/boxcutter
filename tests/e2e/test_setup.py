"""
E2E: Setup page — path saving persists across page reloads.

Catches the class of bug where POST /api/config appears to succeed
but the values are not written (or are written to the wrong file).
"""


def test_setup_saves_and_reloads_paths(page, live_server, tmp_path):
    fake_db = str(tmp_path / "master.db")
    fake_music = str(tmp_path / "Music")

    page.goto(f"{live_server}/setup")
    page.wait_for_load_state("load")

    # Fill in required fields
    page.locator("input[name='db_path']").fill(fake_db)
    page.locator("input[name='music_root']").fill(fake_music)

    # force=True bypasses Playwright's stability check, which can fail when
    # the rekordbox-status polling (every 2.5 s) causes DOM layout shifts.
    page.locator("button[type='submit']").click(force=True)

    # Should show the flash confirmation
    page.wait_for_selector(".flash", timeout=5000)
    assert "saved" in page.locator(".flash").inner_text().lower()

    # Reload the setup page and verify values stuck
    page.goto(f"{live_server}/setup")
    saved_db = page.locator("input[name='db_path']").input_value()
    saved_music = page.locator("input[name='music_root']").input_value()

    assert saved_db == fake_db, f"db_path not persisted — got {saved_db!r}"
    assert saved_music == fake_music, f"music_root not persisted — got {saved_music!r}"
