"""
Bundle UI contract — Playwright tests against the started bundle artifact.

These tests catch regressions that escape source-tree pytest because they
only manifest in the rendered DOM of a running Flask process. Specifically:

- REG-002 class: DOM forms posting to state-mutating routes without a
  csrf_token field (bypasses the window.fetch monkey-patch).
- 403 surprises on routes the user actually clicks (the gate may be too
  aggressive on a route a test never exercised).
- Missing meta[name='bc-token'] on a page (would make every JS fetch from
  that page silently 403).
- Pages that 500 because a template variable went missing.

Run modes
---------
    # Source mode (validates the test logic itself):
    pytest tests/bundle/ui/

    # Bundle mode (the real test, used in release gate):
    BOXCUTTER_BUNDLE_EXE=/path/to/BoxCutter.exe pytest tests/bundle/ui/

Why parametrization is tight
----------------------------
Earlier iterations parametrised broadly over every primary page, which
flooded the dev Flask server with concurrent rekordbox_status polls
(subprocess.run per request → backed up the worker). The tests that
matter are: every primary page renders with the bc-token meta tag, and
every state-mutating DOM form carries a matching csrf_token. We get
that with a small, reliable set rather than parametrising over every
nav surface.
"""

from __future__ import annotations

# Pages that MUST have a meta[name='bc-token'] for the fetch monkey-patch
# to function. If this meta tag is missing on any of these, every state-
# mutating fetch from that page silently 403s.
TOKEN_BEARING_PAGES = [
    "/",
    "/setup",
    "/tool/relocate",
    "/tool/strip_comments",
    "/history",
    "/backup_cleaner",
]


def _meta_token(page) -> str | None:
    return page.evaluate(
        "() => document.querySelector('meta[name=\"bc-token\"]')?.content || null"
    )


def test_homepage_renders_with_csrf_meta(page, live_server):
    response = page.goto(live_server + "/", wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    body = page.content()
    assert "Traceback" not in body
    assert "Internal Server Error" not in body
    token = _meta_token(page)
    assert token and len(token) > 16, f"missing/short bc-token on /: {token!r}"


def test_setup_form_carries_csrf_token_matching_meta(page, live_server):
    """The setup form is the most-used DOM form. Both source and bundle modes
    render it; both must carry a csrf_token matching the meta tag."""
    page.goto(live_server + "/setup", wait_until="domcontentloaded")
    meta_token = _meta_token(page)
    assert meta_token, "meta token missing on /setup"
    form_token = page.locator('form input[name="csrf_token"]').first.get_attribute("value")
    assert form_token, "setup form missing csrf_token hidden input"
    assert form_token == meta_token, f"setup csrf_token {form_token!r} != meta {meta_token!r}"


def test_quit_form_carries_csrf_token_when_frozen(page, live_server, is_frozen_target):
    """REG-002 detector. The Quit App form renders only when is_frozen, so:
    - Source mode: assert the form is absent (would mean the template guard broke).
    - Bundle mode: assert the form is present AND has csrf_token matching meta.
    """
    page.goto(live_server + "/", wait_until="domcontentloaded")
    form_count = page.locator("#quit-form").count()

    if not is_frozen_target:
        assert form_count == 0, (
            "Quit form rendered in source mode — is_frozen template guard broken"
        )
        return

    assert form_count == 1, "Quit form not rendered in frozen bundle"
    meta_token = _meta_token(page)
    form_token = page.locator('#quit-form input[name="csrf_token"]').get_attribute("value")
    assert form_token, (
        "REG-002: Quit form missing csrf_token hidden input — "
        "DOM form submission to /shutdown will 403"
    )
    assert form_token == meta_token, (
        f"REG-002: Quit form token {form_token!r} != meta token {meta_token!r}"
    )


def test_primary_pages_load_with_token_meta(page, live_server):
    """Spot-check the canonical token-bearing pages. One test that visits all
    of them rather than 6 parametrised tests, to keep total page-creation
    overhead bounded and avoid flaky cumulative state."""
    failures: list[str] = []
    for path in TOKEN_BEARING_PAGES:
        try:
            response = page.goto(live_server + path, wait_until="domcontentloaded", timeout=10000)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: navigation failed — {exc}")
            continue
        if response is None or response.status != 200:
            status = response.status if response else "no-response"
            failures.append(f"{path}: status={status}")
            continue
        body = page.content()
        if "Traceback" in body:
            failures.append(f"{path}: Python traceback in body")
            continue
        token = _meta_token(page)
        if not token:
            failures.append(f"{path}: missing bc-token meta tag")
    assert not failures, "\n  - " + "\n  - ".join(failures)
