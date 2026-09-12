from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite+aiosqlite:///./data/pilot.db'
    admin_username: str = 'admin'
    admin_password: SecretStr = Field(min_length=12)
    export_token: SecretStr = Field(min_length=24)
    public_base_url: str = 'http://localhost:8000'
    countries: str = 'in,us'
    categories: str = ''
    api_base_url: str = 'https://iptv-org.github.io/api'
    epg_urls: str = ''
    sync_on_start: bool = True
    scheduler_enabled: bool = True
    health_interval_hours: int = Field(default=6, ge=1)
    check_timeout: float = Field(default=5, gt=0, le=30)
    check_concurrency: int = Field(default=20, ge=1, le=100)
    max_download_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)

    def values(self, field: str) -> set[str]:
        return {v.strip().lower() for v in getattr(self, field).split(',') if v.strip()}
