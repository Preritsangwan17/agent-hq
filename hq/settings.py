"""Paths and environment for Agent HQ. Everything else imports from here."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = Path(os.environ.get("HQ_DB_PATH", DATA / "hq.db"))
RUN_DIR = DATA / "run"
LOG_DIR = DATA / "logs"
ARTIFACTS = DATA / "artifacts"
AGENTS_DIR = ROOT / "agents"
CONFIG_DIR = ROOT / "config"
WEB_DIST = ROOT / "web" / "dist"
# Tests/screenshots point HQ_ENV_FILE + HQ_DB_PATH at data/test/ so they never touch Prerit's real passcode or DB.
ENV_PATH = Path(os.environ.get("HQ_ENV_FILE", ROOT / ".env"))
MIGRATIONS_DIR = ROOT / "hq" / "db" / "migrations"

API_HOST = "0.0.0.0" if os.environ.get("HQ_LAN") == "1" else "127.0.0.1"
API_PORT = int(os.environ.get("HQ_PORT", "8765"))
TZ_DISPLAY = "Asia/Kolkata"


def load_env(path: Path = ENV_PATH) -> dict:
    """Parse .env (KEY=VALUE lines) into os.environ without overriding values already set."""
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def set_env_value(key: str, value: str, path: Path = ENV_PATH) -> None:
    """Insert or replace KEY=VALUE in .env (file mode 600) and in os.environ."""
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
    os.environ[key] = value


def ensure_dirs() -> None:
    for d in (DATA, RUN_DIR, LOG_DIR, ARTIFACTS):
        d.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
