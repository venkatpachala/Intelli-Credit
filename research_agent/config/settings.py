"""
config/settings.py
==================
Centralised settings — loaded once via get_settings().
All values come from environment variables (or .env file).
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    app_name: str = "ResearchAgent"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/research_agent"

    # ── External APIs ─────────────────────────────────────────
    mca_base_url: str = "https://api.mca21.gov.in/v1"
    gstn_base_url: str = "https://api.mastergst.com/gstnapi/taxpayerDetails"
    ecourts_base_url: str = "https://ecourts.gov.in/ecourts_home"
    rbi_base_url: str = "https://www.rbi.org.in"

    # ── Tavily (news search) ──────────────────────────────────
    tavily_api_key: str = ""

    # ── Scoring ───────────────────────────────────────────────
    base_score: int = 100
    rejection_threshold: int = 0
    high_risk_threshold: int = 40
    medium_risk_threshold: int = 70

    # ── Timeouts ─────────────────────────────────────────────
    source_timeout_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
