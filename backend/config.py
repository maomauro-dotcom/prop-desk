"""Settings from environment variables (optionally a local .env file, never committed)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    webhook_secret: str = ""
    dashboard_token: str = ""
    tradovate_enabled: bool = False
    ib_enabled: bool = False
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_timeout_s: float = 15.0
    claude_transport: str = "anthropic"
    database_url: str = "sqlite:///./propdesk.db"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    clock_interval_s: float = 15.0

    @classmethod
    def from_env(cls, dotenv: Path | None = None) -> "Settings":
        load_dotenv(dotenv or Path(__file__).resolve().parents[1] / ".env")
        return cls(
            webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            dashboard_token=os.environ.get("DASHBOARD_TOKEN", ""),
            tradovate_enabled=_flag("TRADOVATE_ENABLED"),
            ib_enabled=_flag("IB_ENABLED"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
            claude_timeout_s=float(os.environ.get("CLAUDE_TIMEOUT_S", "15") or 15),
            claude_transport=os.environ.get("CLAUDE_TRANSPORT", "anthropic") or "anthropic",
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./propdesk.db") or "sqlite:///./propdesk.db",
            cors_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
                          if o.strip()],
        )
