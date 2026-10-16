"""Runtime configuration loaded from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    return _REPO_ROOT / "data"


class Settings(BaseSettings):
    """Process settings. Secrets have no usable default."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str = ""
    app_auth_secret: str = ""
    app_access_password: str = ""
    app_secret_encryption_key: str = ""
    allowed_hosts: str = "localhost,127.0.0.1"
    cors_origins: str = "http://127.0.0.1:43117,http://localhost:43117"
    log_level: str = "INFO"
    sse_heartbeat_seconds: float = 15.0

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir.is_absolute():
            return self.data_dir
        return Path.cwd() / self.data_dir

    @property
    def resolved_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        database_path = self.resolved_data_dir / "ai_novel_writer.db"
        return f"sqlite:///{database_path}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
