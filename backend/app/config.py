"""Runtime settings. All secrets come from the environment — never from code.

Stage 1 (offline): only ``policy_path`` is needed.
Stage 2 (live):    ``gemini_api_key`` + DB/Redis URLs (Parts 7–9) join here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Try to load .env / .env.local if python-dotenv is available (dev convenience).
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)        # .env
    load_dotenv(".env.local", override=True)  # .env.local takes precedence
except ImportError:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = REPO_ROOT / "assignment" / "policy_terms.json"


@dataclass(frozen=True)
class Settings:
    policy_path: Path = DEFAULT_POLICY_PATH
    gemini_api_key: str | None = field(default=None)
    database_url: str | None = field(default=None)
    redis_url: str | None = field(default=None)
    frontend_url: str = "http://localhost:3000"


def get_settings() -> Settings:
    override = os.getenv("POLICY_PATH")
    return Settings(
        policy_path=Path(override) if override else DEFAULT_POLICY_PATH,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        database_url=os.getenv("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL"),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000"),
    )
