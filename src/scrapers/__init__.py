from .base import BaseScraper
from .olyrents import OlyrentsScraper
from .teamnwpm import TeamNWPMScraper
from .amh import AMHScraper

SCRAPERS = {
    "olyrents": OlyrentsScraper,
    "teamnwpm": TeamNWPMScraper,
    "amh": AMHScraper,
}

__all__ = ["BaseScraper", "SCRAPERS"]
