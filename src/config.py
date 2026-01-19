"""Configuration loader for rental search."""

import yaml
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class LocationConfig(BaseModel):
    center_zip: str
    center_city: str
    center_state: str
    latitude: float
    longitude: float
    radius_miles: int
    flexible_radius_miles: int
    allowed_cities: list[str] = []  # If set, only show listings from these cities


class BudgetConfig(BaseModel):
    max_rent: int
    flexible_buffer: int

    @property
    def flexible_max(self) -> int:
        return self.max_rent + self.flexible_buffer


class RoomsConfig(BaseModel):
    min_bedrooms: int
    min_bathrooms: float
    min_sqft: int
    best_match_bedrooms: int = 3
    best_match_sqft: int = 1500


class KeywordsConfig(BaseModel):
    preferred: list[str]
    dealbreakers: list[str]


class SourceConfig(BaseModel):
    name: str
    scraper: str
    url: str
    enabled: bool = True


class SchedulerConfig(BaseModel):
    interval_hours: int
    run_on_startup: bool


class DashboardConfig(BaseModel):
    host: str
    port: int


class AppConfig(BaseModel):
    location: LocationConfig
    budget: BudgetConfig
    rooms: RoomsConfig
    keywords: KeywordsConfig
    sources: list[SourceConfig]
    scheduler: SchedulerConfig
    dashboard: DashboardConfig


_config: Optional[AppConfig] = None


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file."""
    global _config

    if _config is not None:
        return _config

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    with open(config_path) as f:
        data = yaml.safe_load(f)

    _config = AppConfig(**data)
    return _config


def get_config() -> AppConfig:
    """Get the current configuration (loads if not already loaded)."""
    return load_config()
