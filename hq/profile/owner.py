"""Who HQ works for: the owner's name and email address, read from config/resume.yaml (`name`, `contact.email`).

This is the one place the rest of the code asks for them: the self-test recipient, the From address of every send,
the Gmail account HQ expects to be connected, and the identity shown in the UI."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths

DEFAULT_NAME = "Prerit Sangwan"
DEFAULT_EMAIL = "sangwanprerit40@gmail.com"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, Any]:
    try:
        return yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _resume() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "resume.yaml"
    try:
        return _load(str(p), p.stat().st_mtime)
    except OSError:
        return {}


def name() -> str:
    return str(_resume().get("name") or DEFAULT_NAME).strip()


def email() -> str:
    return str((_resume().get("contact") or {}).get("email") or DEFAULT_EMAIL).strip().lower()


def is_owner_address(addr: str | None) -> bool:
    return bool(addr) and addr.strip().lower() == email()


def info() -> dict[str, Any]:
    contact = _resume().get("contact") or {}
    return {"name": name(), "email": email(), "linkedin": contact.get("linkedin"), "github": contact.get("github")}
