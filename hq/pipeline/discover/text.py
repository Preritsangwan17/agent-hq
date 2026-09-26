"""HTML → readable text, and small helpers for posting text."""
from __future__ import annotations

import html
import re

from selectolax.parser import HTMLParser

BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol", "table"}


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    if "<" not in raw and "&lt;" in raw:
        raw = html.unescape(raw)     # Greenhouse returns escaped HTML in `content`
    tree = HTMLParser(raw)
    for tag in ("script", "style", "noscript", "svg", "head"):
        for node in tree.css(tag):
            node.decompose()
    for node in tree.css(",".join(BLOCK)):
        node.insert_after("\n")
    for node in tree.css("li"):
        node.insert_before("• ")
    text = tree.body.text(separator=" ") if tree.body else tree.text(separator=" ")
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sentences(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n+", text):
        block = block.strip(" •-\t")
        if not block:
            continue
        out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", block) if p.strip())
    return out
