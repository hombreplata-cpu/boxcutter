"""
Tests for the remaining four api_run routes in app.py.

Covers (regression guards):
- cleanup: --scan-root required; --delete-dir/--exclude forwarded; --db-path passed
- strip_comments: dirs are positional; --write added when not dry-run;
  --db-path is NEVER included (PR #53 regression guard);
  strip_comments succeeds even when db_path is not configured
- fix_metadata: --db-path passed; 400 when db_path absent; --ids forwarded
- add_new: --watch-dir and --playlist-id required; --db-path passed
"""

from unittest.mock import patch

from helpers import make_proc_mock, run_sse

# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup_passes_scan_root(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/cleanup", {"scan_root": str(tmp_path), "dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--scan-root" in cmd
    assert str(tmp_path) in cmd


def test_cleanup_passes_delete_dir_when_set(flask_client, tmp_path):
    delete_dir = str(tmp_path / "TRASH")
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(
            flask_client,
            "/api/run/cleanup",
            {"scan_root": str(tmp_path), "delete_dir": delete_dir, "dry_run": "1"},
        )
    cmd = mock_popen.call_args[0][0]
    assert "--delete-dir" in cmd
    assert delete_dir in cmd


def test_cleanup_omits_delete_dir_when_blank_and_not_in_config(flask_client_no_paths, tmp_path):
    """--delete-dir absent from cmd when neither the param nor the config supplies one."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(
            flask_client_no_paths,
            "/api/run/cleanup",
            {"scan_root": str(tmp_path), "delete_dir": "", "dry_run": "1"},
        )
    cmd = mock_popen.call_args[0][0]
    assert "--delete-dir" not in cmd


def test_cleanup_passes_exclude_when_set(flask_client, tmp_path):
    exclude = str(tmp_path / "skip")
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(
            flask_client,
            "/api/run/cleanup",
            {"scan_root": str(tmp_path), "exclude": exclude, "dry_run": "1"},
        )
    cmd = mock_popen.call_args[0][0]
    assert "--exclude" in cmd
    assert exclude in cmd


def test_cleanup_passes_db_path(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/cleanup", {"scan_root": str(tmp_path), "dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--db-path" in cmd


def test_cleanup_missing_scan_root_returns_400(flask_client_no_paths):
    """400 when scan_root is absent and no music_root fallback is configured."""
    resp = flask_client_no_paths.get("/api/run/cleanup", query_string={"dry_run": "1"})
    assert resp.status_code == 400


def test_cleanup_missing_db_path_returns_400(flask_client_no_db, tmp_path):
    resp = flask_client_no_db.get(
        "/api/run/cleanup", query_string={"scan_root": str(tmp_path), "dry_run": "1"}
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# strip_comments
# ---------------------------------------------------------------------------


def test_strip_comments_passes_dir1(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/strip_comments", {"dir1": str(tmp_path)})
    cmd = mock_popen.call_args[0][0]
    assert str(tmp_path) in cmd


def test_strip_comments_db_path_never_in_cmd(flask_client, tmp_path):
    """Regression: strip_comment_urls.py does not accept --db-path (PR #53)."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/strip_comments", {"dir1": str(tmp_path)})
    cmd = mock_popen.call_args[0][0]
    assert "--db-path" not in cmd


def test_strip_comments_write_flag_added_when_not_dry_run(flask_client, tmp_path):
    """--write is appended when dry_run param is absent/0."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/strip_comments", {"dir1": str(tmp_path), "dry_run": "0"})
    cmd = mock_popen.call_args[0][0]
    assert "--write" in cmd


def test_strip_comments_no_write_flag_when_dry_run(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/strip_comments", {"dir1": str(tmp_path), "dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--write" not in cmd


def test_strip_comments_works_without_db_path_configured(flask_client_no_db, tmp_path):
    """strip_comments must NOT return 400 when db_path is missing — it doesn't need it."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        resp = run_sse(flask_client_no_db, "/api/run/strip_comments", {"dir1": str(tmp_path)})
    assert resp.status_code == 200


def test_strip_comments_missing_dir_returns_400(flask_client_no_paths):
    """400 when no dir param is supplied and music_root config is empty."""
    resp = flask_client_no_paths.get("/api/run/strip_comments", query_string={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# fix_metadata
# ---------------------------------------------------------------------------


def test_fix_metadata_passes_db_path(flask_client):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/fix_metadata", {"dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--db-path" in cmd


def test_fix_metadata_missing_db_path_returns_400(flask_client_no_db):
    resp = flask_client_no_db.get("/api/run/fix_metadata", query_string={"dry_run": "1"})
    assert resp.status_code == 400


def test_fix_metadata_passes_ids_when_set(flask_client):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/fix_metadata", {"ids": "1,2,3", "dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--ids" in cmd
    assert cmd[cmd.index("--ids") + 1] == "1,2,3"


def test_fix_metadata_omits_ids_when_blank(flask_client):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(flask_client, "/api/run/fix_metadata", {"ids": "", "dry_run": "1"})
    cmd = mock_popen.call_args[0][0]
    assert "--ids" not in cmd


# ---------------------------------------------------------------------------
# add_new
# ---------------------------------------------------------------------------


def test_add_new_passes_watch_dir_and_playlist_id(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(
            flask_client,
            "/api/run/add_new",
            {"watch_dir": str(tmp_path), "playlist_id": "42", "dry_run": "1"},
        )
    cmd = mock_popen.call_args[0][0]
    assert "--watch-dir" in cmd
    assert str(tmp_path) in cmd
    assert "--playlist-id" in cmd
    assert cmd[cmd.index("--playlist-id") + 1] == "42"


def test_add_new_missing_watch_dir_returns_400(flask_client_no_paths):
    """400 when watch_dir is absent and no watch_dir fallback is configured."""
    resp = flask_client_no_paths.get("/api/run/add_new", query_string={"playlist_id": "42"})
    assert resp.status_code == 400


def test_add_new_missing_playlist_id_returns_400(flask_client, tmp_path):
    resp = flask_client.get("/api/run/add_new", query_string={"watch_dir": str(tmp_path)})
    assert resp.status_code == 400


def test_add_new_missing_db_path_returns_400(flask_client_no_db, tmp_path):
    resp = flask_client_no_db.get(
        "/api/run/add_new",
        query_string={"watch_dir": str(tmp_path), "playlist_id": "42"},
    )
    assert resp.status_code == 400


def test_add_new_passes_db_path(flask_client, tmp_path):
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = make_proc_mock()
        run_sse(
            flask_client,
            "/api/run/add_new",
            {"watch_dir": str(tmp_path), "playlist_id": "42", "dry_run": "1"},
        )
    cmd = mock_popen.call_args[0][0]
    assert "--db-path" in cmd
