"""Browser-based scraper using Playwright for sites with bot protection.

Uses async Playwright API for compatibility with FastAPI.
"""

import os
import re
import asyncio
from typing import Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedListing

# Set Playwright browsers path for Render deployment
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/render/.cache/ms-playwright"


class BrowserScraper(BaseScraper):
    """Base scraper that uses Playwright for JavaScript-rendered pages."""

    def __init__(self, source_name: str, base_url: str):
        # Don't call parent __init__ to avoid httpx client
        self.source_name = source_name
        self.base_url = base_url
        self._browser = None
        self._page = None
        self._playwright = None

    def _run_async(self, coro):
        """Run an async coroutine from sync code."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context (FastAPI), create a new thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _get_browser_async(self):
        """Lazy-load Playwright browser asynchronously."""
        if self._browser is None:
            try:
                print(f"[{self.source_name}] Importing Playwright...")
                from playwright.async_api import async_playwright

                # Check if browsers need to be installed (Render free tier doesn't persist build cache)
                await self._ensure_browsers_installed()

                print(f"[{self.source_name}] Starting Playwright...")
                self._playwright = await async_playwright().start()
                # Try Firefox first (fewer system deps), fall back to Chromium
                print(f"[{self.source_name}] Launching Firefox...")
                try:
                    self._browser = await self._playwright.firefox.launch(headless=True)
                except Exception as firefox_err:
                    print(f"[{self.source_name}] Firefox failed: {firefox_err}, trying Chromium...")
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage']
                    )
                print(f"[{self.source_name}] Browser launched successfully!")
            except Exception as e:
                print(f"[{self.source_name}] Failed to start browser: {e}")
                import traceback
                traceback.print_exc()
                raise
        return self._browser

    async def _create_stealth_page(self, browser):
        """Create a new page with stealth settings to avoid bot detection."""
        # Realistic user agent
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )

        page = await context.new_page()

        # Add stealth scripts to mask automation
        await page.add_init_script("""
            // Mask webdriver
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Mask plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Mask languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        return page, context

    async def _ensure_browsers_installed(self):
        """Install Playwright browsers if not present (needed for Render free tier)."""
        import subprocess

        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/.cache/ms-playwright")

        # Check if Firefox exists
        firefox_path = os.path.join(browsers_path, "firefox-1497", "firefox", "firefox")
        if not os.path.exists(firefox_path):
            print(f"[{self.source_name}] Browsers not found, installing at runtime...")
            try:
                # Install Firefox
                result = subprocess.run(
                    ["playwright", "install", "firefox"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    print(f"[{self.source_name}] Firefox installed successfully")
                else:
                    print(f"[{self.source_name}] Firefox install warning: {result.stderr}")
            except Exception as e:
                print(f"[{self.source_name}] Browser install failed: {e}")

    async def _fetch_page_async(self, url: str) -> str:
        """Fetch a page using Playwright browser asynchronously."""
        browser = await self._get_browser_async()

        page = await browser.new_page()
        try:
            # Set realistic viewport
            await page.set_viewport_size({"width": 1920, "height": 1080})

            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait for dynamic content
            await page.wait_for_timeout(2000)
            html = await page.content()
            return html
        finally:
            await page.close()

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch a page using Playwright browser."""
        html = self._run_async(self._fetch_page_async(url))
        return BeautifulSoup(html, "lxml")

    async def _close_async(self):
        """Close browser asynchronously."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def close(self):
        """Close the browser."""
        try:
            self._run_async(self._close_async())
        except Exception as e:
            print(f"[{self.source_name}] Error closing browser: {e}")

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
    def parse_bedrooms(text: str) -> Optional[int]:
        """Extract bedroom count from text like '3 bed', '3BR', etc."""
        if not text:
            return None
        match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', text.lower())
        if match:
            return int(match.group(1))
        match = re.search(r'(\d+)', text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def parse_bathrooms(text: str) -> Optional[float]:
        """Extract bathroom count from text like '2 bath', '1.5 BA', etc."""
        if not text:
            return None
        match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)', text.lower())
        if match:
            return float(match.group(1))
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def parse_sqft(text: str) -> Optional[int]:
        """Extract square footage from text like '1,200 sqft', '1200 sq ft', etc."""
        if not text:
            return None
        cleaned = text.replace(',', '')
        match = re.search(r'(\d+)\s*(?:sq\.?\s*ft|sqft|sf)', cleaned.lower())
        if match:
            return int(match.group(1))
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
