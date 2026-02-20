from .base import BaseScraper, ScrapedListing
from .olyrents import OlyrentsScraper
from .teamnwpm import TeamNWPMScraper
from .amh import AMHScraper
from .hometownpm import HometownPMScraper
from .tjguyer import TJGuyerScraper
from .kenzie import KenzieScraper
from .greene import GreeneScraper
from .windermere import WindermereScraper
from .simplyhome import SimplyHomeScraper
from .capitol_pm import CapitolPMScraper
from .bluesummit import BlueSummitScraper
from .invitationhomes import InvitationHomesScraper
from .rantsgroup import RantsGroupScraper
from .rpmwa018 import RPMWA018Scraper
from .bennettprops import BennettPropsScraper
from .narrowspm import NarrowsPMScraper
from .mvppropertypros import MVPPropertyProsScraper
from .welcomehomerentals import WelcomeHomeRentalsScraper
from .vanguardrealty import VanguardRealtyScraper
from .elitesheltonrentals import EliteSheltonRentalsScraper
from .utopiamanagement import UtopiaManagementScraper

SCRAPERS = {
    "olyrents": OlyrentsScraper,
    "teamnwpm": TeamNWPMScraper,
    "amh": AMHScraper,
    "hometownpm": HometownPMScraper,
    "tjguyer": TJGuyerScraper,
    "kenzie": KenzieScraper,
    "greene": GreeneScraper,
    "windermere": WindermereScraper,
    "simplyhome": SimplyHomeScraper,
    "capitol_pm": CapitolPMScraper,
    "bluesummit": BlueSummitScraper,
    "invitationhomes": InvitationHomesScraper,
    "rantsgroup": RantsGroupScraper,
    "rpmwa018": RPMWA018Scraper,
    "bennettprops": BennettPropsScraper,
    "narrowspm": NarrowsPMScraper,
    "mvppropertypros": MVPPropertyProsScraper,
    "welcomehomerentals": WelcomeHomeRentalsScraper,
    "vanguardrealty": VanguardRealtyScraper,
    "elitesheltonrentals": EliteSheltonRentalsScraper,
    "utopiamanagement": UtopiaManagementScraper,
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
    "WindermereScraper",
    "SimplyHomeScraper",
    "CapitolPMScraper",
    "BlueSummitScraper",
    "InvitationHomesScraper",
    "RantsGroupScraper",
    "RPMWA018Scraper",
    "BennettPropsScraper",
    "NarrowsPMScraper",
    "MVPPropertyProsScraper",
    "WelcomeHomeRentalsScraper",
    "VanguardRealtyScraper",
    "EliteSheltonRentalsScraper",
    "UtopiaManagementScraper",
    "SCRAPERS",
]
