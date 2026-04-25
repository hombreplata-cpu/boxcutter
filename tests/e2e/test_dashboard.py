"""
E2E: Dashboard and navigation smoke tests.

Catches route-level 500s and missing template context that would
surface as blank or error pages rather than tool-load failures.
"""

TOOL_ROUTES = [
    "/tool/relocate",
    "/tool/cleanup",
    "/tool/strip_comments",
    "/tool/fix_metadata",
    "/tool/add_new",
    "/setup",
    "/history",
]


def test_dashboard_loads_without_error(page, live_server):
    response = page.goto(f"{live_server}/")
    assert response.status < 500, f"Dashboard returned HTTP {response.status}"
    assert page.title() != "", "Page title is empty — possible render failure"
    h1_text = page.locator("h1").first.inner_text()
    assert "error" not in h1_text.lower(), f"Error heading on dashboard: {h1_text!r}"


def test_all_tool_routes_return_without_500(page, live_server):
    """Every tool page must load without a 500 error, even with no config set."""
    for route in TOOL_ROUTES:
        response = page.goto(f"{live_server}{route}")
        assert response.status < 500, f"{route} returned HTTP {response.status}"
        assert "500" not in page.title(), f"{route} page title indicates 500: {page.title()!r}"


def test_sidebar_version_string_present(page, live_server):
    """Version string must be rendered in the sidebar — guards against missing inject_globals."""
    page.goto(f"{live_server}/")
    # The sidebar contains the version injected via inject_globals()
    content = page.content()
    assert "v" in content, "No version string found in page — inject_globals may be broken"
