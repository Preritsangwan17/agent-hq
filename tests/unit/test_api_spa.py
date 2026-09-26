"""SPA serving edge cases (CONTRACT §1): client-side routes fall back to index.html, missing files do not."""
from __future__ import annotations


def _dist(hq_env):
    dist = hq_env.root / "web-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    return dist


def test_client_routes_fall_back_to_index(authed, hq_env):
    _dist(hq_env)
    for path in ("/", "/pipeline", "/o/01M3F3PRVV2ABT7V1XG0VQ455V", "/agents", "/login?next=/pipeline"):
        r = authed.get(path)
        assert r.status_code == 200 and r.text == "<html>app</html>", path
        assert r.headers["cache-control"] == "no-cache"


def test_existing_files_are_served_with_cache_headers(authed, hq_env):
    _dist(hq_env)
    r = authed.get("/assets/index-abc123.js")
    assert r.status_code == 200 and r.text == "console.log(1)"
    assert "immutable" in r.headers["cache-control"]
    r = authed.get("/favicon.svg")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_missing_static_files_404_instead_of_html(authed, hq_env):
    """A tab still holding an old bundle name after a rebuild must get a 404, not index.html served as JS."""
    _dist(hq_env)
    for path in ("/assets/index-OLDHASH.js", "/assets/whatever", "/robots.txt", "/app.css", "/logo.PNG"):
        r = authed.get(path)
        assert r.status_code == 404, path
        assert "<html>" not in r.text


def test_api_paths_never_fall_back(authed, hq_env):
    _dist(hq_env)
    assert authed.get("/api/nope").status_code == 404
    assert authed.get("/api").json() == {"error": "not found"}
