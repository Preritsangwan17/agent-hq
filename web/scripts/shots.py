"""Screenshot SPA routes at desktop (1440x900) and mobile (390x844) with headless Chrome (Playwright).

Usage (dev server in mock mode must be running, e.g. `VITE_MOCK=1 npx vite --port 5180`):
    ../.venv/bin/python scripts/shots.py --base http://localhost:5180 --out ../data/test/shots/foundation \
        / /pipeline "/login?mock_auth=out"

Every request to a non-localhost host is aborted. Console errors and page errors are printed and make the
script exit non-zero.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def slug(route: str) -> str:
    path = route.split("?", 1)[0].strip("/") or "home"
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")


async def shoot(base: str, routes: list[str], out: Path, wait_ms: int, full_page: bool, only: str | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    problems = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        try:
            for name, (w, h) in VIEWPORTS.items():
                if only and only != name:
                    continue
                for route in routes:
                    # fresh context per shot: independent sessionStorage (mock auth switches) and storage
                    ctx = await browser.new_context(
                        viewport={"width": w, "height": h},
                        device_scale_factor=2 if name == "mobile" else 1,
                        is_mobile=name == "mobile",
                        has_touch=name == "mobile",
                        color_scheme="dark",
                    )

                    async def guard(r):
                        host = urlparse(r.request.url).hostname or ""
                        if host in LOCAL_HOSTS or r.request.url.startswith(("data:", "blob:")):
                            await r.continue_()
                        else:
                            print(f"  blocked non-local request: {r.request.url}")
                            await r.abort()

                    await ctx.route("**/*", guard)
                    page = await ctx.new_page()
                    errors: list[str] = []
                    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
                    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                    await page.goto(base.rstrip("/") + route, wait_until="networkidle")
                    await page.wait_for_timeout(wait_ms)
                    file = out / f"{slug(route)}-{name}.png"
                    await page.screenshot(path=str(file), full_page=full_page)
                    print(f"{file}  ({w}x{h})")
                    for e in errors:
                        print(f"  {e}")
                    problems += len(errors)
                    await ctx.close()
        finally:
            await browser.close()
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("routes", nargs="*", default=["/"])
    ap.add_argument("--base", default="http://localhost:5180")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data/test/shots/web"))
    ap.add_argument("--wait", type=int, default=2500, help="ms to wait after load (animations, sim ticks)")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--only", choices=list(VIEWPORTS), help="only one viewport")
    a = ap.parse_args()
    problems = asyncio.run(shoot(a.base, a.routes, Path(a.out), a.wait, a.full_page, a.only))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
