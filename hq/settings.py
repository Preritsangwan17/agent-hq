"""Paths and environment for Agent HQ. Everything else imports from here.

Tests and throwaway runs point HQ_ENV_FILE / HQ_DB_PATH (and optionally HQ_DATA_DIR, HQ_AGENTS_DIR, HQ_RUN_DIR, HQ_LOG_DIR)
at data/test/ so they never touch Prerit's real passcode, database, agent configs or pidfiles.
Code elsewhere reads these as module attributes at call time (``settings.DB_PATH``) so tests can monkeypatch them.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("HQ_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("HQ_DB_PATH", DATA / "hq.db"))
RUN_DIR = Path(os.environ.get("HQ_RUN_DIR", DATA / "run"))
LOG_DIR = Path(os.environ.get("HQ_LOG_DIR", DATA / "logs"))
ARTIFACTS = DATA / "artifacts"
AGENTS_DIR = Path(os.environ.get("HQ_AGENTS_DIR", ROOT / "agents"))
CONFIG_DIR = ROOT / "config"
WEB_DIST = ROOT / "web" / "dist"
ENV_PATH = Path(os.environ.get("HQ_ENV_FILE", ROOT / ".env"))
MIGRATIONS_DIR = ROOT / "hq" / "db" / "migrations"

API_HOST = "0.0.0.0" if os.environ.get("HQ_LAN") == "1" else "127.0.0.1"
API_PORT = int(os.environ.get("HQ_PORT", "8765"))
TZ_DISPLAY = "Asia/Kolkata"


def read_env_file(path: Path | None = None) -> dict:
    """Parse .env (KEY=VALUE lines) without touching os.environ."""
    path = path or ENV_PATH
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env(path: Path | None = None) -> dict:
    """Parse .env (KEY=VALUE lines) into os.environ without overriding values already set."""
    values = read_env_file(path)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


_fresh_cache: dict[str, tuple[float, dict]] = {}


def env_fresh(key: str) -> str | None:
    """A secret/connection value as it is in .env *now* (so connecting Gmail or adding an API key needs no restart),
    falling back to the process environment. Safety flags (HQ_FORCE_DRY_RUN, HQ_MODE) deliberately don't use this."""
    path = ENV_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    cached = _fresh_cache.get(str(path))
    if cached is None or cached[0] != mtime:
        cached = (mtime, read_env_file(path) if mtime >= 0 else {})
        _fresh_cache[str(path)] = cached
    value = cached[1].get(key)
    return value if value else (os.environ.get(key) or None)


def set_env_value(key: str, value: str, path: Path | None = None, *, export: bool = True) -> None:
    """Insert or replace KEY=VALUE in .env (file mode 600) and, unless export=False, in os.environ (safety flags
    like HQ_FORCE_DRY_RUN must only take effect after a restart, so they are written with export=False)."""
    path = path or ENV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)
    if export:
        os.environ[key] = value


def ensure_dirs() -> None:
    for d in (DATA, RUN_DIR, LOG_DIR, ARTIFACTS):
        d.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
