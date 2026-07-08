from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "trading_journal.sqlite3"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = DB_PATH
    data_dir: Path = DATA_DIR
    llm_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None
    llm_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    tool_timeout_s: float = float(os.getenv("TJ_TOOL_TIMEOUT_S", "8"))
    agent_max_steps: int = int(os.getenv("TJ_AGENT_MAX_STEPS", "5"))


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings

