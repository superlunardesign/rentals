"""Scraper for Blue Summit Realty property listings.

Uses browser-based scraping since the page renders listings with JavaScript.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class BlueSummitScraper(BrowserScraper):
    """Scraper for bluesummitrealty.com rentals.

    Uses Playwright browser to render JavaScript content.
    """

    def __init__(self, url: str = "https://www.bluesummitrealty.com/property-management/#listings"):
        super().__init__(source_name="bluesummit", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Blue Summit Realty."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page with browser...")
            listings = self._run_async(self._scrape_listings())
            print(f"[{self.source_name}] Total: {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_listings(self) -> list[ScrapedListing]:
        """Scrape listings using Playwright browser."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page: {self.base_url}")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Wait for listings to load
            print(f"[{self.source_name}] Waiting for listings to load...")
            try:
                await page.wait_for_selector('a.teaser__card', timeout=10000)
                print(f"[{self.source_name}] Listings found")
            except Exception:
                print(f"[{self.source_name}] Primary selector not found, checking page...")
                # Debug: show what's on the page
                html = await page.content()
                soup = BeautifulSoup(html, "lxml")
                all_classes = set()
                for el in soup.find_all(class_=True)[:50]:
                    for cls in el.get('class', []):
                        all_classes.add(cls)
                print(f"[{self.source_name}] Page classes: {list(all_classes)[:30]}")
                return listings

            # Get page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all listing cards
            cards = soup.select("a.teaser__card")
            print(f"[{self.source_name}] Found {len(cards)} listing cards")

            for i, card in enumerate(cards):
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(cards)}: {listing.address or listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing card {i+1}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error during scrape: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Close page AND browser to free memory
            await page.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        return listings

    def _parse_card(self, card: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing card."""
        try:
            # URL
            url = card.get("href", "")
            if url and not url.startswith("http"):
                url = urljoin(self.base_url, url)

            # Price
            price_el = card.select_one(".teaser__price__title")
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Address
            address_el = card.select_one(".teaser__address")
            address = address_el.get_text(strip=True) if address_el else None

            # Parse city from address
            city, state, zip_code = None, "WA", None
            if address:
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()

            # Beds, Baths, SqFt from additional info spans
            info_spans = card.select(".teaser__additional-info span")
            bedrooms, bathrooms, sqft = None, None, None

            for span in info_spans:
                text = span.get_text(strip=True)

                if "Bed" in text:
                    bed_match = re.search(r'([\d.]+)', text)
                    if bed_match:
                        bedrooms = int(float(bed_match.group(1)))

                elif "Bath" in text:
                    bath_match = re.search(r'([\d.]+)', text)
                    if bath_match:
                        bathrooms = float(bath_match.group(1))

                elif "SqFt" in text:
                    sqft_match = re.search(r'([\d,]+)', text)
                    if sqft_match:
                        sqft = int(sqft_match.group(1).replace(',', ''))

            # Image - check both src and data-src for lazy loading
            img_el = card.select_one(".teaser__img img")
            image_url = None
            if img_el:
                # Prefer data-src (full image) over src (placeholder)
                image_url = img_el.get("data-src") or img_el.get("src")
                # Skip placeholder images
                if image_url and ("/util/" in image_url or "no-image" in image_url):
                    image_url = img_el.get("data-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Generate source ID from URL
            source_id = None
            if url:
                slug_match = re.search(r'/listing/cms/([^/]+)/?', url)
                if slug_match:
                    source_id = f"bluesummit_{slug_match.group(1)}"

            if not source_id:
                source_id = f"bluesummit_{abs(hash(url or address))}"

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=address or "Blue Summit Property",
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing card: {e}")
            return None
