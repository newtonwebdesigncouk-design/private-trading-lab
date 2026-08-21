"""Environment configuration with a closed, simulation-only trading mode."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.enums import TradingMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    app_env: str = "development"
    database_url: str = "sqlite:///./data/trading_lab.db"
    log_level: str = "INFO"
    trading_mode: TradingMode = TradingMode.BACKTEST
    trading_kill_switch: bool = False
    market_data_cache_dir: Path = Path("data/cache")
    random_seed: int = Field(default=1729, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
