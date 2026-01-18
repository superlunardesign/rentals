from .base import BaseScraper, ScrapedListing
from .olyrents import OlyrentsScraper
from .teamnwpm import TeamNWPMScraper
from .amh import AMHScraper
from .hometownpm import HometownPMScraper
from .tjguyer import TJGuyerScraper
from .kenzie import KenzieScraper
from .greene import GreeneScraper

SCRAPERS = {
    "olyrents": OlyrentsScraper,
    "teamnwpm": TeamNWPMScraper,
    "amh": AMHScraper,
    "hometownpm": HometownPMScraper,
    "tjguyer": TJGuyerScraper,
    "kenzie": KenzieScraper,
    "greene": GreeneScraper,
}

__all__ = [
    "BaseScraper",
    "ScrapedListing",
    "OlyrentsScraper",
    "TeamNWPMScraper",
    "AMHScraper",
    "HometownPMScraper",
    "TJGuyerScraper",
    "KenzieScraper",
    "GreeneScraper",
    "SCRAPERS",
]
