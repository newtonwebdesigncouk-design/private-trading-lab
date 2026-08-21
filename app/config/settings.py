"""Environment configuration with a closed, simulation-only trading mode."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.phase2 import Phase2Configuration
from app.config.phase3 import Phase3Configuration
from app.models.enums import TradingMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="forbid")

    app_env: str = "development"
    database_url: str = "sqlite:///./data/trading_lab.db"
    log_level: str = "INFO"
    trading_mode: TradingMode = TradingMode.BACKTEST
    trading_kill_switch: bool = False
    market_data_cache_dir: Path = Path("data/cache")
    random_seed: int = Field(default=1729, ge=0)
    phase2: Phase2Configuration = Field(default_factory=Phase2Configuration)
    phase3: Phase3Configuration = Field(default_factory=Phase3Configuration)
    trading_lab_api_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
