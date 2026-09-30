"""Application configuration.

Secrets are read from environment variables (optionally via a local `.env`
file). The Groq API key and model reuse the SAME variable names as the
existing Review Reply AI project so a single credential works for both.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings loaded from the environment / `.env` file."""

    # --- Groq (reused from the Review Reply AI project) -------------------
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # --- Gemini (fallback when a Groq call fails transiently) -------------
    # Leave GEMINI_API_KEY empty to disable the fallback.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # --- Google review page -----------------------------------------------
    # Public "write a review" URL for Kaur Threads Boutique. The customer
    # submits the review themselves on Google using this link; the backend
    # never posts to Google. Configured here as the single source of truth.
    google_review_url: str = ""

    # --- Review history ---------------------------------------------------
    # SQLite file of accepted reviews, used to keep every new review unique
    # across restarts. Point it at a persistent disk in production, or use
    # ":memory:" to keep history only for the life of the process.
    review_history_path: str = str(PROJECT_ROOT / "data" / "review_history.sqlite3")

    # --- CORS -------------------------------------------------------------
    # Comma-separated browser origins allowed to call this API. Defaults
    # cover the local Vite dev server so a future frontend works out of the
    # box; override with CORS_ALLOW_ORIGINS in .env for other hosts.
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed list of allowed CORS origins."""
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
