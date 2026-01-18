from .base import BaseScraper, ScrapedListing
from .olyrents import OlyrentsScraper
from .teamnwpm import TeamNWPMScraper
from .amh import AMHScraper
from .hometownpm import HometownPMScraper
from .tjguyer import TJGuyerScraper

SCRAPERS = {
    "olyrents": OlyrentsScraper,
    "teamnwpm": TeamNWPMScraper,
    "amh": AMHScraper,
    "hometownpm": HometownPMScraper,
    "tjguyer": TJGuyerScraper,
}

__all__ = [
    "BaseScraper",
    "ScrapedListing",
    "OlyrentsScraper",
    "TeamNWPMScraper",
    "AMHScraper",
    "HometownPMScraper",
    "TJGuyerScraper",
    "SCRAPERS",
]
