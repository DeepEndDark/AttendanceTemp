import os
import sys
import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict


def _runtime_base_dir() -> str:
    """
    Directory the .env file lives in / should be written to.

    In a frozen (--onefile) build, __file__ resolves to a path inside
    sys._MEIPASS — a temp extraction folder PyInstaller deletes when the
    process exits. Writing .env there means the auto-generated SECRET_KEY
    silently regenerates on every single launch, invalidating every
    previously-issued login token each time the app restarts.

    The correct location is next to the actual .exe, which survives
    between runs. In dev mode, this resolves to the repo root (three
    levels up from backend/app/core/), matching where .env already lives.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )


_ENV_PATH = os.path.join(_runtime_base_dir(), ".env")


class Settings(BaseSettings):
    # env_file as an absolute path — NOT the bare ".env" string, which
    # pydantic-settings would otherwise resolve against the process's
    # current working directory at launch (e.g. wherever a shortcut's
    # "Start in" folder points, not necessarily next to the .exe).
    model_config = SettingsConfigDict(env_file=_ENV_PATH, env_file_encoding="utf-8")

    secret_key: str = "dev-secret-key-replace-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    firebase_credentials_path: str = "firebase_credentials.json"


def _ensure_secret_key() -> Settings:
    """
    On first run, generate a cryptographically random secret key and
    persist it to .env (next to the .exe / at the repo root) so it
    survives restarts. Subsequent runs load it from .env via
    pydantic-settings.
    """
    s = Settings()
    if s.secret_key == "dev-secret-key-replace-in-production":
        new_key = secrets.token_hex(32)
        # Write / update .env
        lines = []
        found = False
        if os.path.exists(_ENV_PATH):
            with open(_ENV_PATH) as f:
                lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.startswith("SECRET_KEY="):
                new_lines.append(f"SECRET_KEY={new_key}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"SECRET_KEY={new_key}\n")
        with open(_ENV_PATH, "w") as f:
            f.writelines(new_lines)
        # Return fresh settings with the new key
        return Settings()
    return s


settings = _ensure_secret_key()