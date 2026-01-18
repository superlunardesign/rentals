"""Browser-based scraper using Playwright for sites with bot protection."""

import re
from typing import Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedListing


class BrowserScraper(BaseScraper):
    """Base scraper that uses Playwright for JavaScript-rendered pages."""

    def __init__(self, source_name: str, base_url: str):
        # Don't call parent __init__ to avoid httpx client
        self.source_name = source_name
        self.base_url = base_url
        self._browser = None
        self._page = None

    def _get_browser(self):
        """Lazy-load Playwright browser."""
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage']
                )
            except Exception as e:
                print(f"[{self.source_name}] Failed to start browser: {e}")
                raise
        return self._browser

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch a page using Playwright browser."""
        browser = self._get_browser()

        if self._page is None:
            self._page = browser.new_page()
            # Set realistic viewport and user agent
            self._page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            self._page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for any dynamic content
            self._page.wait_for_timeout(2000)
            html = self._page.content()
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            print(f"[{self.source_name}] Error fetching {url}: {e}")
            raise

    def close(self):
        """Close the browser."""
        if self._page:
            self._page.close()
            self._page = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if hasattr(self, '_playwright') and self._playwright:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Inherit utility methods from BaseScraper
    @staticmethod
    def parse_rent(text: str) -> Optional[int]:
        """Extract rent amount from text."""
        if not text:
            return None
        cleaned = re.sub(r'[,$\/a-zA-Z\s]', '', text)
        try:
            rent = int(cleaned)
            if 100 < rent < 50000:
                return rent
        except ValueError:
            pass
        return None

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean up scraped text."""
        if not text:
            return ""
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
        """Extract matching keywords from text."""
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
