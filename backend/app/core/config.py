import os
import secrets
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "dev-secret-key-replace-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    firebase_credentials_path: str = "firebase_credentials.json"


def _ensure_secret_key() -> Settings:
    """
    On first run, generate a cryptographically random secret key and
    persist it to .env so it survives restarts. Subsequent runs load
    it from .env via pydantic-settings.
    """
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
    env_path = os.path.normpath(env_path)

    s = Settings()
    if s.secret_key == "dev-secret-key-replace-in-production":
        new_key = secrets.token_hex(32)
        # Write / update .env
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path) as f:
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
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        # Return fresh settings with the new key
        return Settings()
    return s


settings = _ensure_secret_key()