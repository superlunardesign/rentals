"""Scraper for Invitation Homes property listings.

Uses browser-based scraping since the page is built with Svelte/JavaScript.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class InvitationHomesScraper(BrowserScraper):
    """Scraper for invitationhomes.com rentals.

    Uses Playwright browser to render JavaScript content.
    """

    def __init__(self, url: str = "https://www.invitationhomes.com/search/houses-for-rent"):
        super().__init__(source_name="invitationhomes", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Invitation Homes."""
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
            await page.goto(self.base_url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)

            # Wait for property cards to load
            print(f"[{self.source_name}] Waiting for listings to load...")
            try:
                await page.wait_for_selector('.property-card', timeout=15000)
                print(f"[{self.source_name}] Listings found")
            except Exception:
                print(f"[{self.source_name}] Primary selector not found, checking page...")
                html = await page.content()
                soup = BeautifulSoup(html, "lxml")
                all_classes = set()
                for el in soup.find_all(class_=True)[:50]:
                    for cls in el.get('class', []):
                        all_classes.add(cls)
                print(f"[{self.source_name}] Page classes: {list(all_classes)[:30]}")
                return listings

            # Scroll down to load more listings (lazy loading)
            print(f"[{self.source_name}] Scrolling to load all listings...")
            last_count = 0
            scroll_attempts = 0
            max_scrolls = 10

            while scroll_attempts < max_scrolls:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                current_count = await page.locator('.property-card').count()
                if current_count == last_count:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0
                    last_count = current_count

                if scroll_attempts >= 2:
                    break

            # Get page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all property cards
            cards = soup.select(".property-card")
            print(f"[{self.source_name}] Found {len(cards)} property cards")

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
            await page.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        return listings

    def _parse_card(self, card: Tag) -> Optional[ScrapedListing]:
        """Parse a single property card."""
        try:
            # Get property ID from card id attribute (e.g., "property-card-list-10117860")
            card_id = card.get("id", "")
            property_id = None
            if card_id:
                id_match = re.search(r'property-card-list-(\d+)', card_id)
                if id_match:
                    property_id = id_match.group(1)

            # URL from the nav wrapper link
            link_el = card.select_one("a.property-card__nav-wrapper")
            url = None
            if link_el:
                href = link_el.get("href", "")
                if href:
                    url = urljoin("https://www.invitationhomes.com", href)
                    # Extract property ID from URL if not found in card id
                    if not property_id:
                        url_match = re.search(r'-(\d+)$', href)
                        if url_match:
                            property_id = url_match.group(1)

            # Price - get base rent from first .property-card__price--base
            price_el = card.select_one(".property-card__price--base")
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Address from .property-card__address spans
            address_el = card.select_one(".property-card__address")
            address = None
            city, state, zip_code = None, None, None

            if address_el:
                spans = address_el.select("span")
                if len(spans) >= 2:
                    street = spans[0].get_text(strip=True)
                    city_state_zip = spans[1].get_text(strip=True)
                    address = f"{street}, {city_state_zip}"

                    # Parse city, state, zip from second span (e.g., "Lacey, WA 98503")
                    csz_match = re.search(r'([^,]+),\s*([A-Z]{2})\s*(\d{5})', city_state_zip)
                    if csz_match:
                        city = csz_match.group(1).strip()
                        state = csz_match.group(2)
                        zip_code = csz_match.group(3)
                elif len(spans) == 1:
                    address = spans[0].get_text(strip=True)

            # Specs: beds, baths, sqft from .property-card__home-specs
            specs_el = card.select_one(".property-card__home-specs")
            bedrooms, bathrooms, sqft = None, None, None

            if specs_el:
                specs_text = specs_el.get_text(strip=True)
                # Format: "3 beds • 1.75 baths • 1,278 sqft"
                bed_match = re.search(r'(\d+)\s*bed', specs_text, re.I)
                if bed_match:
                    bedrooms = int(bed_match.group(1))

                bath_match = re.search(r'([\d.]+)\s*bath', specs_text, re.I)
                if bath_match:
                    bathrooms = float(bath_match.group(1))

                sqft_match = re.search(r'([\d,]+)\s*sqft', specs_text, re.I)
                if sqft_match:
                    sqft = int(sqft_match.group(1).replace(',', ''))

            # Image from carousel
            img_el = card.select_one(".carousel__slide img")
            image_url = None
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src")
                # Skip fallback/placeholder images
                if image_url and "house-card-fallback" in image_url:
                    image_url = None

            # Generate source ID
            source_id = f"invh_{property_id}" if property_id else f"invh_{abs(hash(url or address))}"

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=address or "Invitation Homes Property",
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
