"""Base scraper class for rental property websites."""

import re
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import httpx
from bs4 import BeautifulSoup


@dataclass
class ScrapedListing:
    """A listing scraped from a property management website."""

    source_name: str
    source_id: str
    url: str
    title: str

    # Optional fields
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    rent: Optional[int] = None
    deposit: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    description: Optional[str] = None
    features: list[str] = field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    image_url: Optional[str] = None

    def generate_id(self) -> str:
        """Generate a unique ID from the URL if source_id not provided."""
        if self.source_id:
            return self.source_id
        return hashlib.md5(self.url.encode()).hexdigest()[:16]


class BaseScraper(ABC):
    """Base class for property scrapers."""

    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
        )

    @abstractmethod
    def scrape(self) -> list[ScrapedListing]:
        """Scrape listings from the website. Must be implemented by subclasses."""
        pass

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch a page and return parsed BeautifulSoup."""
        response = self.client.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def fetch_html(self, url: str) -> str:
        """Fetch raw HTML content."""
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Utility methods for parsing

    @staticmethod
    def parse_rent(text: str) -> Optional[int]:
        """Extract rent amount from text like '$1,500/mo' or '1500'."""
        if not text:
            return None
        # Remove common characters and extract number
        cleaned = re.sub(r'[,$\/a-zA-Z\s]', '', text)
        try:
            rent = int(cleaned)
            # Sanity check - rent should be reasonable
            if 100 < rent < 50000:
                return rent
        except ValueError:
            pass
        return None

    @staticmethod
    def parse_bedrooms(text: str) -> Optional[int]:
        """Extract bedroom count from text like '3 bed', '3BR', etc."""
        if not text:
            return None
        # Look for patterns like "3 bed", "3BR", "3 bedroom"
        match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', text.lower())
        if match:
            return int(match.group(1))
        # Try just finding a number
        match = re.search(r'(\d+)', text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def parse_bathrooms(text: str) -> Optional[float]:
        """Extract bathroom count from text like '2 bath', '1.5 BA', etc."""
        if not text:
            return None
        # Look for patterns like "2 bath", "1.5 BA", "2 bathroom"
        match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)', text.lower())
        if match:
            return float(match.group(1))
        # Try just finding a number
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def parse_sqft(text: str) -> Optional[int]:
        """Extract square footage from text like '1,200 sqft', '1200 sq ft', etc."""
        if not text:
            return None
        # Remove commas and look for number before sqft/sf
        cleaned = text.replace(',', '')
        match = re.search(r'(\d+)\s*(?:sq\.?\s*ft|sqft|sf)', cleaned.lower())
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean up scraped text (remove extra whitespace, etc.)."""
        if not text:
            return ""
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', text)
        return cleaned.strip()

    @staticmethod
    def extract_zip_code(text: str) -> Optional[str]:
        """Extract a 5-digit ZIP code from text."""
        if not text:
            return None
        match = re.search(r'\b(\d{5})(?:-\d{4})?\b', text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def extract_keywords(text: str, keywords: list[str] = None) -> list[str]:
        """Extract matching keywords from text.

        Default keywords are common rental features.
        """
        if keywords is None:
            keywords = [
                "office", "fence", "fenced yard", "garage", "carport",
                "updated", "renovated", "remodeled", "new",
                "washer", "dryer", "w/d", "laundry",
                "pet friendly", "pets ok", "pets allowed", "dog", "cat",
                "bonus room", "extra room", "den", "storage",
                "dishwasher", "air conditioning", "a/c", "ac",
                "fireplace", "patio", "deck", "yard",
                "hardwood", "granite", "stainless",
            ]

        if not text:
            return []

        text_lower = text.lower()
        found = []
        for keyword in keywords:
            if keyword.lower() in text_lower:
                found.append(keyword)
        return found

    def scrape_detail_page(self, url: str) -> dict:
        """Scrape additional details from individual listing page.

        Override in subclasses for site-specific parsing.
        Returns dict with: bedrooms, bathrooms, sqft, description, features
        """
        details = {
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "description": None,
            "features": [],
        }

        try:
            soup = self.fetch_page(url)
            text = soup.get_text()
            text_lower = text.lower()

            # Extract specs using regex
            bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', text_lower)
            if bed_match:
                details["bedrooms"] = int(bed_match.group(1))

            bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', text_lower)
            if bath_match:
                details["bathrooms"] = float(bath_match.group(1))

            sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf|square feet)', text_lower)
            if sqft_match:
                details["sqft"] = int(sqft_match.group(1).replace(',', ''))

            # Look for description
            for selector in [".description", ".property-description", "[class*='description']"]:
                elems = soup.select(selector)
                for elem in elems:
                    desc = self.clean_text(elem.get_text())
                    if len(desc) > 50:
                        details["description"] = desc[:1000]
                        break
                if details["description"]:
                    break

            # Extract keywords/features
            details["features"] = self.extract_keywords(text)

        except Exception as e:
            print(f"[{self.source_name}] Error scraping detail page {url}: {e}")

        return details
