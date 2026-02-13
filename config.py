import os

class Config:
    """
    Central configuration for StudentOS.

    Uses environment variables in production (Render),
    and safe fallbacks locally.
    """

    # Flask security key
    # In production this MUST come from Render environment variables
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev_secret_key_change_me")

    # Future database support (not required yet, but ready)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///studentos.db"  # local fallback
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False