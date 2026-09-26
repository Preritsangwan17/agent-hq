"""Serve the built SPA from web/dist with index.html fallback for client-side routes."""
from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from hq import settings

PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Agent HQ</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{background:#070B14;color:#E2E8F0;font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;
min-height:100vh;margin:0}main{max-width:32rem;padding:2rem}code{background:#ffffff14;padding:.1rem .4rem;
border-radius:4px}</style></head><body><main><h1>Agent HQ API is running</h1>
<p>The web UI has not been built yet. Run <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>
(or <code>./start.sh</code>) and reload.</p></main></body></html>"""


def mount_spa(app: FastAPI) -> None:
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        dist = settings.WEB_DIST.resolve()
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(PLACEHOLDER)
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and dist in candidate.parents:
                immutable = "/assets/" in f"/{candidate.relative_to(dist).as_posix()}"
                cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if _is_static_asset(full_path):  # a stale hashed bundle must 404, not come back as HTML
                return PlainTextResponse("not found", status_code=404, headers={"Cache-Control": "no-cache"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


STATIC_SUFFIXES = {".js", ".mjs", ".css", ".map", ".json", ".webmanifest", ".txt", ".xml", ".wasm", ".png", ".jpg",
                   ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif", ".woff", ".woff2", ".ttf", ".otf"}


def _is_static_asset(path: str) -> bool:
    """Requests for files (not client-side routes): anything under assets/ or with a static-file extension."""
    return path.startswith("assets/") or PurePosixPath(path).suffix.lower() in STATIC_SUFFIXES
