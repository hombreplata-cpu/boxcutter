# PLAN 012 — Stream Rekordbox

**Branch:** `feature/stream-rekordbox` off `main`
**Closes:** PR #34 (feature/mytag-manager — superseded)

---

## 1. Rename

- "Remote Listener" → "Stream Rekordbox" in sidebar, page titles, and dashboard

## 2. Remove standalone My Tag Manager

- Delete `templates/mytag.html`
- Remove `/tool/mytag` route from `app.py`
- Remove My Tag Manager card from `dashboard.html`
- Remove `mytag` from `TOOL_LABELS` in `app.py`

## 3. Dedicated Restore page

- New `/restore` route + `restore.html` in sidebar
- Consolidate the "Something broke?" collapsible panels from all tool pages into one place
- Replace per-page panels with a simple "→ Restore a backup" link

## 4. Mobile action sheet (`···` on each track row in `listen.html`)

- Tap track row → plays immediately (existing behaviour unchanged)
- Tap `···` → action sheet slides up from bottom with three sections:
  - **Rate** — 5-star row; tap to set, tap same star to clear
  - **Tag** — scrollable My Tags list, current tags checked, tap to toggle
  - **Add to Playlist** — playlist list, already-added checked, tap to toggle

## 5. New API endpoints

| Method   | Path                                             | Purpose                                      |
|----------|--------------------------------------------------|----------------------------------------------|
| `POST`   | `/api/tracks/<id>/rating`                        | Set 0–5 star rating (→ 0/51/102/153/204/255) |
| `GET`    | `/api/tracks/<id>/mytags`                        | Fetch assigned tags                          |
| `POST`   | `/api/tracks/<id>/mytags`                        | Assign a tag                                 |
| `DELETE` | `/api/tracks/<id>/mytags/<assignment_id>`        | Remove a tag                                 |
| `GET`    | `/api/mytags`                                    | List all My Tag groups + children            |
| `GET`    | `/api/tracks/<id>/playlists`                     | Playlists the track belongs to               |
| `POST`   | `/api/tracks/<id>/playlists/<playlist_id>`       | Add track to playlist                        |
| `DELETE` | `/api/tracks/<id>/playlists/<playlist_id>`       | Remove track from playlist                   |

## 6. Lazy backup

- No backup on app open
- On first write in a streaming session (rate/tag/playlist): back up `master.db` first, then apply the write
- Subsequent writes in the same session skip the backup (already exists)
- Session resets on server restart or 2-hour idle
- Backup naming: `master_backup_stream_YYYYMMDD_HHMMSS.db`
- Backup location: `<pioneer-rekordbox-dir>/rekordbocks-backups/`
