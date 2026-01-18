from .base import BaseScraper, ScrapedListing
from .olyrents import OlyrentsScraper
from .teamnwpm import TeamNWPMScraper
from .amh import AMHScraper

SCRAPERS = {
    "olyrents": OlyrentsScraper,
    "teamnwpm": TeamNWPMScraper,
    "amh": AMHScraper,
}

__all__ = [
    "BaseScraper",
    "ScrapedListing",
    "OlyrentsScraper",
    "TeamNWPMScraper",
    "AMHScraper",
    "SCRAPERS",
]
