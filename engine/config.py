from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TJ_DATA_DIR", ROOT_DIR / "data")).expanduser().resolve()
ENGINE_PORT = int(os.environ.get("TJ_PORT", "8765"))
DB_PATH = DATA_DIR / "trading_journal.sqlite3"


@dataclass(frozen=True)
class Settings:
    """Non-secret process settings; provider configuration lives in SQLite."""
    host: str = "127.0.0.1"
    port: int = ENGINE_PORT
    db_path: Path = DB_PATH
    data_dir: Path = DATA_DIR
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    tool_timeout_s: float = 8
    agent_max_steps: int = 5


def get_settings() -> Settings:
    """Build fixed process settings without reading provider environment variables."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
