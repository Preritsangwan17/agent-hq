"""Tailored résumé (CONTRACT_C §5): a port of legacy build.py's resume_html with approved bullets only, rendered to
PDF by headless Chrome (macOS app or a chrome/chromium binary) or Playwright's Chromium, then post-checked with pypdf:
exactly one page, and every word on it comes from the approved strings."""
from __future__ import annotations

import asyncio
import html
import shutil
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from hq.resume.content import approved_strings, content, unapproved_words

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 14mm 15mm; }
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; font-size: 10.3pt; color: #111; line-height: 1.38; }
h1 { font-size: 20pt; margin: 0 0 2px; letter-spacing: 0.2px; }
.contact { font-size: 9.4pt; color: #333; margin-bottom: 8px; }
.contact a, .proj a { color: #0b4f9c; text-decoration: none; }
.summary { margin: 6px 0 4px; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #999; padding-bottom: 2px; margin: 12px 0 5px; }
.ph { display: flex; justify-content: space-between; }
.ph span { color: #444; font-size: 9.4pt; }
.ph span:last-child { white-space: nowrap; padding-left: 12px; }
.tech { font-style: italic; color: #444; font-size: 9.4pt; }
ul { margin: 3px 0 7px 16px; padding: 0; } li { margin-bottom: 2px; }
.sk b { display: inline-block; min-width: 88px; }
"""


def resume_html(summary: str, order: list[str]) -> str:
    c = content()
    e = html.escape
    projects = []
    for key in order:
        p = c["projects"][key]
        bullets = "".join(f"<li>{e(b['text'])}</li>" for b in p["bullets"])
        projects.append(f'<div class="proj"><div class="ph"><b><a href="{e(p["url"])}">{e(p["title"])}</a></b>'
                        f'<span>{e(p["date"])}</span></div><div class="tech">{e(p["tech"])}</div><ul>{bullets}</ul></div>')
    skills = "".join(f'<div class="sk"><b>{e(s["label"])}:</b> {e(s["value"])}</div>' for s in c["skills"])
    ct = c["contact"]
    contact = " &middot; ".join([e(ct["email"]),
                                 f'<a href="{e(ct["linkedin"])}">linkedin.com/in/prerit-sangwan-1b7572304</a>',
                                 f'<a href="{e(ct["github"])}">github.com/Preritsangwan17</a>',
                                 *[e(x) for x in ct.get("extras", [])]])
    ed = c["education"]
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{e(c["name"])} - Resume</title>'
            f"<style>{CSS}</style></head><body><h1>{e(c['name'])}</h1><div class=\"contact\">{contact}</div>"
            f'<div class="summary">{e(summary)}</div><h2>Education</h2><div class="ph"><span style="color:#111;'
            f'font-size:10.3pt"><b>{e(ed["school"].split(",")[0])}</b>, {e(ed["school"].split(", ")[-1])} &mdash; '
            f'{e(ed["degree"])}</span><span>{e(ed["status"])}</span></div><h2>Projects</h2>{"".join(projects)}'
            f"<h2>Skills</h2>{skills}</body></html>")


def chrome_binary() -> str | None:
    if Path(MAC_CHROME).exists():
        return MAC_CHROME
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


async def render_pdf(html_path: Path, pdf_path: Path) -> str:
    """Returns the renderer used. Chrome CLI first (as legacy build.py did), else Playwright's Chromium."""
    chrome = chrome_binary()
    if chrome:
        proc = await asyncio.create_subprocess_exec(
            chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
            html_path.as_uri(), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=60)
        if pdf_path.exists():
            return "chrome"
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        exe = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        browser = await p.chromium.launch(executable_path=exe if Path(exe).exists() else None)
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("file:", "data:"))
                             else r.abort())
            await page.goto(html_path.as_uri())
            await page.pdf(path=str(pdf_path), format="A4", prefer_css_page_size=True)
        finally:
            await browser.close()
    return "playwright"


@dataclass
class PdfCheck:
    pages: int
    unapproved: list[str]

    @property
    def ok(self) -> bool:
        return self.pages == 1 and not self.unapproved


def check_pdf(pdf_path: Path, summary: str) -> PdfCheck:
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return PdfCheck(len(reader.pages), unapproved_words(text, summary))


async def build(out_dir: Path, *, summary: str, order: list[str]) -> tuple[Path, Path, PdfCheck, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "resume.html"
    page.write_text(resume_html(summary, order))
    pdf = out_dir / "Prerit_Sangwan_Resume.pdf"
    renderer = await render_pdf(page, pdf)
    return page, pdf, check_pdf(pdf, summary), renderer


__all__ = ["approved_strings", "build", "check_pdf", "resume_html"]
