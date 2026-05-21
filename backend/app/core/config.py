from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "dev-secret-key-replace-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    firebase_credentials_path: str = "firebase_credentials.json"


settings = Settings()
